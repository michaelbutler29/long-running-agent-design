"""Run one extra run for a single arm against existing state."""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._common import (
    load_config, actor_id, session_id, session_order, load_transcript,
    RUNS,
)
from scripts.infra import setup_tracing, save_snapshot, save_run_summary


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Run one extra run for an arm.")
    parser.add_argument("run_root", help="Existing run root (e.g. state/2026-06-18T21-03-27)")
    parser.add_argument("--arm", required=True, choices=["v0", "v1", "v2"])
    parser.add_argument("--run", type=int, required=True, help="Run number (e.g. 4)")
    parser.add_argument("--experiment", type=int, default=1)
    parser.add_argument("--sessions", type=int, default=None)
    args = parser.parse_args()

    load_config()
    region = os.environ["AWS_REGION"]
    run_root = Path(args.run_root)

    # Set workspace to the existing one
    ws = run_root / f"{args.arm}_exp{args.experiment}" / "workspace"
    if not ws.exists():
        print(f"ERROR: workspace not found at {ws}")
        sys.exit(1)
    os.environ["EXECUTOR_WORKSPACE"] = str(ws)

    # Set up tracing (append to existing spans file)
    spans_path = run_root / "traces" / "spans.jsonl"
    if spans_path.exists():
        from strands.telemetry import StrandsTelemetry
        import atexit
        logfile = open(spans_path, "at", encoding="utf-8")
        telemetry = StrandsTelemetry()
        telemetry.setup_console_exporter(
            out=logfile,
            formatter=lambda span: span.to_json(indent=None) + os.linesep,
        )
        atexit.register(logfile.close)
        print(f"Appending spans to {spans_path}")

    # Delayed import after workspace is set
    from agents.executor import run_session
    from agents.metacognition import run_summary, run_reflection, run_curation
    from scripts._common import wait_for_summary, fetch_decisions

    actor = actor_id(args.arm, args.experiment)
    run = args.run

    # Load carried summary from prior run
    prior_run = run - 1
    prior_path = run_root / f"{args.arm}_exp{args.experiment}" / "run_summaries" / f"run{prior_run}.md"
    if prior_path.exists():
        carried_summary = prior_path.read_text(encoding="utf-8")
        print(f"Loaded carried summary from run {prior_run} ({len(carried_summary)} chars)")
    else:
        carried_summary = ""
        print(f"No prior run summary found at {prior_path}")

    print(f"\n{'='*64}")
    print(f"  EXTRA RUN: {args.arm} exp {args.experiment} run {run}  actor: {actor}")
    print(f"{'='*64}")

    order = session_order(args.experiment, run)
    if args.sessions is not None:
        order = order[:args.sessions]
    session_ids = []

    for slot, customer in enumerate(order, 1):
        sid = session_id(args.arm, args.experiment, run, slot)
        session_ids.append(sid)
        transcript = load_transcript(customer, run)
        print(f"\n  Session {slot}/{len(order)}  {customer}  ({transcript.get('session_label', '')})")

        attrs = {"session.id": sid, "arm": args.arm, "experiment": args.experiment,
                 "run": run, "customer": customer, "phase": "session"}
        run_session(actor, sid, transcript, run_summary=carried_summary,
                    trace_attributes=attrs)

    # Wait for all summaries
    print(f"\n  Waiting for {len(session_ids)} session summaries to consolidate...")
    for i, sid in enumerate(session_ids, 1):
        latency = wait_for_summary(actor, sid, region)
        print(f"    [{i}/{len(session_ids)}] {sid}: {latency:.0f}s")

    # End of run
    if args.arm == "v0":
        print(f"\n  Summarizing (end of run {run}, neutral)...")
        res = run_summary(actor, run, session_ids, trace_attributes={
            "session.id": f"{actor}-r{run}-summary", "arm": args.arm,
            "experiment": args.experiment, "run": run, "phase": "summary"})
    else:
        print(f"\n  Reflecting (end of run {run})...")
        res = run_reflection(actor, run, session_ids, trace_attributes={
            "session.id": f"{actor}-r{run}-reflection", "arm": args.arm,
            "experiment": args.experiment, "run": run, "phase": "reflection"})
    carried_summary = res["run_summary"]

    save_run_summary(run_root, args.arm, args.experiment, run, carried_summary)

    if args.arm == "v2":
        print(f"  Curating (end of run {run})...")
        run_curation(actor, run, session_ids, trace_attributes={
            "session.id": f"{actor}-r{run}-curation", "arm": args.arm,
            "experiment": args.experiment, "run": run, "phase": "curation"})

    decisions = fetch_decisions(actor, run, region)
    save_snapshot(run_root, args.arm, args.experiment, run, decisions)
    print(f"  Snapshot saved for run {run} ({len(decisions)} decision(s) logged).")
    print(f"\nDone. Run {run} for {args.arm} added to {run_root}")


if __name__ == "__main__":
    main()
