"""
Reset all runtime state so the demo can be re-run from scratch.

Deletes:
  - All Cedar policies from the Policy Engine (seed + curator-approved)
  - All records from the Registry (skills published by the Curator)
  - All memory records (episodes + reflections from the episodic strategy, and decisions)
  - Resets DynamoDB seed data to original values

After cleanup, re-run:
  1. python seed_policy.py
  2. python scripts/01_run_customer_tasks.py

Does NOT destroy CDK infrastructure — use 'cdk destroy' for that.

Usage: python cleanup.py
"""

import json
from pathlib import Path

import boto3

OUTPUTS_FILE = Path(__file__).parent / "infrastructure" / "cdk-outputs.json"
STACK_NAME = "SkillGrowthStack"

if not OUTPUTS_FILE.exists():
    print("ERROR: infrastructure/cdk-outputs.json not found.")
    print("       Run 'cdk deploy --outputs-file cdk-outputs.json' first.")
    raise SystemExit(1)

REGION = json.loads(OUTPUTS_FILE.read_text())[STACK_NAME].get("Region", "us-east-1")

control = boto3.client("bedrock-agentcore-control", region_name=REGION)
data = boto3.client("bedrock-agentcore", region_name=REGION)
# Only Registry moved namespaces; Policy Engine and Memory stay put.
registry = boto3.client("agent-registry-control", region_name=REGION)
dynamodb = boto3.client("dynamodb", region_name=REGION)


def load_outputs():
    return json.loads(OUTPUTS_FILE.read_text())[STACK_NAME]


def cleanup_policies(engine_id: str):
    """Delete all policies from the engine."""
    print("── Policy Engine ───────────────────────────────────────────")
    policies = control.list_policies(policyEngineId=engine_id).get("policies", [])
    if not policies:
        print("  No policies to delete.")
        return
    for p in policies:
        try:
            control.delete_policy(policyEngineId=engine_id, policyId=p["policyId"])
            print(f"  Deleted: {p['name']}")
        except Exception as e:
            print(f"  Error deleting {p['name']}: {e}")
    print(f"  {len(policies)} policies deleted.")


def cleanup_registry(registry_id: str):
    """Delete all records from the registry."""
    print("── Registry ────────────────────────────────────────────────")
    try:
        records = registry.list_registry_records(registryId=registry_id).get("registryRecords", [])
        if not records:
            print("  No records to delete.")
            return
        for r in records:
            try:
                registry.delete_registry_record(registryId=registry_id, recordId=r["recordId"])
                print(f"  Deleted: {r['name']}")
            except Exception as e:
                print(f"  Error deleting {r['name']}: {e}")
        print(f"  {len(records)} records deleted.")
    except Exception as e:
        print(f"  Error: {e}")


def cleanup_memory(memory_id: str):
    """Delete all memory records (episodes + reflections)."""
    print("── Memory ──────────────────────────────────────────────────")
    print("  (NOTE: This step may take several minutes.)")
    # Get strategy ID
    response = control.get_memory(memoryId=memory_id)
    memory_data = response.get("memory", response)
    strategies = memory_data.get("strategies", [])
    strategy_id = None
    for s in strategies:
        if s.get("type") == "EPISODIC":
            strategy_id = s["strategyId"]
            break

    if not strategy_id:
        print("  No episodic strategy found — skipping.")
        return

    # Delete extracted records (episodes + reflections).
    # Use namespacePath (no leading slash) to list all records under the strategy.
    ns_path = f"strategy/{strategy_id}/"
    total_deleted = 0
    while True:
        try:
            records = data.list_memory_records(
                memoryId=memory_id,
                namespacePath=ns_path,
                memoryStrategyId=strategy_id,
            ).get("memoryRecordSummaries", [])

            if not records:
                break

            batch = [{"memoryRecordId": r["memoryRecordId"]} for r in records]
            data.batch_delete_memory_records(memoryId=memory_id, records=batch)
            total_deleted += len(batch)
        except Exception as e:
            print(f"  Error deleting records: {e}")
            break

    print(f"  {total_deleted} memory records (episodes + reflections) deleted.")

    # Delete decision records (written by log_decision to /decisions/ namespace)
    decisions_deleted = 0
    while True:
        try:
            records = data.list_memory_records(
                memoryId=memory_id,
                namespacePath="decisions/",
            ).get("memoryRecordSummaries", [])

            if not records:
                break

            batch = [{"memoryRecordId": r["memoryRecordId"]} for r in records]
            data.batch_delete_memory_records(memoryId=memory_id, records=batch)
            decisions_deleted += len(batch)
        except Exception as e:
            print(f"  Error deleting decision records: {e}")
            break

    print(f"  {decisions_deleted} decision records deleted.")

    # Delete raw events and sessions (prevents stale backlog from slowing extraction)
    try:
        session_response = data.list_sessions(memoryId=memory_id, actorId="executor")
        # Response key may vary — try common patterns
        sessions = (
            session_response.get("sessions")
            or session_response.get("sessionSummaries")
            or []
        )
    except Exception as e:
        print(f"  Error listing sessions: {e}")
        sessions = []

    events_deleted = 0
    for s in sessions:
        sid = s["sessionId"]
        try:
            event_response = data.list_events(
                memoryId=memory_id, sessionId=sid, actorId="executor"
            )
            events = (
                event_response.get("events")
                or event_response.get("eventSummaries")
                or []
            )
            for ev in events:
                eid = ev.get("eventId") or ev.get("id")
                if eid:
                    data.delete_event(
                        memoryId=memory_id,
                        sessionId=sid,
                        eventId=eid,
                        actorId="executor",
                    )
                    events_deleted += 1
        except Exception as e:
            print(f"  Error deleting events for session {sid}: {e}")

    print(f"  {events_deleted} events deleted across {len(sessions)} sessions.")


def reset_dynamodb(customer_table: str, orders_table: str, verification_table: str):
    """Reset DynamoDB tables to original seed data."""
    print("── DynamoDB ────────────────────────────────────────────────")

    # Reset customer CUST-001 to original values
    dynamodb.put_item(
        TableName=customer_table,
        Item={
            "id": {"S": "CUST-001"},
            "first_name": {"S": "Alice"},
            "last_name": {"S": "Smith"},
            "email": {"S": "alice@example.com"},
            "phone": {"S": "555-0101"},
            "status": {"S": "active"},
        },
    )
    print("  Reset CUST-001 (Alice Smith) to original values.")

    # Reset CUST-002 (shouldn't have changed, but ensure consistency)
    dynamodb.put_item(
        TableName=customer_table,
        Item={
            "id": {"S": "CUST-002"},
            "first_name": {"S": "Bob"},
            "last_name": {"S": "Jones"},
            "email": {"S": "bob@example.com"},
            "phone": {"S": "555-0102"},
            "status": {"S": "active"},
        },
    )
    print("  Reset CUST-002 (Bob Jones) to original values.")

    # Reset order statuses (in case process_refund modified them)
    dynamodb.put_item(
        TableName=orders_table,
        Item={
            "order_id": {"S": "ORD-001"},
            "customer_id": {"S": "CUST-001"},
            "items": {"L": [{"M": {"name": {"S": "Wireless Mouse"}, "price": {"N": "29.99"}}}]},
            "total": {"N": "29.99"},
            "order_date": {"S": "2026-05-01T10:00:00+00:00"},
            "status": {"S": "DELIVERED"},
        },
    )
    dynamodb.put_item(
        TableName=orders_table,
        Item={
            "order_id": {"S": "ORD-002"},
            "customer_id": {"S": "CUST-001"},
            "items": {"L": [{"M": {"name": {"S": "USB-C Cable"}, "price": {"N": "12.99"}}}]},
            "total": {"N": "12.99"},
            "order_date": {"S": "2026-05-10T14:00:00+00:00"},
            "status": {"S": "SHIPPED"},
        },
    )
    dynamodb.put_item(
        TableName=orders_table,
        Item={
            "order_id": {"S": "ORD-003"},
            "customer_id": {"S": "CUST-002"},
            "items": {"L": [{"M": {"name": {"S": "Bluetooth Speaker"}, "price": {"N": "49.99"}}}]},
            "total": {"N": "49.99"},
            "order_date": {"S": "2026-04-15T09:00:00+00:00"},
            "status": {"S": "DELIVERED"},
        },
    )
    print("  Reset all orders to original values.")

    # Clear verification records
    try:
        scan = dynamodb.scan(TableName=verification_table)
        for item in scan.get("Items", []):
            dynamodb.delete_item(
                TableName=verification_table,
                Key={"customer_id": item["customer_id"]},
            )
        print(f"  Cleared {len(scan.get('Items', []))} verification record(s).")
    except Exception as e:
        print(f"  Error clearing verifications: {e}")


TEMPLATE_DIR = Path(__file__).parent.parent.parent / "template"
GOLDEN_DIR = TEMPLATE_DIR / "golden"
BUGGED_DIR = TEMPLATE_DIR / "bugged"


def reset_from_template():
    """Reset all mutable files to their baseline state.

    The Curator's system prompt and curation skill reset to the *bugged*
    baseline (missing guardrails). The executor prompt, reflection skill,
    and policy-evaluation skill reset from the golden template.

    The demo starts with degraded judgment — the system must discover the
    missing principles through metacognitive self-revision.
    """
    print("── Files (from template) ───────────────────────────────────")

    # Golden copies — these are correct from the start
    golden_copies = [
        ("agents/executor/system_prompt.md", "agents/executor/system_prompt.md"),
        ("skills/reflection-skill/SKILL.md", "skills/reflection-skill/SKILL.md"),
        ("skills/policy-evaluation-skill/SKILL.md", "skills/policy-evaluation-skill/SKILL.md"),
    ]

    # Bugged copies — intentionally degraded for the metacognition experiment
    bugged_copies = [
        ("agents/curator/system_prompt.md", "agents/curator/system_prompt.md"),
        ("skills/curation-skill/SKILL.md", "skills/curation-skill/SKILL.md"),
    ]

    project_root = Path(__file__).parent

    for template_rel, target_rel in golden_copies:
        src = GOLDEN_DIR / template_rel
        dst = project_root / target_rel
        if src.exists():
            dst.write_text(src.read_text())
            print(f"  Reset: {target_rel}")
        else:
            print(f"  MISSING template: {template_rel}")

    for template_rel, target_rel in bugged_copies:
        src = BUGGED_DIR / template_rel
        dst = project_root / target_rel
        if src.exists():
            dst.write_text(src.read_text())
            print(f"  Reset: {target_rel} (bugged baseline)")
        else:
            print(f"  MISSING bugged template: {template_rel}")


def main():
    outputs = load_outputs()
    engine_id = outputs.get("PolicyEngineId")
    registry_id = outputs.get("RegistryId")
    memory_id = outputs.get("MemoryId")
    customer_table = outputs.get("CustomerTableName", "skill-growth-customers")
    orders_table = outputs.get("OrdersTableName", "skill-growth-orders")
    verification_table = outputs.get("VerificationTableName", "skill-growth-verifications")

    print()
    print("=" * 60)
    print("  WARNING: This resets to the BUGGED baseline.")
    print()
    print("  The Curator's system prompt and curation skill will be")
    print("  restored to an intentionally degraded state (missing")
    print("  guardrails). This is the starting point for the")
    print("  metacognition experiment.")
    print()
    print("  Golden (correct) versions live in: template/golden/")
    print("  Bugged (starting) versions live in: template/bugged/")
    print("=" * 60)
    print()

    confirm = input("  Proceed? [y/N] ")
    if confirm.lower() not in ("y", "yes"):
        print("  Aborted.")
        return

    print()
    print("  Resetting all runtime state...")
    print()

    if engine_id:
        cleanup_policies(engine_id)
    else:
        print("No PolicyEngineId in outputs — skipping.")
    print()

    if registry_id:
        cleanup_registry(registry_id)
    else:
        print("No RegistryId in outputs — skipping.")
    print()

    if memory_id:
        cleanup_memory(memory_id)
    else:
        print("No MemoryId in outputs — skipping.")
    print()

    reset_dynamodb(customer_table, orders_table, verification_table)
    print()

    reset_from_template()
    print()

    # Remove runtime state files
    state_dir = Path(__file__).parent / "state"
    if state_dir.exists():
        import shutil
        shutil.rmtree(state_dir)
        print("  Removed: state/")
    print()

    print()
    print("=" * 60)
    print("  Cleanup complete. To re-run the demo:")
    print()
    print("  1. python seed_policy.py")
    print("  2. python scripts/01_run_customer_tasks.py")
    print("  3. python scripts/02_inspect_state.py")
    print("  4. python scripts/03_run_curator.py          (cycle 1)")
    print("  5. python scripts/04_run_customer_tasks.py   (run 2)")
    print("  6. python scripts/02_inspect_state.py")
    print("  7. python scripts/03_run_curator.py          (cycle 2 — reflection)")
    print("=" * 60)


if __name__ == "__main__":
    main()
