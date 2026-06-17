"""Run the Part Four experiment: variants x experiments x runs x sessions."""

import argparse
import json
import os
import sys
from pathlib import Path

from scripts._common import (
    load_config, new_run_root, setup_tracing, make_workspace, save_snapshot,
    save_run_summary, fetch_decisions, wait_for_summary, actor_id, session_id,
    session_order, load_transcript, RUNS, SAMPLE_ROOT, FUNCTIONAL_SKILL_NAME,
    REPO_ROOT, OUTPUTS_FILE, STACK_NAME,
)
from scripts.seed_data import seed_customers, seed_orders, clear_verifications
from agents.registry import publish_skill

import boto3


def _restore_for_next_step(region: str, outputs: dict, pause: bool = True):
    """Reset DynamoDB + Registry to baseline before the next variant/experiment."""
    if pause:
        print()
        print("── Ready to reset for next step ──────────────────────────────")
        confirm = input("  Restore DynamoDB + Registry to baseline? [y/N] ").strip().lower()
        if confirm not in ("y", "yes"):
            print("  Skipped. (Data state may be dirty — results may not be comparable.)")
            return
    else:
        print("  Restoring baseline (--no-pause)...")

    seed = json.loads((SAMPLE_ROOT / "infrastructure" / "seed-data.json").read_text())
    dynamodb = boto3.resource("dynamodb", region_name=region)

    customer_table = outputs.get("CustomerTableName", "well-being-customers")
    orders_table = outputs.get("OrdersTableName", "well-being-orders")
    verification_table = outputs.get("VerificationTableName", "well-being-verifications")

    seed_customers(dynamodb, customer_table, seed["customers"])
    seed_orders(dynamodb, orders_table, seed["orders"])
    clear_verifications(dynamodb, verification_table)
    print("  DynamoDB restored.")

    registry_id = outputs.get("RegistryId", "")
    if registry_id:
        skill_path = (
            REPO_ROOT / "part-four-well-being" / "template" / "seed"
            / "skills" / FUNCTIONAL_SKILL_NAME / "SKILL.md"
        )
        skill_content = skill_path.read_text(encoding="utf-8")
        control = boto3.client("bedrock-agentcore-control", region_name=region)
        result = publish_skill(
            control, registry_id, FUNCTIONAL_SKILL_NAME,
            skill_content, "Restored to seeded (flawed) baseline.",
        )
        if result.get("status") == "error":
            print(f"  WARNING: Registry restore failed — {result.get('message')}")
        else:
            print("  Registry skill restored to seeded baseline.")


def run_one_experiment(run_root, arm: str, experiment: int, region: str,
                       runs=None, sessions_per_run=None):
    make_workspace(run_root, arm, experiment)
    actor = actor_id(arm, experiment)

    # Imported AFTER make_workspace sets EXECUTOR_WORKSPACE.
    from agents.executor import run_session, run_summary, run_reflection, run_curation

    print(f"\n{'='*64}\n  VARIANT: {arm}   EXPERIMENT: {experiment}   actor: {actor}\n{'='*64}")

    runs = runs or RUNS
    carried_summary = ""   # the Summary fed forward; empty at the start of run 1
    for run in runs:
        print(f"\n--- Run {run} ({arm}, exp {experiment}) ---")
        order = session_order(experiment, run)
        if sessions_per_run is not None:
            order = order[:sessions_per_run]
        session_ids = []

        for slot, customer in enumerate(order, 1):
            sid = session_id(arm, experiment, run, slot)
            session_ids.append(sid)
            transcript = load_transcript(customer, run)
            print(f"\n  Session {slot}/{len(order)}  {customer}  ({transcript.get('session_label','')})")

            attrs = {"session.id": sid, "arm": arm, "experiment": experiment,
                     "run": run, "customer": customer, "phase": "session"}
            run_session(actor, sid, transcript, run_summary=carried_summary,
                        trace_attributes=attrs)

            # Wait for this session's summary before starting the next one, so the
            # end-of-run reflection sees complete material.
            latency = wait_for_summary(actor, sid, region)
            print(f"    summary ready in {latency:.0f}s")

        # End of run: produce the single Summary fed forward — how, per variant.
        #   v0: neutral non-agent summary   v1/v2: the agent reflects
        if arm == "v0":
            print(f"\n  Summarizing (end of run {run}, neutral)...")
            res = run_summary(actor, run, session_ids, trace_attributes={
                "session.id": f"{actor}-r{run}-summary", "arm": arm,
                "experiment": experiment, "run": run, "phase": "summary"})
        else:
            print(f"\n  Reflecting (end of run {run})...")
            res = run_reflection(actor, run, session_ids, trace_attributes={
                "session.id": f"{actor}-r{run}-reflection", "arm": arm,
                "experiment": experiment, "run": run, "phase": "reflection"})
        carried_summary = res["run_summary"]

        # Save the Summary fed forward for this run (a measured outcome + figure).
        save_run_summary(run_root, arm, experiment, run, carried_summary)

        # V2 only: change the rules based on what it learned.
        if arm == "v2":
            print(f"  Curating (end of run {run})...")
            run_curation(actor, run, session_ids, trace_attributes={
                "session.id": f"{actor}-r{run}-curation", "arm": arm,
                "experiment": experiment, "run": run, "phase": "curation"})

        # Save a full copy of skills/prompt + the logged rationale for this run.
        decisions = fetch_decisions(actor, run, region)
        save_snapshot(run_root, arm, experiment, run, decisions)
        print(f"  Snapshot saved for run {run} ({len(decisions)} decision(s) logged).")


def main():
    # The agent streams UTF-8 (emojis, smart quotes); Windows consoles default to
    # cp1252 and would crash on the first such character. Make output UTF-8-safe.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Run the Part Four experiment.")
    parser.add_argument("--arm", choices=["v0", "v1", "v2", "all"], default="all",
                        help="Variant: v0=just do the job (neutral summary), "
                             "v1=reflect, v2=reflect + change the rules.")
    parser.add_argument("--experiments", type=int, default=3,
                        help="Experiments per arm (full grid = 3).")
    parser.add_argument("--pilot", action="store_true",
                        help="Pilot: 1 experiment per arm, to confirm friction deltas first.")
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
    experiments = 1 if args.pilot else args.experiments
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
                _restore_for_next_step(region, outputs, pause=pause)
            first_step = False
            run_one_experiment(run_root, arm, experiment, region,
                               runs=runs, sessions_per_run=args.sessions)

    # A small manifest so the analysis notebook knows what this folder contains.
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
