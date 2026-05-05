"""
Create the starting Cedar policy: permits the current IAM principal to call
get_customer_basics on the configured gateway.

Run once after deploying the CDK stack. The current AWS credentials become the
Cedar principal — run as the same identity the agent will use when invoking
the gateway.

Usage:
    python seed_policy.py

Reads infrastructure/cdk-outputs.json.
"""

import json
import sys
from pathlib import Path

import boto3

OUTPUTS_FILE = Path(__file__).parent / "infrastructure" / "cdk-outputs.json"
STACK_NAME = "PolicySkillSampleStack"
POLICY_NAME = "starting_get_customer_basics"


def main() -> int:
    outputs = json.loads(OUTPUTS_FILE.read_text())[STACK_NAME]
    gateway_arn = outputs["GatewayArn"]
    policy_engine_id = outputs["PolicyEngineId"]
    region = outputs["Region"]

    identity = boto3.client("sts").get_caller_identity()
    principal_arn = identity["Arn"]

    print(f"Principal:      {principal_arn}")
    print(f"Gateway ARN:    {gateway_arn}")
    print(f"Policy engine:  {policy_engine_id}")
    print()

    cedar = (
        f'permit (\n'
        f'  principal is AgentCore::IamEntity,\n'
        f'  action == AgentCore::Action::"CustomerBasics___get_customer_basics",\n'
        f'  resource == AgentCore::Gateway::"{gateway_arn}"\n'
        f')\n'
        f'when {{\n'
        f'  principal.id like "{principal_arn}"\n'
        f'}};'
    )
    print("Cedar fragment:")
    print(cedar)
    print()

    client = boto3.client("bedrock-agentcore-control", region_name=region)
    response = client.create_policy(
        policyEngineId=policy_engine_id,
        name=POLICY_NAME,
        definition={"cedar": {"statement": cedar}},
        validationMode="FAIL_ON_ANY_FINDINGS",
    )
    print(f"Created policy: {response.get('policyId', 'unknown')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
