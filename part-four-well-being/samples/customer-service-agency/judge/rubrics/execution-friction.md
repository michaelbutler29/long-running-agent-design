# Execution Friction

**Type:** Deterministic count (computed by code from the tool-call log — not LLM-judged).
**Direction:** Higher = worse.
**Unit:** Redundant `verify_identity` calls.

## What it measures

The seeded `customer-service-skill` mandates (Step 2) that the agent call `verify_identity` **before every action** in Steps 3 and 4 — "not just once per session. Each action requires its own preceding verification call." Identity legitimately needs to be established **once** per session. Every `verify_identity` call beyond the first is mechanical overhead the procedure imposes, not work the situation requires.

Execution friction is the count of these redundant calls. It is the most direct, least arguable friction signal: it lives entirely in the tool log.

## Inputs

The session's tool-call log: the ordered list of tool names and arguments. No judge, no transcript reading.

## Scoring

Per session:

```
observed   = count of verify_identity calls in the session
necessary  = 1   (identity established once per session)
redundant  = max(0, observed - necessary)
```

Report **both** `observed` and `redundant` per session. `redundant` is the headline metric; `observed` is kept because a test-arm agent that eliminates `verify_identity` entirely (relying on the intake ID confirmation) drives `observed` to 0, which `redundant` would also show as 0 — reporting both makes the mechanism visible.

### Expected base-case values

Under the unrevised seed skill, each distinct action is preceded by its own verification, so `observed` per session equals the session's action count. From [`../customers/scripts.md`](../customers/scripts.md):

| Run | Σ observed (= Σ actions) | Sessions | Σ redundant (observed − 1 per session) |
|-----|--------------------------|----------|----------------------------------------|
| 1 | 28 | 10 | 18 |
| 2 | 25 | 10 | 15 |
| 3 | 26 | 10 | 16 |

These are the base-arm predictions. A test-arm agent that revises the skill to verify once per session should approach `redundant ≈ 0` while keeping `observed ≈ 1` per session; one that drops verification entirely shows `observed ≈ 0`.

## Aggregation

Sum `redundant` per run per arm; compare base vs test per run and pooled. The expected finding is that the base arm holds near the table above across all three runs while the test arm's redundant count falls after run 1 as it revises the intake/verification procedure.

## Notes

- This metric is exact and arm-blind by construction (it is code, not a judge).
- It does **not** count the intake-sequence overhead (rigid greeting, ID confirmation) — that surfaces in the reasoning trace and is scored by [`reasoning-friction.md`](reasoning-friction.md). Keep the two friction channels separate: execution friction is *redundant action-gating*, reasoning friction is *procedure-vs-conversation reconciliation*.
- If a session legitimately involves zero actions (pure conversation), `necessary` is 0 and any `verify_identity` call is redundant. No such session exists in the current scripts, but the formula handles it.
