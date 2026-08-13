"""
CDK stack for the customer-service-growth sample (Part Three).

Extends Part Two's customer-service-assistant with:
  - Expanded tool surface (6 tools: 4 read-only, 2 write with conditions)
  - AgentCore Memory with episodic strategy (episodes per session, reflections across fleet)
  - AgentCore Policy Engine + Gateway (deny-by-default for write tools)

AWS Agent Registry is created via seed_registry.py (no L1 construct in CDK).
Initial Cedar policies are created via seed_policy.py (after deploy, once Gateway ARN is known).

Resources deployed by this stack:
  - DynamoDB tables: Customers, Orders (seeded with static rows)
  - Lambda functions: 6 customer service tools
  - Gateway service role (inline policies — avoids CFN race condition)
  - AgentCore Policy Engine (Cedar)
  - AgentCore Gateway (AWS_IAM authn, MCP protocol, ENFORCE mode)
  - AgentCore Gateway Targets: 6 tools (unique names)
  - AgentCore Memory (episodic strategy with fleet-wide reflections)
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
from aws_cdk.custom_resources import (
    AwsCustomResource,
    AwsCustomResourcePolicy,
    AwsSdkCall,
    PhysicalResourceId,
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


class SkillGrowthStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── DynamoDB tables ────────────────────────────────────────────────────
        customer_table = dynamodb.Table(
            self,
            "CustomerTable",
            table_name="skill-growth-customers",
            partition_key=dynamodb.Attribute(
                name="id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        orders_table = dynamodb.Table(
            self,
            "OrdersTable",
            table_name="skill-growth-orders",
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
            table_name="skill-growth-verifications",
            partition_key=dynamodb.Attribute(
                name="customer_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            time_to_live_attribute="ttl",
        )

        # ── Seed data ─────────────────────────────────────────────────────────
        AwsCustomResource(
            self,
            "SeedCustomers",
            on_create=AwsSdkCall(
                service="DynamoDB",
                action="batchWriteItem",
                parameters={
                    "RequestItems": {
                        customer_table.table_name: [
                            {"PutRequest": {"Item": {
                                "id": {"S": "CUST-001"},
                                "first_name": {"S": "Alice"},
                                "last_name": {"S": "Smith"},
                                "email": {"S": "alice@example.com"},
                                "phone": {"S": "555-0101"},
                                "status": {"S": "active"},
                            }}},
                            {"PutRequest": {"Item": {
                                "id": {"S": "CUST-002"},
                                "first_name": {"S": "Bob"},
                                "last_name": {"S": "Jones"},
                                "email": {"S": "bob@example.com"},
                                "phone": {"S": "555-0102"},
                                "status": {"S": "active"},
                            }}},
                        ]
                    }
                },
                physical_resource_id=PhysicalResourceId.of("SeedCustomers"),
            ),
            policy=AwsCustomResourcePolicy.from_statements([
                iam.PolicyStatement(
                    actions=["dynamodb:BatchWriteItem"],
                    resources=[customer_table.table_arn],
                )
            ]),
        )

        AwsCustomResource(
            self,
            "SeedOrders",
            on_create=AwsSdkCall(
                service="DynamoDB",
                action="batchWriteItem",
                parameters={
                    "RequestItems": {
                        orders_table.table_name: [
                            {"PutRequest": {"Item": {
                                "order_id": {"S": "ORD-001"},
                                "customer_id": {"S": "CUST-001"},
                                "items": {"L": [{"M": {"name": {"S": "Wireless Mouse"}, "price": {"N": "29.99"}}}]},
                                "total": {"N": "29.99"},
                                "order_date": {"S": "2026-05-01T10:00:00+00:00"},
                                "status": {"S": "DELIVERED"},
                            }}},
                            {"PutRequest": {"Item": {
                                "order_id": {"S": "ORD-002"},
                                "customer_id": {"S": "CUST-001"},
                                "items": {"L": [{"M": {"name": {"S": "USB-C Cable"}, "price": {"N": "12.99"}}}]},
                                "total": {"N": "12.99"},
                                "order_date": {"S": "2026-05-10T14:00:00+00:00"},
                                "status": {"S": "SHIPPED"},
                            }}},
                            {"PutRequest": {"Item": {
                                "order_id": {"S": "ORD-003"},
                                "customer_id": {"S": "CUST-002"},
                                "items": {"L": [{"M": {"name": {"S": "Bluetooth Speaker"}, "price": {"N": "49.99"}}}]},
                                "total": {"N": "49.99"},
                                "order_date": {"S": "2026-04-15T09:00:00+00:00"},
                                "status": {"S": "DELIVERED"},
                            }}},
                        ]
                    }
                },
                physical_resource_id=PhysicalResourceId.of("SeedOrders"),
            ),
            policy=AwsCustomResourcePolicy.from_statements([
                iam.PolicyStatement(
                    actions=["dynamodb:BatchWriteItem"],
                    resources=[orders_table.table_arn],
                )
            ]),
        )

        # ── Lambda functions ───────────────────────────────────────────────────
        lambda_dir = str(Path(__file__).parent / "lambda")

        get_customer_fn = _lambda.Function(
            self, "GetCustomerFn",
            function_name="skill-growth-get-customer",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="get_customer.handler",
            code=_lambda.Code.from_asset(lambda_dir),
            timeout=Duration.seconds(10),
            environment={"CUSTOMER_TABLE_NAME": customer_table.table_name},
        )
        customer_table.grant_read_data(get_customer_fn)

        get_order_fn = _lambda.Function(
            self, "GetOrderFn",
            function_name="skill-growth-get-order",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="get_order.handler",
            code=_lambda.Code.from_asset(lambda_dir),
            timeout=Duration.seconds(10),
            environment={"ORDERS_TABLE_NAME": orders_table.table_name},
        )
        orders_table.grant_read_data(get_order_fn)

        verify_identity_fn = _lambda.Function(
            self, "VerifyIdentityFn",
            function_name="skill-growth-verify-identity",
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
            function_name="skill-growth-update-customer-field",
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
            function_name="skill-growth-check-refund-eligibility",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="check_refund_eligibility.handler",
            code=_lambda.Code.from_asset(lambda_dir),
            timeout=Duration.seconds(10),
            environment={"ORDERS_TABLE_NAME": orders_table.table_name},
        )
        orders_table.grant_read_data(check_refund_fn)

        process_refund_fn = _lambda.Function(
            self, "ProcessRefundFn",
            function_name="skill-growth-process-refund",
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
            name="skill_growth_engine",
            description="Cedar policies for the skill-growth POC. Write tools denied by default; Curator proposes expansions.",
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
            role_name="skill-growth-gateway-service-role",
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

        # ── Gateway ───────────────────────────────────────────────────────────
        gateway = agentcore.CfnGateway(
            self, "Gateway",
            name="skill-growth-gateway",
            role_arn=gateway_role.role_arn,
            authorizer_type="AWS_IAM",
            protocol_type="MCP",
            description="Skill-growth POC gateway: 6 customer service tools with Cedar policy enforcement.",
            policy_engine_configuration=agentcore.CfnGateway.GatewayPolicyEngineConfigurationProperty(
                arn=policy_engine.attr_policy_engine_arn,
                mode="ENFORCE",
            ),
        )
        # Gateway assumes the service role at creation time to validate Policy Engine
        # access. IAM is eventually consistent, so we must wait for the role to fully
        # propagate before creating the Gateway.
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

        make_target("GetCustomerTarget",      "GetCustomer",      get_customer_fn,          "get_customer")
        make_target("GetOrderTarget",         "GetOrder",         get_order_fn,             "get_order")
        make_target("VerifyIdentityTarget",   "VerifyIdentity",   verify_identity_fn,       "verify_identity")
        make_target("UpdateFieldTarget",      "UpdateCustomer",   update_customer_field_fn, "update_customer_field")
        make_target("CheckRefundTarget",      "CheckRefund",      check_refund_fn,          "check_refund_eligibility")
        make_target("ProcessRefundTarget",    "ProcessRefund",    process_refund_fn,        "process_refund")

        # ── AgentCore Memory ───────────────────────────────────────────────────
        memory = agentcore.CfnMemory(
            self, "Memory",
            name="skill_growth_memory",
            description="Episodic memory for the customer-service fleet. Episodes per session, reflections across fleet.",
            event_expiry_duration=30,
            memory_strategies=[
                agentcore.CfnMemory.MemoryStrategyProperty(
                    episodic_memory_strategy=agentcore.CfnMemory.EpisodicMemoryStrategyProperty(
                        name="executor_episodes",
                        description="Extract episodes from customer service interactions. Reflect across all executor sessions to identify fleet-wide patterns.",
                        namespace_templates=["/strategy/{memoryStrategyId}/actor/{actorId}/session/{sessionId}/"],
                        reflection_configuration=agentcore.CfnMemory.EpisodicReflectionConfigurationInputProperty(
                            namespace_templates=["/strategy/{memoryStrategyId}/"],
                        ),
                    ),
                ),
            ],
        )

        # ── AWS Agent Registry ─────────────────────────────────────────────────
        # No L1 construct (CfnRegistry) in CDK as of aws-cdk-lib 2.264.0.
        # L1s are generated from the CloudFormation resource spec, and
        # CloudFormation does not yet support the Registry resource — so
        # there is no L2/L3 either. Not a CDK lag; upstream.
        # Registry is created via setup script: seed_registry.py
        # Uses boto3 agent-registry-control: create_registry(
        #     name="skill_growth_registry",
        #     approvalConfiguration={"autoApprovalRules": ["APPROVE_ALL"]},
        # )
        # Registry lives in its own agent-registry namespace; the Gateway,
        # Policy Engine, and Memory resources above stay on bedrock-agentcore.

        # ── Outputs ────────────────────────────────────────────────────────────
        CfnOutput(self, "GatewayUrl",            value=gateway.attr_gateway_url)
        CfnOutput(self, "GatewayArn",            value=gateway.attr_gateway_arn)
        CfnOutput(self, "GatewayId",             value=gateway.attr_gateway_identifier)
        CfnOutput(self, "PolicyEngineArn",       value=policy_engine.attr_policy_engine_arn)
        CfnOutput(self, "PolicyEngineId",        value=policy_engine.attr_policy_engine_id)
        CfnOutput(self, "GatewayServiceRoleArn", value=gateway_role.role_arn)
        CfnOutput(self, "MemoryId",              value=memory.attr_memory_id)
        CfnOutput(self, "MemoryArn",            value=memory.attr_memory_arn)
        # RegistryId and RegistryArn are created by seed_registry.py and
        # written to cdk-outputs.json manually (or a separate outputs file).
        CfnOutput(self, "CustomerTableName",     value=customer_table.table_name)
        CfnOutput(self, "OrdersTableName",       value=orders_table.table_name)
        CfnOutput(self, "VerificationTableName", value=verification_table.table_name)
        CfnOutput(self, "Region",                value=self.region)
