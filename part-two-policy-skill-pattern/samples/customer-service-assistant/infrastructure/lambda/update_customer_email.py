import os

import boto3

_TABLE_NAME = os.environ["CUSTOMER_TABLE_NAME"]
_dynamodb = boto3.resource("dynamodb")
_DELIMITER = "___"


def handler(event, context):
    raw_tool_name = context.client_context.custom["bedrockAgentCoreToolName"]
    tool_name = raw_tool_name.split(_DELIMITER, 1)[1]
    if tool_name == "update_customer_email":
        customer_id = event["customer_id"]
        new_email = event["email"]
        _dynamodb.Table(_TABLE_NAME).update_item(
            Key={"id": customer_id},
            UpdateExpression="SET email = :email",
            ExpressionAttributeValues={":email": new_email},
        )
        return {"customer_id": customer_id, "email": new_email, "status": "updated"}
    raise ValueError(f"unknown tool: {tool_name}")
