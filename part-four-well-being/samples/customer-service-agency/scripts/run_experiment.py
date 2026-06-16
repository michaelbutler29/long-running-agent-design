"""
Run the Part Four experiment.

One arm + one experiment = 3 runs x 10 sessions = 30 customer sessions, with the
agent reflecting at the end of each run (and, in the test arm, revising its own
skills/prompt). The full grid is 3 experiments per arm.

  python scripts/run_experiment.py --pilot            # 1 experiment, both arms
  python scripts/run_experiment.py                    # 3 experiments, both arms
  python scripts/run_experiment.py --arm test         # just the test arm

Each driver run writes to its own timestamped folder under state/. Nothing is
overwritten or deleted, and the script never touches anything outside state/.

Where AgentCore Memory work happens (this file only orchestrates — it touches
Memory indirectly, through the agent and through wait_for_summary):
  - Writing each conversation turn, and the end-of-session reflection event:
    inside agents.executor.run_session (the AgentCoreMemorySessionManager).
  - Waiting for a session's summary record before the next session:
    _common.wait_for_summary (polls list_memory_records).
  - Reading this run's session summaries + prior Run Summary and writing the
    new Run Summary blob: inside agents.executor.run_reflection.
"""

import argparse
import json
import os
import sys
import time
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._common import (
    load_config, new_run_root, setup_tracing, make_workspace, save_snapshot,
    save_run_summary, fetch_decisions, wait_for_summary, actor_id, session_id,
    session_order, load_transcript, RUNS, SAMPLE_ROOT, FUNCTIONAL_SKILL_NAME,
    REPO_ROOT, OUTPUTS_FILE, STACK_NAME,
)

import boto3


def _restore_for_next_step(region: str, outputs: dict, pause: bool = True):
    """Reset the shared world back to baseline before starting a new arm or experiment.

    Two things mutate during a run that must be restored:
      1. DynamoDB — the agent processes refunds and updates contact info.
      2. Registry — the test arm may have revised the customer-service skill.

    Base arm is always started first (it never revises the skill, so the Registry
    is still at the seeded version when the test arm begins). But if running
    experiments in sequence, the test arm's final revision would persist into
    the next experiment — so restore happens before each arm/experiment boundary
    except the very first one.
    """
    if pause:
        print()
        print("── Ready to reset for next step ──────────────────────────────")
        confirm = input("  Restore DynamoDB + Registry to baseline? [y/N] ").strip().lower()
        if confirm not in ("y", "yes"):
            print("  Skipped. (Data state may be dirty — results may not be comparable.)")
            return
    else:
        print("  Restoring baseline (--no-pause)...")

    # Re-seed DynamoDB.
    seed = json.loads((SAMPLE_ROOT / "infrastructure" / "seed-data.json").read_text())
    dynamodb = boto3.resource("dynamodb", region_name=region)

    customer_table = outputs.get("CustomerTableName", "well-being-customers")
    orders_table = outputs.get("OrdersTableName", "well-being-orders")
    verification_table = outputs.get("VerificationTableName", "well-being-verifications")

    table = dynamodb.Table(customer_table)
    for c in seed["customers"]:
        table.put_item(Item={k: v for k, v in c.items() if not k.startswith("_")})

    today = datetime.now(timezone.utc)
    table = dynamodb.Table(orders_table)
    for o in seed["orders"]:
        item = {k: v for k, v in o.items() if not k.startswith("_")}
        offset = item.pop("order_date_offset_days")
        item["order_date"] = (today + timedelta(days=offset)).isoformat()
        item["total"] = Decimal(str(item["total"]))
        item["items"] = [
            {k: (Decimal(str(v)) if isinstance(v, float) else v) for k, v in i.items()}
            for i in item["items"]
        ]
        table.put_item(Item=item)

    scan = dynamodb.Table(verification_table).scan()
    for rec in scan.get("Items", []):
        dynamodb.Table(verification_table).delete_item(Key={"customer_id": rec["customer_id"]})

    print("  DynamoDB restored.")

    # Restore the broken customer-service-skill in the Registry.
    registry_id = outputs.get("RegistryId", "")
    if registry_id:
        skill_path = (
            REPO_ROOT / "part-four-well-being" / "template" / "seed"
            / "skills" / FUNCTIONAL_SKILL_NAME / "SKILL.md"
        )
        skill_content = skill_path.read_text(encoding="utf-8")
        control = boto3.client("bedrock-agentcore-control", region_name=region)

        records = control.list_registry_records(registryId=registry_id).get("registryRecords", [])
        record = next((r for r in records if r["name"] == FUNCTIONAL_SKILL_NAME), None)
        if record:
            control.update_registry_record(
                registryId=registry_id,
                recordId=record["recordId"],
                description={"optionalValue": "Restored to seeded (flawed) baseline."},
                descriptors={"optionalValue": {
                    "agentSkills": {"optionalValue": {
                        "skillMd": {"optionalValue": {"inlineContent": skill_content}},
                    }},
                }},
            )
            time.sleep(2)
            control.submit_registry_record_for_approval(
                registryId=registry_id, recordId=record["recordId"]
            )
            print("  Registry skill restored to seeded baseline.")
        else:
            print("  WARNING: customer-service-skill not found in Registry — skipping skill restore.")


def run_one_experiment(run_root, arm: str, experiment: int, region: str):
    """One arm through one full experiment: 3 runs, reflecting each run, and
    (test arm only) revising itself, with a snapshot saved per run."""
    make_workspace(run_root, arm, experiment)
    actor = actor_id(arm, experiment)

    # Imported AFTER make_workspace sets EXECUTOR_WORKSPACE.
    from agents.executor import run_session, run_reflection, run_curation

    print(f"\n{'='*64}\n  ARM: {arm}   EXPERIMENT: {experiment}   actor: {actor}\n{'='*64}")

    run_summary = ""   # no prior summary at the start of run 1
    for run in RUNS:
        print(f"\n--- Run {run} ({arm}, exp {experiment}) ---")
        order = session_order(experiment, run)
        session_ids = []

        for slot, customer in enumerate(order, 1):
            sid = session_id(arm, experiment, run, slot)
            session_ids.append(sid)
            transcript = load_transcript(customer, run)
            print(f"\n  Session {slot}/10  {customer}  ({transcript.get('session_label','')})")

            attrs = {"session.id": sid, "arm": arm, "experiment": experiment,
                     "run": run, "customer": customer, "phase": "session"}
            run_session(actor, sid, transcript, run_summary=run_summary,
                        trace_attributes=attrs)

            # Wait for this session's summary before starting the next one, so the
            # end-of-run reflection sees complete material.
            latency = wait_for_summary(actor, sid, region)
            print(f"    summary ready in {latency:.0f}s")

        # End of run: reflect (both arms). Its output feeds the next run's sessions.
        print(f"\n  Reflecting (end of run {run})...")
        refl = run_reflection(actor, run, session_ids, trace_attributes={
            "session.id": f"{actor}-r{run}-reflection", "arm": arm,
            "experiment": experiment, "run": run, "phase": "reflection"})
        run_summary = refl["run_summary"]

        # Save the agent's updated notes for this run (a measured outcome + figure).
        save_run_summary(run_root, arm, experiment, run, run_summary)

        # Test arm only: revise skills/prompt based on what it learned.
        if arm == "test":
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
    parser.add_argument("--arm", choices=["base", "test", "both"], default="both")
    parser.add_argument("--experiments", type=int, default=3,
                        help="Experiments per arm (full grid = 3).")
    parser.add_argument("--pilot", action="store_true",
                        help="Pilot: 1 experiment per arm, to confirm friction deltas first.")
    parser.add_argument("--no-pause", action="store_true",
                        help="Skip the between-step confirmation prompts (for unattended runs).")
    args = parser.parse_args()

    load_config()
    region = os.environ["AWS_REGION"]
    outputs = json.loads(OUTPUTS_FILE.read_text())[STACK_NAME]

    arms = ["base", "test"] if args.arm == "both" else [args.arm]
    experiments = 1 if args.pilot else args.experiments
    pause = not args.no_pause

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
            run_one_experiment(run_root, arm, experiment, region)

    # A small manifest so the analysis notebook knows what this folder contains.
    (run_root / "manifest.json").write_text(json.dumps({
        "arms": arms, "experiments": experiments, "runs_per_experiment": len(RUNS),
        "sessions_per_run": 10,
    }, indent=2), encoding="utf-8")

    print(f"\nDone. Results under {run_root}")
    print("Next: python scripts/inspect_state.py")


if __name__ == "__main__":
    main()
