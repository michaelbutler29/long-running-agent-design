#!/usr/bin/env python3
"""CDK app entry point for the Part Four well-being experiment."""

import os

import aws_cdk as cdk

from stack import WellBeingStack

app = cdk.App()

WellBeingStack(
    app,
    "PartFourWellBeingStack",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
    ),
    description="Part Four well-being experiment: Gateway + PolicyEngine + Memory + Registry + DynamoDB + Lambdas.",
)

app.synth()