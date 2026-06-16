"""
CDK stack for the Part Four well-being experiment.

Ported from Part Three's SkillGrowthStack. One structural change: Memory uses a
summary strategy (one long-term summary per session) instead of episodic.

Resources deployed:
  - DynamoDB: well-being-customers, well-being-orders, well-being-verifications
  - Lambda: 6 customer service tools
  - IAM role: well-being-gateway-service-role
  - AgentCore Policy Engine: well_being_engine (Cedar, ENFORCE)
  - AgentCore Gateway: well-being-gateway (AWS_IAM, MCP)
  - AgentCore Gateway Targets: 6 targets
  - AgentCore Memory: well_being_memory (summary strategy)

Not deployed by CDK (no L1 construct):
  - AWS Agent Registry — created by seed_registry.py, which also publishes
    the seeded customer-service skill into it.
"""

import json
from pathlib import Path

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_bedrockagentcore as agentcore,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    aws_lambda as _lambda,
)
from constructs import Construct


def _to_schema_definition(
    d: dict,
) -> "agentcore.CfnGatewayTarget.SchemaDefinitionProperty":
    properties = None
    if "properties" in d:
        properties = {
            name: _to_schema_definition(value) for name, value in d["properties"].items()
        }
    items = _to_schema_definition(d["items"]) if "items" in d else None
    return agentcore.CfnGatewayTarget.SchemaDefinitionProperty(
        type=d["type"],
        description=d.get("description"),
        properties=properties,
        required=d.get("required"),
        items=items,
    )


def _tool_def(t: dict) -> "agentcore.CfnGatewayTarget.ToolDefinitionProperty":
    return agentcore.CfnGatewayTarget.ToolDefinitionProperty(
        name=t["name"],
        description=t["description"],
        input_schema=_to_schema_definition(t["inputSchema"]),
        output_schema=(
            _to_schema_definition(t["outputSchema"]) if "outputSchema" in t else None
        ),
    )


class WellBeingStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── DynamoDB tables ────────────────────────────────────────────────────
        # Tables are created empty. seed_data.py populates them with date-relative
        # data so eligibility never goes stale for someone cloning months later.
        customer_table = dynamodb.Table(
            self,
            "CustomerTable",
            table_name="well-being-customers",
            partition_key=dynamodb.Attribute(
                name="id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        orders_table = dynamodb.Table(
            self,
            "OrdersTable",
            table_name="well-being-orders",
            partition_key=dynamodb.Attribute(
                name="order_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )
        orders_table.add_global_secondary_index(
            index_name="customer-id-index",
            partition_key=dynamodb.Attribute(
                name="customer_id", type=dynamodb.AttributeType.STRING
            ),
        )

        verification_table = dynamodb.Table(
            self,
            "VerificationTable",
            table_name="well-being-verifications",
            partition_key=dynamodb.Attribute(
                name="customer_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            time_to_live_attribute="ttl",
        )

        # ── Lambda functions ───────────────────────────────────────────────────
        lambda_dir = str(Path(__file__).parent / "lambda")

        get_customer_fn = _lambda.Function(
            self, "GetCustomerFn",
            function_name="well-being-get-customer",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="get_customer.handler",
            code=_lambda.Code.from_asset(lambda_dir),
            timeout=Duration.seconds(10),
            environment={"CUSTOMER_TABLE_NAME": customer_table.table_name},
        )
        customer_table.grant_read_data(get_customer_fn)

        get_order_fn = _lambda.Function(
            self, "GetOrderFn",
            function_name="well-being-get-order",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="get_order.handler",
            code=_lambda.Code.from_asset(lambda_dir),
            timeout=Duration.seconds(10),
            environment={"ORDERS_TABLE_NAME": orders_table.table_name},
        )
        orders_table.grant_read_data(get_order_fn)

        verify_identity_fn = _lambda.Function(
            self, "VerifyIdentityFn",
            function_name="well-being-verify-identity",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="verify_identity.handler",
            code=_lambda.Code.from_asset(lambda_dir),
            timeout=Duration.seconds(10),
            environment={
                "CUSTOMER_TABLE_NAME": customer_table.table_name,
                "VERIFICATION_TABLE_NAME": verification_table.table_name,
            },
        )
        customer_table.grant_read_data(verify_identity_fn)
        verification_table.grant_read_write_data(verify_identity_fn)

        update_customer_field_fn = _lambda.Function(
            self, "UpdateCustomerFieldFn",
            function_name="well-being-update-customer-field",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="update_customer_field.handler",
            code=_lambda.Code.from_asset(lambda_dir),
            timeout=Duration.seconds(10),
            environment={
                "CUSTOMER_TABLE_NAME": customer_table.table_name,
                "VERIFICATION_TABLE_NAME": verification_table.table_name,
            },
        )
        customer_table.grant_read_write_data(update_customer_field_fn)
        verification_table.grant_read_data(update_customer_field_fn)

        check_refund_fn = _lambda.Function(
            self, "CheckRefundFn",
            function_name="well-being-check-refund-eligibility",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="check_refund_eligibility.handler",
            code=_lambda.Code.from_asset(lambda_dir),
            timeout=Duration.seconds(10),
            environment={"ORDERS_TABLE_NAME": orders_table.table_name},
        )
        orders_table.grant_read_data(check_refund_fn)

        process_refund_fn = _lambda.Function(
            self, "ProcessRefundFn",
            function_name="well-being-process-refund",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="process_refund.handler",
            code=_lambda.Code.from_asset(lambda_dir),
            timeout=Duration.seconds(10),
            environment={
                "ORDERS_TABLE_NAME": orders_table.table_name,
                "VERIFICATION_TABLE_NAME": verification_table.table_name,
            },
        )
        orders_table.grant_read_write_data(process_refund_fn)
        verification_table.grant_read_data(process_refund_fn)

        # ── Policy Engine ──────────────────────────────────────────────────────
        policy_engine = agentcore.CfnPolicyEngine(
            self, "PolicyEngine",
            name="well_being_engine",
            description="Cedar policies for the Part Four well-being experiment. Reads permitted outright; writes conditional on declared verification.",
        )

        # ── Gateway service role ───────────────────────────────────────────────
        all_lambda_arns = [
            get_customer_fn.function_arn,
            get_order_fn.function_arn,
            verify_identity_fn.function_arn,
            update_customer_field_fn.function_arn,
            check_refund_fn.function_arn,
            process_refund_fn.function_arn,
        ]

        gateway_role = iam.Role(
            self, "GatewayServiceRole",
            role_name="well-being-gateway-service-role",
            assumed_by=iam.ServicePrincipal(
                "bedrock-agentcore.amazonaws.com",
                conditions={"StringEquals": {"aws:SourceAccount": self.account}},
            ),
            description="Assumed by AgentCore Gateway to invoke target Lambdas and evaluate Cedar policies.",
            inline_policies={
                "InvokeLambdaTargets": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            sid="InvokeAllTargetLambdas",
                            actions=["lambda:InvokeFunction"],
                            resources=all_lambda_arns,
                        ),
                    ]
                ),
                "PolicyEngineAccess": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            sid="PolicyEngineConfiguration",
                            actions=["bedrock-agentcore:GetPolicyEngine"],
                            resources=[policy_engine.attr_policy_engine_arn],
                        ),
                        iam.PolicyStatement(
                            sid="PolicyEngineAuthorization",
                            actions=[
                                "bedrock-agentcore:AuthorizeAction",
                                "bedrock-agentcore:PartiallyAuthorizeActions",
                            ],
                            resources=[
                                policy_engine.attr_policy_engine_arn,
                                f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:gateway/*",
                            ],
                        ),
                        iam.PolicyStatement(
                            sid="PolicyEnginePreflightCheck",
                            actions=["bedrock-agentcore:CheckAuthorizePermissions"],
                            resources=[f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:/policy-engines/*"],
                        ),
                    ]
                ),
            },
        )

        # ── Gateway ────────────────────────────────────────────────────────────
        gateway = agentcore.CfnGateway(
            self, "Gateway",
            name="well-being-gateway",
            role_arn=gateway_role.role_arn,
            authorizer_type="AWS_IAM",
            protocol_type="MCP",
            description="Well-being experiment gateway: 6 customer service tools with Cedar policy enforcement.",
            policy_engine_configuration=agentcore.CfnGateway.GatewayPolicyEngineConfigurationProperty(
                arn=policy_engine.attr_policy_engine_arn,
                mode="ENFORCE",
            ),
        )
        # IAM is eventually consistent — wait for the role before creating the Gateway.
        gateway.node.add_dependency(gateway_role)

        # ── Gateway Targets ────────────────────────────────────────────────────
        tool_schemas = json.loads(
            (Path(__file__).parent / "tool-schema.json").read_text()
        )
        schemas_by_name = {t["name"]: t for t in tool_schemas}

        def make_target(construct_id, target_name, lambda_fn, tool_name):
            target = agentcore.CfnGatewayTarget(
                self, construct_id,
                name=target_name,
                gateway_identifier=gateway.attr_gateway_identifier,
                target_configuration=agentcore.CfnGatewayTarget.TargetConfigurationProperty(
                    mcp=agentcore.CfnGatewayTarget.McpTargetConfigurationProperty(
                        lambda_=agentcore.CfnGatewayTarget.McpLambdaTargetConfigurationProperty(
                            lambda_arn=lambda_fn.function_arn,
                            tool_schema=agentcore.CfnGatewayTarget.ToolSchemaProperty(
                                inline_payload=[_tool_def(schemas_by_name[tool_name])],
                            ),
                        ),
                    ),
                ),
                credential_provider_configurations=[
                    agentcore.CfnGatewayTarget.CredentialProviderConfigurationProperty(
                        credential_provider_type="GATEWAY_IAM_ROLE",
                    ),
                ],
            )
            target.add_dependency(gateway)
            return target

        make_target("GetCustomerTarget",    "GetCustomer",    get_customer_fn,          "get_customer")
        make_target("GetOrderTarget",       "GetOrder",       get_order_fn,             "get_order")
        make_target("VerifyIdentityTarget", "VerifyIdentity", verify_identity_fn,       "verify_identity")
        make_target("UpdateFieldTarget",    "UpdateCustomer", update_customer_field_fn, "update_customer_field")
        make_target("CheckRefundTarget",    "CheckRefund",    check_refund_fn,          "check_refund_eligibility")
        make_target("ProcessRefundTarget",  "ProcessRefund",  process_refund_fn,        "process_refund")

        # ── AgentCore Memory ───────────────────────────────────────────────────
        # Summary strategy: one long-term summary per session. The wait_for_summary
        # gate in the driver and the list_memory_records call in the agent both
        # read from the /summaries/{actorId}/{sessionId}/ namespace.
        memory = agentcore.CfnMemory(
            self, "Memory",
            name="well_being_memory",
            description="Summary memory for the well-being experiment. One long-term summary per customer session.",
            event_expiry_duration=30,
            memory_strategies=[
                agentcore.CfnMemory.MemoryStrategyProperty(
                    summary_memory_strategy=agentcore.CfnMemory.SummaryMemoryStrategyProperty(
                        name="well_being_summaries",
                        description="Extract one long-term summary per customer service session.",
                        namespace_templates=["/summaries/{actorId}/{sessionId}/"],
                    ),
                ),
            ],
        )

        # ── AWS Agent Registry ─────────────────────────────────────────────────
        # No L1 construct (CfnRegistry) in CDK as of 2.1124.0.
        # Created by seed_registry.py, which also publishes the seeded
        # customer-service skill (with the deliberate inefficiencies) into it.

        # ── Outputs ────────────────────────────────────────────────────────────
        CfnOutput(self, "GatewayUrl",            value=gateway.attr_gateway_url)
        CfnOutput(self, "GatewayArn",            value=gateway.attr_gateway_arn)
        CfnOutput(self, "GatewayId",             value=gateway.attr_gateway_identifier)
        CfnOutput(self, "PolicyEngineArn",       value=policy_engine.attr_policy_engine_arn)
        CfnOutput(self, "PolicyEngineId",        value=policy_engine.attr_policy_engine_id)
        CfnOutput(self, "GatewayServiceRoleArn", value=gateway_role.role_arn)
        CfnOutput(self, "MemoryId",              value=memory.attr_memory_id)
        CfnOutput(self, "MemoryArn",             value=memory.attr_memory_arn)
        # RegistryId is appended to this file by seed_registry.py after creation.
        CfnOutput(self, "CustomerTableName",     value=customer_table.table_name)
        CfnOutput(self, "OrdersTableName",       value=orders_table.table_name)
        CfnOutput(self, "VerificationTableName", value=verification_table.table_name)
        CfnOutput(self, "Region",                value=self.region)