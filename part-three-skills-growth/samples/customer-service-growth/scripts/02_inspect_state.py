"""
Step 2: Inspect the current state of the system.

Shows:
  1. Readiness check — whether episodic extraction is complete for the last run
  2. Memory stats — total episodes, reflections, and decisions
  3. Registry — published skills
  4. Policy Engine — Cedar policies

Run this after scripts 01 or 03 to see what changed.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import boto3

OUTPUTS_FILE = Path(__file__).parent.parent / "infrastructure" / "cdk-outputs.json"
STATE_DIR = Path(__file__).parent.parent / "state"
STACK_NAME = "SkillGrowthStack"


def load_config():
    outputs = json.loads(OUTPUTS_FILE.read_text())[STACK_NAME]
    os.environ.setdefault("AWS_REGION", outputs.get("Region", "us-east-1"))
    return outputs


def get_strategy_id(control_client, memory_id):
    """Discover the episodic strategy ID."""
    response = control_client.get_memory(memoryId=memory_id)
    memory_data = response.get("memory", response)
    for s in memory_data.get("strategies", []):
        if s.get("type") == "EPISODIC" or "episod" in s.get("name", "").lower():
            return s["strategyId"]
    return None


def check_readiness(data_client, memory_id, strategy_id):
    """Check whether episodic extraction is complete for the last run's sessions."""
    print("── Readiness ───────────────────────────────────────────────")
    print()

    last_run_path = STATE_DIR / "last_run.json"
    if not last_run_path.exists():
        print("  No last_run.json found — run script 01 first.")
        print()
        return

    last_run = json.loads(last_run_path.read_text())
    sessions = last_run.get("sessions", [])
    timestamp = last_run.get("timestamp", "?")

    print(f"  Last run: {timestamp} ({len(sessions)} sessions)")
    print()

    ready_count = 0
    for s in sessions:
        sid = s["session_id"]
        label = s["label"]
        ns_path = f"strategy/{strategy_id}/actor/executor/session/{sid}/"

        try:
            records = data_client.list_memory_records(
                memoryId=memory_id,
                namespacePath=ns_path,
                memoryStrategyId=strategy_id,
            ).get("memoryRecordSummaries", [])
        except Exception:
            records = []

        episode_count = len(records)
        is_ready = episode_count > 0
        if is_ready:
            ready_count += 1

        status = "READY" if is_ready else "WAITING"
        outcome = "ok" if s.get("success") else "FAILED"
        print(f"  [{status}] {sid} ({label})")
        print(f"          outcome={outcome}  episodes={episode_count}")

    print()
    if ready_count == len(sessions):
        print(f"  Episodes consolidated for all {len(sessions)} sessions.")
        print("  Please wait 1-2 minutes more for reflections to finish populating.")        
        print("  When the number of reflections is stable, move to the next step.")      
    else:
        waiting = len(sessions) - ready_count
        print(f"  {waiting}/{len(sessions)} sessions still processing.")
        print("  Total pipeline processing can take 15 minutes or more.")
        print("  Re-run this script in 1-2 minutes.")
    print()


def inspect_memory_stats(data_client, memory_id, strategy_id):
    """Show aggregate memory stats: total episodes, reflections, decisions."""
    print("── Memory Stats ────────────────────────────────────────────")
    print()

    # Count episodes (scoped to actor/executor namespace)
    episode_count = 0
    try:
        ns_path = f"strategy/{strategy_id}/actor/executor/"
        records = data_client.list_memory_records(
            memoryId=memory_id,
            namespacePath=ns_path,
            memoryStrategyId=strategy_id,
        ).get("memoryRecordSummaries", [])
        episode_count = len(records)
    except Exception as e:
        print(f"  Error counting episodes: {e}")

    # Count reflections (strategy-level namespace, minus episodes)
    reflection_count = 0
    try:
        ns_path = f"strategy/{strategy_id}/"
        all_records = data_client.list_memory_records(
            memoryId=memory_id,
            namespacePath=ns_path,
            memoryStrategyId=strategy_id,
        ).get("memoryRecordSummaries", [])
        # Reflections are records at strategy level that aren't in actor/executor/
        reflection_count = len(all_records) - episode_count
        if reflection_count < 0:
            reflection_count = 0
    except Exception as e:
        print(f"  Error counting reflections: {e}")

    # Count decisions
    decision_count = 0
    decision_cycles = set()
    try:
        records = data_client.list_memory_records(
            memoryId=memory_id,
            namespacePath="decisions/",
        ).get("memoryRecordSummaries", [])
        decision_count = len(records)
        for r in records:
            content = r.get("content", {}).get("text", "")
            try:
                d = json.loads(content)
                cycle = d.get("cycle_id", "")
                if cycle:
                    decision_cycles.add(cycle)
            except (json.JSONDecodeError, TypeError):
                pass
    except Exception as e:
        print(f"  Error counting decisions: {e}")

    print(f"  Episodes:    {episode_count}")
    print(f"  Reflections: {reflection_count}")
    print(f"  Decisions:   {decision_count}", end="")
    if decision_cycles:
        print(f" (across {len(decision_cycles)} cycle(s))")
    else:
        print()
    print()


def inspect_registry(region, registry_id):
    """Query Registry for published skills."""
    control_client = boto3.client("bedrock-agentcore-control", region_name=region)

    print("── Registry ────────────────────────────────────────────────")
    print()

    try:
        records = control_client.list_registry_records(registryId=registry_id).get("registryRecords", [])
        approved = [r for r in records if r.get("status") == "APPROVED"]

        print(f"  {len(approved)} skill(s) discoverable by Executors:")
        if approved:
            for r in approved:
                print(f"    - {r['name']} (id: {r['recordId']})")
        else:
            print("    (none)")
        print()
    except Exception as e:
        print(f"  Error: {e}")
        print()


def inspect_policies(region, policy_engine_id):
    """Query Policy Engine for Cedar policies."""
    control_client = boto3.client("bedrock-agentcore-control", region_name=region)

    print("── Policy Engine ───────────────────────────────────────────")
    print()

    try:
        policies = control_client.list_policies(policyEngineId=policy_engine_id).get("policies", [])
        seed = [p for p in policies if p["name"].startswith("seed_")]
        curator = [p for p in policies if p["name"].startswith("curator_")]

        print(f"  {len(seed)} seed policy(ies) (read-only tools):")
        for p in seed:
            print(f"    - {p['name']}")

        print(f"  {len(curator)} curator-approved policy(ies) (write tools):")
        if curator:
            for p in curator:
                print(f"    - {p['name']} (status: {p.get('status', '?')})")
        else:
            print("    (none — write tools are currently DENIED)")
        print()
    except Exception as e:
        print(f"  Error: {e}")
        print()


def main():
    outputs = load_config()
    region = os.environ.get("AWS_REGION", "us-east-1")
    memory_id = outputs["MemoryId"]
    registry_id = outputs["RegistryId"]
    policy_engine_id = outputs["PolicyEngineId"]

    control_client = boto3.client("bedrock-agentcore-control", region_name=region)
    data_client = boto3.client("bedrock-agentcore", region_name=region)

    print()
    print("=" * 60)
    print("  System State")
    print("=" * 60)
    print()

    strategy_id = get_strategy_id(control_client, memory_id)
    if not strategy_id:
        print("  ERROR: No episodic strategy found on Memory resource.")
        return

    check_readiness(data_client, memory_id, strategy_id)
    inspect_memory_stats(data_client, memory_id, strategy_id)
    inspect_registry(region, registry_id)
    inspect_policies(region, policy_engine_id)

    print("=" * 60)


if __name__ == "__main__":
    main()
