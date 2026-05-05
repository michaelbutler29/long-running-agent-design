import os

import boto3
from boto3.dynamodb.conditions import Key

_TABLE_NAME = os.environ["ORDERS_TABLE_NAME"]
_dynamodb = boto3.resource("dynamodb")
_DELIMITER = "___"


def handler(event, context):
    raw_tool_name = context.client_context.custom["bedrockAgentCoreToolName"]
    tool_name = raw_tool_name.split(_DELIMITER, 1)[1]
    if tool_name == "get_order_status":
        customer_id = event["customer_id"]
        result = _dynamodb.Table(_TABLE_NAME).query(
            IndexName="customer-id-index",
            KeyConditionExpression=Key("customer_id").eq(customer_id),
        )
        items = result.get("Items", [])
        return {"orders": [{"order_id": i["order_id"], "status": i["status"]} for i in items]}
    raise ValueError(f"unknown tool: {tool_name}")
