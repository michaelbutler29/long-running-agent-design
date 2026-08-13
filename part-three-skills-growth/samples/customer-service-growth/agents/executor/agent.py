"""
Executor agent — a frozen class instantiated per customer interaction.

Discovers skills from Registry via MCP, calls tools via Gateway,
reports outcomes (including denials) to Memory. Does not propose
its own growth or negotiate its own boundaries.

Memory integration uses AgentCoreMemorySessionManager as the Strands
session_manager, which writes events in real-time during execution.
This gives the episodic strategy turn-by-turn extraction with natural
idle gaps, enabling faster episode completion detection.
"""

import json
import os
import uuid
from pathlib import Path

import boto3
from strands import Agent
from strands.models.bedrock import BedrockModel
from strands.tools.mcp import MCPClient
from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client
from bedrock_agentcore.memory.integrations.strands.config import (
    AgentCoreMemoryConfig,
    RetrievalConfig,
)
from bedrock_agentcore.memory.integrations.strands.session_manager import (
    AgentCoreMemorySessionManager,
)
from agents.callback import AgentCallbackHandler

SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.md").read_text()

REGION = os.environ.get("AWS_REGION", "us-east-1")
GATEWAY_URL = os.environ["AGENTCORE_GATEWAY_URL"]
REGISTRY_ID = os.environ["AGENTCORE_REGISTRY_ID"]
MEMORY_ID = os.environ["AGENTCORE_MEMORY_ID"]
MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6")

# NOTE: the migration guide documents the MCP search tool rename but not the
# MCP endpoint host. This follows the new data plane host (agent-registry
# .{region}.api.aws) and keeps the /registry/{id}/mcp path. Verify against a
# live registry before relying on it; the request is signed for agent-registry.
REGISTRY_MCP_ENDPOINT = (
    f"https://agent-registry.{REGION}.api.aws/registry/{REGISTRY_ID}/mcp"
)


def _search_registry_for_skills(task_description: str) -> str:
    """Search the Registry MCP endpoint for relevant skills."""
    import urllib.request
    import urllib.error
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    session = boto3.Session()
    credentials = session.get_credentials().get_frozen_credentials()

    body = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "search_discoverable_registry_records",
            "arguments": {
                "searchQuery": task_description,
                "maxResults": 3,
            },
        },
    })

    request = AWSRequest(
        method="POST",
        url=REGISTRY_MCP_ENDPOINT,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    SigV4Auth(credentials, "agent-registry", REGION).add_auth(request)

    req = urllib.request.Request(
        REGISTRY_MCP_ENDPOINT,
        data=body.encode(),
        headers=dict(request.headers),
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode())
    except urllib.error.HTTPError:
        return ""

    content = result.get("result", {}).get("content", [])
    if not content:
        return ""

    text = content[0].get("text", "")
    try:
        records = json.loads(text)
        if isinstance(records, list):
            skills = []
            for r in records:
                descriptors = r.get("descriptors", {})
                skill_md = (
                    descriptors.get("agentSkillsDefinition", {})
                    .get("additionalData", {})
                    .get("skillMd", {})
                    .get("data", "")
                )
                if skill_md:
                    skills.append(skill_md)
            return "\n\n---\n\n".join(skills)
    except (json.JSONDecodeError, TypeError):
        pass

    return ""


def _get_strategy_id() -> str:
    """Discover the episodic strategy ID from the Memory resource."""
    control = boto3.client("bedrock-agentcore-control", region_name=REGION)
    response = control.get_memory(memoryId=MEMORY_ID)
    memory_data = response.get("memory", response)
    for s in memory_data.get("strategies", []):
        if s.get("type") == "EPISODIC":
            return s["strategyId"]
    return ""


_STRATEGY_ID = None


def _strategy_id():
    global _STRATEGY_ID
    if _STRATEGY_ID is None:
        _STRATEGY_ID = _get_strategy_id()
    return _STRATEGY_ID


def make_executor(session_id: str):
    """Create an Executor agent with real-time Memory integration.

    Uses AgentCoreMemorySessionManager as the Strands session_manager
    so events are written turn-by-turn during execution, giving the
    episodic strategy natural idle gaps for completion detection.
    """
    mcp_client = MCPClient(lambda: aws_iam_streamablehttp_client(
        endpoint=GATEWAY_URL,
        aws_region=REGION,
        aws_service="bedrock-agentcore",
    ))

    model = BedrockModel(model_id=MODEL_ID, region_name=REGION)

    strategy_id = _strategy_id()
    memory_config = AgentCoreMemoryConfig(
        memory_id=MEMORY_ID,
        session_id=session_id,
        actor_id="executor",
        retrieval_config={},
    )

    session_manager = AgentCoreMemorySessionManager(
        agentcore_memory_config=memory_config,
        region_name=REGION,
    )

    agent = Agent(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        tools=[mcp_client],
        callback_handler=AgentCallbackHandler("Executor"),
        session_manager=session_manager,
    )

    return agent


def run_conversation(turns: list[str]) -> dict:
    """
    Run a multi-turn customer conversation through the Executor.

    Real customer interactions are multi-turn: greetings, identity
    verification, the actual request, confirmations, follow-ups.

    1. Search Registry for relevant skills (using first substantive turn)
    2. Create agent with a single session
    3. Send each customer turn sequentially
    4. Return outcome from the final response
    """
    session_id = f"task-{uuid.uuid4().hex[:12]}"

    # 1. Discover skills from the substantive turns
    task_summary = " ".join(turns[:3])
    skills_text = _search_registry_for_skills(task_summary)
    skills_applied = []

    # 2. Create agent once — all turns share this session
    agent = make_executor(session_id)

    # Inject skill context on first turn if skills were discovered
    first_turn = turns[0]
    if skills_text:
        skills_applied = ["registry_skill"]
        first_turn = f"""## Available Skills (from Registry — follow these procedures)
{skills_text}

## Customer message
{turns[0]}"""

    # 3. Send each turn (session_manager writes events per turn)
    print(f"\n[Customer] {turns[0]}")
    agent.callback_handler._at_line_start = True
    result = agent(first_turn)
    for turn in turns[1:]:
        print(f"\n[Customer] {turn}")
        agent.callback_handler._at_line_start = True
        result = agent(turn)

    # 4. Parse outcome from final response
    response_text = str(result)
    denials = []
    for msg in agent.messages:
        if msg.get("role") == "assistant":
            for block in msg.get("content", []):
                text = block.get("text", "") if isinstance(block, dict) else ""
                if "unable to" in text.lower() or "can't help with that" in text.lower() or "not able to" in text.lower():
                    denials.append(text[:500])
                    break

    return {
        "result": response_text[:2000],
        "success": len(denials) == 0,
        "skills_applied": skills_applied,
        "denials": denials,
        "session_id": session_id,
    }
