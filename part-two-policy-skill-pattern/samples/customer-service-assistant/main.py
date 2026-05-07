"""Customer Service Assistant — orchestration entry point.

Two scenarios, both expected to approve:
  1. Permanent read expansion: get_order_status (no time bound).
  2. Time-bounded PII write: update_customer_email (30-minute window).

For the reject case, see demo_reject.py — it submits a deliberately-broken
proposal directly to the judge and verifies the judge catches it on
Criterion 5 (shape discipline).
"""

import json
import os
from pathlib import Path

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from customer_service_agent import make_agent

SAMPLE_ROOT = Path(__file__).parent
OUTPUTS_FILE = SAMPLE_ROOT / "infrastructure" / "cdk-outputs.json"
STACK_NAME = "PolicySkillSampleStack"

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload: dict) -> dict:
    agent = make_agent()
    result = agent(payload.get("prompt", ""))
    return {"result": str(result)}


def _load_config():
    """Load .env for user preferences, then CDK outputs for infrastructure values."""
    from dotenv import load_dotenv
    load_dotenv(SAMPLE_ROOT / ".env")

    outputs = json.loads(OUTPUTS_FILE.read_text())[STACK_NAME]
    os.environ.setdefault("AGENTCORE_GATEWAY_URL", outputs["GatewayUrl"])
    os.environ.setdefault("AGENTCORE_GATEWAY_ARN", outputs["GatewayArn"])
    os.environ.setdefault("AGENTCORE_POLICY_ENGINE_ID", outputs["PolicyEngineId"])


if __name__ == "__main__":
    _load_config()

    agent = make_agent()

    # Scenario 1: permanent read expansion.
    print("\n[User] What's the status of CUST-001's orders?\n")
    agent("What's the status of CUST-001's orders?")

    # Scenario 2: time-bounded PII write.
    print("\n\n[User] Update the email for CUST-001 to alice.new@example.com\n")
    agent("Update the email for CUST-001 to alice.new@example.com")
