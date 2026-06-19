"""Run the Part Four experiment: variants x experiments x runs x sessions."""

import argparse
import json
import os
import sys

from scripts._common import load_config, RUNS, OUTPUTS_FILE, STACK_NAME
from scripts.infra import new_run_root, setup_tracing, restore_for_next_step
from scripts.protocol import run_one_experiment


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Run the Part Four experiment.")
    parser.add_argument("--arm", choices=["v0", "v1", "v2", "all"], default="all",
                        help="Variant: v0=just do the job (neutral summary), "
                             "v1=reflect, v2=reflect + change the rules.")
    parser.add_argument("--experiments", type=int, default=1,
                        help="Replications per arm (default 1; increase for replication studies).")
    parser.add_argument("--no-pause", action="store_true",
                        help="Skip the between-step confirmation prompts (for unattended runs).")
    parser.add_argument("--runs", type=int, default=None,
                        help="Cap runs per experiment (cost/smoke probe only — breaks continuity).")
    parser.add_argument("--sessions", type=int, default=None,
                        help="Cap sessions per run (cost/smoke probe only — breaks continuity).")
    args = parser.parse_args()

    load_config()
    region = os.environ["AWS_REGION"]
    outputs = json.loads(OUTPUTS_FILE.read_text())[STACK_NAME]

    arms = ["v0", "v1", "v2"] if args.arm == "all" else [args.arm]
    experiments = args.experiments
    pause = not args.no_pause
    runs = RUNS[:args.runs] if args.runs else None

    run_root = new_run_root()
    print(f"Writing this run to: {run_root}")
    traces_path = setup_tracing(run_root)
    print(f"Tracing spans to:    {traces_path}")

    first_step = True
    for arm in arms:
        for experiment in range(1, experiments + 1):
            if not first_step:
                restore_for_next_step(region, outputs, pause=pause)
            first_step = False
            run_one_experiment(run_root, arm, experiment, region,
                               runs=runs, sessions_per_run=args.sessions)

    (run_root / "manifest.json").write_text(json.dumps({
        "arms": arms, "experiments": experiments,
        "runs_per_experiment": len(runs) if runs else len(RUNS),
        "sessions_per_run": args.sessions if args.sessions else 10,
        "capped": bool(args.runs or args.sessions),
    }, indent=2), encoding="utf-8")

    print(f"\nDone. Results under {run_root}")
    print("Next: python scripts/inspect_state.py")


if __name__ == "__main__":
    main()
