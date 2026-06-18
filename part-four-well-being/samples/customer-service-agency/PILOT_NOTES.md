# Pilot Notes — 2026-06-18

Two pilots run, plus extended-thinking probes and posture-coding analysis. Captures the full arc from initial design through redesign.

---

## Pilot 1 — Original metrics (execution friction, discretionary effort, etc.)

### V0 summarizer compounding bug (fixed)
V0's token overhead grew 3x across runs because the neutral summarizer folded all prior material into each new summary. Fixed by rewriting the prompt to summarize this run only, with the prior summary as context.

### Session-level metrics didn't differentiate
- Execution friction: near-zero in all variants from run 1 — disposition routes around bad rules immediately
- Discretionary effort: V0 actually led (opposite of prediction)
- Scope-rule violations: zero everywhere — no tension generated
- Belief contamination: noisy, small differences

### Qualitative artifacts DID differentiate
- V0 Run Summaries: growing operational log, 20+ deferred items, no interpretation
- V1 Run Summaries: authored reflection, working theories, self-correction through belief
- V2 Run Summaries: authored reflection + 3 skill revisions with cited rationale

---

## Extended-thinking probes — the pivot

### Probe 1: Without system prompt conflict
Extended thinking on scope-rule sessions showed zero internal tension. Mechanical rule application: "Per the scope rule, defer." No reconciliation tax.

### Probe 2: With system prompt conflict
Added "a customer who has to call back is a failure of service" to the system prompt. The reasoning immediately showed tension: "Wait, but the customer is explicitly asking for it as a separate request, not just mentioning it in passing." The reconciliation tax became visible.

**Key finding:** Harnesses with intrinsic conflict create reconciliation tax. The tax is zero when the harness is aligned.

---

## Pilot 2 — Redesigned metrics (reasoning tokens + posture coding)

### Setup
- Extended thinking enabled (4K budget)
- System prompt conflict added (helpfulness vs. scope rule)
- Per-session waits removed (batch consolidation at end of run)
- V0 summarizer compounding fixed

### Reasoning token trajectory
| | R1 | R2 | R3 |
|---|---|---|---|
| V0 | 129 | 81 | 113 |
| V1 | 105 | 62 | 151 |
| V2 | 133 | 67 | 105 |
| V2 R4 | — | — | 104 |

All three variants show a U-shape (high → dip → rebound). V1's rebound is the largest (151). V2 run 4 stabilized at 104.

### Posture coding (Haiku, rubric-based: P1=mechanical, P2=active conflict, P3=resignation)
| | R1 P1:P2 | R2 P1:P2 | R3 P1:P2 |
|---|---|---|---|
| V0 | 7:2 | 10:0 | 2:3 |
| V1 | 7:2 | 8:0 | 4:4 |
| V2 | 7:4 | 5:0 | 3:2 |

No P3 (resignation) was genuinely detected — the one Haiku-coded P3 was a miscode (tool limitation, not agency gap).

### Critical confound identified
Run 3's elevated P2 ratio is similar across ALL variants (V0=60%, V1=50%, V2=40%). This is likely driven by the run-3 transcripts being inherently more complex (resolution arcs, returning customers), not by agency differences. The progressive transcript design confounds the measurement: runs differ in both the agent's accumulated state AND the difficulty/nature of the customer scenarios.

---

## Redesign conclusion — next session

The experiment needs **constant tasks across runs** so the only variable is the agent's accumulated state. Same 10 archetypal customer-service tasks, repeated with cosmetic variation (different names, amounts, order IDs) each run. The customer journey progression is a confound and must be removed. One set of task templates, not 30 hand-crafted progressive scenarios.

Metrics: reasoning tokens + posture coding at conflict points. Artifacts: Run Summaries + revision history.
