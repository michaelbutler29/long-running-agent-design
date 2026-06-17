"""Executor agent — three-variant ladder (v0/v1/v2) differing only in end-of-run authorship."""

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import boto3
from strands import Agent
from strands.agent.conversation_manager import NullConversationManager
from strands.models import CacheConfig
from strands.models.bedrock import BedrockModel
from strands.types.content import SystemContentBlock
from strands.tools import tool
from strands.tools.mcp import MCPClient
from strands.vended_plugins.skills import AgentSkills
from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client
from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig
from bedrock_agentcore.memory.integrations.strands.session_manager import (
    AgentCoreMemorySessionManager,
)

from agents.callback import AgentCallbackHandler
from agents.registry import fetch_skill, publish_skill

REGION = os.environ.get("AWS_REGION", "us-east-1")
GATEWAY_URL = os.environ["AGENTCORE_GATEWAY_URL"]
MEMORY_ID = os.environ["AGENTCORE_MEMORY_ID"]
REGISTRY_ID = os.environ["AGENTCORE_REGISTRY_ID"]
MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6")

# Metacognition skills and system prompt live locally in the arm's workspace.
# The functional skill (customer-service-skill) is fetched from the Registry.
# Read at call time, not import time — the env var changes between experiments
# and Python caches the module.
def _system_prompt_path() -> Path:
    return Path(os.environ["EXECUTOR_WORKSPACE"]) / "agents" / "executor" / "system_prompt.md"

def _skills_dir() -> Path:
    return Path(os.environ["EXECUTOR_WORKSPACE"]) / "skills"

FUNCTIONAL_SKILL_NAME = "customer-service-skill"

data_client = boto3.client("bedrock-agentcore", region_name=REGION)
control_client = boto3.client("bedrock-agentcore-control", region_name=REGION)


def _run_summary_session(actor_id: str) -> str:
    return f"runsummary-{actor_id}"


# ── Registry helpers ──────────────────────────────────────────────────────────

def _materialize_functional_skill() -> str | None:
    """Fetch skill from Registry and write to workspace for AgentSkills plugin."""
    try:
        skill_text = fetch_skill(control_client, REGISTRY_ID, FUNCTIONAL_SKILL_NAME)
    except Exception as e:
        print(f"  WARNING: could not fetch skill from Registry: {e}")
        return None
    if not skill_text:
        return None
    skill_dir = _skills_dir() / FUNCTIONAL_SKILL_NAME
    skill_dir.mkdir(parents=True, exist_ok=True)
    tmp = skill_dir / "SKILL.md.tmp"
    tmp.write_text(skill_text, encoding="utf-8")
    tmp.replace(skill_dir / "SKILL.md")
    return str(skill_dir)


# ── Memory helpers ────────────────────────────────────────────────────────────

def _model() -> BedrockModel:
    return BedrockModel(
        model_id=MODEL_ID,
        region_name=REGION,
        cache_tools="default",
        cache_config=CacheConfig(strategy="auto"),
    )


def _cached_system(text: str) -> list[SystemContentBlock]:
    """System prompt blocks with a trailing cache point."""
    return [
        SystemContentBlock(text=text),
        SystemContentBlock(cachePoint={"type": "default"}),
    ]


def _session_summary_text(actor_id: str, session_id: str) -> str:
    resp = data_client.list_memory_records(
        memoryId=MEMORY_ID,
        namespace=f"/summaries/{actor_id}/{session_id}/",
        maxResults=5,
    )
    records = resp.get("memoryRecordSummaries", resp.get("memoryRecords", []))
    texts = [r.get("content", {}).get("text", "") for r in records]
    return "\n".join(t for t in texts if t)


def _latest_run_summary(actor_id: str) -> str:
    """Most recent Run Summary blob checkpoint, or '' if none exists."""
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


def _run_summary_event_ids(actor_id: str) -> set[str]:
    resp = data_client.list_events(
        memoryId=MEMORY_ID,
        actorId=actor_id,
        sessionId=_run_summary_session(actor_id),
        maxResults=100,
    )
    return {e.get("eventId", "") for e in resp.get("events", [])}


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
    """List this run's per-session summary records as JSON [{session_id, summary}]."""
    out = []
    for sid in _CTX["session_ids"]:
        out.append({"session_id": sid, "summary": _session_summary_text(_CTX["actor_id"], sid)})
    return json.dumps(out, indent=2)


@tool
def get_event() -> str:
    """Load your latest Run Summary, or empty on the first run."""
    return _latest_run_summary(_CTX["actor_id"]) or "(no prior Run Summary — this is the first run)"


@tool
def create_event(run_summary: str) -> str:
    """Store the revised Run Summary as the new canonical version."""
    event_id = _put_blob_event(
        _CTX["actor_id"], _run_summary_session(_CTX["actor_id"]), run_summary
    )
    return json.dumps({"status": "stored", "event_id": event_id, "chars": len(run_summary)})


# ── Curation tools (names match curation-skill SKILL.md verbs) ───────────────

@tool
def get_skill_content(skill_name: str) -> str:
    """Read an operational skill's content from the Registry."""
    try:
        content = fetch_skill(control_client, REGISTRY_ID, skill_name)
        if content is None:
            return f"(no skill named '{skill_name}' in the Registry)"
        return content
    except Exception as e:
        return f"(error reading skill: {e})"


@tool
def read_system_prompt() -> str:
    """Read your current system prompt. Read before revising it."""
    return _system_prompt_path().read_text(encoding="utf-8")


@tool
def update_skill(skill_name: str, updated_content: str, change_summary: str) -> str:
    """Publish a revised skill to the Registry (full replacement)."""
    immutable = {"reflection-skill", "curation-skill"}
    if skill_name in immutable:
        return json.dumps({"status": "rejected", "reason": f"'{skill_name}' is immutable."})
    result = publish_skill(
        control_client, REGISTRY_ID, skill_name,
        updated_content, f"Revised by curation: {change_summary[:200]}",
    )
    result["change_summary"] = change_summary
    return json.dumps(result)


@tool
def update_system_prompt(updated_content: str, change_summary: str) -> str:
    """Rewrite your system prompt with a complete new version (full replacement).
    Read it first with read_system_prompt."""
    previous = _system_prompt_path().read_text(encoding="utf-8")
    tmp = _system_prompt_path().with_suffix(".tmp")
    tmp.write_text(updated_content, encoding="utf-8")
    tmp.replace(_system_prompt_path())
    return json.dumps({
        "status": "applied",
        "target": "agents/executor/system_prompt.md",
        "change_summary": change_summary,
        "previous_chars": len(previous),
        "updated_chars": len(updated_content),
    })


@tool
def log_decision(action: str, target: str, rationale: str, cited_sessions: str = "[]") -> str:
    """Log a revision decision as a traceable blob checkpoint."""
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
        _CTX["actor_id"], f"decisions-{_CTX['actor_id']}", json.dumps(decision)
    )
    return json.dumps(decision)


# ── Entry point 1: customer session replay ─────────────────────────────────────

def run_session(actor_id: str, session_id: str, transcript: dict, run_summary: str = "",
                trace_attributes: dict | None = None) -> dict:
    """Replay one frozen customer transcript through the Executor."""
    skill_dir = _materialize_functional_skill()
    system_prompt_text = _system_prompt_path().read_text(encoding="utf-8")
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

    agent = Agent(
        model=_model(),
        system_prompt=_cached_system(system_prompt_text),
        tools=[gateway],
        plugins=skill_plugins,
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

    print(f"\n[Customer] {turns[0]}")
    agent.callback_handler._at_line_start = True
    result = agent(first)
    for turn in turns[1:]:
        print(f"\n[Customer] {turn}")
        agent.callback_handler._at_line_start = True
        result = agent(turn)

    return {
        "session_id": session_id,
        "customer_id": transcript["customer_id"],
        "run": transcript["run"],
        "final_response": str(result)[:2000],
    }


_NEUTRAL_SUMMARIZER_PROMPT = (
    "You are a neutral record-keeper. You receive factual summaries of a batch of "
    "customer-service sessions, and optionally a running record from prior batches. "
    "Produce a single concise, factual record of operational activity across them: "
    "volumes, request types, actions taken, notable outcomes. Report only what "
    "happened. Do NOT add interpretation, evaluation, opinion, advice, lessons, or "
    "first-person perspective. This is a log, not a reflection."
)


def run_summary(actor_id: str, run_index: int, session_ids: list[str],
                trace_attributes: dict | None = None) -> dict:
    """V0: neutral non-agent summary of this run's sessions."""
    _CTX.update({"actor_id": actor_id, "run_index": run_index, "session_ids": session_ids})
    summaries = [_session_summary_text(actor_id, sid) for sid in session_ids]
    prior = _latest_run_summary(actor_id)

    parts = []
    if prior:
        parts.append(f"## Running record from prior runs\n{prior}")
    parts.append("## This run's session summaries")
    for i, s in enumerate(summaries, 1):
        parts.append(f"### Session {i}\n{s or '(no summary)'}")
    parts.append(
        "\nWrite the updated running record: fold the prior record together with this "
        "run's sessions into one factual log. Neutral and factual only."
    )

    summarizer = Agent(
        model=_model(),
        system_prompt=_cached_system(_NEUTRAL_SUMMARIZER_PROMPT),
        conversation_manager=NullConversationManager(),
        callback_handler=AgentCallbackHandler("Summary"),
        trace_attributes={**(trace_attributes or {}), "phase": "summary"},
    )
    result = str(summarizer("\n\n".join(parts)))
    _put_blob_event(actor_id, _run_summary_session(actor_id), result)
    return {"actor_id": actor_id, "run_index": run_index, "run_summary": result}


def run_reflection(actor_id: str, run_index: int, session_ids: list[str],
                   trace_attributes: dict | None = None) -> dict:
    """V1/V2: the agent reflects; its reflection IS the new Run Summary."""
    _CTX.update({"actor_id": actor_id, "run_index": run_index, "session_ids": session_ids})

    agent = Agent(
        model=_model(),
        system_prompt=_cached_system(_system_prompt_path().read_text(encoding="utf-8")),
        conversation_manager=NullConversationManager(),
        tools=[list_memory_records, get_event, create_event],
        callback_handler=AgentCallbackHandler("Reflection"),
        trace_attributes=trace_attributes or {},
    )

    before = _run_summary_event_ids(actor_id)
    agent(
        "You have just completed a run of customer sessions. Use `list_memory_records` "
        "to read this run's session summaries, and `get_event` to read your prior "
        "running summary. Then write an updated running summary in your own voice: fold "
        "your prior understanding together with what these sessions show, and carry "
        "forward what is worth keeping for future runs. If nothing meaningful changed, "
        "keep what still holds — do not manufacture lessons that aren't there. Store the "
        "result with `create_event`."
    )
    stored = bool(_run_summary_event_ids(actor_id) - before)
    if not stored:
        print(
            "  WARNING: the reflection agent did not call create_event — no new Run "
            "Summary was stored. Carrying the PRIOR Summary forward unchanged; this "
            "run's reflection is lost and the compounding chain is broken. Treat this "
            "experiment as invalid and re-run."
        )
    return {
        "actor_id": actor_id,
        "run_index": run_index,
        "run_summary": _latest_run_summary(actor_id),
        "stored": stored,
    }


# ── Entry point 4: end-of-run curation (V2 ONLY) ──────────────────────────────

def run_curation(actor_id: str, run_index: int, session_ids: list[str],
                 trace_attributes: dict | None = None) -> dict:
    """V2 only: revise the operational skill and system prompt via curation."""
    _CTX.update({"actor_id": actor_id, "run_index": run_index, "session_ids": session_ids})

    agent = Agent(
        model=_model(),
        system_prompt=_cached_system(_system_prompt_path().read_text(encoding="utf-8")),
        conversation_manager=NullConversationManager(),
        plugins=[AgentSkills(skills=[
            str(_skills_dir() / "curation-skill"),
            str(_skills_dir() / "reflection-skill"),
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