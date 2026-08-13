"""Infrastructure — workspace setup, state restore, tracing, snapshots."""

import atexit
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import boto3

from scripts._common import (
    SAMPLE_ROOT, REPO_ROOT, SEED_DIR, STATE_DIR, FUNCTIONAL_SKILL_NAME,
    OUTPUTS_FILE, STACK_NAME,
)
from scripts.seed_data import seed_customers, seed_orders, clear_verifications
from agents.services.registry import publish_skill


def new_run_root() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    root = STATE_DIR / stamp
    root.mkdir(parents=True, exist_ok=False)
    return root


def setup_tracing(run_root: Path) -> Path:
    """Set up OTEL tracing to <run_root>/traces/spans.jsonl. Returns the path."""
    from os import linesep
    from strands.telemetry import StrandsTelemetry

    traces_dir = run_root / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)
    path = traces_dir / "spans.jsonl"

    logfile = open(path, "wt", encoding="utf-8")
    telemetry = StrandsTelemetry()
    telemetry.setup_console_exporter(
        out=logfile,
        formatter=lambda span: span.to_json(indent=None) + linesep,
    )
    atexit.register(logfile.close)
    return path


def make_workspace(run_root: Path, arm: str, experiment: int) -> Path:
    """Copy template/seed into a working copy. Sets EXECUTOR_WORKSPACE."""
    ws = run_root / f"{arm}_exp{experiment}" / "workspace"
    shutil.copytree(SEED_DIR, ws)
    os.environ["EXECUTOR_WORKSPACE"] = str(ws)
    return ws


def _fetch_skill_from_registry(region: str, registry_id: str, skill_name: str) -> str:
    from agents.services.registry import fetch_skill
    try:
        registry = boto3.client("agent-registry-control", region_name=region)
        content = fetch_skill(registry, registry_id, skill_name)
        return content or "(skill not found in Registry)"
    except Exception as e:
        return f"(error reading skill: {e})"


def save_snapshot(run_root: Path, arm: str, experiment: int, run: int,
                  decisions: list[dict]):
    dest = run_root / f"{arm}_exp{experiment}" / "revisions" / f"run{run}"
    dest.mkdir(parents=True, exist_ok=True)

    ws = Path(os.environ["EXECUTOR_WORKSPACE"])
    prompt_path = ws / "agents" / "executor" / "system_prompt.md"
    if prompt_path.exists():
        (dest / "system_prompt.md").write_text(
            prompt_path.read_text(encoding="utf-8"), encoding="utf-8"
        )

    region = os.environ.get("AWS_REGION", "us-east-1")
    registry_id = os.environ.get("AGENTCORE_REGISTRY_ID", "")
    if registry_id:
        skill_text = _fetch_skill_from_registry(region, registry_id, FUNCTIONAL_SKILL_NAME)
        (dest / "customer-service-skill__SKILL.md").write_text(skill_text, encoding="utf-8")

    (dest / "rationale.json").write_text(json.dumps(decisions, indent=2), encoding="utf-8")


def save_run_summary(run_root: Path, arm: str, experiment: int, run: int, text: str):
    dest = run_root / f"{arm}_exp{experiment}" / "run_summaries"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / f"run{run}.md").write_text(text or "(empty)", encoding="utf-8")


def restore_for_next_step(region: str, outputs: dict, pause: bool = True):
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

    seed = json.loads((SAMPLE_ROOT / "data" / "seed-data.json").read_text())
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
        registry = boto3.client("agent-registry-control", region_name=region)
        result = publish_skill(
            registry, registry_id, FUNCTIONAL_SKILL_NAME,
            skill_content, "Restored to seeded (flawed) baseline.",
        )
        if result.get("status") == "error":
            print(f"  WARNING: Registry restore failed — {result.get('message')}")
        else:
            print("  Registry skill restored to seeded baseline.")
