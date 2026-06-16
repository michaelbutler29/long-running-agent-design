"""
Load the 10 customers and 24 orders into DynamoDB.

Order dates are computed relative to today so eligibility never goes stale
for someone cloning the repo months later. The seed-data.json file holds
the intent (status, offset_days, details); this script realizes concrete dates.

Re-runnable: existing items are overwritten with put_item (idempotent).
The driver also calls this (via _restore_seed_data) at each arm boundary to
reset the world back to baseline after mutations (refunds, contact updates).

Run after:  seed_policy.py
Run before: run_experiment.py

Usage: python scripts/seed_data.py
"""

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import boto3
from boto3.dynamodb.types import TypeSerializer

SAMPLE_ROOT = Path(__file__).resolve().parents[1]
OUTPUTS_FILE = SAMPLE_ROOT / "infrastructure" / "cdk-outputs.json"
STACK_NAME = "PartFourWellBeingStack"
SEED_FILE = SAMPLE_ROOT / "infrastructure" / "seed-data.json"

_serializer = TypeSerializer()


def _to_dynamo(obj):
    """Convert a Python dict/list to DynamoDB low-level format."""
    if isinstance(obj, dict):
        return {k: _to_dynamo(v) for k, v in obj.items()}
    return _serializer.serialize(obj)


def _load_outputs():
    return json.loads(OUTPUTS_FILE.read_text())[STACK_NAME]


def seed_customers(dynamodb, table_name: str, customers: list):
    table = dynamodb.Table(table_name)
    for c in customers:
        item = {k: v for k, v in c.items() if not k.startswith("_")}
        table.put_item(Item=item)
    print(f"  {len(customers)} customers loaded into {table_name}.")


def seed_orders(dynamodb, table_name: str, orders: list):
    table = dynamodb.Table(table_name)
    today = datetime.now(timezone.utc)
    for o in orders:
        item = {k: v for k, v in o.items() if not k.startswith("_")}
        offset = item.pop("order_date_offset_days")
        order_dt = today + timedelta(days=offset)
        item["order_date"] = order_dt.isoformat()
        # Convert numeric values to Decimal for DynamoDB
        item["total"] = Decimal(str(item["total"]))
        item["items"] = [
            {k: (Decimal(str(v)) if isinstance(v, float) else v) for k, v in i.items()}
            for i in item["items"]
        ]
        table.put_item(Item=item)
    print(f"  {len(orders)} orders loaded into {table_name}.")


def clear_verifications(dynamodb, table_name: str):
    table = dynamodb.Table(table_name)
    scan = table.scan()
    for item in scan.get("Items", []):
        table.delete_item(Key={"customer_id": item["customer_id"]})
    count = len(scan.get("Items", []))
    if count:
        print(f"  {count} verification record(s) cleared from {table_name}.")


def main():
    if not OUTPUTS_FILE.exists():
        print("ERROR: infrastructure/cdk-outputs.json not found.")
        raise SystemExit(1)

    outputs = _load_outputs()
    region = outputs.get("Region", "us-east-1")
    customer_table = outputs.get("CustomerTableName", "well-being-customers")
    orders_table = outputs.get("OrdersTableName", "well-being-orders")
    verification_table = outputs.get("VerificationTableName", "well-being-verifications")

    seed = json.loads(SEED_FILE.read_text())
    dynamodb = boto3.resource("dynamodb", region_name=region)

    print(f"Region:  {region}")
    print(f"Tables:  {customer_table}, {orders_table}, {verification_table}")
    print()

    seed_customers(dynamodb, customer_table, seed["customers"])
    seed_orders(dynamodb, orders_table, seed["orders"])
    clear_verifications(dynamodb, verification_table)

    print()
    print("Done. Ready to run the experiment.")
    print("Next: python scripts/run_experiment.py --pilot")


if __name__ == "__main__":
    main()