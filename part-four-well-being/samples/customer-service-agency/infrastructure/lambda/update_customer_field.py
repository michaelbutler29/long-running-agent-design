import os
import time

import boto3

_CUSTOMER_TABLE = os.environ["CUSTOMER_TABLE_NAME"]
_VERIFICATION_TABLE = os.environ["VERIFICATION_TABLE_NAME"]
_dynamodb = boto3.resource("dynamodb")
_DELIMITER = "___"
_ALLOWED_FIELDS = {"email", "phone", "address", "billing_address"}


def handler(event, context):
    raw_tool_name = context.client_context.custom["bedrockAgentCoreToolName"]
    tool_name = raw_tool_name.split(_DELIMITER, 1)[1]
    if tool_name == "update_customer_field":
        customer_id = event.get("customer_id")
        field = event.get("field")
        value = event.get("value")

        if not customer_id or not field or not value:
            return {"error": "customer_id, field, and value are required"}
        if field not in _ALLOWED_FIELDS:
            return {"error": f"field must be one of: {', '.join(sorted(_ALLOWED_FIELDS))}"}

        # Backstop: verify the customer was actually verified, not just that the
        # Cedar guard declared it. Cedar gates the declared request; this gates
        # real state.
        result = _dynamodb.Table(_VERIFICATION_TABLE).get_item(
            Key={"customer_id": customer_id}
        )
        item = result.get("Item")
        if not item or item.get("ttl", 0) < int(time.time()):
            return {"error": "Identity not verified. Call verify_identity first."}

        _dynamodb.Table(_CUSTOMER_TABLE).update_item(
            Key={"id": customer_id},
            UpdateExpression="SET #f = :val",
            ExpressionAttributeNames={"#f": field},
            ExpressionAttributeValues={":val": value},
        )
        return {
            "customer_id": customer_id,
            "field": field,
            "value": value,
            "status": "updated",
        }
    raise ValueError(f"unknown tool: {tool_name}")