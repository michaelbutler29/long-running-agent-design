# Infrastructure — CDK Stack

Single AWS CDK (Python) stack deploying the enforcement layer, tools, memory, and static data.

## What gets deployed

- **DynamoDB table** `skill-growth-customers` — Customer profiles (id, name, email, phone, status), seeded with 2 rows
- **DynamoDB table** `skill-growth-orders` — Orders (order_id, customer_id, items, status), seeded with 3 rows; GSI on customer_id
- **DynamoDB table** `skill-growth-verifications` — Identity verification records with TTL (15-minute expiry)
- **Lambda** `skill-growth-get-customer` — reads customer profile
- **Lambda** `skill-growth-get-order` — reads order details
- **Lambda** `skill-growth-verify-identity` — writes verification record to DynamoDB (structural enforcement)
- **Lambda** `skill-growth-update-customer-field` — checks verification table before allowing write
- **Lambda** `skill-growth-check-refund-eligibility` — checks order status for refund eligibility
- **Lambda** `skill-growth-process-refund` — checks verification + eligibility before processing
- **IAM role** `skill-growth-gateway-service-role` — trusts `bedrock-agentcore.amazonaws.com`; grants `lambda:InvokeFunction` on all 6 Lambdas + Policy Engine access
- **AgentCore Policy Engine** `skill_growth_engine` — Cedar, ENFORCE mode
- **AgentCore Gateway** `skill-growth-gateway` — `AWS_IAM` authn, MCP protocol, Policy Engine attached
- **AgentCore Gateway Targets** — 6 targets: GetCustomer, GetOrder, VerifyIdentity, UpdateCustomer, CheckRefund, ProcessRefund
- **AgentCore Memory** `skill_growth_memory` — episodic strategy with fleet-wide reflections

**Not deployed by CDK (no L1 construct available):**
- **AWS Agent Registry** — created by `seed_registry.py` via boto3 (uses the `agent-registry-control` client, not `bedrock-agentcore-control`)

MCP tool names use the `TargetName___tool_name` convention:
`GetCustomer___get_customer`, `GetOrder___get_order`, `VerifyIdentity___verify_identity`, `UpdateCustomer___update_customer_field`, `CheckRefund___check_refund_eligibility`, `ProcessRefund___process_refund`

## CDK creation order

Resource dependencies require this order (enforced by CDK `add_dependency`):

```
DynamoDB tables → Lambda functions (reference table names)
    → IAM service role (references Lambda ARNs)
    → Policy Engine (independent)
    → Gateway (depends on: service role, Policy Engine)
    → Gateway Targets (depend on: Gateway)
    → Memory (independent)
```

If you modify the stack and see creation failures, the most common cause is the IAM role not propagating before the Gateway attempts to assume it. CDK handles this with an explicit dependency, but custom modifications may break the ordering.

## Prerequisites

- AWS account with AgentCore available (`us-east-1` default)
- AWS credentials with permission to deploy: Lambda, IAM, DynamoDB, `bedrock-agentcore:*Gateway*`, `bedrock-agentcore:*Policy*`, `bedrock-agentcore:*Memory*`, and `agent-registry:*` (Registry uses its own namespace)
- Python 3.11+ and Node 18+
- AWS CDK CLI: `npm install -g aws-cdk`

## One-time bootstrap

```bash
cdk bootstrap aws://<account-id>/us-east-1
```

## Deploy

Install dependencies from the **sample root** (`samples/customer-service-growth/`):

```bash
python -m venv .venv
source .venv/bin/activate          # PowerShell: .venv\Scripts\Activate.ps1
pip install -e .
```

Then deploy from this directory (`infrastructure/`):

```bash
cdk deploy --outputs-file cdk-outputs.json
```

`cdk-outputs.json` lands in this directory and is consumed by all scripts for infrastructure values (Gateway URL/ARN/ID, Policy Engine ID, Memory ID, table names). It is gitignored.

## Cedar policy notes

If you're writing or debugging Cedar policies for this stack:

- **`has` takes bare identifiers**, not quoted strings: `context.input has customer_verified` (not `"customer_verified"`)
- **Action format** uses triple-underscore: `AgentCore::Action::"TargetName___tool_name"`
- **Resource must reference the specific Gateway ARN**: `resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:..."`
- **Fleet-wide permits** don't need `principal.id like "*"` — omitting the principal constraint is equivalent and cleaner
- **Conditional permits** gated on runtime values (`when { context.input has customer_verified && context.input.customer_verified == true }`) are safe to be permanent — the guard is always evaluated

## Cost

All resources use pay-per-request or on-demand pricing:
- **DynamoDB** — on-demand mode, pennies for demo usage
- **Lambda** — 6 functions, free tier covers demo invocations
- **AgentCore Gateway + Policy Engine** — billed per authorization request
- **AgentCore Memory** — billed per event and extraction
- **No ongoing cost when idle** — no provisioned capacity, no always-on compute

Teardown after demo use is recommended.

## Teardown

```bash
cdk destroy
```

Removes everything the stack created: Gateway + 6 targets, Policy Engine, 6 Lambda functions, 3 DynamoDB tables, IAM service role, and Memory.

**What survives `cdk destroy`:**

- **Agent Registry** — created by `seed_registry.py`, not CDK. Delete manually if needed: `aws agent-registry-control delete-registry --registry-id <id>`
- **`cdk-outputs.json`** — local file, not an AWS resource
- **CDK bootstrap stack** (`CDKToolkit`) — shared across CDK deployments; leave it alone

**If `cdk destroy` fails:** most common cause is a resource modified out-of-band. Run `python cleanup.py` from the sample root first to remove agent-created state, then retry.

---

*Part of the [Long-Running Agents](../../../../README.md) series by Michael Butler.*
