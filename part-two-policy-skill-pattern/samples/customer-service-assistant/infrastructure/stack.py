"""
CDK stack for the customer-service-assistant policy-skill proof-of-concept.

Resources:
  - DynamoDB tables: Customer, Orders (seeded with static rows via AwsCustomResource)
  - Lambda functions: GetCustomerBasics, GetOrderStatus, UpdateCustomerEmail
  - Gateway service role (inline policies — avoids CFN race condition)
  - AgentCore Policy Engine (Cedar)
  - AgentCore Gateway (AWS_IAM authn, MCP protocol, ENFORCE mode)
  - AgentCore Gateway Targets: CustomerBasics, OrderStatus, CustomerEmail
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


class PolicySkillSampleStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── DynamoDB tables ────────────────────────────────────────────────────
        customer_table = dynamodb.Table(
            self,
            "CustomerTable",
            table_name="policy-skill-customers",
            partition_key=dynamodb.Attribute(
                name="id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        orders_table = dynamodb.Table(
            self,
            "OrdersTable",
            table_name="policy-skill-orders",
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

        # ── Static seed data ───────────────────────────────────────────────────
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
                            }}},
                            {"PutRequest": {"Item": {
                                "id": {"S": "CUST-002"},
                                "first_name": {"S": "Bob"},
                                "last_name": {"S": "Jones"},
                                "email": {"S": "bob@example.com"},
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
                                "status": {"S": "SHIPPED"},
                            }}},
                            {"PutRequest": {"Item": {
                                "order_id": {"S": "ORD-002"},
                                "customer_id": {"S": "CUST-001"},
                                "status": {"S": "DELIVERED"},
                            }}},
                            {"PutRequest": {"Item": {
                                "order_id": {"S": "ORD-003"},
                                "customer_id": {"S": "CUST-002"},
                                "status": {"S": "PROCESSING"},
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

        get_customer_basics_fn = _lambda.Function(
            self,
            "GetCustomerBasicsFunction",
            function_name="policy-skill-get-customer-basics",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="get_customer_basics.handler",
            code=_lambda.Code.from_asset(lambda_dir),
            timeout=Duration.seconds(10),
            environment={"CUSTOMER_TABLE_NAME": customer_table.table_name},
        )
        customer_table.grant_read_data(get_customer_basics_fn)

        get_order_status_fn = _lambda.Function(
            self,
            "GetOrderStatusFunction",
            function_name="policy-skill-get-order-status",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="get_order_status.handler",
            code=_lambda.Code.from_asset(lambda_dir),
            timeout=Duration.seconds(10),
            environment={"ORDERS_TABLE_NAME": orders_table.table_name},
        )
        orders_table.grant_read_data(get_order_status_fn)

        update_customer_email_fn = _lambda.Function(
            self,
            "UpdateCustomerEmailFunction",
            function_name="policy-skill-update-customer-email",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="update_customer_email.handler",
            code=_lambda.Code.from_asset(lambda_dir),
            timeout=Duration.seconds(10),
            environment={"CUSTOMER_TABLE_NAME": customer_table.table_name},
        )
        customer_table.grant_read_write_data(update_customer_email_fn)

        # ── Policy Engine ──────────────────────────────────────────────────────
        policy_engine = agentcore.CfnPolicyEngine(
            self,
            "PolicyEngine",
            name="policy_skill_engine",
            description="Cedar policies for the customer-service-assistant proof-of-concept. Mutated at runtime by the incorporator.",
        )

        # Inline policies (not separate AWS::IAM::Policy resources) so all permissions
        # are present the instant the Role enters CREATE_COMPLETE. Without this, the
        # Gateway create call races the Policy attachment and fails with
        # "Access denied while calling GetPolicyEngine".
        gateway_role = iam.Role(
            self,
            "GatewayServiceRole",
            role_name="policy-skill-gateway-service-role",
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
                            resources=[
                                get_customer_basics_fn.function_arn,
                                get_order_status_fn.function_arn,
                                update_customer_email_fn.function_arn,
                            ],
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
                            resources=["*"],
                        ),
                    ]
                ),
            },
        )

        gateway = agentcore.CfnGateway(
            self,
            "Gateway",
            name="policy-skill-gateway",
            role_arn=gateway_role.role_arn,
            authorizer_type="AWS_IAM",
            protocol_type="MCP",
            description="Policy-skill customer-service-assistant gateway.",
            policy_engine_configuration=agentcore.CfnGateway.GatewayPolicyEngineConfigurationProperty(
                arn=policy_engine.attr_policy_engine_arn,
                mode="ENFORCE",
            ),
        )

        # ── Gateway Targets ────────────────────────────────────────────────────
        tool_schemas = json.loads(
            (Path(__file__).parent / "tool-schema.json").read_text()
        )
        schemas_by_name = {t["name"]: t for t in tool_schemas}

        def make_target(construct_id, target_name, lambda_fn, tool_name):
            target = agentcore.CfnGatewayTarget(
                self,
                construct_id,
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
                # Required for Lambda targets despite CFN docs marking it optional.
                credential_provider_configurations=[
                    agentcore.CfnGatewayTarget.CredentialProviderConfigurationProperty(
                        credential_provider_type="GATEWAY_IAM_ROLE",
                    ),
                ],
            )
            target.add_dependency(gateway)
            return target

        make_target("CustomerBasicsTarget", "CustomerBasics", get_customer_basics_fn, "get_customer_basics")
        make_target("OrderStatusTarget",    "OrderStatus",    get_order_status_fn,    "get_order_status")
        make_target("CustomerEmailTarget",  "CustomerEmail",  update_customer_email_fn, "update_customer_email")

        # ── Outputs ────────────────────────────────────────────────────────────
        CfnOutput(self, "GatewayUrl",            value=gateway.attr_gateway_url)
        CfnOutput(self, "GatewayArn",            value=gateway.attr_gateway_arn)
        CfnOutput(self, "GatewayId",             value=gateway.attr_gateway_identifier)
        CfnOutput(self, "PolicyEngineArn",       value=policy_engine.attr_policy_engine_arn)
        CfnOutput(self, "PolicyEngineId",        value=policy_engine.attr_policy_engine_id)
        CfnOutput(self, "GatewayServiceRoleArn", value=gateway_role.role_arn)
        CfnOutput(self, "CustomerTableName",     value=customer_table.table_name)
        CfnOutput(self, "OrdersTableName",       value=orders_table.table_name)
        CfnOutput(self, "Region",                value=self.region)
