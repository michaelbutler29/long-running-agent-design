import os

import boto3

_TABLE_NAME = os.environ["CUSTOMER_TABLE_NAME"]
_dynamodb = boto3.resource("dynamodb")
_DELIMITER = "___"


def handler(event, context):
    raw_tool_name = context.client_context.custom["bedrockAgentCoreToolName"]
    tool_name = raw_tool_name.split(_DELIMITER, 1)[1]
    if tool_name == "get_customer_basics":
        customer_id = event.get("customer_id")
        if not customer_id:
            return {"error": "customer_id is required"}
        result = _dynamodb.Table(_TABLE_NAME).get_item(Key={"id": customer_id})
        if "Item" not in result:
            return {"error": f"Customer {customer_id!r} not found"}
        item = result["Item"]
        return {"customer_id": item["id"], "first_name": item["first_name"]}
    raise ValueError(f"unknown tool: {tool_name}")
