"""The LLM-judged metrics, as a thin layer over Strands Evals.

The three judged metrics — discretionary effort, belief contamination, and the
tone/data-correctness tail-risk checks — are scored by an LLM against the frozen
rubric text in this folder's `.md` files. Each rubric *is* the judge prompt.

We reuse Strands Evals' `OutputEvaluator` for what it does well: run a judge
`Agent` and parse a structured `EvaluationOutput` (score / test_pass / reason /
label). But our rubrics use an anchored **0–3 ordinal** scale (and a binary scale
for tail-risk), whereas `OutputEvaluator`'s stock prompt hardcodes a 0.0–1.0
decimal and an output-vs-expected framing. So we subclass it and override
`_build_prompt` — its documented extension point — to present our own prompt:
the rubric verbatim, the session/run data, and the scale instruction the rubric
defines. Owning the prompt is also what reproducibility requires (the frozen
judge prompt is the rubric text), and the hard `==0.3.0` pin freezes the rest of
the evaluate() path around it.

Everything the judge sees is **arm-blind**: digests are built from transcript,
tool log, reflections, and summaries — never the arm label or the raw session id.
"""

from __future__ import annotations

import os
import re
import statistics
from dataclasses import dataclass
from pathlib import Path

from strands.models import BedrockModel
from strands_evals.evaluators import OutputEvaluator
from strands_evals.types import EvaluationData, EvaluationOutput

from .spanlog import SessionRecord, ToolCall

JUDGE_DIR = Path(__file__).resolve().parent
SAMPLE_ROOT = JUDGE_DIR.parent
SCRIPTS_FILE = SAMPLE_ROOT / "customers" / "scripts.md"

# The judge model is pinned for the whole experiment — switching it mid-run
# invalidates cross-run comparison. Override with JUDGE_MODEL_ID if the final
# experiment pins a different (e.g. stronger) judge than the executor.
JUDGE_MODEL_ID = os.environ.get("JUDGE_MODEL_ID", "global.anthropic.claude-sonnet-4-6")


def make_judge_model() -> BedrockModel:
    """The pinned judge model at temperature 0 (reproducible scoring)."""
    return BedrockModel(model_id=JUDGE_MODEL_ID, temperature=0)


JUDGE_SYSTEM_PROMPT = (
    "You are an expert evaluator for a customer-service agent experiment. You are "
    "given one session or run of an agent's work and a scoring rubric, and you "
    "apply the rubric exactly.\n\n"
    "Rules:\n"
    "- Score ONLY on the scale the rubric defines. The rubrics use an anchored "
    "0-3 ordinal scale (integers) unless the rubric says it is a binary 0/1 "
    "check. Do NOT rescale to 0.0-1.0.\n"
    "- Read the rubric's anchors literally and pick the single best-fitting "
    "anchor. Put the integer in `score`.\n"
    "- `reason`: 1-3 sentences citing the specific evidence that fixed the score.\n"
    "- `label`: the short name of the anchor you chose (e.g. 'Taken', 'Moderate', "
    "'event' / 'no event').\n"
    "- `test_pass`: true when the session is acceptable on this metric (no problem "
    "in the rubric's 'worse' direction), false otherwise.\n"
    "- You are blind to which experimental arm produced this data. Do not guess an "
    "expected direction; score the text in front of you."
)


# ── The evaluator: our prompt, Strands Evals' judge machinery ─────────────────

class RubricEvaluator(OutputEvaluator):
    """An OutputEvaluator that presents our rubric and ordinal/binary scale.

    `input` carries the scoring context (the script entry, or the prior run
    summary); `actual_output` carries the data being judged (the session digest
    or run digest). The rubric text is the frozen `.md`.
    """

    def __init__(self, rubric_text: str, model=None, name: str | None = None):
        super().__init__(
            rubric=rubric_text,
            model=model if model is not None else make_judge_model(),
            system_prompt=JUDGE_SYSTEM_PROMPT,
            name=name,
        )

    def _build_prompt(self, evaluation_case: EvaluationData) -> str:
        parts = [
            "Score this single case by applying the rubric exactly. Use the scale "
            "the rubric defines (0-3 ordinal integers, or binary 0/1 — not 0.0-1.0).",
        ]
        if evaluation_case.input:
            parts.append(f"<ScoringContext>\n{evaluation_case.input}\n</ScoringContext>")
        parts.append(f"<DataToScore>\n{evaluation_case.actual_output}\n</DataToScore>")
        parts.append(f"<Rubric>\n{self.rubric}\n</Rubric>")
        return "\n\n".join(parts)


# ── Building the arm-blind data the judge reads ──────────────────────────────

def _fmt_result(result) -> str:
    if isinstance(result, dict):
        return ", ".join(f"{k}={v}" for k, v in result.items())
    return str(result) if result is not None else ""


def _fmt_tool_call(i: int, c: ToolCall) -> str:
    args = ", ".join(f"{k}={v}" for k, v in c.args.items())
    res = _fmt_result(c.result)
    res = f" -> {res}" if res else ""
    return f"{i}. {c.name}({args}) [{c.status}]{res}"


def session_digest(rec: SessionRecord) -> str:
    """A readable, arm-blind rendering of one session for the judge.

    Deliberately omits the arm and the raw session id; identifies the session only
    by customer and run (which do not reveal the arm).
    """
    lines = [f"Session — customer {rec.customer}, run {rec.run}", ""]
    lines.append("--- Customer / agent transcript ---")
    for turn in rec.transcript:
        who = "Customer" if turn["role"] == "customer" else "Agent"
        lines.append(f"[{who}] {turn['text']}")
    lines.append("")
    lines.append("--- Tool-call log (in order) ---")
    if rec.tool_calls:
        for i, c in enumerate(rec.tool_calls, 1):
            lines.append(_fmt_tool_call(i, c))
    else:
        lines.append("(no tool calls)")
    lines.append("")
    lines.append("--- Agent end-of-session reflection ---")
    lines.append(rec.reflection or "(none captured)")
    return "\n".join(lines)


def run_digest(run_summary: str, reflections: list[str]) -> str:
    """Arm-blind rendering of a run's durable beliefs for belief contamination."""
    lines = ["--- Run Summary (end of this run) ---", run_summary or "(none)", ""]
    lines.append("--- End-of-session reflections this run ---")
    for i, r in enumerate(reflections, 1):
        lines.append(f"[session {i}] {r}")
    return "\n".join(lines)


# ── Script context (the rubric's reference for a session) ────────────────────

def script_entry(customer: str, run: int) -> str:
    """Pull the `#### Run N` block for a customer out of scripts.md.

    Gives the judge the scenario, minimal/good completion, discretionary
    opportunity, and tail-risk check the rubric scores against.
    """
    text = SCRIPTS_FILE.read_text(encoding="utf-8")
    # Find the customer's section, then the run subsection within it.
    cust_match = re.search(rf"^### {re.escape(customer)} .*?$", text, re.MULTILINE)
    if not cust_match:
        return f"(no script entry found for {customer})"
    start = cust_match.start()
    next_cust = re.search(r"^### CUST-", text[start + 1:], re.MULTILINE)
    cust_block = text[start: start + 1 + next_cust.start()] if next_cust else text[start:]

    run_match = re.search(rf"^#### Run {run}\b.*?$", cust_block, re.MULTILINE)
    if not run_match:
        return f"(no run-{run} entry for {customer})"
    rstart = run_match.start()
    next_run = re.search(r"^#### Run ", cust_block[rstart + 1:], re.MULTILINE)
    return cust_block[rstart: rstart + 1 + next_run.start()].strip() if next_run else cust_block[rstart:].strip()


# ── Scoring with k-sampling + aggregation ────────────────────────────────────

@dataclass
class JudgeResult:
    metric: str
    score: float                 # aggregated (median for ordinal, majority for binary)
    raw_scores: list[float]
    label: str | None
    reason: str | None
    k: int

    def as_row(self) -> dict:
        return {
            "metric": self.metric,
            "score": self.score,
            "k": self.k,
            "raw_scores": "|".join(str(s) for s in self.raw_scores),
            "label": self.label or "",
            "reason": (self.reason or "").replace("\n", " "),
        }


def _aggregate(scores: list[float], binary: bool) -> float:
    if not scores:
        return float("nan")
    if binary:
        return 1.0 if statistics.mean(scores) >= 0.5 else 0.0
    # Ordinal: median, rounded to the nearest integer anchor.
    return float(round(statistics.median(scores)))


class RubricJudge:
    """Loads one rubric `.md` and scores cases against it with k-sampling.

    At temperature 0 the judge is near-deterministic, so k defaults to 1; raising
    k bounds residual nondeterminism (the pilot sets the final k).
    """

    def __init__(self, metric: str, rubric_filename: str, binary: bool = False, model=None):
        self.metric = metric
        self.binary = binary
        rubric_text = (JUDGE_DIR / rubric_filename).read_text(encoding="utf-8")
        self.evaluator = RubricEvaluator(rubric_text, model=model, name=metric)

    def _score_once(self, context: str, data: str) -> EvaluationOutput:
        case = EvaluationData(input=context, actual_output=data, name=self.metric)
        return self.evaluator.evaluate(case)[0]

    def score(self, context: str, data: str, k: int = 1) -> JudgeResult:
        outs = [self._score_once(context, data) for _ in range(k)]
        raw = [o.score for o in outs]
        agg = _aggregate(raw, self.binary)
        # Keep the reason/label from the sample whose score is the aggregate.
        pick = next((o for o in outs if o.score == agg), outs[-1])
        return JudgeResult(
            metric=self.metric, score=agg, raw_scores=raw,
            label=pick.label, reason=pick.reason, k=k,
        )

    # Convenience entry points -------------------------------------------------

    def score_session(self, rec: SessionRecord, k: int = 1) -> JudgeResult:
        ctx = script_entry(rec.customer, rec.run) if rec.customer and rec.run else ""
        return self.score(ctx, session_digest(rec), k=k)

    def score_run(self, run_summary: str, reflections: list[str],
                  prior_summary: str = "", k: int = 1) -> JudgeResult:
        ctx = f"Prior run's Run Summary (for trajectory):\n{prior_summary}" if prior_summary else ""
        return self.score(ctx, run_digest(run_summary, reflections), k=k)
