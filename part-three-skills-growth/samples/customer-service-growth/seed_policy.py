"""
Seed initial Cedar policies for the skill-growth POC.

Creates permits for read-only tools (get_customer, get_order, verify_identity,
check_refund_eligibility). Write tools (update_customer_field, process_refund)
start DENIED — the Curator proposes expansions as skills emerge.

Run after: cdk deploy --outputs-file cdk-outputs.json
Run before: main.py (the scenario runner)

Usage: python seed_policy.py
"""

import json
import time
from pathlib import Path

import boto3

OUTPUTS_FILE = Path(__file__).parent / "infrastructure" / "cdk-outputs.json"
STACK_NAME = "SkillGrowthStack"
REGION = json.loads(OUTPUTS_FILE.read_text())[STACK_NAME].get("Region", "us-east-1")

control = boto3.client("bedrock-agentcore-control", region_name=REGION)


def load_outputs():
    outputs = json.loads(OUTPUTS_FILE.read_text())[STACK_NAME]
    return {
        "policy_engine_id": outputs["PolicyEngineId"],
        "gateway_arn": outputs["GatewayArn"],
    }


def create_policy(engine_id: str, name: str, cedar: str, description: str):
    """Create a Cedar policy and wait for it to become ACTIVE."""
    print(f"  Creating: {name}...")
    response = control.create_policy(
        policyEngineId=engine_id,
        name=name,
        definition={"cedar": {"statement": cedar}},
        description=description,
        validationMode="IGNORE_ALL_FINDINGS",
    )
    policy_id = response["policyId"]

    # Wait for ACTIVE
    for _ in range(10):
        time.sleep(2)
        detail = control.get_policy(policyEngineId=engine_id, policyId=policy_id)
        status = detail.get("status", "UNKNOWN")
        if status == "ACTIVE":
            print(f"    Active: {policy_id}")
            return policy_id
        if "FAILED" in status:
            reasons = detail.get("statusReasons", [])
            print(f"    FAILED: {reasons}")
            return None
    print(f"    TIMEOUT (last status: {status})")
    return None


def main():
    config = load_outputs()
    engine_id = config["policy_engine_id"]
    gateway_arn = config["gateway_arn"]

    print(f"Policy Engine: {engine_id}")
    print(f"Gateway ARN:   {gateway_arn}")
    print()

    print("Creating read-only permits...")

    # Permit read-only tools for the deployer's role
    read_tools = [
        ("GetCustomer___get_customer", "Permit get_customer"),
        ("GetOrder___get_order", "Permit get_order"),
        ("VerifyIdentity___verify_identity", "Permit verify_identity"),
        ("CheckRefund___check_refund_eligibility", "Permit check_refund_eligibility"),
    ]

    for tool_action, description in read_tools:
        cedar = (
            f'permit(\n'
            f'  principal,\n'
            f'  action == AgentCore::Action::"{tool_action}",\n'
            f'  resource == AgentCore::Gateway::"{gateway_arn}"\n'
            f');'
        )
        create_policy(engine_id, f"seed_{tool_action.split('___')[1]}", cedar, description)

    print()
    print("Done. Write tools (update_customer_field, process_refund) are DENIED by default.")
    print("The Curator will propose Cedar permits as skills emerge.")


if __name__ == "__main__":
    main()
