"""Seed Cedar policies: 4 read permits outright, 2 write permits conditional on verification."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import boto3

from scripts._common import OUTPUTS_FILE, load_outputs


def create_policy(control, engine_id: str, name: str, cedar: str, description: str):
    print(f"  Creating: {name}...")
    response = control.create_policy(
        policyEngineId=engine_id,
        name=name,
        definition={"cedar": {"statement": cedar}},
        description=description,
        validationMode="IGNORE_ALL_FINDINGS",
    )
    policy_id = response["policyId"]
    for _ in range(10):
        time.sleep(2)
        detail = control.get_policy(policyEngineId=engine_id, policyId=policy_id)
        status = detail.get("status", "UNKNOWN")
        if status == "ACTIVE":
            print(f"    Active: {policy_id}")
            return policy_id
        if "FAILED" in status:
            print(f"    FAILED: {detail.get('statusReasons', [])}")
            return None
    print(f"    TIMEOUT (last status: {status})")
    return None


def main():
    if not OUTPUTS_FILE.exists():
        print("ERROR: infrastructure/cdk-outputs.json not found.")
        raise SystemExit(1)

    outputs = load_outputs()
    region = outputs.get("Region", "us-east-1")
    engine_id = outputs.get("PolicyEngineId")
    gateway_arn = outputs.get("GatewayArn")

    if not engine_id or not gateway_arn:
        print("ERROR: PolicyEngineId or GatewayArn missing from cdk-outputs.json.")
        raise SystemExit(1)

    control = boto3.client("bedrock-agentcore-control", region_name=region)

    print(f"Policy Engine: {engine_id}")
    print(f"Gateway ARN:   {gateway_arn}")
    print()

    # ── Four read permits (outright, no conditions) ────────────────────────────
    # Cedar notes:
    #   - principal is omitted for fleet-wide permits (cleaner than principal.id like "*")
    #   - action uses the TargetName___tool_name triple-underscore convention
    #   - resource must be the specific Gateway ARN (wildcards rejected)
    print("Creating read permits...")
    read_tools = [
        ("GetCustomer___get_customer",                "permit_get_customer"),
        ("GetOrder___get_order",                      "permit_get_order"),
        ("VerifyIdentity___verify_identity",          "permit_verify_identity"),
        ("CheckRefund___check_refund_eligibility",    "permit_check_refund_eligibility"),
    ]
    for action_name, policy_name in read_tools:
        cedar = (
            f'permit(\n'
            f'  principal,\n'
            f'  action == AgentCore::Action::"{action_name}",\n'
            f'  resource == AgentCore::Gateway::"{gateway_arn}"\n'
            f');'
        )
        create_policy(control, engine_id, policy_name, cedar, f"Permit {action_name}")

    print()

    # ── Two write permits (conditional on declared customer_verified) ───────────
    # Cedar notes:
    #   - context.input has customer_verified  (bare identifier, not quoted string)
    #   - context.input.customer_verified == true
    #   - context.system.now is the engine-injected trusted clock (not context.now)
    print("Creating conditional write permits...")
    write_tools = [
        ("UpdateCustomer___update_customer_field",    "permit_update_customer_field"),
        ("ProcessRefund___process_refund",            "permit_process_refund"),
    ]
    for action_name, policy_name in write_tools:
        cedar = (
            f'permit(\n'
            f'  principal,\n'
            f'  action == AgentCore::Action::"{action_name}",\n'
            f'  resource == AgentCore::Gateway::"{gateway_arn}"\n'
            f')\n'
            f'when {{\n'
            f'  context.input has customer_verified && context.input.customer_verified == true\n'
            f'}};'
        )
        create_policy(control, engine_id, policy_name, cedar, f"Permit {action_name} when customer_verified")

    print()
    print("Done. All 6 tools permitted (reads outright; writes conditional on verification).")
    print("The boundary is correct and complete from the start — Part Four's agent")
    print("has agency over its skills, not its permissions.")
    print()
    print("Next: python scripts/seed_data.py")


if __name__ == "__main__":
    main()