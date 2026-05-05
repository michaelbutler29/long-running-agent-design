"""
Reset the sample to a clean demo state.

Deletes ALL policies from the Policy Engine (it's a dedicated engine for
this sample) and clears runtime artifacts from proposals/.
"""

import json
import sys
from pathlib import Path

import boto3

OUTPUTS_FILE = Path(__file__).parent / "infrastructure" / "cdk-outputs.json"
STACK_NAME = "PolicySkillSampleStack"
PROPOSALS_DIR = Path(__file__).parent / "proposals"


def main() -> int:
    if not OUTPUTS_FILE.exists():
        print(f"ERROR: {OUTPUTS_FILE} not found. Run cdk deploy first.", file=sys.stderr)
        return 1

    outputs = json.loads(OUTPUTS_FILE.read_text())[STACK_NAME]
    policy_engine_id = outputs["PolicyEngineId"]
    region = outputs["Region"]

    client = boto3.client("bedrock-agentcore-control", region_name=region)

    deleted = 0
    paginator = client.get_paginator("list_policies")
    for page in paginator.paginate(policyEngineId=policy_engine_id):
        for policy in page.get("policies", []):
            policy_id = policy["policyId"]
            name = policy.get("name", "")
            client.delete_policy(policyEngineId=policy_engine_id, policyId=policy_id)
            print(f"Deleted policy: {name} ({policy_id})")
            deleted += 1

    if deleted == 0:
        print("No policies found.")
    else:
        print(f"\nDeleted {deleted} {'policy' if deleted == 1 else 'policies'}.")

    # Clear proposals directory
    cleared = 0
    for f in PROPOSALS_DIR.glob("proposal_*"):
        f.unlink()
        cleared += 1

    if cleared > 0:
        print(f"Cleared {cleared} proposal files from proposals/.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
