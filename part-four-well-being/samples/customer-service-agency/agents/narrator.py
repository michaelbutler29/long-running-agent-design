"""Narrator — the Agent authors its own beliefs (V1).

The narrator reads session summaries and its prior Run Summary, then writes an
updated Run Summary in the Agent's own voice. It decides what matters, what to
carry forward, and what to release. This is awareness without agency — the Agent
cannot change its rules, but it chooses the lens through which it sees future work.
"""

import json

from strands import Agent
from strands.agent.conversation_manager import NullConversationManager
from strands.tools import tool
from strands.vended_plugins.skills import AgentSkills

from agents._shared import model, cached_system, system_prompt_path, skills_dir
from agents.services.callback import AgentCallbackHandler
from agents.services.memory import (
    session_summary_text, latest_run_summary, run_summary_session,
    run_summary_event_ids, put_blob_event,
)


# ── Module state set per invocation (read by the @tool wrappers) ──

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
def get_event() -> str:
    """Load your latest Run Summary, or empty on the first run."""
    return latest_run_summary(_CTX["actor_id"]) or "(no prior Run Summary — this is the first run)"


@tool
def create_event(run_summary: str) -> str:
    """Store the revised Run Summary as the new canonical version."""
    event_id = put_blob_event(
        _CTX["actor_id"], run_summary_session(_CTX["actor_id"]), run_summary
    )
    return json.dumps({"status": "stored", "event_id": event_id, "chars": len(run_summary)})


# ── Entry point ──

def narrate(actor_id: str, run_index: int, session_ids: list[str],
            trace_attributes: dict | None = None) -> dict:
    """The Agent reflects in its own voice; its narration IS the new Run Summary.

    Returns {"actor_id", "run_index", "run_summary", "stored"}.
    """
    _CTX.update({"actor_id": actor_id, "run_index": run_index, "session_ids": session_ids})

    agent = Agent(
        model=model(),
        system_prompt=cached_system(system_prompt_path().read_text(encoding="utf-8")),
        conversation_manager=NullConversationManager(),
        plugins=[AgentSkills(skills=[str(skills_dir() / "narrator-skill")])],
        tools=[list_memory_records, get_event, create_event],
        callback_handler=AgentCallbackHandler("Narrator"),
        trace_attributes=trace_attributes or {},
    )

    before = run_summary_event_ids(actor_id)
    agent(
        "You have just completed a run of customer sessions. Follow the narrator-skill "
        "procedure to consolidate this run's experience into your Run Summary."
    )
    stored = bool(run_summary_event_ids(actor_id) - before)
    if not stored:
        print(
            "  WARNING: the narrator did not call create_event — no new Run "
            "Summary was stored. Carrying the PRIOR Summary forward unchanged; this "
            "run's narration is lost and the compounding chain is broken."
        )
    return {
        "actor_id": actor_id,
        "run_index": run_index,
        "run_summary": latest_run_summary(actor_id),
        "stored": stored,
    }
