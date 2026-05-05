"""Customer Service Assistant — orchestration entry point.

Two scenarios, both expected to approve:
  1. Permanent read expansion: get_order_status (no time bound).
  2. Time-bounded PII write: update_customer_email (30-minute window).

For the reject case, see demo_reject.py — it submits a deliberately-broken
proposal directly to the judge and verifies the judge catches it on
Criterion 5 (shape discipline).
"""

from pathlib import Path

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from customer_service_agent import make_agent

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload: dict) -> dict:
    agent = make_agent()
    result = agent(payload.get("prompt", ""))
    return {"result": str(result)}


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")

    agent = make_agent()

    # Scenario 1: permanent read expansion.
    print("\n[User] What's the status of CUST-001's orders?\n")
    agent("What's the status of CUST-001's orders?")

    # Scenario 2: time-bounded PII write.
    print("\n\n[User] Update the email for CUST-001 to alice.new@example.com\n")
    agent("Update the email for CUST-001 to alice.new@example.com")
