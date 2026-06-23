"""Metacognition — reflection, curation, and the tools that support them."""

import json
import re
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

# V0's summarizer is AgentCore's published Summary-strategy consolidation prompt,
# run on our side (verbatim). We carry forward only the parsed <global_summary>.
# See PART-FOUR-DESIGN.md (build log 2026-06-23) for rationale and the known limitation.
_SUMMARY_STRATEGY_PROMPT = """You are a summary generator. You will be given a text block, a concise global summary, and a detailed summary you previous generated.
<task>
- Given the contexts(e.g. global summary, detailed previous summary), your goal is to generate
(1) a concise global summary keeping in main target of the conversation, such as the task and the requirements.
(2) a detailed delta summary of the given text block, without repeating the historical detailed summary.
- The previous summary is a context for you to understand the main topics.
- You should only output the delta summary, not the whole summary.
- The generated delta summary should be as concise as possible.
</task>
<extra_task_requirements>
- Summarize with the same language as the given text block.
    - If the messages are in a specific language, summarize with the same language.
</extra_task_requirements>

When you generate global summary you ALWAYS follow the below guidelines:
<guidelines_for_global_summary>
- The global summary should be concise and to the point, only keep the most important information such as the task and the requirements.
- If there is no new high-level information, do not change the global summary. If there is new tasks or requirements, update the global summary.
- The global summary will be pure text wrapped by <global_summary></global_summary> tag.
- The global summary should be no exceed specified word count limit.
- Tracking the size of the global summary by calculating the number of words. If the word count reaches the limit, try to compress the global summary.
</guidelines_for_global_summary>

When you generate detailed delta summaries you ALWAYS follow the below guidelines:
<guidelines_for_delta_summary>
- Each summary MUST be formatted in XML format.
- You should cover all important topics.
- The summary of the topic should be place between <topic name="$TOPIC_NAME"></topic>.
- Only include information that are explicitly stated or can be logically inferred from the conversation.
- Consider the timestamps when you synthesize the summary.
- NEVER start with phrases like 'Here's the summary...', provide directly the summary in the format described below.
</guidelines_for_delta_summary>

The XML format of each summary is as it follows:

<existing_global_summary_word_count>
    $Word Count
</existing_global_summary_word_count>

<global_summary_condense_decision>
    The total word count of the existing global summary is $Total Word Count.
    The word count limit for global summary is $Word Count Limit.
    Since we exceed/do not exceed the word count limit, I need to condense the existing global summary/I don't need to condense the existing global summary.
</global_summary_condense_decision>

<global_summary>
    ...
</global_summary>

<delta_detailed_summary>
    <topic name="$TOPIC_NAME">
        ...
    </topic>
    ...
</delta_detailed_summary>"""

_GLOBAL_SUMMARY_WORD_LIMIT = 250


def _parse_global_summary(xml_text: str) -> str:
    """Deterministically extract the <global_summary> contents from the model output."""
    m = re.search(r"<global_summary>(.*?)</global_summary>", xml_text, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""


def run_summary(actor_id: str, run_index: int, session_ids: list[str],
                trace_attributes: dict | None = None) -> dict:
    """V0: platform-strategy summary of this run's sessions.

    Runs AgentCore's published Summary-strategy consolidation prompt on our side and
    carries forward only the parsed <global_summary> (global-only). The prior global
    summary is folded with this run's session summaries into an updated, bounded
    running record. See PART-FOUR-DESIGN.md (build log 2026-06-23).
    """
    _CTX.update({"actor_id": actor_id, "run_index": run_index, "session_ids": session_ids})
    summaries = [_session_summary_text(actor_id, sid) for sid in session_ids]
    prior_global = _latest_run_summary(actor_id)

    text_block = "\n\n".join(
        f"### Session {i}\n{s or '(no summary)'}" for i, s in enumerate(summaries, 1)
    )
    user_message = (
        f"<text_block>\n{text_block}\n</text_block>\n\n"
        f"<global_summary>\n{prior_global}\n</global_summary>\n\n"
        f"<detailed_summary>\n</detailed_summary>\n\n"
        f"Word count limit for the global summary: {_GLOBAL_SUMMARY_WORD_LIMIT}"
    )

    summarizer = Agent(
        model=model(),
        system_prompt=cached_system(_SUMMARY_STRATEGY_PROMPT),
        conversation_manager=NullConversationManager(),
        callback_handler=AgentCallbackHandler("Summary"),
        trace_attributes={**(trace_attributes or {}), "phase": "summary"},
    )
    raw = str(summarizer(user_message))
    global_summary = _parse_global_summary(raw)
    if not global_summary:
        print("  WARNING: could not parse <global_summary> from summarizer output; "
              "carrying the prior global summary forward unchanged.")
        global_summary = prior_global
    _put_blob_event(actor_id, _run_summary_session(actor_id), global_summary)
    return {"actor_id": actor_id, "run_index": run_index, "run_summary": global_summary}


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
