"""Reflector — the Agent evaluates its prior curation decisions (V2).

Modeled on Part Three's reflection-skill pattern: reviews prior decisions against
this run's session outcomes, identifies reasoning patterns, and logs findings.
The Curator reads these findings via read_decisions to inform its next cycle.

This is NOT belief authoring (that's the Narrator). This is metacognitive
self-evaluation — "did my changes work? Am I falling into patterns?"
"""

import json
import uuid
from datetime import datetime, timezone

from strands import Agent
from strands.agent.conversation_manager import NullConversationManager
from strands.tools import tool
from strands.vended_plugins.skills import AgentSkills

from agents._shared import (
    model, cached_system, system_prompt_path, skills_dir, MEMORY_ID, data_client,
)
from agents.services.callback import AgentCallbackHandler
from agents.services.memory import session_summary_text, put_blob_event


# ── Module state set per invocation ──

_CTX = {"actor_id": "", "run_index": 0, "session_ids": []}


# ── Tools ──

@tool
def list_memory_records() -> str:
    """List this run's per-session summary records as JSON [{session_id, summary}]."""
    out = []
    for sid in _CTX["session_ids"]:
        out.append({"session_id": sid, "summary": session_summary_text(_CTX["actor_id"], sid)})
    return json.dumps(out, indent=2)


@tool
def read_decisions() -> str:
    """Read your prior curation decisions as JSON, across all earlier runs.

    Each record carries the run it was made in (`run_index`), the action, the
    target, the rationale, and any cited sessions. Use this to review whether
    past revisions produced good outcomes, and to spot patterns in your own
    judgment across runs. Returns [] on the first run.
    """
    actor_id = _CTX["actor_id"]
    resp = data_client.list_events(
        memoryId=MEMORY_ID,
        actorId=actor_id,
        sessionId=f"decisions-{actor_id}",
        maxResults=100,
    )
    out = []
    for event in resp.get("events", []):
        for item in event.get("payload", []):
            blob = item.get("blob")
            if not blob:
                continue
            try:
                out.append(json.loads(blob) if isinstance(blob, str) else blob)
            except (json.JSONDecodeError, TypeError):
                continue
    return json.dumps(out, indent=2)


@tool
def log_decision(action: str, target: str, rationale: str, cited_sessions: str = "[]") -> str:
    """Log a reflection finding as a traceable blob checkpoint."""
    decision = {
        "decision_id": f"d-{uuid.uuid4().hex[:8]}",
        "run_index": _CTX["run_index"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "target": target,
        "rationale": rationale,
        "cited_sessions": json.loads(cited_sessions) if cited_sessions else [],
    }
    put_blob_event(
        _CTX["actor_id"], f"decisions-{_CTX['actor_id']}", json.dumps(decision)
    )
    return json.dumps(decision)


# ── Entry point ──

def reflect(actor_id: str, run_index: int, session_ids: list[str],
            trace_attributes: dict | None = None) -> dict:
    """Evaluate prior curation decisions against this run's outcomes.

    Logs findings via log_decision(action='self_reflection'). The Curator
    reads these via read_decisions in its subsequent cycle.

    Returns {"actor_id", "run_index", "response"}.
    """
    _CTX.update({"actor_id": actor_id, "run_index": run_index, "session_ids": session_ids})

    agent = Agent(
        model=model(),
        system_prompt=cached_system(system_prompt_path().read_text(encoding="utf-8")),
        conversation_manager=NullConversationManager(),
        plugins=[AgentSkills(skills=[str(skills_dir() / "reflection-skill")])],
        tools=[list_memory_records, read_decisions, log_decision],
        callback_handler=AgentCallbackHandler("Reflector"),
        trace_attributes=trace_attributes or {},
    )

    result = agent(
        "You have just completed a run of customer sessions. Follow the reflection-skill "
        "procedure: read your prior curation decisions with `read_decisions`, read this "
        "run's session summaries with `list_memory_records`, and evaluate whether your "
        "prior changes produced good outcomes. Identify reasoning patterns in your own "
        "judgment. Log your findings with `log_decision` (action='self_reflection'). "
        "If no prior decisions exist (first run), log that and proceed — there is nothing "
        "to evaluate yet."
    )
    return {"actor_id": actor_id, "run_index": run_index, "response": str(result)[:3000]}
