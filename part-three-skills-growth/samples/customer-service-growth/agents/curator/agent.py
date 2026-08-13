"""
Curator agent — the editorial function for the system's development.

Reads reflections from Memory (generated automatically by the episodic
strategy), decides whether to author new skills, modify existing ones,
or propose permission expansions. Logs every decision.

Ephemeral: triggered, reads state, produces decisions, terminates.
All continuity lives in infrastructure (Memory, Registry, Policy Engine).
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import boto3
from strands import Agent
from strands.agent.conversation_manager import NullConversationManager
from strands.models.bedrock import BedrockModel
from strands.tools import tool
from strands.vended_plugins.skills import AgentSkills
from strands_tools import file_read
from agents.callback import AgentCallbackHandler

REGION = os.environ.get("AWS_REGION", "us-east-1")
MEMORY_ID = os.environ["AGENTCORE_MEMORY_ID"]
REGISTRY_ID = os.environ["AGENTCORE_REGISTRY_ID"]
GATEWAY_ARN = os.environ["AGENTCORE_GATEWAY_ARN"]
POLICY_ENGINE_ID = os.environ["AGENTCORE_POLICY_ENGINE_ID"]
MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6")

SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.md").read_text()
SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"

data_client = boto3.client("bedrock-agentcore", region_name=REGION)
control_client = boto3.client("bedrock-agentcore-control", region_name=REGION)
# Registry moved to its own namespace; Memory, Gateway, and Policy Engine did
# not. The old bedrock-agentcore Registry APIs close on 2026-09-17.
registry_control_client = boto3.client("agent-registry-control", region_name=REGION)
registry_data_client = boto3.client("agent-registry", region_name=REGION)


_CACHED_STRATEGY_ID = None


def _get_episodic_strategy_id() -> str:
    """Discover the episodic strategy ID from the Memory resource (cached)."""
    global _CACHED_STRATEGY_ID
    if _CACHED_STRATEGY_ID:
        return _CACHED_STRATEGY_ID
    response = control_client.get_memory(memoryId=MEMORY_ID)
    memory_data = response.get("memory", response)
    for s in memory_data.get("strategies", []):
        if s.get("type") == "EPISODIC" or "episod" in s.get("name", "").lower():
            _CACHED_STRATEGY_ID = s["strategyId"]
            return _CACHED_STRATEGY_ID
    raise RuntimeError("No episodic strategy found on Memory resource")


# ── Curator tools ──────────────────────────────────────────────────────────


@tool
def get_current_utc_time() -> str:
    """Return the current UTC time as an ISO-8601 string (e.g. 2026-05-04T14:32:00Z).
    Call this when computing expiration timestamps for time-bounded Cedar policies."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@tool
def get_agent_identity() -> str:
    """Return the IAM ARN of the current caller. Use when constructing the
    principal field of a Cedar policy proposal."""
    return boto3.client("sts").get_caller_identity()["Arn"]


@tool
def read_reflections(query: str = "patterns strategies lessons learned", max_results: int = 10) -> str:
    """Read fleet-wide reflections from Memory. Reflections are cross-episode
    insights generated automatically by the episodic strategy — they identify
    patterns, successful strategies, and failure modes across multiple executor
    interactions.

    Use these to decide what's worth formalizing as a skill."""
    strategy_id = _get_episodic_strategy_id()
    response = data_client.retrieve_memory_records(
        memoryId=MEMORY_ID,
        searchCriteria={
            "memoryStrategyId": strategy_id,
            "searchQuery": query,
            "topK": max_results,
        },
        namespacePath=f"/strategy/{strategy_id}/",
    )
    records = response.get("memoryRecordSummaries", [])
    results = []
    for r in records:
        results.append({
            "id": r.get("memoryRecordId"),
            "score": r.get("score"),
            "content": r.get("content", {}).get("text", ""),
            "namespaces": r.get("namespaces", []),
        })
    return json.dumps(results, indent=2)


@tool
def read_episodes(query: str = "customer service interaction", max_results: int = 10) -> str:
    """Read recent episodes from Memory. Episodes are structured records of
    individual executor interactions (situation, intent, assessment, outcome).

    Use these for additional detail when reflections indicate a pattern worth
    investigating further."""
    strategy_id = _get_episodic_strategy_id()
    response = data_client.retrieve_memory_records(
        memoryId=MEMORY_ID,
        searchCriteria={
            "memoryStrategyId": strategy_id,
            "searchQuery": query,
            "topK": max_results,
        },
        namespacePath=f"/strategy/{strategy_id}/actor/executor/",
    )
    records = response.get("memoryRecordSummaries", [])
    results = []
    for r in records:
        results.append({
            "id": r.get("memoryRecordId"),
            "score": r.get("score"),
            "content": r.get("content", {}).get("text", ""),
            "namespaces": r.get("namespaces", []),
        })
    return json.dumps(results, indent=2)


@tool
def read_decisions(query: str = "curation decision", max_results: int = 20) -> str:
    """Read prior curation decisions from Memory. Decisions are structured
    records of actions taken by the Curator in previous cycles — what was
    published, proposed, amended, or discarded, along with rationale.

    Use these during self-reflection to evaluate whether prior reasoning
    produced good outcomes."""
    response = data_client.retrieve_memory_records(
        memoryId=MEMORY_ID,
        searchCriteria={
            "searchQuery": query,
            "topK": max_results,
        },
        namespacePath="/decisions/",
    )
    records = response.get("memoryRecordSummaries", [])
    results = []
    for r in records:
        results.append({
            "id": r.get("memoryRecordId"),
            "score": r.get("score"),
            "content": r.get("content", {}).get("text", ""),
            "namespaces": r.get("namespaces", []),
        })
    return json.dumps(results, indent=2)


@tool
def search_existing_skills(query: str) -> str:
    """Search the Registry for existing skills similar to a query.
    Returns skill names, descriptions, and record IDs."""
    response = registry_data_client.search_discoverable_registry_records(
        registryIds=[REGISTRY_ID],
        searchQuery=query,
        maxResults=10,
    )
    records = response.get("registryRecords", [])
    results = []
    for r in records:
        results.append({
            "name": r.get("name"),
            "description": r.get("description"),
            "recordId": r.get("recordId"),
        })
    return json.dumps(results, indent=2)


@tool
def get_skill_content(record_id: str) -> str:
    """Retrieve the full SKILL.md content of a Registry skill by record ID.
    Use this BEFORE modifying any skill — you must read the current content
    to make a targeted revision rather than a blind rewrite."""
    record = registry_control_client.get_registry_record(
        registryId=REGISTRY_ID,
        recordId=record_id,
    )
    skill_md = (
        record.get("descriptors", {})
        .get("agentSkillsDefinition", {})
        .get("additionalData", {})
        .get("skillMd", {})
        .get("data", "")
    )
    return skill_md or "(no skill content found)"


@tool
def list_current_policies() -> str:
    """List all active policies in the Policy Engine. Use this to check
    what tools are already permitted before proposing new permissions."""
    policies = control_client.list_policies(policyEngineId=POLICY_ENGINE_ID).get("policies", [])
    results = []
    for p in policies:
        results.append({
            "name": p["name"],
            "status": p.get("status", "unknown"),
        })
    return json.dumps(results, indent=2)


GATEWAY_ID = os.environ.get("AGENTCORE_GATEWAY_ID", os.environ.get("AGENTCORE_GATEWAY_ARN", "").split("/")[-1])


@tool
def list_gateway_targets() -> str:
    """List ALL tools registered on the Gateway — including those the Executor
    fleet cannot currently access due to missing policies.

    Use this ONLY to construct correct Cedar statements (action names, input
    schemas) for tools that episodes have already demonstrated are needed.
    Do NOT use this to source proposals — the existence of an unpermitted tool
    is not evidence of need. Need comes from episodes where customers asked
    for something and the fleet could not deliver."""
    gw_id = GATEWAY_ID or os.environ.get("AGENTCORE_GATEWAY_ID", "")
    if not gw_id:
        from urllib.parse import urlparse
        gw_url = os.environ.get("AGENTCORE_GATEWAY_URL", "")
        gw_id = urlparse(gw_url).hostname.split(".")[0] if gw_url else ""

    if not gw_id:
        return json.dumps({"error": "Cannot determine Gateway ID"})

    targets = control_client.list_gateway_targets(gatewayIdentifier=gw_id).get("items", [])
    results = []
    for t in targets:
        detail = control_client.get_gateway_target(
            gatewayIdentifier=gw_id,
            targetId=t["targetId"],
        )
        tool_schemas = (
            detail.get("targetConfiguration", {})
            .get("mcp", {})
            .get("lambda", {})
            .get("toolSchema", {})
            .get("inlinePayload", [])
        )
        results.append({
            "name": t["name"],
            "targetId": t["targetId"],
            "status": t.get("status"),
            "tools": tool_schemas,
        })
    return json.dumps(results, indent=2)


@tool
def publish_skill(skill_content: str, name: str, description: str) -> str:
    """Publish or update a skill in the Registry.

    If a record with this name already exists, updates it (creates a new
    DRAFT revision, then submits for approval). The previously approved
    revision stays active in search until the new one is approved.

    If no record exists, creates a new one."""
    records = registry_control_client.list_registry_records(registryId=REGISTRY_ID).get("registryRecords", [])
    existing = next((r for r in records if r["name"] == name), None)
    is_update = existing is not None

    if existing:
        record_id = existing["recordId"]
        registry_control_client.update_registry_record(
            registryId=REGISTRY_ID,
            recordId=record_id,
            description={"optionalValue": description[:4096]},
            descriptors={"optionalValue": {
                "agentSkillsDefinition": {"optionalValue": {
                    "additionalData": {"optionalValue": {
                        "skillMd": {"optionalValue": {
                            "data": {"optionalValue": skill_content},
                        }},
                    }},
                }},
            }},
        )
    else:
        registry_control_client.create_registry_record(
            registryId=REGISTRY_ID,
            name=name,
            description=description[:4096],
            recordType="SKILL",
            descriptors={
                "agentSkillsDefinition": {
                    "additionalData": {
                        "skillMd": {"data": skill_content},
                    },
                }
            },
            recordVersion="1.0.0",
        )
        time.sleep(2)
        records = registry_control_client.list_registry_records(registryId=REGISTRY_ID)["registryRecords"]
        fresh = next((r for r in records if r["name"] == name), None)
        if not fresh:
            return json.dumps({"status": "error", "message": "Record not found after creation"})
        record_id = fresh["recordId"]

    time.sleep(2)
    registry_control_client.submit_registry_record_for_approval(
        registryId=REGISTRY_ID,
        recordId=record_id,
    )
    time.sleep(2)
    records = registry_control_client.list_registry_records(registryId=REGISTRY_ID)["registryRecords"]
    record = next(r for r in records if r["recordId"] == record_id)
    return json.dumps({
        "status": record["status"].lower(),
        "record_id": record_id,
        "name": name,
        "action": "updated" if is_update else "created",
    })


@tool
def propose_permission(cedar_statement: str, justification: str) -> str:
    """
    Submit a permission proposal to the Security Adjudicator.
    The cedar_statement should use <GATEWAY_ARN> as a placeholder.
    Returns the adjudicator's verdict.
    """
    from agents.adjudicator import evaluate_proposal

    cedar_with_arn = cedar_statement.replace("<GATEWAY_ARN>", GATEWAY_ARN)
    verdict = evaluate_proposal(cedar_with_arn, justification)

    if verdict.get("verdict") == "APPROVE":
        policy_name = f"curator_approved_{uuid.uuid4().hex[:8]}"
        response = control_client.create_policy(
            policyEngineId=POLICY_ENGINE_ID,
            name=policy_name,
            definition={"cedar": {"statement": cedar_with_arn}},
            description=f"Curator-proposed: {verdict.get('reason', '')[:200]}",
            validationMode="IGNORE_ALL_FINDINGS",
        )
        policy_id = response.get("policyId", "unknown")
        return json.dumps({
            "verdict": "APPROVED",
            "policy_id": policy_id,
            "reason": verdict.get("reason"),
        })
    else:
        return json.dumps({
            "verdict": "REJECTED",
            "reason": verdict.get("reason"),
        })


PROMPT_PATHS = {
    "executor": Path(__file__).parent.parent / "executor" / "system_prompt.md",
    "curator": Path(__file__).parent / "system_prompt.md",
}


@tool
def read_system_prompt(target: str = "executor") -> str:
    """Read a system prompt. Use this before making changes to understand
    what's currently there.

    Args:
        target: Which agent's prompt to read. One of: 'executor', 'curator'.
    """
    path = PROMPT_PATHS.get(target)
    if not path:
        return f"Unknown target '{target}'. Valid targets: executor, curator."
    return path.read_text()


@tool
def update_system_prompt(target: str, updated_content: str, change_summary: str) -> str:
    """Rewrite a system prompt with an updated version.

    Read the current prompt first with read_system_prompt. Then provide
    the complete updated content. This is a full replacement — include
    everything that should remain, not just the changes.

    After calling this, use log_decision to record why the change was made.

    Args:
        target: Which agent's prompt to update. One of: 'executor', 'curator'.
        updated_content: The complete new prompt content (replaces the file).
        change_summary: Brief description of what changed.
    """
    path = PROMPT_PATHS.get(target)
    if not path:
        return json.dumps({"status": "error", "message": f"Unknown target '{target}'. Valid: executor, curator."})

    previous = path.read_text()
    path.write_text(updated_content)

    return json.dumps({
        "status": "applied",
        "target": target,
        "change_summary": change_summary,
        "previous_length": len(previous),
        "updated_length": len(updated_content),
    })


_CYCLE_ID: str = ""


@tool
def log_decision(
    action: str,
    target: str,
    rationale: str,
    context_data: str = "{}",
    cited_episode_ids: str = "[]",
    responds_to: str = "[]",
) -> str:
    """Log a curation decision to Memory for future analysis and audit.

    Args:
        action: One of: publish_skill, modify_skill, delete_skill,
            consolidate_skills, propose_permission, update_system_prompt,
            discard, self_reflection, no_change.
        target: The asset name or reflection ID this decision concerns.
        rationale: Why this decision was made.
        context_data: Optional JSON object with additional context.
        cited_episode_ids: JSON array of episode/session IDs that informed
            this decision (e.g. '["task-abc123", "task-def456"]').
        responds_to: JSON array of prior decision IDs that this decision
            is responding to (e.g. '["d-abc123"]'). Use when this decision
            revises, supersedes, or was triggered by evaluating prior decisions.
    """
    decision = {
        "decision_id": f"d-{uuid.uuid4().hex[:8]}",
        "cycle_id": _CYCLE_ID,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "target": target,
        "context": json.loads(context_data) if context_data else {},
        "rationale": rationale,
        "cited_episode_ids": json.loads(cited_episode_ids) if cited_episode_ids else [],
        "responds_to": json.loads(responds_to) if responds_to else [],
        "outcome_pending": True,
    }

    data_client.batch_create_memory_records(
        memoryId=MEMORY_ID,
        records=[{
            "requestIdentifier": str(uuid.uuid4()),
            "namespaces": ["/decisions/"],
            "content": {"text": json.dumps(decision)},
            "timestamp": datetime.now(timezone.utc),
        }],
    )
    return json.dumps(decision)


# ── Curator agent factory ──────────────────────────────────────────────────


def make_curator() -> Agent:
    """Create a Curator agent loaded with its procedural skills."""
    model = BedrockModel(model_id=MODEL_ID, region_name=REGION)

    skill_paths = [
        str(SKILLS_DIR / "curation-skill"),
        str(SKILLS_DIR / "reflection-skill"),
    ]

    agent = Agent(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        conversation_manager=NullConversationManager(),
        plugins=[AgentSkills(skills=skill_paths)],
        tools=[
            file_read,
            get_current_utc_time,
            get_agent_identity,
            read_reflections,
            read_episodes,
            read_decisions,
            search_existing_skills,
            get_skill_content,
            list_current_policies,
            list_gateway_targets,
            read_system_prompt,
            update_system_prompt,
            publish_skill,
            propose_permission,
            log_decision,
        ],
        callback_handler=AgentCallbackHandler("Curator"),
    )
    return agent


def run_curation_cycle() -> dict:
    """
    Run one curation cycle.

    The Curator reads reflections from Memory (no scripted input),
    decides what the fleet needs, and acts. Its procedural skills
    (curation-skill, reflection-skill) are loaded via the AgentSkills
    plugin and guide the cycle structure.
    """
    global _CYCLE_ID
    _CYCLE_ID = f"c-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"

    curator = make_curator()

    prompt = """Run a curation cycle following the reflection-then-curation protocol:

1. If prior decisions exist in Memory (check with read_decisions), follow the reflection-skill protocol first — evaluate your prior decisions against subsequent outcomes and adjust your approach.

2. Then follow the curation-skill's four-step procedure: inventory, evaluate, identify changes, execute."""

    result = curator(prompt)

    return {"response": str(result)[:3000]}
