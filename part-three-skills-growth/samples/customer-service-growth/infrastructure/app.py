#!/usr/bin/env python3
"""CDK app entry point for the skill-growth proof-of-concept (Part Three)."""

import os

import aws_cdk as cdk

from stack import SkillGrowthStack

app = cdk.App()

SkillGrowthStack(
    app,
    "SkillGrowthStack",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
    ),
    description="skill-growth POC: Gateway + PolicyEngine + Memory + Registry + DynamoDB + Lambdas for the skill lifecycle pattern.",
)

app.synth()
