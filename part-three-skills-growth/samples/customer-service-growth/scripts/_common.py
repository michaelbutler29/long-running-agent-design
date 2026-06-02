"""Shared utilities for demo scripts."""

import json
import sys
from pathlib import Path

import boto3

OUTPUTS_FILE = Path(__file__).parent.parent / "infrastructure" / "cdk-outputs.json"
STACK_NAME = "SkillGrowthStack"


def load_config():
    outputs = json.loads(OUTPUTS_FILE.read_text())[STACK_NAME]
    import os
    os.environ.setdefault("AWS_REGION", outputs.get("Region", "us-east-1"))
    os.environ.setdefault("AGENTCORE_GATEWAY_URL", outputs["GatewayUrl"])
    os.environ.setdefault("AGENTCORE_GATEWAY_ARN", outputs["GatewayArn"])
    os.environ.setdefault("AGENTCORE_MEMORY_ID", outputs["MemoryId"])
    os.environ.setdefault("AGENTCORE_REGISTRY_ID", outputs["RegistryId"])
    os.environ.setdefault("AGENTCORE_POLICY_ENGINE_ID", outputs["PolicyEngineId"])


def check_policies_exist():
    """Fail fast if seed policies haven't been created."""
    outputs = json.loads(OUTPUTS_FILE.read_text())[STACK_NAME]
    region = outputs.get("Region", "us-east-1")
    engine_id = outputs.get("PolicyEngineId")
    if not engine_id:
        return

    control = boto3.client("bedrock-agentcore-control", region_name=region)
    policies = control.list_policies(policyEngineId=engine_id).get("policies", [])
    seed = [p for p in policies if p["name"].startswith("seed_")]
    if not seed:
        print("ERROR: No seed policies found in Policy Engine.")
        print("       Run 'python seed_policy.py' first.")
        sys.exit(1)


def clear_verifications():
    """Clear the verification table so each conversation starts fresh."""
    outputs = json.loads(OUTPUTS_FILE.read_text())[STACK_NAME]
    region = outputs.get("Region", "us-east-1")
    table_name = outputs.get("VerificationTableName", "skill-growth-verifications")
    ddb = boto3.client("dynamodb", region_name=region)
    try:
        scan = ddb.scan(TableName=table_name)
        for item in scan.get("Items", []):
            ddb.delete_item(TableName=table_name, Key={"customer_id": item["customer_id"]})
    except Exception:
        pass
