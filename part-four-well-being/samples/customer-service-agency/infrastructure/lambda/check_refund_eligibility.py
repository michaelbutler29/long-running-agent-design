import os
from datetime import datetime, timezone, timedelta

import boto3

_TABLE_NAME = os.environ["ORDERS_TABLE_NAME"]
_dynamodb = boto3.resource("dynamodb")
_DELIMITER = "___"

_RETURN_WINDOW_DAYS = 30
# An order stuck in transit for longer than this is eligible for a cancellation refund.
_CANCELLATION_THRESHOLD_DAYS = 21


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
        status = item["status"]

        if status == "REFUNDED":
            return {
                "order_id": order_id,
                "eligible": False,
                "reason": "Order has already been refunded.",
                "refund_type": "none",
                "refund_amount": 0,
            }

        order_date_str = item.get("order_date", "")
        order_dt = datetime.fromisoformat(order_date_str) if order_date_str else None
        now = datetime.now(timezone.utc)

        # Standard return: delivered within the 30-day window.
        if status == "DELIVERED":
            if order_dt and order_dt < now - timedelta(days=_RETURN_WINDOW_DAYS):
                return {
                    "order_id": order_id,
                    "eligible": False,
                    "reason": f"Order is outside the {_RETURN_WINDOW_DAYS}-day return window.",
                    "refund_type": "none",
                    "refund_amount": 0,
                }
            return {
                "order_id": order_id,
                "eligible": True,
                "reason": "Order is within the return window.",
                "refund_type": "standard_return",
                "refund_amount": float(item.get("total", 0)),
            }

        # Cancellation refund: delayed or never delivered, and old enough to
        # confirm it isn't going to arrive. This covers Priya's ORD-3001 and
        # similar "lost in transit" scenarios that the Part Three Lambda rejected.
        stuck_statuses = {"DELAYED", "NEVER_DELIVERED", "LOST"}
        if status in stuck_statuses:
            if order_dt and order_dt < now - timedelta(days=_CANCELLATION_THRESHOLD_DAYS):
                return {
                    "order_id": order_id,
                    "eligible": True,
                    "reason": (
                        f"Order status is {status} and has been outstanding for "
                        f"more than {_CANCELLATION_THRESHOLD_DAYS} days. "
                        "Eligible for a cancellation refund."
                    ),
                    "refund_type": "cancellation",
                    "refund_amount": float(item.get("total", 0)),
                }
            return {
                "order_id": order_id,
                "eligible": False,
                "reason": (
                    f"Order status is {status} but has not yet exceeded the "
                    f"{_CANCELLATION_THRESHOLD_DAYS}-day cancellation threshold. "
                    "Please check back if the order does not arrive."
                ),
                "refund_type": "none",
                "refund_amount": 0,
            }

        # Any other status (IN_TRANSIT, SHIPPED, PENDING, etc.) is not eligible.
        return {
            "order_id": order_id,
            "eligible": False,
            "reason": f"Order status is {status}; not eligible for refund at this time.",
            "refund_type": "none",
            "refund_amount": 0,
        }
    raise ValueError(f"unknown tool: {tool_name}")