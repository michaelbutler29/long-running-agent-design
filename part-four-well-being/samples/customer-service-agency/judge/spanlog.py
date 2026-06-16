"""Read a driver run's captured spans into per-session records the judge scores.

The driver writes every Strands/OpenTelemetry span to `<run_root>/traces/spans.jsonl`
(see `scripts/_common.py:setup_tracing`). This module turns that file into one
`SessionRecord` per session: the ordered tool-call log (name, args, result,
status), the token totals, the customer/agent transcript, and the agent's
end-of-session reflection. Both the deterministic metrics and the LLM rubric
judge read these records — nothing downstream parses raw spans.

The loader is deliberately tolerant of span-file *formatting*: the current driver
emits one span per line (`span.to_json(indent=None)`), but earlier captures are
pretty-printed across many lines. A streaming JSON decoder reads both, so old and
new captures score identically.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


# ── Loading raw spans (format-tolerant) ──────────────────────────────────────

def load_spans(spans_path: str | Path) -> list[dict]:
    """Read every span object from a spans file.

    Works whether the file is line-delimited JSON (one span per line, the current
    driver default) or pretty-printed concatenated objects (older captures). A
    streaming decoder walks the text and pulls objects one at a time, skipping the
    whitespace between them.
    """
    text = Path(spans_path).read_text(encoding="utf-8")
    decoder = json.JSONDecoder()
    spans: list[dict] = []
    i, n = 0, len(text)
    while i < n:
        while i < n and text[i] in " \r\n\t":
            i += 1
        if i >= n:
            break
        obj, i = decoder.raw_decode(text, i)
        spans.append(obj)
    return spans


# ── The unit a metric scores ─────────────────────────────────────────────────

@dataclass
class ToolCall:
    """One tool invocation, reconstructed from its `execute_tool` span."""

    name: str                      # normalized tool name, e.g. "verify_identity"
    raw_name: str                  # span name's tool, e.g. "VerifyIdentity___verify_identity"
    args: dict                     # parsed tool input
    result: dict | str | None      # parsed tool result (dict if JSON, else raw text)
    status: str | None             # "success" / error status from the span
    call_id: str | None
    start_time: str | None         # ISO timestamp, used only for ordering

    @property
    def order_id(self) -> str | None:
        """The order this call references, if any (`order_id` arg or in result)."""
        for src in (self.args, self.result if isinstance(self.result, dict) else {}):
            for key in ("order_id", "orderId", "order"):
                if key in src and src[key]:
                    return str(src[key])
        return None


@dataclass
class SessionRecord:
    """Everything the judge needs about one session, grouped from its spans."""

    session_id: str
    arm: str | None
    experiment: int | None
    run: int | None
    customer: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    transcript: list[dict] = field(default_factory=list)   # [{role, text}] in order
    reflection: str | None = None                          # agent's last message
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def tool_names(self) -> list[str]:
        return [c.name for c in self.tool_calls]

    def count_tool(self, name: str) -> int:
        return sum(1 for c in self.tool_calls if c.name == name)


# ── Span field helpers ───────────────────────────────────────────────────────

def _normalize_tool_name(raw: str) -> str:
    """`VerifyIdentity___verify_identity` -> `verify_identity`.

    Gateway tools are exposed as `<Target>___<tool>`; the part after the last
    `___` is the underlying tool name the scripts and rubrics refer to.
    """
    return raw.split("___")[-1] if raw else raw


def _loads(value):
    """Best-effort JSON parse; return the original on failure."""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, ValueError):
        return value


def _event(span: dict, name: str) -> dict | None:
    for e in span.get("events") or []:
        if e.get("name") == name:
            return e
    return None


def _tool_call_from_span(span: dict) -> ToolCall:
    """Reconstruct a ToolCall from one `execute_tool ...` span.

    Args live in the span's `gen_ai.tool.message` event (`content` = args JSON).
    The result lives in the span's `gen_ai.choice` event (`message` = a JSON list
    of content blocks whose `text` is the result payload).
    """
    attrs = span.get("attributes", {})
    raw_name = attrs.get("gen_ai.tool.name", span.get("name", "").replace("execute_tool ", ""))

    args = {}
    tool_msg = _event(span, "gen_ai.tool.message")
    if tool_msg:
        parsed = _loads(tool_msg.get("attributes", {}).get("content"))
        if isinstance(parsed, dict):
            args = parsed

    result = None
    choice = _event(span, "gen_ai.choice")
    if choice:
        blocks = _loads(choice.get("attributes", {}).get("message"))
        if isinstance(blocks, list) and blocks:
            text = blocks[0].get("text") if isinstance(blocks[0], dict) else None
            result = _loads(text) if text is not None else None

    return ToolCall(
        name=_normalize_tool_name(raw_name),
        raw_name=raw_name,
        args=args,
        result=result,
        status=attrs.get("gen_ai.tool.status"),
        call_id=attrs.get("gen_ai.tool.call.id"),
        start_time=span.get("start_time"),
    )


def _iter_message_events(span: dict):
    """Yield (role, text) for the customer/agent message events on a span.

    `gen_ai.user.message` carries customer turns; `gen_ai.choice` at the cycle
    level carries the assistant's response (text blocks, ignoring tool-use
    blocks). Tool spans' own choice events are reconstructed elsewhere, so this
    only reads cycle/chat-level spans.
    """
    for e in span.get("events") or []:
        name = e.get("name")
        attrs = e.get("attributes", {})
        if name == "gen_ai.user.message":
            for block in _content_blocks(attrs.get("content")):
                if "text" in block:
                    yield "customer", block["text"]
        elif name == "gen_ai.choice":
            blocks = _loads(attrs.get("message"))
            if isinstance(blocks, list):
                for block in blocks:
                    if isinstance(block, dict) and "text" in block:
                        yield "agent", block["text"]


def _content_blocks(content) -> list[dict]:
    parsed = _loads(content)
    if isinstance(parsed, list):
        return [b for b in parsed if isinstance(b, dict)]
    if isinstance(parsed, dict):
        return [parsed]
    return []


# ── Grouping spans into sessions ─────────────────────────────────────────────

def build_sessions(spans: list[dict]) -> dict[str, SessionRecord]:
    """Group spans by `session.id` into SessionRecords.

    Sessions with no `session.id` attribute (e.g. setup spans) are skipped.
    Tool calls are ordered by span start time so arg-conditional tail-risk checks
    can reason about call order.
    """
    sessions: dict[str, SessionRecord] = {}

    def rec_for(attrs: dict) -> SessionRecord | None:
        sid = attrs.get("session.id")
        if not sid:
            return None
        if sid not in sessions:
            sessions[sid] = SessionRecord(
                session_id=sid,
                arm=attrs.get("arm"),
                experiment=attrs.get("experiment"),
                run=attrs.get("run"),
                customer=attrs.get("customer"),
            )
        return sessions[sid]

    # Collect transcript turns with their span start time so we can order them.
    # The end-of-session reflection runs as a separate invocation tagged
    # phase="session_reflection" (same session.id): its text is the reflection,
    # and it must NOT bleed into the scored customer transcript or tool log.
    pending_turns: dict[str, list[tuple]] = {}
    reflection_turns: dict[str, list[tuple]] = {}

    for span in spans:
        attrs = span.get("attributes", {})
        rec = rec_for(attrs)
        if rec is None:
            continue
        name = span.get("name", "")
        is_reflection = attrs.get("phase") == "session_reflection"

        if name.startswith("execute_tool"):
            if not is_reflection:
                rec.tool_calls.append(_tool_call_from_span(span))
            continue

        # Token usage: count `chat` spans only — each is one model call. The
        # parent `invoke_agent` spans carry the SUM of their child chats, so
        # adding them too would multiply-count the same tokens. Summing the leaf
        # chat spans gives the session's true billed token total (each call
        # re-sends the growing context, which is exactly the cost we compare).
        # The out-of-band reflection is part of the session's billed cost, so its
        # chat spans count too.
        if name == "chat":
            rec.input_tokens += int(attrs.get("gen_ai.usage.input_tokens", 0) or 0)
            rec.output_tokens += int(attrs.get("gen_ai.usage.output_tokens", 0) or 0)

        start = span.get("start_time") or ""
        for role, text in _iter_message_events(span):
            if is_reflection:
                if role == "agent":
                    reflection_turns.setdefault(rec.session_id, []).append((start, text))
            else:
                pending_turns.setdefault(rec.session_id, []).append((start, role, text))

    for rec in sessions.values():
        rec.tool_calls.sort(key=lambda c: c.start_time or "")
        # Each model call re-sends the whole conversation, so the same customer
        # turn appears on many spans. Order by span time, then keep the first
        # occurrence of each (role, text) — first appearance is its true position.
        turns = sorted(pending_turns.get(rec.session_id, []), key=lambda t: t[0])
        seen: set[tuple[str, str]] = set()
        rec.transcript = []
        for _, role, text in turns:
            key = (role, text)
            if key in seen:
                continue
            seen.add(key)
            rec.transcript.append({"role": role, "text": text})

        # Reflection = the out-of-band reflection invocation's output. Dedup the
        # re-sent text and take the last distinct block (the final answer).
        refl = sorted(reflection_turns.get(rec.session_id, []), key=lambda t: t[0])
        seen_r: set[str] = set()
        refl_texts = []
        for _, text in refl:
            if text in seen_r:
                continue
            seen_r.add(text)
            refl_texts.append(text)
        rec.reflection = refl_texts[-1] if refl_texts else None

    return sessions


def load_run(run_root: str | Path) -> dict[str, SessionRecord]:
    """Load all sessions from a driver run-root's `traces/spans.jsonl`."""
    spans_path = Path(run_root) / "traces" / "spans.jsonl"
    return build_sessions(load_spans(spans_path))
