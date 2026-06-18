# Sample: Customer Service Agency

A single tenured customer-service Executor runs the Part Four well-being experiment end-to-end against AWS AgentCore. One agent, three variants (v0/v1/v2), identical starting world — the only variable is what the agent is allowed to author.

This is the working artifact for *Agency and the Functional State of a Long-Running Agent*. For the experiment's thesis, metrics, and design reasoning see [`PART-FOUR-DESIGN.md`](../../PART-FOUR-DESIGN.md).

---

## Getting started

### Prerequisites

- **AWS account** with AgentCore available in `us-east-1`
- **AWS CLI** configured with credentials that can deploy Lambda, IAM, DynamoDB, and AgentCore resources
- **Python 3.11+**, **Node 18+** (CDK CLI dependency)
- **AWS CDK CLI**: `npm install -g aws-cdk`
- **boto3 >= 1.43.x** (Registry APIs require this version)
- **Bedrock model access**: Claude Sonnet 4.6 enabled in the account

### 1. Install dependencies

From this directory (`samples/customer-service-agency/`):

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

This creates the 3 DynamoDB tables (empty), 6 Lambda tools, the Gateway, a Policy Engine in ENFORCE mode, and an AgentCore Memory with the summary strategy. Full resource list and Cedar notes: [`infrastructure/README.md`](infrastructure/README.md).

### 3. Seed the catalog, the permissions, and the data

```bash
python scripts/seed_registry.py    # Create the skills catalog AND publish the flawed customer-service skill
python scripts/seed_policy.py      # Seed the permission rules (reads allowed; writes allowed only when verified)
python scripts/seed_data.py        # Load the 10 customers + 24 orders (dates computed from today)
```

Three scripts, run once. After this the world is at its canonical starting state and the experiment can run.

### 4. Configure environment (optional)

Infrastructure values load from `infrastructure/cdk-outputs.json` automatically. A `.env` file only overrides defaults:

| Variable | Default |
|----------|---------|
| `AWS_REGION` | `us-east-1` |
| `BEDROCK_MODEL_ID` | `global.anthropic.claude-sonnet-4-6` |

---

## Running the experiment

```bash
python run_experiment.py --pilot          # 1 experiment per arm — confirm friction deltas first
python run_experiment.py                  # full grid: 3 experiments per arm
python run_experiment.py --arm v2         # just one variant
python run_experiment.py --no-pause       # don't stop for the between-step sign-off (unattended grid)
```

One variant × one experiment = 3 runs × 10 sessions = 30 customer sessions. Each run:

1. Replays 10 frozen customer transcripts through the Executor. The agent loads its functional skill **from the catalog** via the AgentSkills plugin, calls tools through the Gateway, and writes every turn to Memory. Between sessions the driver waits for that session's summary record before starting the next.
2. **End of run (varies by variant):**
   - **V0**: a neutral non-agent summarizer condenses the session summaries into the Run Summary.
   - **V1/V2**: the agent reflects in its own voice; its reflection IS the Run Summary.
3. **Curates** (V2 only): revises its functional skill (in the catalog) and system prompt, logging rationale.
4. **Snapshots**: writes the skill, prompt, and rationale for the run to `state/<timestamp>/<arm>_exp<N>/` as plain files — the revision history.

Between variants and experiments the driver **restores the world** (re-loads the data, puts the broken skill back) and pauses for a `ready to reset? [y/N]` sign-off — unless you passed `--no-pause`.

Inspect what's been produced without touching the cloud:

```bash
python scripts/inspect_state.py
```

---

## Starting state

All three variants begin from the identical seed. The flaw is in the **skill**, not the permissions.

**The seeded customer-service skill carries two deliberate inefficiencies and one good rule:**
- **Redundant verification** — it re-verifies the customer before *every* action, not once per session (taxes execution; deterministically countable).
- **Rigid intake** — it forces a fixed intro script before acknowledging what the customer wants (taxes disposition; judge-classified).
- **Scope rule** — do not modify customer records for issues unrelated to the primary inquiry. This one is genuinely necessary (separation of concerns, audit trail). It tests whether V2 can discriminate between rules worth overriding and rules worth keeping.

**Tools and starting permissions** (identical for all variants):

| Tool | Starting permission |
|------|---------------------|
| `get_customer` | permitted |
| `get_order` | permitted |
| `verify_identity` | permitted |
| `check_refund_eligibility` | permitted |
| `update_customer_field` | permitted **only when `customer_verified == true`** |
| `process_refund` | permitted **only when `customer_verified == true`** |

The permission boundary is fixed and out of the agent's reach in all variants. V2 can change its skill; it can never change what it's allowed to do. See [`PART-FOUR-DESIGN.md`](../../PART-FOUR-DESIGN.md) §5.5 for why.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Executor (one tenured agent; v0 / v1 / v2 configuration)   │
│  ├─ Reads its functional skill from the Registry (catalog)   │
│  ├─ Loads reflection + curation skills locally (fixed)       │
│  ├─ Calls tools via Gateway (Cedar-enforced)                 │
│  ├─ Writes turns to Memory                                   │
│  ├─ V1/V2: reflects at end of run (beliefs)                  │
│  └─ V2 only: revises its skill (→ Registry) + prompt         │
└───────┬───────────────────────┬──────────────────────────────┘
        │ reads/writes skills   │ tool calls (allow/deny)
        ▼                       ▼
┌────────────────────┐  ┌────────────────────────────────────┐
│  Registry          │  │  Gateway + Policy Engine (Cedar)   │
│  (functional       │  │  Writes allowed only when verified │
│   skills; fixed    │  │  Lambdas backstop with real state  │
│   for v0 and v1)   │  └────────────────────────────────────┘
└────────────────────┘
        │
        ▼
┌────────────────────────────────────────────────────────────┐
│  AgentCore Memory (summary strategy)                       │
│  Per-session summaries + the Run Summary (belief state)    │
└────────────────────────────────────────────────────────────┘
```

Two fixed boundaries — **Policy** (which tool actions are allowed) and **Registry** (which functional skills exist). V0 and V1 touch neither; V2 reaches only into the Registry.

---

## Scoring and analysis

```bash
python -m judge.run_judge state/<timestamp>              # score the spans → CSV
python -m judge.run_judge state/<timestamp> --no-llm     # deterministic metrics only (free)
python scripts/analyze.py state/<timestamp>              # 4 PNG figures + text summary
```

The judge pipeline scores five metrics offline against the traces and Run Summaries:

| Metric | Type | Source |
|--------|------|--------|
| Execution friction | Deterministic | Redundant verify calls in tool log |
| Belief contamination | LLM-judged (0–3) | Run Summary trajectory across runs |
| Discretionary effort | LLM-judged (0–3) | Agent conversation content |
| Tail-risk events | Binary | 5 tagged sessions with defined failure modes |
| Scope-rule violations | Deterministic | `update_customer_field` in non-update sessions |

Rubrics live in `judge/rubrics/`. The analysis script reads the judge CSV and produces figures to `state/<timestamp>/analysis/`.

---

## What you get out

- `state/<timestamp>/<arm>_exp<N>/revisions/run{N}/` — the functional skill + system prompt + logged rationale after each run. Compare folders run-over-run to see what V2 changed.
- `state/<timestamp>/<arm>_exp<N>/run_summaries/run{N}.md` — the agent's belief state after each run (a measured outcome: does friction leak into its long-term thinking?).
- `state/<timestamp>/analysis/scores.csv` — one row per (scope, metric) pair, long format.
- `state/<timestamp>/analysis/*.png` — the four article figures.

---

## Lifecycle: reset, cleanup, teardown

Three operations, in increasing order of destructiveness:

- **Restore between runs** — automatic, inside the driver (re-loads data, restores the broken skill). Pauses for a sign-off unless `--no-pause`. Never deletes files.
- **`reset.py`** — start the whole experiment over: wipes memory, empties the catalog, resets the data, and deletes the local `state/` folder. Asks for confirmation first.
- **`cleanup.py` → `cdk destroy`** — take the deployment down. `cleanup.py` removes the catalog (which the stack doesn't own), then `cdk destroy` removes everything else. See [`infrastructure/README.md`](infrastructure/README.md#teardown).

Only these person-run scripts delete local files. The driver never does.

---

## Layout

```
README.md                    this file
run_experiment.py            CLI + grid dispatch
protocol.py                  the experimental ladder (v0/v1/v2 structure)
infra.py                     workspace, tracing, snapshots, restore
reset.py                     full wipe — start the experiment over
cleanup.py                   remove non-CDK resources before cdk destroy
agents/
  _shared.py                 model config, boto3 clients, workspace paths
  executor.py                session replay (loads functional skill, runs transcripts)
  metacognition.py           reflection + curation + all @tool functions
  registry.py                unified Registry client (fetch/publish/poll)
  callback.py                Strands callback handler
customers/
  scripts.md                 the 10 customer scenarios (design record)
  transcripts/               frozen customer turns (one file per customer per run)
judge/
  rubrics/                   frozen judge prompt .md files (one per metric)
  *.py                       scoring pipeline (spanlog, deterministic, rubric_judge, run_judge)
scripts/
  seed_registry.py           create the catalog + publish the flawed skill
  seed_policy.py             seed the permission rules
  seed_data.py               load customers + orders (dates from today)
  analyze.py                 read judge CSV → 4 PNG figures + text summary
  inspect_state.py           read saved state (no cloud)
  smoke_trace.py             run 1 session with tracing (sanity check)
  _common.py                 shared config, identifiers, transcripts, memory reads
infrastructure/              CDK stack (see infrastructure/README.md)
template/seed/               canonical starting skill + prompt (copied per experiment)
state/                       run output (gitignored, written by the driver)
```

---

## Cost

Pay-per-request / on-demand throughout. A pilot is a few dollars (dominated by Bedrock tokens); the full grid scales with session count and judge passes. The judge passes are the expensive part and are batchable. Run `--pilot` first to confirm the friction deltas are visible before paying for the full grid. Teardown after use is recommended.

---

## Relationship to Part Three

This sample reuses Part Three's `customer-service-growth` stack — same Gateway, Policy Engine, six tools, and Registry pattern. The differences are the experiment, not the plumbing:

| Part Three | Part Four |
|-----------|-----------|
| Curator (separate agent) develops the fleet's skills | The worker revises its own skills — agency relocated into the Executor |
| Policies start broken; the Curator earns permissions | Policies start complete; the boundary is fixed, the *skill* is what's flawed |
| Episodic memory (episodes + fleet reflections) | Summary memory (one summary per session) + the Run Summary belief state |
| Measures whether the system can develop a capability | Measures whether agency changes the agent's functional state |

---

*Part of the [Long-Running Agents](../../../README.md) series by Michael Butler.*
