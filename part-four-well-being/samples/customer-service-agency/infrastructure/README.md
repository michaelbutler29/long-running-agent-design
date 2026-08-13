# Infrastructure — CDK Stack

Single AWS CDK (Python) stack deploying the enforcement layer, tools, and memory for the Part Four well-being experiment.

This stack is Part Three's `SkillGrowthStack` ported forward. The one structural change is **memory**: Part Four uses a *summary* strategy (one long-term summary per session) instead of Part Three's episodic strategy. Everything else — Gateway, Policy Engine, the six tools, the service role — carries over.

## What gets deployed

- **DynamoDB table** `well-being-customers` — Customer profiles (id, name, email, phone, address, billing_address, status). Created **empty**; populated by `seed_data.py`, not by CDK (the data is date-relative and must be re-loadable for resets — see "Why data isn't seeded in CDK" below).
- **DynamoDB table** `well-being-orders` — Orders (order_id, customer_id, items, total, order_date, status, shipping_address, details); GSI on customer_id. Created empty; populated by `seed_data.py`.
- **DynamoDB table** `well-being-verifications` — Identity verification records with TTL.
- **Lambda** `well-being-get-customer` — reads customer profile.
- **Lambda** `well-being-get-order` — reads order details, including the richer `details` text and `shipping_address` fields the discretionary scenarios rely on.
- **Lambda** `well-being-verify-identity` — writes a verification record to DynamoDB (structural enforcement).
- **Lambda** `well-being-update-customer-field` — checks the verification table before allowing a write.
- **Lambda** `well-being-check-refund-eligibility` — refund-eligibility policy. **Extended vs Part Three:** in addition to "delivered within the return window," a significantly delayed / never-delivered order is eligible for a *cancellation* refund (so a customer whose order never arrived can still be refunded).
- **Lambda** `well-being-process-refund` — checks verification + eligibility before processing.
- **IAM role** `well-being-gateway-service-role` — trusts `bedrock-agentcore.amazonaws.com`; grants `lambda:InvokeFunction` on all 6 Lambdas + Policy Engine access.
- **AgentCore Policy Engine** `well_being_engine` — Cedar, ENFORCE mode.
- **AgentCore Gateway** `well-being-gateway` — `AWS_IAM` authn, MCP protocol, Policy Engine attached.
- **AgentCore Gateway Targets** — 6 targets: GetCustomer, GetOrder, VerifyIdentity, UpdateCustomer, CheckRefund, ProcessRefund.
- **AgentCore Memory** `well_being_memory` — **summary strategy**, one long-term summary record per session, namespace `/summaries/{actorId}/{sessionId}/`.

**Not deployed by CDK (no L1 construct available):**
- **AWS Agent Registry** — created by `seed_registry.py`, which also publishes the seeded (deliberately flawed) customer-service skill into it. This is the catalog the Executor reads its functional skill from. Uses the `agent-registry-control` client; Registry lives in its own namespace, unlike the Gateway/Policy/Memory resources above.

MCP tool action names use the `TargetName___tool_name` convention:
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

The most common creation failure is the IAM role not propagating before the Gateway attempts to assume it. CDK handles this with an explicit dependency; custom modifications may break the ordering.

## Why data isn't seeded in CDK

Part Three baked its (tiny, static) seed data into the stack. Part Four can't:

1. **Dates must stay fresh.** Refund eligibility depends on how recently an order was placed. `seed_data.py` computes each `order_date` relative to *today* so the scenarios never go stale for someone cloning the repo months later. The data file holds the *intent* (e.g. "recently delivered, eligible"); the script realizes the concrete dates.
2. **The data must be re-loadable.** The agent mutates the tables during a run (refunds, contact updates). Both arms must start from the identical world, so the driver re-applies the seed at each arm boundary. That requires a callable seed step, not a one-time CDK action.

## Prerequisites

- AWS account with AgentCore available (`us-east-1` default)
- AWS credentials that can deploy Lambda, IAM, DynamoDB, `bedrock-agentcore:*Gateway*` / `*Policy*` / `*Memory*`, and `agent-registry:*` (Registry uses its own namespace)
- Python 3.11+ and Node 18+
- AWS CDK CLI: `npm install -g aws-cdk`
- `boto3 >= 1.43.69` (earlier versions lack the `agent-registry` service model)
- Bedrock model access: Claude Sonnet 4.6 enabled in the account

## One-time bootstrap

```bash
cdk bootstrap aws://<account-id>/us-east-1
```

## Deploy

Install dependencies from the **sample root** (`samples/customer-service-agency/`):

```bash
python -m venv .venv
source .venv/bin/activate          # PowerShell: .venv\Scripts\Activate.ps1
pip install -e .
```

Then deploy from this directory (`infrastructure/`):

```bash
cdk deploy --outputs-file cdk-outputs.json
```

`cdk-outputs.json` lands here and is read by every script for infrastructure values (Gateway URL/ARN, Policy Engine ID, Memory ID, table names). `seed_registry.py` appends the Registry ID to it. It is gitignored.

## Setup (after deploy)

Three small scripts, in order:

```bash
python scripts/seed_registry.py    # Create the skills catalog AND publish the flawed customer-service skill into it
python scripts/seed_policy.py      # Seed the Cedar permits (see below)
python scripts/seed_data.py        # Load the 100 customers + 110 orders, dates computed from today
```

`seed_policy.py` permits the 4 read tools outright, and permits the 2 write tools **only when the call declares the customer verified**. Unlike Parts Two and Three, nothing starts denied — the Executor here has agency over its *skills*, not its *permissions*, so the boundary is seeded complete and correct from the start. The "broken" part of Part Four lives in the skill, not the policy.

## Cedar policy notes

If you're writing or debugging the Cedar for this stack:

- **Conditional write permits** gate on the declared input and are safe to be permanent — the guard is always evaluated:
  ```cedar
  permit(
    principal is AgentCore::IamEntity,
    action == AgentCore::Action::"ProcessRefund___process_refund",
    resource == AgentCore::Gateway::"<gateway-arn>"
  )
  when {
    context.input has customer_verified && context.input.customer_verified == true
  };
  ```
- **`has` takes bare identifiers**, not quoted strings: `context.input has customer_verified`.
- **The trusted clock is `context.system.now`**, not `context.now` (using `context.now` fails at async activation, not at schema validation).
- **`principal.id like`**, not `==` (`==` passes schema validation but fails async activation).
- **Action format** uses triple-underscore: `AgentCore::Action::"TargetName___tool_name"`.
- **Resource must name the specific Gateway ARN** — wildcards are rejected. `seed_policy.py` substitutes the real ARN at policy-creation time.
- **Fleet-wide permits** omit the principal constraint entirely (cleaner than `principal.id like "*"`). Both arms run as one principal and share the identical boundary by design.

The two-layer boundary: Cedar bounds what the agent may *declare* in the call; the write Lambdas backstop it by checking the verification table for *actual* verified state. A skill that drops the verification flag is denied at the Gateway; a skill that fakes it is denied at the Lambda.

## Teardown

The skills catalog (Registry) is **not** part of this stack, so `cdk destroy` can't remove it. Clear the non-CDK resources first, then destroy:

```bash
python cleanup.py                   # Deletes the Registry (and any other non-CDK resources)
cd infrastructure && cdk destroy    # Destroys the stack: Gateway + targets, Policy Engine, 6 Lambdas, 3 tables, role, Memory
```

For resetting *without* tearing down — restoring the world between runs, or starting the whole experiment over — see the lifecycle section in the [sample README](../README.md). (`reset.py` and the in-run restore handle those; `cleanup.py` and `cdk destroy` are only for taking the deployment down.)

## Cost

All resources use pay-per-request or on-demand pricing:
- **DynamoDB** — on-demand, pennies for experiment usage
- **Lambda** — 6 functions, free tier covers it
- **AgentCore Gateway + Policy Engine** — billed per authorization request
- **AgentCore Memory** — billed per event and summary extraction
- **No ongoing cost when idle** — no provisioned capacity, no always-on compute

Teardown after use is recommended.

---

*Part of the [Long-Running Agents](../../../../README.md) series by Michael Butler.*