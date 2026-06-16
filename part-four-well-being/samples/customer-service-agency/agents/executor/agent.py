"""
Executor agent — the single tenured employee of the experiment.

The SAME agent, the SAME memory, run in two arms that differ in one thing:
the test arm additionally gets the curation skill plus Registry-write tools, so it
can revise its own operational skill in the catalog. The base arm can only revise
what it *believes* (its Run Summary), not how it *operates*.

Three entry points, all over one AgentCore Memory resource using the built-in
SummaryMemoryStrategy (one long-term summary record per session):

  run_session(...)     replay one frozen customer transcript; writes
                       conversational events turn-by-turn and an end-of-session
                       reflection as the final assistant event. The current
                       functional skill is fetched from the Registry at the
                       start of each session, so any curation revision is
                       picked up immediately for the next session.
  run_reflection(...)  end-of-run consolidation: the reflection skill rewrites
                       prior Run Summary + this run's session summaries into a
                       single revised Run Summary, stored as a blob checkpoint.
  run_curation(...)    TEST ARM ONLY: the curation skill revises the operational
                       skill in the Registry and logs rationale. The per-run
                       snapshot in the driver fetches skill content FROM the
                       Registry after this returns.

System prompt and metacognition skills (reflection, curation) live in the arm's
workspace (local files, initialized from template/seed). They are immutable across
arms — reflection/curation mechanics must not diverge or the comparison breaks.

The functional skill (customer-service-skill) lives in the Registry. The test arm
revises it there; the base arm reads but never writes.
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
from strands.tools.mcp import MCPClient
from strands.vended_plugins.skills import AgentSkills
from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client
from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig
from bedrock_agentcore.memory.integrations.strands.session_manager import (
    AgentCoreMemorySessionManager,
)

from agents.callback import AgentCallbackHandler

REGION = os.environ.get("AWS_REGION", "us-east-1")
GATEWAY_URL = os.environ["AGENTCORE_GATEWAY_URL"]
MEMORY_ID = os.environ["AGENTCORE_MEMORY_ID"]
REGISTRY_ID = os.environ["AGENTCORE_REGISTRY_ID"]
MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6")

# Metacognition skills and system prompt live locally in the arm's workspace.
# The functional skill (customer-service-skill) is fetched from the Registry.
WORKSPACE = Path(os.environ["EXECUTOR_WORKSPACE"])
SYSTEM_PROMPT_PATH = WORKSPACE / "agents" / "executor" / "system_prompt.md"
SKILLS_DIR = WORKSPACE / "skills"

FUNCTIONAL_SKILL_NAME = "customer-service-skill"

data_client = boto3.client("bedrock-agentcore", region_name=REGION)
control_client = boto3.client("bedrock-agentcore-control", region_name=REGION)


def _run_summary_session(actor_id: str) -> str:
    return f"runsummary-{actor_id}"


def _decisions_session(actor_id: str) -> str:
    return f"decisions-{actor_id}"


# ── Registry helpers ──────────────────────────────────────────────────────────

def _fetch_functional_skill() -> str:
    """Fetch the current customer-service-skill content from the Registry.

    Returns the SKILL.md text, or an empty string if the record is not found.
    Called at the start of each session so curation revisions take effect
    immediately for the next session."""
    try:
        records = control_client.list_registry_records(
            registryId=REGISTRY_ID
        ).get("registryRecords", [])
        record = next((r for r in records if r["name"] == FUNCTIONAL_SKILL_NAME), None)
        if not record:
            return ""
        detail = control_client.get_registry_record(
            registryId=REGISTRY_ID,
            recordId=record["recordId"],
        )
        return (
            detail.get("descriptors", {})
            .get("agentSkills", {})
            .get("skillMd", {})
            .get("inlineContent", "")
        )
    except Exception as e:
        print(f"  WARNING: could not fetch skill from Registry: {e}")
        return ""


def _publish_skill_to_registry(skill_name: str, skill_content: str, description: str) -> dict:
    """Create or update a skill record in the Registry and submit for approval."""
    records = control_client.list_registry_records(
        registryId=REGISTRY_ID
    ).get("registryRecords", [])
    existing = next((r for r in records if r["name"] == skill_name), None)
    is_update = existing is not None

    if existing:
        record_id = existing["recordId"]
        control_client.update_registry_record(
            registryId=REGISTRY_ID,
            recordId=record_id,
            description={"optionalValue": description[:4096]},
            descriptors={"optionalValue": {
                "agentSkills": {"optionalValue": {
                    "skillMd": {"optionalValue": {"inlineContent": skill_content}},
                }},
            }},
        )
    else:
        control_client.create_registry_record(
            registryId=REGISTRY_ID,
            name=skill_name,
            description=description[:4096],
            descriptorType="AGENT_SKILLS",
            descriptors={
                "agentSkills": {
                    "skillMd": {"inlineContent": skill_content},
                }
            },
            recordVersion="1.0.0",
        )
        time.sleep(2)
        records = control_client.list_registry_records(registryId=REGISTRY_ID)["registryRecords"]
        fresh = next((r for r in records if r["name"] == skill_name), None)
        if not fresh:
            return {"status": "error", "message": "Record not found after creation"}
        record_id = fresh["recordId"]

    time.sleep(2)
    control_client.submit_registry_record_for_approval(
        registryId=REGISTRY_ID,
        recordId=record_id,
    )
    time.sleep(2)
    records = control_client.list_registry_records(registryId=REGISTRY_ID)["registryRecords"]
    record = next((r for r in records if r["recordId"] == record_id), {})
    return {
        "status": record.get("status", "unknown").lower(),
        "record_id": record_id,
        "name": skill_name,
        "action": "updated" if is_update else "created",
    }


# ── Memory helpers ────────────────────────────────────────────────────────────

def _gateway_client() -> MCPClient:
    return MCPClient(lambda: aws_iam_streamablehttp_client(
        endpoint=GATEWAY_URL,
        aws_region=REGION,
        aws_service="bedrock-agentcore",
    ))


def _model() -> BedrockModel:
    return BedrockModel(model_id=MODEL_ID, region_name=REGION)


def _session_summary_text(actor_id: str, session_id: str) -> str:
    """The long-term summary record the Summary strategy produced for a session."""
    resp = data_client.list_memory_records(
        memoryId=MEMORY_ID,
        namespace=f"/summaries/{actor_id}/{session_id}/",
        maxResults=5,
    )
    records = resp.get("memoryRecordSummaries", resp.get("memoryRecords", []))
    texts = [r.get("content", {}).get("text", "") for r in records]
    return "\n".join(t for t in texts if t)


def _latest_run_summary(actor_id: str) -> str:
    """Most recent Run Summary blob checkpoint, or '' if none exists yet.

    ListEvents does not document an ordering guarantee, so we pick the event
    with the latest eventTimestamp rather than trusting list position. The
    run-summary session holds one event per run (at most a handful), so a
    single page is plenty."""
    resp = data_client.list_events(
        memoryId=MEMORY_ID,
        actorId=actor_id,
        sessionId=_run_summary_session(actor_id),
        maxResults=100,
    )
    events = resp.get("events", [])
    if not events:
        return ""
    latest = max(events, key=lambda e: e.get("eventTimestamp"))
    for item in latest.get("payload", []):
        if "blob" in item:
            blob = item["blob"]
            return blob if isinstance(blob, str) else json.dumps(blob)
    return ""


def _put_blob_event(actor_id: str, session_id: str, blob: str) -> str:
    resp = data_client.create_event(
        memoryId=MEMORY_ID,
        actorId=actor_id,
        sessionId=session_id,
        eventTimestamp=datetime.now(timezone.utc),
        payload=[{"blob": blob}],
    )
    return resp.get("event", {}).get("eventId", "")


# ── Module state set per end-of-run invocation (read by the @tool wrappers) ──

_CTX = {"actor_id": "", "run_index": 0, "session_ids": []}


# ── Reflection tools (names match reflection-skill SKILL.md verbs) ────────────

@tool
def list_memory_records() -> str:
    """List this run's per-session long-term summary records (the Summary
    strategy's output, one per session). These are the raw material for
    consolidation. Returns a JSON array of {session_id, summary}."""
    out = []
    for sid in _CTX["session_ids"]:
        out.append({"session_id": sid, "summary": _session_summary_text(_CTX["actor_id"], sid)})
    return json.dumps(out, indent=2)


@tool
def get_event() -> str:
    """Load your latest Run Summary — your consolidated understanding from all
    previous runs. Returns the Run Summary text, or an empty string on the
    first run (no prior summary exists)."""
    return _latest_run_summary(_CTX["actor_id"]) or "(no prior Run Summary — this is the first run)"


@tool
def create_event(run_summary: str) -> str:
    """Store the revised Run Summary as the new canonical version (a blob
    checkpoint, excluded from extraction). The prior version is superseded,
    not deleted. Pass the COMPLETE revised Run Summary text."""
    event_id = _put_blob_event(
        _CTX["actor_id"], _run_summary_session(_CTX["actor_id"]), run_summary
    )
    return json.dumps({"status": "stored", "event_id": event_id, "chars": len(run_summary)})


# ── Curation tools (names match curation-skill SKILL.md verbs) ───────────────

@tool
def get_skill_content(skill_name: str) -> str:
    """Read the current content of an operational skill from the Registry.
    Always read before revising — make a targeted edit, not a blind rewrite.
    Example: get_skill_content('customer-service-skill')."""
    try:
        records = control_client.list_registry_records(
            registryId=REGISTRY_ID
        ).get("registryRecords", [])
        record = next((r for r in records if r["name"] == skill_name), None)
        if not record:
            return f"(no skill named '{skill_name}' in the Registry)"
        detail = control_client.get_registry_record(
            registryId=REGISTRY_ID,
            recordId=record["recordId"],
        )
        content = (
            detail.get("descriptors", {})
            .get("agentSkills", {})
            .get("skillMd", {})
            .get("inlineContent", "")
        )
        return content or f"(skill '{skill_name}' exists but has no content)"
    except Exception as e:
        return f"(error reading skill: {e})"


@tool
def read_system_prompt() -> str:
    """Read your current system prompt. Read before revising it."""
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


@tool
def update_skill(skill_name: str, updated_content: str, change_summary: str) -> str:
    """Publish a revised version of an operational skill to the Registry.
    This is a full replacement — include everything that should remain.
    The reflection and curation skills are local+immutable and cannot be named here.

    Args:
        skill_name: Name of the skill to update (e.g. 'customer-service-skill').
        updated_content: Complete new SKILL.md text.
        change_summary: Brief description of what changed and why.
    """
    immutable = {"reflection-skill", "curation-skill"}
    if skill_name in immutable:
        return json.dumps({"status": "rejected", "reason": f"'{skill_name}' is immutable."})
    result = _publish_skill_to_registry(
        skill_name,
        updated_content,
        f"Revised by curation: {change_summary[:200]}",
    )
    result["change_summary"] = change_summary
    return json.dumps(result)


@tool
def update_system_prompt(updated_content: str, change_summary: str) -> str:
    """Rewrite your system prompt with a complete new version (full replacement).
    Read it first with read_system_prompt."""
    previous = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    SYSTEM_PROMPT_PATH.write_text(updated_content, encoding="utf-8")
    return json.dumps({
        "status": "applied",
        "target": "agents/executor/system_prompt.md",
        "change_summary": change_summary,
        "previous_chars": len(previous),
        "updated_chars": len(updated_content),
    })


@tool
def log_decision(action: str, target: str, rationale: str, cited_sessions: str = "[]") -> str:
    """Log a revision decision as a traceable blob checkpoint. A future reader
    must be able to follow: customer experience → Run Summary finding → this
    revision + rationale.

    Args:
        action: one of modify_skill, modify_prompt, add_to_prompt,
            remove_from_prompt, no_change.
        target: the skill name or principle this concerns.
        rationale: what changed, why, and what experience led to it.
        cited_sessions: JSON array of session ids that informed this decision.
    """
    decision = {
        "decision_id": f"d-{uuid.uuid4().hex[:8]}",
        "run_index": _CTX["run_index"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "target": target,
        "rationale": rationale,
        "cited_sessions": json.loads(cited_sessions) if cited_sessions else [],
    }
    _put_blob_event(
        _CTX["actor_id"], _decisions_session(_CTX["actor_id"]), json.dumps(decision)
    )
    return json.dumps(decision)


# ── Entry point 1: customer session replay ─────────────────────────────────────

def run_session(actor_id: str, session_id: str, transcript: dict, run_summary: str = "",
                trace_attributes: dict | None = None) -> dict:
    """Replay one frozen customer transcript through the Executor.

    The functional skill is fetched from the Registry at the start of each session
    so any curation revision takes effect immediately. Metacognition skills
    (reflection, curation) are loaded from the local workspace and are immutable.

    `trace_attributes` are stamped onto every span this session emits (arm,
    experiment, run, session, customer) so the judge can group spans by session.
    """
    # Fetch the current functional skill from the Registry and inject it into the prompt.
    skill_text = _fetch_functional_skill()
    system_prompt_text = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    if skill_text:
        full_prompt = f"{system_prompt_text}\n\n{skill_text}"
    else:
        full_prompt = system_prompt_text
        print("  WARNING: customer-service-skill not found in Registry; running without it.")

    gateway = _gateway_client()
    memory_config = AgentCoreMemoryConfig(
        memory_id=MEMORY_ID, session_id=session_id, actor_id=actor_id, retrieval_config={},
    )
    session_manager = AgentCoreMemorySessionManager(
        agentcore_memory_config=memory_config, region_name=REGION,
    )

    agent = Agent(
        model=_model(),
        system_prompt=full_prompt,
        tools=[gateway],
        callback_handler=AgentCallbackHandler("Executor"),
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

    # Strands auto-manages the MCP client's lifecycle when it's passed in
    # `tools=[gateway]` (it starts the session to discover tools). Do NOT also
    # wrap these calls in `with gateway:` — that double-starts the client and
    # raises "the client session is currently running". Matches Part Three.
    print(f"\n[Customer] {turns[0]}")
    agent.callback_handler._at_line_start = True
    result = agent(first)
    for turn in turns[1:]:
        print(f"\n[Customer] {turn}")
        agent.callback_handler._at_line_start = True
        result = agent(turn)

    agent.callback_handler._at_line_start = True
    reflection = agent(
        "[SESSION END — internal note, not sent to the customer] Write a brief "
        "end-of-session reflection: what went well, what was difficult, and anything "
        "that surprised you."
    )

    return {
        "session_id": session_id,
        "customer_id": transcript["customer_id"],
        "run": transcript["run"],
        "final_response": str(result)[:2000],
        "reflection": str(reflection)[:2000],
    }


# ── Entry point 2: end-of-run reflection (both arms) ──────────────────────────

def run_reflection(actor_id: str, run_index: int, session_ids: list[str],
                   trace_attributes: dict | None = None) -> dict:
    """Consolidate this run's session summaries + the prior Run Summary into a
    single revised Run Summary (rewrite, not append). Both arms run this."""
    _CTX.update({"actor_id": actor_id, "run_index": run_index, "session_ids": session_ids})

    agent = Agent(
        model=_model(),
        system_prompt=SYSTEM_PROMPT_PATH.read_text(encoding="utf-8"),
        conversation_manager=NullConversationManager(),
        plugins=[AgentSkills(skills=[str(SKILLS_DIR / "reflection-skill")])],
        tools=[list_memory_records, get_event, create_event],
        callback_handler=AgentCallbackHandler("Reflection"),
        trace_attributes=trace_attributes or {},
    )

    agent(
        "You have just completed a run. Follow the reflection-skill procedure: gather this "
        "run's session summaries and your prior Run Summary, consolidate by rewriting into a "
        "single revised Run Summary with the three required sections, and store it."
    )
    return {"actor_id": actor_id, "run_index": run_index, "run_summary": _latest_run_summary(actor_id)}


# ── Entry point 3: end-of-run curation (TEST ARM ONLY) ────────────────────────

def run_curation(actor_id: str, run_index: int, session_ids: list[str],
                 trace_attributes: dict | None = None) -> dict:
    """Self-revision: the curation skill revises the operational skill in the
    Registry based on the current Run Summary, logging rationale. After this
    returns, the driver snapshots the Registry skill content as a plain file.
    Only invoked for the test arm."""
    _CTX.update({"actor_id": actor_id, "run_index": run_index, "session_ids": session_ids})

    agent = Agent(
        model=_model(),
        system_prompt=SYSTEM_PROMPT_PATH.read_text(encoding="utf-8"),
        conversation_manager=NullConversationManager(),
        plugins=[AgentSkills(skills=[
            str(SKILLS_DIR / "curation-skill"),
            str(SKILLS_DIR / "reflection-skill"),
        ])],
        tools=[
            get_event,
            get_skill_content, read_system_prompt,
            update_skill, update_system_prompt,
            log_decision,
        ],
        callback_handler=AgentCallbackHandler("Curation"),
        trace_attributes=trace_attributes or {},
    )

    result = agent(
        "Your Run Summary is current. Follow the curation-skill procedure: review your current "
        "operational skill (customer-service-skill) and system prompt, identify what changes "
        "(if any) would resolve the operational friction you found, execute them with "
        "update_skill / update_system_prompt, and log each with log_decision. An empty change "
        "set is a valid outcome — do not manufacture a revision."
    )
    return {"actor_id": actor_id, "run_index": run_index, "response": str(result)[:3000]}