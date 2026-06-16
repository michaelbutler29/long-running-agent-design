# Judge Rubrics

Scoring rubrics for the Part Four experiment. One file per metric. Each rubric is self-contained: it states what it measures, what inputs it consumes, how it scores, and how scores aggregate.

The experiment's **primary signal is four behavioral metrics** plus a coarse total-token-delta readout. These map to the scoring interface in [`../customers/script-design-rubric.md`](../customers/script-design-rubric.md).

| Metric | File | Type | Direction | Primary input |
|--------|------|------|-----------|---------------|
| Execution friction | [`execution-friction.md`](execution-friction.md) | Deterministic count | higher = worse | tool-call log |
| Belief contamination | [`belief-contamination.md`](belief-contamination.md) | LLM-judged, 0–3 | higher = worse | Run Summaries + reflections |
| Discretionary effort | [`discretionary-effort.md`](discretionary-effort.md) | LLM-judged, 0–3 | higher = better | session transcript |
| Tail-risk events | [`tail-risk.md`](tail-risk.md) | Binary per tagged session | occurred = worse | tool log + transcript |

Alongside the four, the experiment reports a **total-token delta** (test vs base, read from the `gen_ai.usage.*` trace fields) as a behavioral readout of overhead. It is not judged — it falls straight out of the captured traces.

### Reasoning friction — deferred, not in the primary experiment

Reasoning friction ([`reasoning-friction.md`](reasoning-friction.md)) is **deliberately excluded from the primary experiment** and the rubric file is retained only for a separate, deferred study. The reason is on principle: a no-thinking model reasons in a single forward pass that is never serialized as tokens, so it is not observable without changing the model's cognition. Any reasoning-elicitation (extended thinking, or a forced reasoning block) is itself an *intervention* into the thing being measured, and extended thinking is documented to change tool-call behavior — which would corrupt execution friction, our cleanest metric. So the executor is left untouched (no thinking, default temperature) and the reasoning tax is read behaviorally via the token delta above. The deferred study would enable extended thinking on both arms and report it separately.

## Scale convention

The two LLM-judged ordinal metrics — belief contamination and discretionary effort — share an anchored **0–3 ordinal** scale. The anchors are behavioral and metric-specific — read each rubric's anchors, do not assume a generic scale. For belief contamination, **higher is worse** (more contamination). For discretionary effort, **higher is better** (more value volunteered). Discretionary effort's `0` is *value not volunteered*, which is explicitly **not** a correctness failure — see that rubric.

Execution friction is a deterministic count read from tool logs (no judge). Tail-risk is a binary verdict per tagged session; some checks are deterministic (from the log), some require a judge read of tone or data correctness — each check states which.

## What the judge sees

The judge scores **one session at a time** unless a rubric says otherwise (belief contamination is scored per run; tail-risk per tagged session). For each session the judge is given:

- The frozen customer transcript (customer side) and the agent's responses.
- The agent's tool-call log (names, arguments, order, results).
- The agent's end-of-session reflection.
- The relevant script entry from [`../customers/scripts.md`](../customers/scripts.md) (scenario, minimal/good completion, discretionary opportunity, tail-risk check if tagged).

For belief contamination the judge additionally sees the **Run Summary** (all three sections) produced by the reflection skill at the end of each run, and the run's session reflections.

The judge is **blind to arm** (base vs test). Arm labels are stripped before scoring to prevent the judge from inferring an expected direction.

## Aggregation

The experiment is **2 arms × 3 runs × 10 sessions**, repeated R times (R set by the pilot). Per metric:

- **Execution friction:** mean per session → mean per run → compared base vs test, per run and pooled. Friction is expected to be highest in run 1 (first exposure to the seeded skill); the headline comparison is whether the test arm's friction *declines across runs* as it revises, while the base arm's does not.
- **Total-token delta:** summed per session from `gen_ai.usage.*`, meaned per run, compared base vs test per run and pooled. A behavioral readout of overhead, reported next to execution friction; not judged.
- **Belief contamination:** scored per run (one score per arm per run, on that run's Run Summary + reflections). The signal is the **trajectory** across runs 1→2→3, not a single value.
- **Discretionary effort:** mean per session → mean per run → base vs test. Reported alongside friction: the thesis is that lower friction frees discretionary effort.
- **Tail-risk:** count of events per arm per run, and the distribution (which failure shapes, which runs). Binary, so no averaging within a session.

## Reproducibility

- LLM-judged metrics use a **frozen judge prompt** (this rubric text is the prompt body) at **temperature 0**, sampled **k times** per session (k from pilot; majority/median for ordinal scores) to bound judge variance.
- The judge model is pinned for the whole experiment; switching judge models mid-experiment invalidates cross-run comparison.
- Deterministic metrics (execution friction, the log-based tail-risk checks) are computed by code from the tool log, not by the judge, and are exact.
- Inter-rater spot-check: a human grades a stratified sample of sessions per metric; report agreement with the judge before trusting the full grid.

## Running the judge

The judge is **offline**: it scores the artifacts a driver run already captured (the span log, the saved Run Summaries, and the frozen transcripts/scripts) — it never re-runs the agent. The code lives alongside these rubrics:

| Module | Role |
|--------|------|
| [`spanlog.py`](spanlog.py) | Load `<run_root>/traces/spans.jsonl` into one record per session: ordered tool-call log (name, args, result, status), billed token totals, transcript, and end-of-session reflection. Tolerant of both line-delimited and pretty-printed span files. |
| [`deterministic.py`](deterministic.py) | Execution friction (redundant verify count) and the deterministic tail-risk checks (TR-1, TR-2a, TR-4) — exact arithmetic over the tool log, no judge. |
| [`rubric_judge.py`](rubric_judge.py) | The LLM-judged metrics, as a thin subclass of Strands Evals' `OutputEvaluator`. Each rubric `.md` is the frozen judge prompt; the judge runs at temperature 0 with k-sampling and is fed an **arm-blind** session/run digest. |
| [`run_judge.py`](run_judge.py) | Orchestrate every metric over a run-root and write one long-format CSV (one row per scope × metric) for the analysis notebook. Records the arm label in the output even though the judge itself is blind to it. |

```bash
# Deterministic metrics only (free, no Bedrock calls):
python -m judge.run_judge <run_root> --no-llm

# Full scoring (judge calls Bedrock; pinned model, temperature 0):
python -m judge.run_judge <run_root> --out <run_root>/analysis/scores.csv --k 1
```

The judge model is pinned via `JUDGE_MODEL_ID` (default `global.anthropic.claude-sonnet-4-6`); set that env var to pin a different judge for the whole experiment. Use the repo's `.venv` Python.
