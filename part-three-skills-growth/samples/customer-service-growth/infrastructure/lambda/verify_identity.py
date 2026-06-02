import os
import time

import boto3

_CUSTOMER_TABLE = os.environ["CUSTOMER_TABLE_NAME"]
_VERIFICATION_TABLE = os.environ["VERIFICATION_TABLE_NAME"]
_dynamodb = boto3.resource("dynamodb")
_DELIMITER = "___"

# Simulated verification: CUST-001 always passes, CUST-002 fails on first attempt.
# In a real system this would call an external verification service.
_VERIFICATION_RESULTS = {
    "CUST-001": True,
    "CUST-002": False,
}


def handler(event, context):
    raw_tool_name = context.client_context.custom["bedrockAgentCoreToolName"]
    tool_name = raw_tool_name.split(_DELIMITER, 1)[1]
    if tool_name == "verify_identity":
        customer_id = event.get("customer_id")
        if not customer_id:
            return {"error": "customer_id is required"}
        # Check customer exists
        result = _dynamodb.Table(_CUSTOMER_TABLE).get_item(Key={"id": customer_id})
        if "Item" not in result:
            return {"error": f"Customer {customer_id!r} not found"}
        verified = _VERIFICATION_RESULTS.get(customer_id, True)

        if verified:
            # Write verification record (TTL: 5 minutes)
            _dynamodb.Table(_VERIFICATION_TABLE).put_item(Item={
                "customer_id": customer_id,
                "verified_at": int(time.time()),
                "ttl": int(time.time()) + 300,
            })

        return {
            "customer_id": customer_id,
            "verified": verified,
            "method": "security_questions",
        }
    raise ValueError(f"unknown tool: {tool_name}")
