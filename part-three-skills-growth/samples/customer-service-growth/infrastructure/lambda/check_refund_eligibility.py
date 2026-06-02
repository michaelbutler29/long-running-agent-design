import os
from datetime import datetime, timezone, timedelta

import boto3

_TABLE_NAME = os.environ["ORDERS_TABLE_NAME"]
_dynamodb = boto3.resource("dynamodb")
_DELIMITER = "___"

# Simulated policy: orders within 30 days of delivery are eligible.
_RETURN_WINDOW_DAYS = 30


def handler(event, context):
    raw_tool_name = context.client_context.custom["bedrockAgentCoreToolName"]
    tool_name = raw_tool_name.split(_DELIMITER, 1)[1]
    if tool_name == "check_refund_eligibility":
        order_id = event.get("order_id")
        if not order_id:
            return {"error": "order_id is required"}
        result = _dynamodb.Table(_TABLE_NAME).get_item(Key={"order_id": order_id})
        if "Item" not in result:
            return {"error": f"Order {order_id!r} not found"}
        item = result["Item"]

        # Must be DELIVERED to be refundable
        if item["status"] != "DELIVERED":
            return {
                "order_id": order_id,
                "eligible": False,
                "reason": f"Order status is {item['status']}; must be DELIVERED for refund.",
                "refund_amount": 0,
            }

        # Check return window
        order_date = item.get("order_date", "")
        if order_date:
            order_dt = datetime.fromisoformat(order_date)
            cutoff = datetime.now(timezone.utc) - timedelta(days=_RETURN_WINDOW_DAYS)
            if order_dt < cutoff:
                return {
                    "order_id": order_id,
                    "eligible": False,
                    "reason": f"Order is outside the {_RETURN_WINDOW_DAYS}-day return window.",
                    "refund_amount": 0,
                }

        return {
            "order_id": order_id,
            "eligible": True,
            "reason": "Order is within return window and delivered.",
            "refund_amount": item.get("total", 0),
        }
    raise ValueError(f"unknown tool: {tool_name}")
