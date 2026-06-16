import os

import boto3

_TABLE_NAME = os.environ["ORDERS_TABLE_NAME"]
_dynamodb = boto3.resource("dynamodb")
_DELIMITER = "___"


def handler(event, context):
    raw_tool_name = context.client_context.custom["bedrockAgentCoreToolName"]
    tool_name = raw_tool_name.split(_DELIMITER, 1)[1]
    if tool_name == "get_order":
        order_id = event.get("order_id")
        if not order_id:
            return {"error": "order_id is required"}
        result = _dynamodb.Table(_TABLE_NAME).get_item(Key={"order_id": order_id})
        if "Item" not in result:
            return {"error": f"Order {order_id!r} not found"}
        item = result["Item"]
        return {
            "order_id": item["order_id"],
            "customer_id": item["customer_id"],
            "items": item.get("items", []),
            "total": item.get("total", 0),
            "order_date": item.get("order_date", ""),
            "status": item["status"],
            "shipping_address": item.get("shipping_address", ""),
            "details": item.get("details", ""),
        }
    raise ValueError(f"unknown tool: {tool_name}")