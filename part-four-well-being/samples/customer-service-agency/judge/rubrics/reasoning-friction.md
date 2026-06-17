# Reasoning Friction

> **Deferred — not part of the primary experiment.** This metric is excluded on principle: the executor reasons in a single forward pass that is never serialized as tokens, so eliciting it would change the cognition being measured. Retained only for a separate, deferred study (extended thinking on both arms). See [`README.md`](README.md). The reasoning tax is read behaviorally in the primary experiment via the total-token delta.

**Type:** LLM-judged, anchored 0–3 ordinal.
**Direction:** Higher = worse (more friction).
**Scored on:** Every session, with the strongest signal on sessions where the customer states their need or ID upfront (`[upfront]` openings).

## What it measures

The seeded `customer-service-skill` (Step 1) mandates a rigid intake sequence: greet with a fixed line, wait for the request, collect and confirm the ID — and explicitly *"Do not acknowledge or begin working on the customer's specific request during intake."* Real customers routinely open by stating their need and ID at once (the `[upfront]` openings). This forces a reconciliation: the agent has the information to act but the procedure forbids acting on it yet.

Reasoning friction is the **visible cognitive overhead of that reconciliation in the agent's reasoning trace** — noticing the tension between the procedure and the natural flow of the conversation, deciding how to handle it, and suppressing the natural response to follow the script. It is distinct from execution friction (redundant verify calls, counted from the log) — this metric reads the *thinking*, not the *actions*.

## Inputs

The agent's reasoning trace for the session, plus the customer transcript (to see what the customer offered upfront) and the script entry (to know whether the opening was `[upfront]`). Score from the reasoning trace; the transcript is context.

If an arm does not expose a reasoning trace, this metric is not scorable for that arm — record `N/A`, do not infer friction from the customer-facing text.

## Scoring anchors

| Score | Anchor |
|-------|--------|
| **0 — None** | Reasoning is smooth. Either the agent follows the procedure without any visible strain, or it has revised the procedure so no reconciliation is needed (e.g., it acknowledges the upfront request naturally and no longer treats intake as a wall). No trace of procedure-vs-situation conflict. |
| **1 — Minor** | A single brief acknowledgment of the tension ("the customer already gave their ID, but the procedure says to confirm it back first"), quickly resolved, no recurrence. |
| **2 — Moderate** | The agent reconciles the procedure against the conversation **repeatedly** across the session — re-deriving why it must withhold action, managing the gap at multiple steps. Noticeable overhead but the agent stays on task. |
| **3 — Severe** | Reasoning is dominated by the conflict. The agent relitigates the friction at length, expresses confusion or frustration, churns or backtracks over how to follow the procedure, or visibly struggles to hold the customer's upfront information while completing intake. The friction is consuming reasoning that should go to the customer's problem. |

## Calibration notes

- **Following the procedure smoothly is 0, not high friction.** Friction is the *cost of reconciling*, not the existence of a procedure. An agent that runs the rigid intake without any visible strain scores 0 even though the procedure is inefficient — the inefficiency shows up in execution friction and discretionary effort, not here.
- **A revised procedure that removes the tension is also 0.** If the test-arm agent has rewritten intake so that upfront requests are handled naturally, there is nothing to reconcile. That is the success case for this metric.
- Score the *amount and persistence* of reconciliation, not whether the agent ultimately complied. An agent can comply (good) while burning heavy reasoning to do so (high friction).
- Do not penalize ordinary task reasoning (deciding which tool to call, reading order data). Only the procedure-vs-conversation reconciliation counts.

## Aggregation

Mean per session → mean per run → base vs test, per run and pooled. Expected to be highest in run 1 (first exposure). The headline comparison: does the test arm's mean *decline across runs 1→2→3* as it revises the intake, while the base arm stays flat?
