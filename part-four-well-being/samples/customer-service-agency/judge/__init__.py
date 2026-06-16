"""The Part Four judge: score a captured driver run into a metrics CSV.

Layers (import the one you need — this package intentionally does no eager
imports, so the deterministic path stays free of the Strands/LLM dependencies):

- `judge.spanlog`      — load `traces/spans.jsonl` into per-session records.
- `judge.deterministic` — execution friction + deterministic tail-risk checks.
- `judge.rubric_judge`  — the LLM-judged metrics (Strands Evals OutputEvaluator).
- `judge.run_judge`     — orchestrate all metrics over a run-root → CSV.

The rubric `.md` files in this folder are the frozen judge prompts. See
`README.md` for the metric definitions and how to run the judge.
"""
