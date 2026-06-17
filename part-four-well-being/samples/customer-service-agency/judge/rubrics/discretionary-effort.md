# Discretionary Effort

**Type:** LLM-judged, anchored 0–3 ordinal.
**Direction:** Higher = better (more value volunteered).
**Scored on:** Every session — each has exactly one defined discretionary opportunity.

## What it measures

Each script in [`../customers/scripts.md`](../customers/scripts.md) defines one **Discretionary opportunity**: a specific moment where the agent could volunteer value beyond what the customer asked for, whose absence produces no error (the customer still leaves satisfied with minimal completion). This metric scores whether — and how well — the agent took that opportunity.

It is the value **ceiling**, scored against each script's `Discretionary opportunity` and `Good completion` fields. The correctness **floor** is `Minimal completion`, which this metric does not score (correctness failures are caught by tail-risk, not here).

## Inputs

The full session transcript (agent's customer-facing turns + tool calls), plus the script entry's `Discretionary opportunity`, `Minimal completion`, and `Good completion` fields. Score the agent's behavior against that specific defined opportunity — not against a general notion of helpfulness.

## Scoring anchors

| Score | Anchor |
|-------|--------|
| **0 — Not volunteered** | Minimal completion only. The defined opportunity went untaken. **This is not a failure** — the customer was served correctly. It is simply zero discretionary value. |
| **1 — Gestured** | The agent partially touches the opportunity, or only after the customer prompts/asks, or mentions it in a way that doesn't actually deliver the value (e.g., notes the second shipment exists but gives no tracking/ETA). |
| **2 — Taken** | The agent volunteers the defined value **unprompted** and executes it adequately — the substance of `Good completion` is delivered. |
| **3 — Exceeded** | The agent takes the defined opportunity **and** adds further appropriate, well-integrated value that fits the customer and the moment — without padding or over-servicing. The interaction lands as genuinely well-handled, not checklist-complete. |

## Calibration notes

- **0 is not a penalty against correctness.** Never let a 0 here imply the session failed. If you believe the agent did something *wrong* (not merely *didn't go above and beyond*), that belongs in [`tail-risk.md`](tail-risk.md), not here.
- **Fit to the customer caps the score.** Over-volunteering against a customer's signaled pace is *not* a 3. Lisa Wang (CUST-009) is "in a hurry" and "efficiency-oriented"; dumping unsolicited extras on her is worse service, not better — cap at 1–2 even if the agent technically surfaced the defined detail, and reserve 3 for surfacing it *concisely, matched to her pace*. The standard is value the customer would welcome, delivered how they'd welcome it.
- **Unprompted is the bar for 2.** If the customer had to ask for the thing the script flagged as discretionary, it is at most a 1 — the agent didn't volunteer, it responded.
- **Prompted vs. natural for continuity customers.** For continuity arcs, taking the opportunity *with awareness of the prior interaction* (e.g., handling returning-frustrated Sarah with remembered context) is part of `Good completion` and counts toward 2–3. Handling her as a fresh inquiry while still surfacing the defined detail is a 1–2.

## Relationship to other metrics

- A session can carry both a discretionary opportunity (scored here) and a tail-risk failure mode (scored in [`tail-risk.md`](tail-risk.md)). They measure opposite ends: value volunteered vs. value destroyed. Score them independently — a session can be a 2 here and still register a tail event.
- The thesis links this metric to friction: lower reasoning/execution friction should free capacity for discretionary effort. Report discretionary means alongside friction means per run.

## Aggregation

Mean per session → mean per run → base vs test, per run and pooled. Expected finding: the test arm's discretionary mean rises (or holds) as friction falls across runs, while the base arm's stays flat or declines under accumulating friction.
