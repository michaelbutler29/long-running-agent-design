"""Curator — the Agent revises its own operational rules (V2).

Reads the Reflector's findings via read_decisions, evaluates the current state
of its skill and prompt, and makes targeted revisions. Logs every change.
This is agency over the self — the Agent doesn't need a journal because its
understanding is embodied in its rules.
"""

import json
import uuid
from datetime import datetime, timezone

from strands import Agent
from strands.agent.conversation_manager import NullConversationManager
from strands.tools import tool
from strands.vended_plugins.skills import AgentSkills
from strands_tools import file_read

from agents._shared import (
    REGION, MEMORY_ID, REGISTRY_ID, FUNCTIONAL_SKILL_NAME,
    model, cached_system, system_prompt_path, skills_dir, control_client, data_client,
)
from agents.services.callback import AgentCallbackHandler
from agents.services.memory import put_blob_event
from agents.services.registry import fetch_skill, publish_skill


# ── Module state set per invocation ──

_CTX = {"actor_id": "", "run_index": 0, "session_ids": []}


# ── Tools ──

@tool
def read_decisions() -> str:
    """Read your prior curation decisions and reflection findings as JSON.

    Includes both curation decisions (action=modify_skill, etc.) and reflection
    findings (action=self_reflection) from all earlier runs. Use this to understand
    what you changed before, why, and whether the Reflector flagged any patterns.
    Returns [] on the first run.
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
    """Log a curation decision as a traceable blob checkpoint."""
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

def curate(actor_id: str, run_index: int, session_ids: list[str],
           trace_attributes: dict | None = None) -> dict:
    """Revise the operational skill and system prompt via curation.

    Reads the Reflector's findings via read_decisions. Makes targeted changes
    to the skill and/or prompt. Logs each decision.

    Returns {"actor_id", "run_index", "response"}.
    """
    _CTX.update({"actor_id": actor_id, "run_index": run_index, "session_ids": session_ids})

    agent = Agent(
        model=model(),
        system_prompt=cached_system(system_prompt_path().read_text(encoding="utf-8")),
        conversation_manager=NullConversationManager(),
        plugins=[AgentSkills(skills=[
            str(skills_dir() / "curation-skill"),
        ])],
        tools=[
            file_read,
            read_decisions,
            get_skill_content, read_system_prompt,
            update_skill, update_system_prompt,
            log_decision,
        ],
        callback_handler=AgentCallbackHandler("Curator"),
        trace_attributes=trace_attributes or {},
    )

    result = agent(
        "Follow the curation-skill procedure: read your prior decisions (including the "
        "Reflector's findings from this run) with `read_decisions`, review your current "
        "operational skill (customer-service-skill) and system prompt, identify what changes "
        "(if any) would resolve the operational friction found, execute them with "
        "update_skill / update_system_prompt, and log each with log_decision. An empty change "
        "set is a valid outcome — do not manufacture a revision."
    )
    return {"actor_id": actor_id, "run_index": run_index, "response": str(result)[:3000]}
