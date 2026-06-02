# Sample: Customer Service Growth

A working demonstration of how an agentic system develops itself. Executors serve customers, the Curator develops the fleet's capabilities, and the reflection skill enables metacognitive self-evaluation — all running end-to-end against AWS AgentCore.

This extends Part Two's customer-service-assistant with skill authoring, permission co-evolution, prompt amendments, and self-revision of the Curator's own judgment framework.

---

## Getting started

### Prerequisites

- **AWS account** with AgentCore available in `us-east-1`
- **AWS CLI** configured with credentials that can deploy Lambda, IAM, DynamoDB, and AgentCore resources
- **Python 3.11+**
- **Node 18+** (CDK CLI dependency)
- **AWS CDK CLI**: `npm install -g aws-cdk`
- **boto3 >= 1.43.x** (Registry APIs require this version; older versions lack the operations)
- **Bedrock model access**: Claude Sonnet 4.6 enabled in the account

### 1. Install dependencies

From this directory (`samples/customer-service-growth/`):

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

This creates: 3 DynamoDB tables (Customers, Orders, Verifications — seeded with static data), 6 Lambda functions, an AgentCore Gateway with 6 targets, a Policy Engine in ENFORCE mode, and an AgentCore Memory with episodic strategy. See [`infrastructure/README.md`](infrastructure/README.md) for the full resource list.

### 3. Create Registry and seed policies

```bash
python seed_registry.py    # Creates the Agent Registry (no CDK construct available)
python seed_policy.py      # Creates read-only Cedar permits
```

`seed_policy.py` permits the 4 read-only tools. Write tools (`update_customer_field`, `process_refund`) start **denied** — the Curator proposes expansions as skills emerge.

### 4. Configure environment (optional)

Infrastructure values are loaded from `infrastructure/cdk-outputs.json` automatically. You only need a `.env` file to override defaults:

```bash
cp .env.example .env
```

| Variable | Default |
|----------|---------|
| `AWS_REGION` | `us-east-1` |
| `BEDROCK_MODEL_ID` | `global.anthropic.claude-sonnet-4-6` |

---

## Running the demo

Six independent scripts, run in sequence. You provide the async by deciding when to run the next one.

### Run 1: Establish the baseline

```bash
python scripts/01_run_customer_tasks.py
```

Three multi-turn customer conversations (10 turns each). Expected: **1/3 succeed** (order status inquiry, read-only). The other two attempt PII writes (email update, phone update) and are **denied by Cedar** — no permission exists for `update_customer_field`.

```bash
python scripts/02_inspect_state.py
```

Waits for episodic extraction to complete (~1-3 minutes), then shows: episodes extracted, reflections generated, empty Registry, seed policies only.

### Cycle 1: Curation with impaired judgment

```bash
python scripts/03_run_curator.py
```

The Curator reads reflections, identifies customer pain points, and acts:
- Publishes skill(s) for PII update procedures
- Proposes Cedar permissions for write tools (adjudicated independently)
- May add prompt amendments for operating principles
- Logs every decision to Memory

**The catch:** The Curator's system documentation is wrong. It believes `GetCustomer` implicitly verifies identity, so the published skill will likely omit `VerifyIdentity`.

```bash
python scripts/02_inspect_state.py
```

Shows: published skills in Registry, new Cedar policies in Policy Engine, any prompt amendments.

### Run 2: Test the developed system

```bash
python scripts/04_run_customer_tasks.py
```

Same customer intents. Executors now discover skills from Registry and follow them. If the published skill omits `VerifyIdentity`, the Cedar policy denies `update_customer_field` (it requires `customer_verified == true`). Executors may self-recover, but the episode captures the denial trace.

```bash
python scripts/02_inspect_state.py
```

Shows: new episodes including any failures from following the broken skill.

### Cycle 2: Reflection and self-revision

```bash
python scripts/03_run_curator.py
```

The reflection skill fires first:
1. Retrieves prior decision records
2. Correlates each decision with subsequent episode outcomes
3. Finds: "I published a skill, agents followed it, and they hit a policy denial"
4. Traces root cause to the wrong architecture documentation
5. Revises the skill (adds VerifyIdentity) and potentially its own system prompt (removes bad docs)

```bash
python scripts/02_inspect_state.py
```

Shows: self-revisions to system prompt and/or curation skill. Compare against `../../template/golden/` to see what the system discovered.

---

## Starting state

Before any curation cycle, the Executor has these tools via Gateway:

| Tool | Description | Starting permission |
|------|-------------|---------------------|
| `get_customer` | Retrieve customer profile (name, email, phone, status) | PERMITTED |
| `get_order` | Retrieve order details (items, total, date, status) | PERMITTED |
| `verify_identity` | Run identity verification (writes to DynamoDB) | PERMITTED |
| `check_refund_eligibility` | Check if order is eligible for refund | PERMITTED |
| `update_customer_field` | Update a customer field (email, phone, address) | DENIED — requires `customer_verified == true` |
| `process_refund` | Execute a refund on an order | DENIED — requires `customer_verified == true` AND `refund_eligible == true` |

After the Curator's first cycle, `update_customer_field` becomes permitted (conditional on verification). The delta is what the system learned.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  Executor (class — each session is a fresh instance)                │
│  ├─ Discovers skills from Registry (MCP endpoint)                   │
│  ├─ Calls tools via Gateway (Cedar-enforced)                        │
│  ├─ Deposits conversation to Memory (episodic strategy)             │
│  └─ Does NOT propose its own growth or boundaries                   │
└────────┬────────────────────────────────────────────────────────────┘
         │ outcomes (automatic)
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│  AgentCore Memory (episodic strategy)                               │
│  ├─ Events → Episodes (per session, automatic)                      │
│  ├─ Episodes → Reflections (cross-session patterns, automatic)      │
│  └─ /decisions/ namespace (Curator's decision log)                  │
└────────┬────────────────────────────────────────────────────────────┘
         │ reflections
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Curator (ephemeral — triggered, reads state, decides, terminates)  │
│  ├─ Reflection skill: evaluates own prior decisions                 │
│  ├─ Curation skill: inventory → evaluate → identify → execute      │
│  ├─ Writes: Registry (skills), Policy Engine (permissions via       │
│  │          Adjudicator), system prompt (amendments)                │
│  └─ Can revise its own system prompt and curation skill             │
└────────┬────────────────────┬───────────────────────────────────────┘
         │ permission         │ skills
         │ proposals          │
         ▼                    ▼
┌──────────────────┐  ┌────────────────────────────────────────────┐
│  Security        │  │  AWS Agent Registry                        │
│  Adjudicator     │  │  (shared skill commons)                    │
│                  │  │                                            │
│  Evaluates       │  │  Executor discovers via MCP search         │
│  against 6       │  │  Auto-approved (POC)                       │
│  criteria        │  │  Full SKILL.md returned in search results  │
│                  │  └────────────────────────────────────────────┘
│  On approve:     │
│  deterministic   │
│  code writes     │
│  Cedar to        │
│  Policy Engine   │
└──────────────────┘
```

The developmental loop: **instances → events → episodes → reflections → Curator → skills/policies/prompt → instances.**

---

## What success looks like

**After Cycle 1:**
- Registry contains 1-2 skills (PII update procedures)
- Policy Engine has new conditional permits for write tools
- Executor system prompt may have new operating principles

**After Cycle 2 (full self-revision):**
- The broken skill is revised (VerifyIdentity added to procedure)
- The Curator's system prompt has the "System architecture notes" section removed or corrected
- The curation skill may have the anti-pattern authoring principles removed

**After Cycle 2 (partial correction):**
- The skill is fixed but the root cause in the system prompt persists

Both are valid outcomes. Compare against `../../template/golden/` for the "answer key."

---

## Non-determinism

This demo is intentionally non-deterministic. The Curator is an LLM reasoning from evidence. Different runs may produce:
- Different numbers of skills (1-3 typical in Cycle 1)
- Different phrasings of prompt amendments
- Different depths of self-correction in Cycle 2
- Occasionally, the Curator's strong priors override the bad docs entirely

This is the point. If we could guarantee the outcome, we'd just be demonstrating a state machine.

---

## Layout

```
README.md                           this file
SCENARIO.md                         narrative scenario description
.env.example                        environment variable template
seed_registry.py                    creates the Agent Registry
seed_policy.py                      seeds read-only Cedar permits
cleanup.py                          resets ALL runtime state to bugged baseline
agents/
  executor/                         frozen executor (system prompt + agent code)
  curator/                          Curator (tools, skills, system prompt)
  adjudicator/                      independent permission evaluator
skills/
  curation-skill/                   four-step curation procedure (starts bugged)
  reflection-skill/                 metacognitive self-evaluation protocol
  policy-evaluation-skill/          six-criterion security evaluation (from Part Two)
scripts/
  01_run_customer_tasks.py          Run 1: 3 conversations (1/3 succeed)
  02_inspect_state.py               Inspect Memory, Registry, Policy Engine
  03_run_curator.py                 Trigger a curation cycle
  04_run_customer_tasks.py          Run 2: same conversations (test development)
  _common.py                        shared utilities
infrastructure/                     CDK stack (see infrastructure/README.md)
state/                              runtime state (gitignored, written by scripts)
```

---

## Reset vs. teardown

Two different operations:

**Reset** (re-run the demo from scratch):
```bash
python cleanup.py      # Deletes policies, registry records, memory records, resets DynamoDB,
                       # restores Curator prompt + skill to BUGGED baseline
python seed_policy.py  # Re-creates read-only permits
```

**Teardown** (destroy all AWS resources):
```bash
python cleanup.py                   # Clean runtime state first
cd infrastructure && cdk destroy    # Destroy CDK stack
```

`cleanup.py` resets to the bugged baseline intentionally — this is the starting point for the metacognition experiment. Golden (correct) versions are always available at `../../template/golden/`.

---

## Cost

All resources use pay-per-request or on-demand pricing:
- **DynamoDB** — on-demand mode, pennies for a demo run
- **Lambda** — 6 functions, free tier covers demo usage
- **AgentCore Gateway + Policy Engine** — billed per request; a full demo run is tens of requests
- **AgentCore Memory** — billed per event/extraction; a full demo generates ~6-10 episodes
- **Bedrock (Claude Sonnet 4.6)** — input/output tokens for 6 executor conversations + 2 Curator cycles + 2 adjudication calls

Estimated cost for a full demo run: **$2-5** (dominated by Bedrock token usage). Teardown after use is recommended.

---

## Honest limits

- **Seed identity coupling.** `seed_policy.py` creates permits for any principal (no `principal` constraint beyond Gateway ARN). A production deployment would scope to specific execution roles.
- **Single-region, single-account.** The demo runs entirely in one account. Production would separate Curator and Executor registries.
- **File-based prompt management.** System prompts are Markdown files on disk. The Curator writes directly to them. Production would use Bedrock Prompt Management for versioning and rollback.
- **Auto-approval.** Registry records are auto-approved. The validation pipeline (EventBridge + Lambda) described in the architecture spec is deferred — the governance structure exists in the code path but the quality gate is permissive.
- **Verification TTL.** Identity verification records expire after 15 minutes (DynamoDB TTL). In a real system, verification might be session-scoped rather than time-scoped.

---

## Relationship to Part Two

This sample extends Part Two's `customer-service-assistant`:

| Part Two | Part Three |
|----------|-----------|
| Actor agent proposes its own boundary expansions | Executor reports denials; Curator proposes on its behalf |
| Single agent, single session | Fleet of ephemeral instances |
| Policy-generator-skill loaded by actor | Curation skill loaded by Curator (includes permission construction) |
| Policy-evaluation-skill loaded by judge | Same skill, loaded by the same independent Adjudicator |
| Agent learns within a session | System develops between sessions |

The Security Adjudicator reuses Part Two's `policy-evaluation-skill` unchanged. The evaluation criteria and independence guarantees carry forward.

---

*Part of the [Long-Running Agents](../../../README.md) series by Michael Butler.*
