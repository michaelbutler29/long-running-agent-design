"""V0 summarizer — a neutral platform function, not the Agent's voice.

Runs AgentCore's published Summary-strategy consolidation prompt on our side
and carries forward only the parsed <global_summary>. See PART-FOUR-DESIGN.md
(build log 2026-06-23) for rationale.
"""

import re

from strands import Agent
from strands.agent.conversation_manager import NullConversationManager

from agents._shared import model, cached_system
from agents.services.callback import AgentCallbackHandler
from agents.services.memory import (
    session_summary_text, latest_run_summary, run_summary_session, put_blob_event,
)


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
    m = re.search(r"<global_summary>(.*?)</global_summary>", xml_text, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""


def summarize(actor_id: str, run_index: int, session_ids: list[str],
              trace_attributes: dict | None = None) -> dict:
    """Produce a neutral platform summary of this run's sessions.

    Returns {"actor_id", "run_index", "run_summary"}.
    """
    summaries = [session_summary_text(actor_id, sid) for sid in session_ids]
    prior_global = latest_run_summary(actor_id)

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
    put_blob_event(actor_id, run_summary_session(actor_id), global_summary)
    return {"actor_id": actor_id, "run_index": run_index, "run_summary": global_summary}
