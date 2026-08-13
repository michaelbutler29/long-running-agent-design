"""Full reset: clear all runtime resources (policies, registry, memory, data). """

import json
import shutil
import time
from pathlib import Path

import boto3

from scripts._common import SAMPLE_ROOT, OUTPUTS_FILE, STACK_NAME


def load_outputs():
    return json.loads(OUTPUTS_FILE.read_text()).get(STACK_NAME, {})


def clear_policies(control, engine_id: str):
    print("── Policy Engine ──────────────────────────────────────────────")
    policies = control.list_policies(policyEngineId=engine_id).get("policies", [])
    if not policies:
        print("  No policies.")
        return
    for p in policies:
        try:
            control.delete_policy(policyEngineId=engine_id, policyId=p["policyId"])
            print(f"  Deleted: {p['name']}")
        except Exception as e:
            print(f"  Error deleting {p['name']}: {e}")
    print(f"  {len(policies)} policies deleted.")


def clear_registry(registry, registry_id: str):
    print("── Registry ───────────────────────────────────────────────────")
    try:
        records = registry.list_registry_records(registryId=registry_id).get("registryRecords", [])
        if not records:
            print("  No records.")
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


def clear_memory(data, control, memory_id: str):
    print("── Memory ─────────────────────────────────────────────────────")
    print("  (This may take a moment.)")

    # Discover the summary strategy ID to scope namespace reads.
    try:
        mem = control.get_memory(memoryId=memory_id)
        memory_data = mem.get("memory", mem)
        strategy_id = None
        for s in memory_data.get("strategies", []):
            if s.get("type") == "SUMMARY" or "summar" in s.get("name", "").lower():
                strategy_id = s["strategyId"]
                break
    except Exception as e:
        print(f"  Could not determine strategy ID: {e}")
        strategy_id = None

    total_deleted = 0

    if strategy_id:
        # Delete extracted summary records.
        while True:
            try:
                records = data.list_memory_records(
                    memoryId=memory_id,
                    namespacePath=f"summaries/",
                    memoryStrategyId=strategy_id,
                ).get("memoryRecordSummaries", [])
                if not records:
                    break
                batch = [{"memoryRecordId": r["memoryRecordId"]} for r in records]
                data.batch_delete_memory_records(memoryId=memory_id, records=batch)
                total_deleted += len(batch)
            except Exception as e:
                print(f"  Error deleting summary records: {e}")
                break
        print(f"  {total_deleted} summary records deleted.")

    # Delete raw events (Run Summary blobs, decision blobs) by listing sessions.
    # Sessions are per-variant per-experiment — enumerate the expected actor IDs.
    arms = ["v0", "v1", "v2"]
    experiments = [1]
    actor_ids = [f"{arm}-exp{exp}" for arm in arms for exp in experiments]
    # Also include the blob-only sessions (runsummary-*, decisions-*)
    blob_sessions = (
        [f"runsummary-{a}" for a in actor_ids] +
        [f"decisions-{a}" for a in actor_ids]
    )
    all_actors = set(actor_ids)

    events_deleted = 0
    for actor in all_actors:
        try:
            sess_resp = data.list_sessions(memoryId=memory_id, actorId=actor)
            sessions = (
                sess_resp.get("sessions") or
                sess_resp.get("sessionSummaries") or []
            )
            for s in sessions:
                sid = s["sessionId"]
                try:
                    ev_resp = data.list_events(memoryId=memory_id, sessionId=sid, actorId=actor)
                    events = ev_resp.get("events") or ev_resp.get("eventSummaries") or []
                    for ev in events:
                        eid = ev.get("eventId") or ev.get("id")
                        if eid:
                            data.delete_event(
                                memoryId=memory_id, sessionId=sid,
                                eventId=eid, actorId=actor,
                            )
                            events_deleted += 1
                except Exception:
                    pass
        except Exception:
            pass
    print(f"  {events_deleted} events deleted.")


def _clear_table(dynamodb, table_name: str, key_attr: str):
    table = dynamodb.Table(table_name)
    scan = table.scan(ProjectionExpression=key_attr)
    items = scan.get("Items", [])
    while scan.get("LastEvaluatedKey"):
        scan = table.scan(ProjectionExpression=key_attr,
                          ExclusiveStartKey=scan["LastEvaluatedKey"])
        items.extend(scan.get("Items", []))
    for item in items:
        table.delete_item(Key={key_attr: item[key_attr]})
    return len(items)


def clear_data(region: str, outputs: dict):
    print("── DynamoDB ───────────────────────────────────────────────────")
    dynamodb = boto3.resource("dynamodb", region_name=region)
    for label, table_name, key_attr in [
        ("customers", outputs.get("CustomerTableName", "well-being-customers"), "id"),
        ("orders", outputs.get("OrdersTableName", "well-being-orders"), "order_id"),
        ("verifications", outputs.get("VerificationTableName", "well-being-verifications"), "customer_id"),
    ]:
        count = _clear_table(dynamodb, table_name, key_attr)
        print(f"  {count} {label} deleted from {table_name}.")


def delete_local_state():
    print("── Local state/ ───────────────────────────────────────────────")
    state_dir = SAMPLE_ROOT / "state"
    if state_dir.exists():
        shutil.rmtree(state_dir)
        print("  Removed: state/")
    else:
        print("  No state/ folder.")


def main():
    # Windows consoles default to cp1252 and crash on the box-drawing characters
    # this script prints; force UTF-8 output (matches the other entry scripts).
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    if not OUTPUTS_FILE.exists():
        print("ERROR: infrastructure/cdk-outputs.json not found.")
        raise SystemExit(1)

    outputs = load_outputs()
    region = outputs.get("Region", "us-east-1")
    engine_id = outputs.get("PolicyEngineId")
    registry_id = outputs.get("RegistryId")
    memory_id = outputs.get("MemoryId")

    print()
    print("=" * 60)
    print("  FULL RESET — clears all cloud runtime state.")
    print()
    print("  This will delete:")
    print("    - All Cedar policies")
    print("    - All Registry records (published skills)")
    print("    - All Memory records (summaries, blob checkpoints)")
    print("    - DynamoDB data (customers, orders, verifications)")
    print()
    print("  Local state/ is preserved (prior runs remain for comparison).")
    print()
    print("  Re-run setup after reset:")
    print("    python scripts/seed_registry.py")
    print("    python scripts/seed_policy.py")
    print("    python scripts/seed_data.py")
    print("=" * 60)
    print()

    confirm = input("  Proceed? [y/N] ")
    if confirm.lower() not in ("y", "yes"):
        print("  Aborted.")
        return

    print()
    control = boto3.client("bedrock-agentcore-control", region_name=region)
    data = boto3.client("bedrock-agentcore", region_name=region)
    registry = boto3.client("agent-registry-control", region_name=region)

    if engine_id:
        clear_policies(control, engine_id)
    else:
        print("No PolicyEngineId — skipping policy cleanup.")
    print()

    if registry_id:
        clear_registry(registry, registry_id)
    else:
        print("No RegistryId — skipping registry cleanup.")
    print()

    if memory_id:
        clear_memory(data, control, memory_id)
    else:
        print("No MemoryId — skipping memory cleanup.")
    print()

    clear_data(region, outputs)
    print()

    print("=" * 60)
    print("  Reset complete.")
    print()
    print("  Re-run setup:")
    print("    python scripts/seed_registry.py")
    print("    python scripts/seed_policy.py")
    print("    python scripts/seed_data.py")
    print("=" * 60)


if __name__ == "__main__":
    main()