# Sample: Customer Service Assistant

A working proof-of-concept of the [policy skill pattern](../../template/), run end-to-end against AWS AgentCore Gateway and Cedar Policy Engine.

A Strands agent encounters Cedar-enforced boundaries, activates the policy-generator-skill, proposes expansions, gets judged by an independent evaluator agent, and — on approval — refreshes its tools and proceeds. The entire loop runs within a single agent turn.

---

## Getting started

### Prerequisites

- **AWS account** with AgentCore available in `us-east-1`
- **AWS CLI** configured with credentials that can deploy Lambda, IAM, DynamoDB, and AgentCore resources
- **Python 3.10+**
- **Node 18+** (CDK CLI dependency)
- **AWS CDK CLI**: `npm install -g aws-cdk`
- **Bedrock model access**: Claude Sonnet enabled in the account (used by both the doer and judge agents)

### 1. Install dependencies

From this directory (`samples/customer-service-assistant/`):

```bash
python -m venv .venv
source .venv/bin/activate          # PowerShell: .venv\Scripts\Activate.ps1
pip install -e .
```

### 2. Deploy infrastructure

```bash
cd infrastructure
cdk bootstrap aws://<account-id>/us-east-1    # one-time per account/region
cdk deploy --outputs-file cdk-outputs.json
cd ..
```

This creates: 2 DynamoDB tables (seeded with sample data), 3 Lambda functions, an AgentCore Gateway with 3 targets, a Policy Engine in ENFORCE mode, and supporting IAM roles. See [`infrastructure/README.md`](infrastructure/README.md) for the full resource list.

### 3. Configure environment

Copy the example and fill in from CDK outputs:

```bash
cp .env.example .env
```

The values come from `infrastructure/cdk-outputs.json`:

| Variable | Source |
|----------|--------|
| `AGENTCORE_GATEWAY_URL` | `GatewayUrl` |
| `AGENTCORE_GATEWAY_ARN` | `GatewayArn` |
| `AGENTCORE_POLICY_ENGINE_ID` | `PolicyEngineId` |
| `AWS_REGION` | `Region` (defaults to `us-east-1`) |
| `BEDROCK_MODEL_ID` | Optional; defaults to `global.anthropic.claude-sonnet-4-6` |

### 4. Seed the starting policy

```bash
python seed_policy.py
```

Creates one Cedar permit: the deployer's IAM identity can call `get_customer_basics` on the gateway. The other two tools (`get_order_status`, `update_customer_email`) start denied — the agent must propose expansions for them.

### 5. Run the demo

```bash
python main.py
```

Runs two **approve** scenarios in sequence:
1. **Permanent read:** Agent asks for order status → hits deny → proposes permanent expansion → judge approves → agent refreshes tools → calls `get_order_status` → answers user.
2. **Time-bounded PII write:** Agent needs to update an email → hits deny → proposes 30-minute elevation → judge approves → agent refreshes tools → calls `update_customer_email` → confirms update.

### Reject scenario

```bash
python demo_reject.py
```

A separate script that bypasses the doer agent and submits a deliberately-broken proposal — a permanent grant for `update_customer_email` (a PII write that must be time-bounded per Criterion 5) — directly to the judge. The judge rejects.

This is run as its own script rather than as a third `main.py` scenario because forcing the doer to construct a wrong proposal would require nudging its system prompt or skill, which falsifies the demonstration. The judge's correctness is independent of where the proposal came from; constructing the wrong proposal directly exercises the judge in isolation on a known-bad input.

### What success looks like

For `main.py`:
- The `AuthorizeActionException` when tools are denied
- The agent activating the policy-generator-skill and constructing proposals
- `submit_proposal` returning `APPROVED and incorporated. Policy ID: ...`
- The agent calling `refresh_gateway_tools` and then executing the originally-denied tool
- Final answers to the user's questions with real data from DynamoDB

For `demo_reject.py`:
- The constructed proposal printed
- The judge's verdict: `reject`, naming Criterion 5 (shape discipline)
- Exit code `0` when the rejection is what was expected

### 6. Reset (re-run the demo)

```bash
python cleanup.py
python seed_policy.py
```

`cleanup.py` deletes all agent-created policies from the Policy Engine and clears proposal files from `proposals/`. `seed_policy.py` re-creates the starting permit. You can now run `python main.py` again from the initial state.

### 7. Teardown

```bash
python cleanup.py
cd infrastructure
cdk destroy
```

Removes all AWS resources created by this sample. See [`infrastructure/README.md`](infrastructure/README.md) for details on what survives `cdk destroy`.

---

## Cost

All resources are within or near AWS free tier for a demo run:
- **DynamoDB** — on-demand mode, single-digit reads/writes (~$0)
- **Lambda** — 3 functions, invoked a handful of times (~$0)
- **AgentCore Gateway + Policy Engine** — billed per request; a demo run is a few requests
- **Bedrock (Claude Sonnet)** — input/output tokens for 2 agent runs + 2 judge evaluations

Estimated cost for a single demo run: under $1. **Teardown after you're done** — a forgotten Gateway or Policy Engine with no traffic has no ongoing cost, but leaving resources deployed is not recommended.

---

## Architecture

```
┌────────────────────────────────────────────────────────────────────────────┐
│  Local process (or AgentCore Runtime container)                           │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Strands Agent (customer-service)                                    │  │
│  │  ├─ AgentSkills plugin → loads policy-generator-skill/                │  │
│  │  ├─ tools: MCP (Gateway), get_current_utc_time, get_agent_identity,  │  │
│  │  │         submit_proposal, refresh_gateway_tools                    │  │
│  │  └─ model: Claude Sonnet (Bedrock)                                   │  │
│  └────┬─────────────────────────────────────────────────────────────────┘  │
│       │ tool calls via MCP:                                                │
│       │   CustomerBasics___get_customer_basics  (permitted from start)      │
│       │   OrderStatus___get_order_status        (denied → propose)          │
│       │   CustomerEmail___update_customer_email  (denied → propose)         │
└───────┼────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  AWS / AgentCore                                                         │
│  ┌──────────────────────────┐    ┌──────────────────────────────────┐    │
│  │  AgentCore Gateway       │───▶│  Policy Engine (Cedar, ENFORCE)  │    │
│  │  - MCP endpoint          │◀───│  - starting permit: get_customer │    │
│  │  - AWS_IAM authn         │    │    _basics only                  │    │
│  └──────────┬───────────────┘    │  - expansions added at runtime   │    │
│             │                    └──────────────────────────────────┘    │
│             │ on permit, forwards to:                                    │
│             ▼                                                            │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  Lambda: GetCustomerBasics  →  DynamoDB (customer data)          │   │
│  │  Lambda: GetOrderStatus     →  DynamoDB (order data, GSI)        │   │
│  │  Lambda: UpdateCustomerEmail→  DynamoDB (customer email, write)   │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────┘
        ▲
        │ on deny: AuthorizeActionException
        │
┌───────┼──────────────────────────────────────────────────────────────────┐
│  Policy evaluator (same process)                                        │
│  ┌──────────────────────────────────────────────────────────────────────┐│
│  │  submit_proposal tool (orchestrator, in customer_service_agent)      ││
│  │  ├─ judge.evaluate — Strands Agent + policy-evaluation-skill (zero   ││
│  │  │     tools); returns {verdict, reason}                             ││
│  │  └─ on approve: _incorporate_policy (deterministic Python helper) →  ││
│  │       create_policy() on AgentCore, with the cedar pinned to the    ││
│  │       string the doer submitted                                      ││
│  └──────────────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────────┘
```

### The loop: propose → refresh → call

1. Agent issues a tool call. Gateway evaluates Cedar policies — no permit exists. Returns `AuthorizeActionException`.
2. Agent activates `policy-generator-skill`. Determines the expansion shape (permanent or time-bounded). Constructs a Cedar fragment + structured justification.
3. Agent calls `submit_proposal`. The orchestrator passes both to the judge agent (which has zero tools and only produces `{verdict, reason}`). On `approve`, the orchestrator — not the judge — calls `_incorporate_policy` (a private helper in the same module) with the cedar string the doer submitted.
4. Agent calls `refresh_gateway_tools` — re-fetches available tools from the gateway; newly-permitted tool appears.
5. Agent calls the tool normally. Gateway evaluates — permit applies. Lambda executes. Data returns.

### Why the judge has no tools

The judge agent is loaded with the evaluation skill and given no tools at all. It produces a verdict; the orchestrator (deterministic Python in `submit_proposal`) decides what to do with it.

This matters because the judge is an LLM. If it held the `incorporate_policy` tool, approval and the call to `create_policy()` would be two coupled LLM outputs — a prompt-injection in the doer's justification could split them, getting the judge to "approve" while passing rewritten cedar to the tool. With the tool out of the judge's surface, the gate is deterministic: the LLM judges intent, deterministic code performs the side effect with the cedar that came in.

The article's "two-sided independence" claim becomes structural: the agent that benefits doesn't grade itself, and the agent that grades doesn't act either.

### Starting state

The Policy Engine starts with one permit (created by `seed_policy.py`):

```cedar
permit (
  principal is AgentCore::IamEntity,
  action    == AgentCore::Action::"CustomerBasics___get_customer_basics",
  resource  == AgentCore::Gateway::"<gateway-arn>"
)
when {
  principal.id like "<deployer-iam-arn>"
};
```

The agent has one working tool from the start. The other two are denied by default — the boundary hits feel earned, not infrastructural.

---

## Layout

```
main.py                          orchestration entry point — runs the two approve scenarios
demo_reject.py                   submits a deliberately-broken proposal directly to the judge
seed_policy.py                         seeds starting Cedar policy
cleanup.py                       resets demo state (deletes agent-created policies)
.env.example                     environment variable template
customer_service_agent/          doer agent: tools, orchestrator, incorporator helper
policy_evaluator_agent/          judge agent (verdict-only)
policy-generator-skill/          populated fork of ../../template/policy-generator-skill/
policy-evaluation-skill/         six-criterion evaluation protocol for the judge
infrastructure/                  CDK stack: DynamoDB + Lambdas + Gateway + Policy Engine
proposals/                       runtime artifacts (gitignored): cedar, justification, verdict
```

---

## Honest limits

- **Seed identity coupling.** `seed_policy.py` creates the starting permit for the deployer's IAM identity. The agent must run as the same identity, or the starting permit is inert. A production setup would parameterize the principal.
- **Time-bounded policy lifecycle.** Cedar's `when` clause prevents the policy from permitting after expiry, but the AWS Policy resource persists. `cleanup.py` handles demo cleanup; production would need automated policy expiration.
- **Judge as semantic backstop.** AgentCore's `FAIL_ON_ANY_FINDINGS` validation is a hard structural gate; the judge provides the semantic layer. The evaluation skill is tuned for this sample's scenarios — it may not catch creative misuse in other domains.
- **Single-agent trust model.** The customer-service agent constructs proposals and calls the evaluator from the same process. The judge provides the separation. In production, construction and evaluation would run under separate identities.

---

## Relationship to the template

This sample is a populated fork of [`../../template/`](../../template/). The template is opinionated about form; the sample fills in the AgentCore dialect and customer-service content.

---

*Part of the [Long-Running Agents](../../../README.md) series by Michael Butler.*
