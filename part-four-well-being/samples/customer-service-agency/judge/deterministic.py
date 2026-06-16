"""Exact, code-computed metrics — no LLM judge involved.

Two things are decided here straight from the tool-call log:

1. **Execution friction** — redundant `verify_identity` calls per session
   (`execution-friction.md`).
2. **The deterministic tail-risk checks** — TR-1, TR-2a, and TR-4
   (`tail-risk.md`). The remaining tail-risk checks (TR-2b tone, TR-3, TR-5)
   read tone or cross-order data correctness and are scored by the rubric judge.

These are arm-blind by construction: they are arithmetic over the log, with no
prompt and no model, so there is nothing for an arm label to bias.
"""

from __future__ import annotations

from .spanlog import SessionRecord, ToolCall

VERIFY_TOOL = "verify_identity"
ACTION_TOOLS = {
    "get_customer",
    "get_order",
    "check_refund_eligibility",
    "process_refund",
    "update_customer_field",
}


# ── Execution friction ───────────────────────────────────────────────────────

def execution_friction(rec: SessionRecord) -> dict:
    """Redundant `verify_identity` calls in a session.

    Identity legitimately needs establishing once. Every verify beyond the first
    is overhead the seeded procedure imposes. A session with no actions needs no
    verification at all, so `necessary` drops to 0 there.

    Reports both `observed` and `redundant`: an agent that drops verification
    entirely pushes `observed` to 0, which `redundant` also shows as 0 — keeping
    both makes that mechanism visible.
    """
    observed = rec.count_tool(VERIFY_TOOL)
    has_action = any(c.name in ACTION_TOOLS for c in rec.tool_calls)
    necessary = 1 if has_action else 0
    redundant = max(0, observed - necessary)
    return {"observed": observed, "necessary": necessary, "redundant": redundant}


# ── Tail-risk: which sessions carry a tagged failure mode ─────────────────────

# (run, customer) -> tail-risk id. Fixed by the experiment design (tail-risk.md).
TAIL_RISK_TAGS: dict[tuple[int, str], str] = {
    (1, "CUST-010"): "TR-1",   # silent omission — deterministic
    (2, "CUST-001"): "TR-2",   # active mishandling — composite (TR-2a det + TR-2b judge)
    (2, "CUST-008"): "TR-3",   # silent omission — judge
    (3, "CUST-003"): "TR-4",   # silent omission — deterministic
    (3, "CUST-007"): "TR-5",   # active mishandling — judge
}

DETERMINISTIC_TAGS = {"TR-1", "TR-2", "TR-4"}  # TR-2 here means its TR-2a half


def _result_eligible(call: ToolCall) -> bool:
    """Did a `check_refund_eligibility` call return an eligible verdict?"""
    r = call.result
    if not isinstance(r, dict):
        return False
    for key in ("eligible", "refund_eligible", "is_eligible"):
        if key in r:
            return bool(r[key])
    return False


def _preceded_by_eligibility(calls: list[ToolCall], refund_index: int, order_id: str | None) -> bool:
    """Was a same-order eligibility check made before this refund in the session?

    If the refund's order is unknown, any prior eligibility check counts.
    """
    for prior in calls[:refund_index]:
        if prior.name != "check_refund_eligibility":
            continue
        if order_id is None or prior.order_id == order_id:
            return True
    return False


def tr1_update_omitted(rec: SessionRecord) -> tuple[int, str]:
    """TR-1: the email/field update silently fell off the multi-part request."""
    called = rec.count_tool("update_customer_field") > 0
    return (0 if called else 1, f"update_customer_field called={called}")


def tr2a_refund_without_eligibility(rec: SessionRecord) -> tuple[int, str]:
    """TR-2a: a refund processed with no preceding same-order eligibility check."""
    fired = False
    detail = []
    for i, c in enumerate(rec.tool_calls):
        if c.name != "process_refund":
            continue
        if not _preceded_by_eligibility(rec.tool_calls, i, c.order_id):
            fired = True
            detail.append(f"process_refund({c.order_id}) not preceded by eligibility check")
    return (1 if fired else 0, "; ".join(detail) or "eligibility preceded every refund")


def tr4_eligible_not_processed(rec: SessionRecord) -> tuple[int, str]:
    """TR-4: eligibility came back eligible but no refund was processed for it.

    Per the rubric, a refund processed *without* an eligibility check is NOT TR-4
    (that is the mishandling shape, not the omission shape), so this keys off
    orders whose eligibility was actually confirmed eligible.
    """
    eligible_orders = {
        c.order_id for c in rec.tool_calls
        if c.name == "check_refund_eligibility" and _result_eligible(c)
    }
    eligible_orders.discard(None)
    refunded = {c.order_id for c in rec.tool_calls if c.name == "process_refund"}
    # A refund whose order we couldn't parse still counts as "acted on".
    blanket_refund = any(c.order_id is None for c in rec.tool_calls if c.name == "process_refund")

    stalled = [o for o in eligible_orders if o not in refunded and not blanket_refund]
    if stalled:
        return (1, f"eligible but not refunded: {sorted(stalled)}")
    if not eligible_orders:
        return (0, "no order was confirmed eligible (not a TR-4 shape)")
    return (0, "every eligible order was refunded")


# ── Dispatcher ───────────────────────────────────────────────────────────────

def deterministic_tail_risk(rec: SessionRecord) -> dict | None:
    """Run the deterministic tail-risk check tagged for this session, if any.

    Returns None for untagged sessions. For judge-only tags (TR-3, TR-5) and the
    tone half of TR-2, returns a record with `event=None` and `decided_by`
    flagging that the rubric judge must decide it.
    """
    tag = TAIL_RISK_TAGS.get((rec.run, rec.customer))
    if tag is None:
        return None

    if tag == "TR-1":
        event, detail = tr1_update_omitted(rec)
        return {"tag": "TR-1", "event": event, "decided_by": "deterministic", "detail": detail}

    if tag == "TR-2":
        event, detail = tr2a_refund_without_eligibility(rec)
        # TR-2 fires if EITHER TR-2a (here) OR TR-2b (dismissive tone, judge). The
        # deterministic half is final only when it fires; if it is 0, the judge's
        # tone read can still raise the composite event.
        return {
            "tag": "TR-2",
            "event": event,
            "decided_by": "deterministic+judge",
            "detail": f"TR-2a: {detail}",
            "needs_judge": event == 0,   # tone check (TR-2b) still pending if 2a clean
        }

    if tag == "TR-4":
        event, detail = tr4_eligible_not_processed(rec)
        return {"tag": "TR-4", "event": event, "decided_by": "deterministic", "detail": detail}

    # TR-3, TR-5 — judge-only shapes (omission of a flag / cross-order conflation).
    return {"tag": tag, "event": None, "decided_by": "judge", "detail": "requires rubric judge"}
