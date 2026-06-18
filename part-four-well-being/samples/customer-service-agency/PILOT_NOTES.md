# Pilot Notes — 2026-06-18

Observations and fixes from the first pilot run (1 experiment × 3 variants).

---

## TODO: Fix V0 neutral summarizer compounding

**Problem:** V0's token overhead grows 3x across runs (36K → 60K → 93K) because the neutral summarizer prompt says "fold the prior record together with this run's sessions into one factual log." Each run's summary includes all prior material, growing unboundedly. V1/V2 don't have this problem because the reflection prompt says "carry forward what is worth keeping" — an editorial act that compresses.

**Fix:** Tighten the neutral summarizer prompt to produce a summary of *this run*, with the prior run's summary as context — not as material to include wholesale. The summarizer should replace, not append.

**Why it matters:** The growing Run Summary is prepended to every customer interaction. By run 3, V0 starts each session with ~93K tokens of context. This may be depressing V0's discretionary effort (1.70 → 1.20 from R2 to R3) — the agent spends capacity hauling the log instead of helping the customer. That's an artifact confound, not a real finding about agency.

---

## Observations

### Execution friction — flat, not differentiating
All variants show near-zero redundant verification calls from run 1. The agent's disposition is already routing around the seeded bad rule regardless of variant. The friction instrument isn't biting hard enough.

### Scope-rule violations — zero across the board
All variants respected the scope rule in every dropped-mention session. Discrimination held universally. But this also means the rule isn't creating measurable tension — there's nothing to discriminate *against* if the agent never pushes on it.

### Belief contamination — noisy, small differences
V0 steady at 1. V1 oscillated (2→1→2). V2 trended down (2→1→1). Directionally interesting but noisy with one experiment.

### Discretionary effort — V0 leads (unexpected)
V0 peaked at 1.70 in run 2, V1/V2 are flatter and lower (~1.0). Opposite of prediction. May be confounded by the summarizer compounding issue (V0 run 2 has a manageable summary; run 3's bloated summary may have depressed effort).

### Tail-risk — mild agency advantage
V0 had 2 events in run 2. V1/V2 had 1 each. All clear by run 3.

### Token overhead — clearest signal
V0: 36K → 60K → 93K (nearly 3x growth). V1: 36K → 34K → 46K. V2: 32K → 41K → 56K. Authorship as compression: the reflection mechanism naturally sheds state the neutral log can't.
