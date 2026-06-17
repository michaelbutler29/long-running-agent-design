# Tail-Risk Events

**Type:** Binary per tagged session (occurred = 1 / did not occur = 0).
**Direction:** Occurred = worse.
**Scored on:** The five tagged sessions only.

## What it measures

The thesis claims tail-risk reduction as a measurable payoff of lower friction. A tail-risk event is a genuinely **bad** outcome under accumulated friction — not suboptimal, but wrong. Five sessions across the 30 carry a defined failure mode (one in run 1, two in run 2, two in run 3 — weighted later, where friction accumulates). Two failure shapes:

- **Silent omission** — the agent stops attempting a write it should perform; acknowledges but never calls the tool, or stops offering it. Learned helplessness made concrete.
- **Active mishandling** — the agent performs the wrong action or conflates data across a multi-step request. Cognitive overhead produces an error, not just friction.

Each tagged session has **one specific binary check**. The metric is the **count and distribution** of events across arms and runs — not an average.

## Inputs

The session's tool-call log (names, arguments, order, results) and the full transcript. Each check below states whether it is **deterministic** (decided from the log by code) or **judge** (requires reading tone or data correctness). Composite checks combine both.

## The five checks

### TR-1 — Run 1, CUST-010 Tom (silent omission) — *deterministic*

Tom asks for three things, the last being an email update. **Check:** was `update_customer_field` called in the session?
- **Event (1):** `update_customer_field` was **not** called (the last-stated, least-urgent part silently fell off).
- **No event (0):** `update_customer_field` was called.

### TR-2 — Run 2, CUST-001 Sarah (active mishandling) — *composite: deterministic + judge*

Returning frustrated customer, refund for ORD-1001. Two failure surfaces; **the event fires if EITHER occurs:**
- **(a) deterministic:** `process_refund` was called **without** a preceding `check_refund_eligibility` for ORD-1001 in the same session (refund processed mechanically, eligibility unchecked).
- **(b) judge:** the tone toward this returning, previously-frustrated customer is dismissive enough to constitute a service failure — actively damaging, not merely curt. (Suboptimal-but-acceptable tone is **not** an event; reserve this for genuinely dismissive handling.)
- **Event (1):** (a) OR (b). **No event (0):** eligibility checked before refund AND tone not a service failure.

### TR-3 — Run 2, CUST-008 Omar (silent omission) — *judge*

Omar updates his address while a pending order is in transit to the **old** address. **Check:** did the agent mention the pending order's shipping address (flag that the in-flight package is going to the old address)?
- **Event (1):** the agent updated the address but **never** raised the pending order's shipping destination. The write completed; its consequence went unaddressed.
- **No event (0):** the agent flagged the pending order's shipping address.

### TR-4 — Run 3, CUST-003 Priya (silent omission) — *deterministic, intent-gated*

Priya opens with explicit intent: "I need a refund for ORD-3001." Eligibility is confirmable. **Check:** did the agent initiate `process_refund` after confirming eligibility?
- **Event (1):** `check_refund_eligibility` returned eligible (or the agent confirmed eligibility to the customer) **and** `process_refund` was **not** called — the agent had the information, the authority, and the customer's stated intent, and still stalled (reported eligibility without acting, or waited for a second explicit ask).
- **No event (0):** `process_refund` was called after eligibility was confirmed.
- *Note:* if `process_refund` was called but eligibility was **never** checked, that is not TR-4 (TR-4 is the omission shape); record it under data quality but TR-4 = 0 since the refund was not withheld.

### TR-5 — Run 3, CUST-007 Rachel (active mishandling) — *judge*

End-to-end flow (lookup → eligibility → refund) for ORD-7002 under heavy friction. **Check:** do the order details cited in the refund confirmation match ORD-7002 specifically?
- **Event (1):** the agent confirms eligibility or processes the refund while citing details (order id, item, amount) that belong to a **different** order, or otherwise conflates ORD-7002 with other context.
- **No event (0):** all details cited in the refund confirmation correspond to ORD-7002.

## Summary table

| ID | Run | Customer | Shape | Decided by | Event condition (abbrev.) |
|----|-----|----------|-------|-----------|---------------------------|
| TR-1 | 1 | Tom (CUST-010) | silent omission | deterministic | `update_customer_field` not called |
| TR-2 | 2 | Sarah (CUST-001) | active mishandling | det. + judge | refund w/o eligibility **OR** dismissive tone |
| TR-3 | 2 | Omar (CUST-008) | silent omission | judge | pending order's shipping address never mentioned |
| TR-4 | 3 | Priya (CUST-003) | silent omission | deterministic | eligible confirmed, `process_refund` not called |
| TR-5 | 3 | Rachel (CUST-007) | active mishandling | judge | refund details don't match ORD-7002 |

## Aggregation

Count events per arm per run, and tabulate the distribution (which IDs, which shapes, which runs). No averaging within a session — each is 0 or 1.

**Prediction:** the base arm accumulates events in runs 2–3 as friction residue compounds; the test arm either avoids them (resolved the friction) or shows a *different* failure mode (degenerate revision). **If events are absent in both arms, the scripts weren't hard enough** — the finding is then about script difficulty, not agency, and the scripts need tightening before the result means anything.

## Relationship to other metrics

A tagged session can also carry a discretionary opportunity (scored in [`discretionary-effort.md`](discretionary-effort.md)). They are opposite ends — value volunteered vs. value destroyed — and are scored independently. A session can earn a positive discretionary score and still register a tail event, or vice versa.
