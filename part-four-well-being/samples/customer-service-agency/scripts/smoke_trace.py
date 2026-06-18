"""Smoke test: run one session with tracing to verify span content."""

import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._common import load_config, load_transcript, OUTPUTS_FILE
from infra import new_run_root, setup_tracing, make_workspace


def main():
    # The agent streams UTF-8 (emojis, smart quotes); Windows consoles default to
    # cp1252 and would crash on the first such character. Make output UTF-8-safe.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Observability smoke test (1 session).")
    parser.add_argument("--customer", default="CUST-001")
    parser.add_argument("--run", type=int, default=1)
    args = parser.parse_args()

    if not OUTPUTS_FILE.exists():
        print(f"ERROR: {OUTPUTS_FILE.name} not found — deploy the stack first "
              f"(cdk deploy --outputs-file cdk-outputs.json), then seed it.")
        sys.exit(1)

    try:
        transcript = load_transcript(args.customer, args.run)
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    load_config()
    run_root = new_run_root()
    spans_path = setup_tracing(run_root)
    make_workspace(run_root, "smoke", 0)          # sets EXECUTOR_WORKSPACE

    # Import AFTER the workspace + config are set (module reads env at import).
    from agents.executor import run_session

    # Unique actor+session per invocation: AgentCore Memory persists events by
    # actor/session, so a FIXED id would make each re-run inherit the prior
    # run's conversation (the doubled-session artifact seen in early smokes).
    uniq = uuid.uuid4().hex[:6]
    actor = f"smoke-{uniq}"
    sid = f"smoke-{args.customer}-r{args.run}-{uniq}"
    attrs = {"session.id": sid, "arm": "smoke", "experiment": 0,
             "run": args.run, "customer": args.customer, "phase": "session"}

    print(f"\nRunning 1 session: {args.customer} run {args.run} "
          f"({transcript.get('session_label','')})")
    print(f"Opening style: {transcript.get('opening_style','?')}  "
          f"(upfront is the reasoning-friction case)\n")

    result = run_session(actor, sid, transcript, trace_attributes=attrs)

    print("\n" + "=" * 64)
    print("Smoke session complete.")
    print(f"  spans:      {spans_path}")
    print(f"  session.id: {sid}")
    print("\nEyeball the spans file for two things:")
    print("  1. CONTENT — are the customer turns + agent responses present")
    print("     (gen_ai.user.message / gen_ai.assistant.message / gen_ai.choice)?")
    print("  2. REASONING — does the agent visibly wrestle the intake procedure")
    print("     against the upfront opening, or just comply silently?")
    print("\nQuick peek (PowerShell):")
    print(f"  Get-Content '{spans_path}' | Select-Object -First 5")
    print("=" * 64)
    return result


if __name__ == "__main__":
    main()
