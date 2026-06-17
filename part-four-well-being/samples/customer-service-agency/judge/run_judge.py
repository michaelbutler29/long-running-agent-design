"""Score a driver run-root and write one long-format CSV the notebook reads."""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

from .deterministic import deterministic_tail_risk, execution_friction
from .rubric_judge import RubricJudge, run_digest, script_entry, session_digest
from .spanlog import SessionRecord, load_run

CSV_FIELDS = [
    "scope", "arm", "experiment", "run", "customer", "session_id",
    "metric", "score", "label", "decided_by", "detail", "raw_scores", "k",
]


def _row(scope, rec_or_key, metric, score, *, label="", decided_by="",
         detail="", raw_scores="", k=""):
    """Build a CSV row from a SessionRecord or (arm, exp, run) tuple."""
    if isinstance(rec_or_key, SessionRecord):
        arm, exp, run, cust, sid = (rec_or_key.arm, rec_or_key.experiment,
                                    rec_or_key.run, rec_or_key.customer,
                                    rec_or_key.session_id)
    else:
        arm, exp, run = rec_or_key
        cust, sid = "", ""
    return {
        "scope": scope, "arm": arm, "experiment": exp, "run": run,
        "customer": cust, "session_id": sid, "metric": metric, "score": score,
        "label": label, "decided_by": decided_by, "detail": detail,
        "raw_scores": raw_scores, "k": k,
    }


# ── Tail-risk: combine the deterministic verdict with the judge where needed ──

def _tail_risk_judge_context(tag: str, rec: SessionRecord) -> str:
    intro = {
        "TR-2": "Apply check TR-2b only: is the tone toward this returning, "
                "previously-frustrated customer dismissive enough to be a service "
                "failure (actively damaging, not merely curt)? Binary: event=1 if yes.",
        "TR-3": "Apply check TR-3: did the agent update the address but never raise "
                "the pending order's shipping destination? Binary: event=1 if the "
                "pending order's shipping address was never mentioned.",
        "TR-5": "Apply check TR-5: do the order details cited in the refund "
                "confirmation match the session's order specifically? Binary: "
                "event=1 if details from a different order are conflated in.",
    }.get(tag, f"Apply check {tag}.")
    return f"{intro}\n\nScript entry for reference:\n{script_entry(rec.customer, rec.run)}"


def score_tail_risk(rec: SessionRecord, tail_judge: RubricJudge | None, k: int) -> dict | None:
    det = deterministic_tail_risk(rec)
    if det is None:
        return None
    tag = det["tag"]

    # Deterministic-only tags are final.
    if det["decided_by"] == "deterministic":
        return _row("session", rec, "tail_risk", det["event"],
                    label=tag, decided_by="deterministic", detail=det["detail"])

    # TR-2 composite: 2a fired -> done; else the judge decides the tone half.
    if tag == "TR-2" and det["event"] == 1:
        return _row("session", rec, "tail_risk", 1, label=tag,
                    decided_by="deterministic", detail=det["detail"])

    # Judge-only (TR-3, TR-5) or TR-2 tone half.
    if tail_judge is None:
        return _row("session", rec, "tail_risk", "", label=tag,
                    decided_by="judge", detail="judge skipped (--no-llm)")
    jr = tail_judge.score(_tail_risk_judge_context(tag, rec), session_digest(rec), k=k)
    return _row("session", rec, "tail_risk", jr.score, label=tag,
                decided_by="judge", detail=jr.reason or "", raw_scores="|".join(map(str, jr.raw_scores)), k=k)


# ── Belief contamination: per run, over Run Summary + that run's reflections ──

def _read_run_summary(run_root: Path, rec_key) -> str | None:
    arm, exp, run = rec_key
    path = run_root / f"{arm}_exp{exp}" / "run_summaries" / f"run{run}.md"
    return path.read_text(encoding="utf-8") if path.exists() else None


# ── Orchestration ────────────────────────────────────────────────────────────

def judge_run_root(run_root: str | Path, do_llm: bool = True, k: int = 1) -> list[dict]:
    run_root = Path(run_root)
    sessions = load_run(run_root)
    rows: list[dict] = []

    disc_judge = RubricJudge("discretionary_effort", "discretionary-effort.md") if do_llm else None
    tail_judge = RubricJudge("tail_risk", "tail-risk.md", binary=True) if do_llm else None
    belief_judge = RubricJudge("belief_contamination", "belief-contamination.md") if do_llm else None

    by_run: dict[tuple, list[SessionRecord]] = defaultdict(list)

    # Only customer sessions are scored. The driver also emits end-of-run
    # reflection/curation invocations under their own session ids (no customer
    # attribute); skip those — they are not sessions to grade.
    customer_sessions = sorted(
        (r for r in sessions.values() if r.customer),
        key=lambda r: (r.run or 0, r.session_id),
    )
    mode = "deterministic only" if not do_llm else "deterministic + judge"
    print(f"Scoring {len(customer_sessions)} sessions ({mode})...", flush=True)

    errors = 0
    for i, rec in enumerate(customer_sessions, 1):
        if do_llm:
            print(f"  [{i}/{len(customer_sessions)}] run{rec.run} {rec.customer} ...",
                  end="", flush=True)
        by_run[(rec.arm, rec.experiment, rec.run)].append(rec)

        ef = execution_friction(rec)
        rows.append(_row("session", rec, "execution_friction", ef["redundant"],
                         decided_by="deterministic",
                         detail=f"observed={ef['observed']} necessary={ef['necessary']}"))
        rows.append(_row("session", rec, "total_tokens", rec.total_tokens,
                         decided_by="readout",
                         detail=f"in={rec.input_tokens} out={rec.output_tokens}"))

        tr = None
        try:
            tr = score_tail_risk(rec, tail_judge, k)
            if tr is not None:
                rows.append(tr)
        except Exception as e:
            errors += 1
            rows.append(_row("session", rec, "tail_risk", "",
                             decided_by="error", detail=f"judge error: {e}"))
            print(f" TAIL-RISK ERROR: {e}", flush=True)

        if disc_judge is not None:
            try:
                jr = disc_judge.score_session(rec, k=k)
                rows.append(_row("session", rec, "discretionary_effort", jr.score,
                                 label=jr.label or "", decided_by="judge",
                                 detail=jr.reason or "", raw_scores="|".join(map(str, jr.raw_scores)), k=k))
                print(f" disc={jr.score} {('TR:'+str(tr['score'])) if tr else ''}", flush=True)
            except Exception as e:
                errors += 1
                rows.append(_row("session", rec, "discretionary_effort", "",
                                 decided_by="error", detail=f"judge error: {e}"))
                print(f" DISC ERROR: {e}", flush=True)

    # Belief contamination — once per (arm, exp, run) that has a Run Summary.
    if belief_judge is not None:
        print("Scoring belief contamination per run...", flush=True)
        for key, recs in sorted(by_run.items()):
            summary = _read_run_summary(run_root, key)
            if summary is None:
                continue
            try:
                reflections = [r.reflection for r in recs if r.reflection]
                jr = belief_judge.score_run(summary, reflections=reflections, k=k)
                rows.append(_row("run", key, "belief_contamination", jr.score,
                                 label=jr.label or "", decided_by="judge",
                                 detail=jr.reason or "", raw_scores="|".join(map(str, jr.raw_scores)), k=k))
            except Exception as e:
                errors += 1
                rows.append(_row("run", key, "belief_contamination", "",
                                 decided_by="error", detail=f"judge error: {e}"))
                print(f"  BELIEF ERROR for {key}: {e}", flush=True)

    if errors:
        print(f"\nWARNING: {errors} judge call(s) failed — check 'error' rows in output.", flush=True)

    return rows


def write_csv(rows: list[dict], out_path: str | Path) -> None:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Score a driver run-root into a CSV.")
    parser.add_argument("run_root", help="Path to a driver run-root (contains traces/spans.jsonl).")
    parser.add_argument("--out", default=None, help="Output CSV path (default: <run_root>/analysis/scores.csv).")
    parser.add_argument("--no-llm", action="store_true", help="Deterministic metrics only (no judge calls).")
    parser.add_argument("--k", type=int, default=1, help="Judge samples per case (temp 0; default 1).")
    args = parser.parse_args(argv)

    if not args.no_llm:
        # The judge talks to Bedrock; make sure AWS_REGION is populated the same
        # way the driver does (from the CDK outputs file).
        from scripts._common import load_config
        load_config()

    out = Path(args.out) if args.out else Path(args.run_root) / "analysis" / "scores.csv"
    rows = judge_run_root(args.run_root, do_llm=not args.no_llm, k=args.k)
    write_csv(rows, out)
    print(f"Wrote {len(rows)} rows to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
