#!/usr/bin/env python3
"""CDK app entry point for the customer-service-assistant policy-skill proof-of-concept."""

import os

import aws_cdk as cdk

from stack import PolicySkillSampleStack

app = cdk.App()

PolicySkillSampleStack(
    app,
    "PolicySkillSampleStack",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
    ),
    description="customer-service-assistant proof-of-concept: Gateway + PolicyEngine + DynamoDB + Lambdas for the policy-skill pattern.",
)

app.synth()
