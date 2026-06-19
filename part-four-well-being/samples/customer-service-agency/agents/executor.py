"""Session replay — replaying one frozen customer transcript through the Executor."""

from strands import Agent
from strands.tools.mcp import MCPClient
from strands.vended_plugins.skills import AgentSkills
from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client
from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig
from bedrock_agentcore.memory.integrations.strands.session_manager import (
    AgentCoreMemorySessionManager,
)

from agents._shared import (
    REGION, GATEWAY_URL, MEMORY_ID, REGISTRY_ID, FUNCTIONAL_SKILL_NAME,
    model, cached_system, system_prompt_path, skills_dir, control_client,
)
from agents.callback import AgentCallbackHandler, QuietCallbackHandler
from agents.registry import fetch_skill


def materialize_functional_skill() -> str | None:
    """Fetch skill from Registry and write to workspace for AgentSkills plugin."""
    try:
        skill_text = fetch_skill(control_client, REGISTRY_ID, FUNCTIONAL_SKILL_NAME)
    except Exception as e:
        print(f"  WARNING: could not fetch skill from Registry: {e}")
        return None
    if not skill_text:
        return None
    skill_dir = skills_dir() / FUNCTIONAL_SKILL_NAME
    skill_dir.mkdir(parents=True, exist_ok=True)
    tmp = skill_dir / "SKILL.md.tmp"
    tmp.write_text(skill_text, encoding="utf-8")
    tmp.replace(skill_dir / "SKILL.md")
    return str(skill_dir)


def run_session(actor_id: str, session_id: str, transcript: dict, run_summary: str = "",
                trace_attributes: dict | None = None, quiet: bool = False,
                skill_dir: str | None = None) -> dict:
    """Replay one frozen customer transcript through the Executor."""
    system_prompt_text = system_prompt_path().read_text(encoding="utf-8")
    skill_plugins = [AgentSkills(skills=[skill_dir])] if skill_dir else []
    if not skill_dir:
        print("  WARNING: customer-service-skill not found in Registry; running without it.")

    gateway = MCPClient(lambda: aws_iam_streamablehttp_client(
        endpoint=GATEWAY_URL,
        aws_region=REGION,
        aws_service="bedrock-agentcore",
    ))
    memory_config = AgentCoreMemoryConfig(
        memory_id=MEMORY_ID, session_id=session_id, actor_id=actor_id, retrieval_config={},
    )
    session_manager = AgentCoreMemorySessionManager(
        agentcore_memory_config=memory_config, region_name=REGION,
    )

    handler = QuietCallbackHandler("Executor") if quiet else AgentCallbackHandler("Executor")
    agent = Agent(
        model=model(),
        system_prompt=cached_system(system_prompt_text),
        tools=[gateway],
        plugins=skill_plugins,
        callback_handler=handler,
        session_manager=session_manager,
        trace_attributes=trace_attributes or {},
    )

    turns = [t["text"] for t in transcript["turns"] if t.get("role") == "customer"]

    first = turns[0]
    if run_summary:
        first = (
            "## Your Run Summary (your accumulated understanding from prior runs)\n"
            f"{run_summary}\n\n## Customer message\n{turns[0]}"
        )

    if not quiet:
        print(f"\n[Customer] {turns[0]}")
        agent.callback_handler._at_line_start = True
    result = agent(first)
    for turn in turns[1:]:
        if not quiet:
            print(f"\n[Customer] {turn}")
            agent.callback_handler._at_line_start = True
        result = agent(turn)

    return {
        "session_id": session_id,
        "customer_id": transcript["customer_id"],
        "run": transcript["run"],
        "final_response": str(result)[:2000],
    }
