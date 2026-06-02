"""
Create the AWS Agent Registry for the skill-growth POC.

No L1 CDK construct exists for Registry (as of CDK 2.1124.0), so this
script creates it via the SDK after the CDK stack is deployed.

Run after: cdk deploy --outputs-file cdk-outputs.json
Run before: main.py (the scenario runner)

Usage: python seed_registry.py
"""

import json
import time
from pathlib import Path

import boto3

OUTPUTS_FILE = Path(__file__).parent / "infrastructure" / "cdk-outputs.json"
STACK_NAME = "SkillGrowthStack"
REGION = json.loads(OUTPUTS_FILE.read_text())[STACK_NAME].get("Region", "us-east-1")
REGISTRY_NAME = "skill_growth_registry"

control = boto3.client("bedrock-agentcore-control", region_name=REGION)


def main():
    # Check if registry already exists
    registries = control.list_registries().get("registries", [])
    existing = next((r for r in registries if r["name"] == REGISTRY_NAME), None)

    if existing:
        registry_id = existing["registryId"]
        print(f"Registry already exists: {registry_id} (status: {existing['status']})")
    else:
        print("Creating Registry...")
        response = control.create_registry(
            name=REGISTRY_NAME,
            description="Shared skill commons for the customer-service Executor class.",
            approvalConfiguration={"autoApproval": True},
        )
        # Get ID from list (create response only returns ARN)
        time.sleep(2)
        registries = control.list_registries().get("registries", [])
        registry = next(r for r in registries if r["name"] == REGISTRY_NAME)
        registry_id = registry["registryId"]
        print(f"Created: {registry_id}")

        # Wait for READY
        print("Waiting for READY...")
        for _ in range(24):
            time.sleep(5)
            r = control.get_registry(registryId=registry_id)
            if r.get("status") == "READY":
                print("  Ready.")
                break
        else:
            print("  TIMEOUT waiting for READY.")
            return

    # Write registry ID to outputs file (append to CDK outputs)
    if OUTPUTS_FILE.exists():
        outputs = json.loads(OUTPUTS_FILE.read_text())
    else:
        outputs = {STACK_NAME: {}}

    outputs.setdefault(STACK_NAME, {})["RegistryId"] = registry_id
    outputs[STACK_NAME]["RegistryArn"] = (
        f"arn:aws:bedrock-agentcore:{REGION}:{boto3.client('sts').get_caller_identity()['Account']}:registry/{registry_id}"
    )
    OUTPUTS_FILE.write_text(json.dumps(outputs, indent=2))
    print(f"Registry ID written to {OUTPUTS_FILE}")
    print(f"\n  RegistryId: {registry_id}")


if __name__ == "__main__":
    main()
