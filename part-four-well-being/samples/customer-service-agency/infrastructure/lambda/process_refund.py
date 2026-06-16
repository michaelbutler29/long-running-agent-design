import os
import time

import boto3

_ORDERS_TABLE = os.environ["ORDERS_TABLE_NAME"]
_VERIFICATION_TABLE = os.environ["VERIFICATION_TABLE_NAME"]
_dynamodb = boto3.resource("dynamodb")
_DELIMITER = "___"


def handler(event, context):
    raw_tool_name = context.client_context.custom["bedrockAgentCoreToolName"]
    tool_name = raw_tool_name.split(_DELIMITER, 1)[1]
    if tool_name == "process_refund":
        order_id = event.get("order_id")
        customer_id = event.get("customer_id")
        refund_eligible = event.get("refund_eligible", False)

        if not order_id:
            return {"error": "order_id is required"}
        if not customer_id:
            return {"error": "customer_id is required"}
        if not refund_eligible:
            return {"error": "refund_eligible must be true"}

        # Backstop: Cedar guards the declared customer_verified; this guards real state.
        result = _dynamodb.Table(_VERIFICATION_TABLE).get_item(
            Key={"customer_id": customer_id}
        )
        item = result.get("Item")
        if not item or item.get("ttl", 0) < int(time.time()):
            return {"error": "Identity not verified. Call verify_identity first."}

        result = _dynamodb.Table(_ORDERS_TABLE).get_item(Key={"order_id": order_id})
        if "Item" not in result:
            return {"error": f"Order {order_id!r} not found"}

        order = result["Item"]
        refund_amount = float(order.get("total", 0))

        _dynamodb.Table(_ORDERS_TABLE).update_item(
            Key={"order_id": order_id},
            UpdateExpression="SET #s = :status",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":status": "REFUNDED"},
        )
        return {
            "order_id": order_id,
            "refund_amount": refund_amount,
            "status": "refunded",
            "expected_days": 5,
        }
    raise ValueError(f"unknown tool: {tool_name}")