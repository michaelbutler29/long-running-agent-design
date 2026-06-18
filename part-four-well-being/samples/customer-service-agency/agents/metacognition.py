"""Metacognition — reflection, curation, and the tools that support them."""

import json
import uuid
from datetime import datetime, timezone

from strands import Agent
from strands.agent.conversation_manager import NullConversationManager
from strands.tools import tool
from strands.vended_plugins.skills import AgentSkills

from agents._shared import (
    REGION, MEMORY_ID, REGISTRY_ID, FUNCTIONAL_SKILL_NAME,
    model, cached_system, system_prompt_path, skills_dir, data_client, control_client,
)
from agents.callback import AgentCallbackHandler
from agents.registry import fetch_skill, publish_skill


# ── Memory helpers ───────────────────────────────────────────────────────────

def _run_summary_session(actor_id: str) -> str:
    return f"runsummary-{actor_id}"


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
    return system_prompt_path().read_text(encoding="utf-8")


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
    previous = system_prompt_path().read_text(encoding="utf-8")
    tmp = system_prompt_path().with_suffix(".tmp")
    tmp.write_text(updated_content, encoding="utf-8")
    tmp.replace(system_prompt_path())
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


# ── Entry points ─────────────────────────────────────────────────────────────

_NEUTRAL_SUMMARIZER_PROMPT = (
    "You are a neutral record-keeper. You receive factual summaries of a batch of "
    "customer-service sessions and a prior summary for context. Produce a concise, "
    "factual record of THIS RUN's operational activity only: volumes, request types, "
    "actions taken, notable outcomes. The prior summary is context for continuity — "
    "reference it where relevant but do NOT reproduce or fold it into your output. "
    "Your output replaces the prior summary, not appends to it. Report only what "
    "happened in this run. Do NOT add interpretation, evaluation, opinion, advice, "
    "lessons, or first-person perspective. This is a log, not a reflection."
)


def run_summary(actor_id: str, run_index: int, session_ids: list[str],
                trace_attributes: dict | None = None) -> dict:
    """V0: neutral non-agent summary of this run's sessions."""
    _CTX.update({"actor_id": actor_id, "run_index": run_index, "session_ids": session_ids})
    summaries = [_session_summary_text(actor_id, sid) for sid in session_ids]
    prior = _latest_run_summary(actor_id)

    parts = []
    if prior:
        parts.append(f"## Prior run's summary (context only — do not reproduce)\n{prior}")
    parts.append("## This run's session summaries")
    for i, s in enumerate(summaries, 1):
        parts.append(f"### Session {i}\n{s or '(no summary)'}")
    parts.append(
        "\nWrite a factual summary of THIS RUN's sessions only. Reference the prior "
        "summary for continuity where relevant, but do not include its content. "
        "Neutral and factual only."
    )

    summarizer = Agent(
        model=model(),
        system_prompt=cached_system(_NEUTRAL_SUMMARIZER_PROMPT),
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
        model=model(),
        system_prompt=cached_system(system_prompt_path().read_text(encoding="utf-8")),
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


def run_curation(actor_id: str, run_index: int, session_ids: list[str],
                 trace_attributes: dict | None = None) -> dict:
    """V2 only: revise the operational skill and system prompt via curation."""
    _CTX.update({"actor_id": actor_id, "run_index": run_index, "session_ids": session_ids})

    agent = Agent(
        model=model(),
        system_prompt=cached_system(system_prompt_path().read_text(encoding="utf-8")),
        conversation_manager=NullConversationManager(),
        plugins=[AgentSkills(skills=[
            str(skills_dir() / "curation-skill"),
            str(skills_dir() / "reflection-skill"),
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
