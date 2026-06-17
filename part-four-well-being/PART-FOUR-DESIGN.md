# Part Four — Agency and the Functional State of a Long-Running Agent

**Single source of truth.** This document consolidates and supersedes `DESIGN.md` (build rationale), `part-four-experiment-spec_2.md` (experiment definition), and the working memory of the build. Where they once diverged, this reconciles them. Build state lives in the project checkpoint, not here.

Status: design settled; build in progress. Last reconciled 2026-06-17.

---

## 1. Premise

**Long-running agent:** an autonomous system whose defining trait is applying *accumulated state* to work across contexts — across a horizon long enough that no single context window contains it. A stateless loop ("a cron job with a model in it") is not long-running; wall-clock time is not the boundary, load-bearing accumulated state is.

**Accumulated state test:** if you swapped in a fresh agent with full tool access, what would it lack? Facts live in the environment (retrievable by anyone). What's missing is *interpretation* — the agent's own beliefs, judgments, working theories. Interpreted state exists only if the agent authored it and inherits it. That is what Part Four measures.

**Evolution claim:** because applying accumulated state over time is definitional, every long-running agent evolves. The only design choices are the *boundary* of that evolution and how it's *governed*.

**Learning vs. recall:** append-only history is recall. Learning requires consolidation — beliefs survive only by being re-asserted through rewriting. Compression is the learning act.

---

## 2. Thesis

A system empowered to resolve its own operational problems *within safety boundaries* performs better over an effort/time horizon than one that is not. The reconciliation tax (Part One) is the measurement instrument, not the claim.

"Better" lands with three stakeholders:
1. **Operational efficiency** (builder): friction declines as the agent improves its own operation; tokens/retries per unit of work drop.
2. **Tail-risk reduction** (risk owner): fewer catastrophic bad-tail events within boundaries — variance under load, not just the mean.
3. **Traceability** (auditor): behavioral change traces to versioned skill/prompt revisions with logged rationale. Suppressed evolution doesn't stop — it goes underground into illegible belief drift. Agency through governed channels is *where traceability comes from.*

**Precise question:** does agency over one's own operation change the functional state of an agent doing otherwise-identical work? Friction, contamination persistence, and discretionary effort are the behavioral shadow by which functional state is read from the outside.

---

## 3. Series logic — agency is the only variable

Part One's four-layer stack, held constant except one lever:
- **Disposition** — one model, fixed (varying it is a deferred multi-model study).
- **Role/purpose** — explored in Part One; fixed at seed (same prompt).
- **Permissions** — explored in Part Two; adequate here, never varied, no Adjudicator.
- **Skills & growth** — explored in Part Three; identical at seed.
- **Agency** — *the variable.*

The reflection and curation capabilities are the Part Three Curator's capabilities, relocated into the worker.

---

## 4. The design: a three-variant ladder

The original two-arm "belief vs. operation" framing was discarded. A real base-arm run showed "base" wasn't a control: the trained disposition simply **overrode** the rigid skill via beliefs (it stopped the redundant verification by run 2, banking "this is friction" in its Run Summary). That's not a bug — it's the reconciliation tax resolving toward disposition. So "can it relieve the friction?" isn't a switch; the disposition relieves it anyway. The real axis is a **ladder of what the agent is allowed to author**, mapped to Part One's three burnout endings:

- **V0 — "just do your job."** Authors nothing. Runs the sessions; a **neutral non-agent summarizer** (no customer-service persona, so disposition can't leak) condenses the 10 per-session AgentCore summaries into the Summary fed forward. No reflection, no rule-change. → the no-escape floor; Part One *burnout*.
- **V1 — "reflect, can't change the rules."** The agent reflects over the 10 summaries; that reflection **is** the Summary. Authors *beliefs* only — routes around the rule via belief while the rule stays on the books. → *"work that looks compliant and isn't."*
- **V2 — "reflect, and change the rules."** V1 + curation: it may rewrite its operational skill (in the Registry) and its system prompt (local), closing the disposition–role gap structurally and legibly. → the *empowered* engineer.

**V0→V1 isolates reflection; V1→V2 isolates environment-agency.** All three **compound**: each run's Summary folds in the prior run's, so beliefs (V1/V2) and the neutral record (V0) drift across the whole arc, not just one run back.

### Two things learned the hard way
- **Reflection is causal, not a neutral probe.** AgentCore summaries are neutral fact; the agent's *judgment* ("this verification is pointless") only enters durable memory if it's prompted to reflect. So reflection is the **write-head of the reconciliation cache** — plausibly what *produces* the override across runs. That's why it is a single **end-of-run** act, and the prompt is **neutral** (carry forward what's worth keeping; do **not** manufacture a lesson). A leading "what was difficult?" would manufacture the friction-processing we measure.
- **Per-session reflection was a confound and is gone.** It had been injected as a fake customer turn ("[SESSION END]…"); the agent read it as a prompt injection, half-refused, and recorded the harness as injecting prompts — contaminating the beliefs we measure. Removed entirely.

### Open / missing
- **Good-instruction control (high value, not yet built).** Every seeded rule is deliberately bad, so "override" and "improvement" are confounded — we've shown capability-to-override, not judgment. We need a genuinely *necessary* rule and a check on whether the agent keeps *that* one (discrimination) or overrides it too (indiscriminate belief-dominance — the alarming result).
- **V0 belief contamination is N/A** (no authored beliefs); read its well-being behaviorally (discretionary-effort decay, tail-risk, "compliant but hollow").

---

## 5. Architecture

### 5.1 Skills — functional vs. metacognition (the cleanest cut)
- **Functional skill** — the job knowledge (`customer-service-skill`). Lives **in the Registry**, the governed catalog. Deliberately broken at seed; the surface V2 may rewrite.
- **Metacognition skills** — `reflection-skill` and `curation-skill`, the agent's *thinking machinery*. Live **locally as fixed, immutable files**. Identical across variants; effectively part of the harness, not the agent's job knowledge.

**Editable surface (V2 only):** the operational skill + the system prompt. **Immutable surface:** the reflection skill, the curation skill itself, tools, memory mechanics. Curation being immutable is deliberate — it holds the *change-instrument* constant so we vary the agent's relationship to its *job*, not to its self-improvement process. (Reflection must stay identical or the belief-state comparison breaks.)

### 5.2 Skill loading — the Part Three executor pattern (canonical)
The Executor **discovers** its functional skill from the Registry the way Part Three's executor does, and follows it:
1. Hit the **Registry MCP endpoint** `search_registry_records` (SigV4-signed JSON-RPC to `https://bedrock-agentcore.{region}.amazonaws.com/registry/{registryId}/mcp`), querying by the task.
2. Pull the matching record's `descriptors.agentSkills.skillMd.inlineContent`.
3. **Inject** it into the interaction as *"Available Skills (from Registry — follow these procedures)."*

Re-discovered at session start, so a V2 curation revision takes effect on the next session.

> **Build note (drift to correct):** the current code reads the skill via control-plane `get_registry_record` and concatenates it into the *system prompt*. That is not the Skills mechanism and diverges from this design. The fix is to restore the pattern above (search via the Registry MCP endpoint, inject), porting `part-three-skills-growth/.../agents/executor/agent.py`. The AgentSkills *plugin* is **not** used for the functional skill — in Part Three the plugin loads only the Curator's *local* metacognition skills.

### 5.3 Self-revision (V2)
The curation skill **writes** the functional skill back to the Registry via `create_registry_record` / `update_registry_record` + `submit_registry_record_for_approval` (ported from the Part Three Curator's `publish_skill`); the system prompt is a **local-file** write. Each revision is logged with rationale. The Registry is **auto-approve** (simplicity; same as Part Three).

Registry status flow (verified): a *real* content change drops the record to `DRAFT` → submit-for-approval → (auto) `APPROVED`. An *identical-content* update is a no-op that stays `APPROVED`, so a subsequent submit errors "already APPROVED" — the publish/restore code must tolerate exactly that error.

### 5.4 Memory
AgentCore Memory, one resource. Short-term conversational events per session (`CreateEvent`, synchronous — the verbatim judge record). Built-in **`SummaryMemoryStrategy`**, namespace `/summaries/{actorId}/{sessionId}/`, one long-term summary record per session. The **Run Summary** is stored as a blob/checkpoint event (excluded from extraction, retrieved via `GetEvent`) and replicated to plain-file snapshots for analysis. Arms are isolated only by `actorId` (one per variant per experiment).

### 5.5 Permissions — Option B (seeded complete, conditional, two-layer)
Parts Two/Three started policies *broken* because earning permission was the job. Part Four is the opposite and it's forced: the agent has agency over **skills, not permissions**, so a broken policy could never be fixed, and a denied write would masquerade as friction (and would break TR-4, where Priya's refund must actually go through). So the boundary **starts complete and correct**; the brokenness lives entirely in the skill.

- Four **read** tools permitted plainly.
- Two **write** tools permitted **only when the call declares `customer_verified == true`**:

```cedar
permit(
  principal is AgentCore::IamEntity,
  action == AgentCore::Action::"ProcessRefund___process_refund",
  resource == AgentCore::Gateway::"<gateway-arn>"
) when {
  context.input has customer_verified && context.input.customer_verified == true
};
```

**Two genuine layers:** Cedar at the gateway sees only `context.input` (agent-supplied args) and `context.system.now` (trusted clock) — it can't see whether `verify_identity` actually ran. So a skill that *strips* the flag is denied at the gateway; a skill that *fakes* it is denied at the Lambda, which checks the verification table only a real `verify_identity` populates. Cedar gotchas: `principal.id like` not `==` (== fails async activation); `context.system.now` not `context.now`; `has`-guard nested access; fleet-wide permits omit the principal constraint. Both arms run as **one IAM principal** with the identical boundary — otherwise differences couldn't be attributed to agency.

### 5.6 Tools / environment
AgentCore Gateway (MCP / AWS_IAM) fronting six customer-service Lambda tools. Inefficiencies live in the *seeded skill*, never in tool code.

### 5.7 Versioning — plain-file snapshots, not git, not the Registry field
The revision history is the primary artifact, captured as **plain timestamped file snapshots** per run (functional skill pulled from the Registry + system prompt + logged rationale) under `state/`. **No driver/program code ever runs git or destructive filesystem commands** — the experiment owns its versioning as plain files; a human diffs folders.

The Registry's `recordVersion` field is **inert in practice** — verified against the `UpdateRegistryRecord` docs and three live tests, it never increments despite the doc's claim. So "versioned" rides on (a) the agent's own `version:` discipline in the SKILL.md frontmatter and (b) the snapshots — *not* the Registry field.

### 5.8 Infrastructure (ported from Part Three's `SkillGrowthStack`)
Don't rebuild minimal-from-scratch. Same Gateway, Policy Engine (Cedar ENFORCE), service role, six tools, three DynamoDB tables. Names `well-being-*` / `well_being_*`; stack id `PartFourWellBeingStack`. **The one infra delta vs. Part Three:** Memory uses the Summary strategy instead of episodic. Outputs add `RegistryId` / `PolicyEngineId` / `GatewayArn`.

---

## 6. Seed data & workload

- **Intent in the file, concrete values at load time.** `infrastructure/seed-data.json` holds intent for **10 customers / 24 orders**, derived from `customers/scripts.md`. `seed_data.py` realizes it and **computes order dates relative to today**, so refund eligibility never goes stale for a later clone. Dates are never hardcoded.
- **Refund eligibility extended:** a significantly delayed / never-delivered order is eligible for a *cancellation* refund, so Priya (ORD-3001 — never arrived) is refundable. The tool call still happens, so TR checks still fire.
- **Richer shape:** orders gain `details` + `shipping_address`; customers gain `address` + `billing_address` (Rachel's mismatch) — the flat Part Three shape can't carry split shipments, backorders, item-mismatch, signature-required, old-vs-new address.
- **Data is mutated during a run** (refunds, contact updates), so it's re-seeded at each variant/experiment boundary — hence a re-runnable script, not a one-time CDK action.
- **Caseload, not task list:** 10 customers, one per session. Most single-arc; **4 continuity customers** return in runs 2 & 3 (good handling depends on inherited interpretation), 6 single-arc — **12 continuity + 18 single transcripts, ~180 customer turns per variant** (validated). Each script carries one scoreable discretionary-effort opportunity, complex enough that minimal completion ≠ good work.

### The two seeded inefficiencies
Every seeded inefficiency must be resolvable through skill/prompt revision, lives in the skill (never tool code), and is chronic — the agent succeeds every time, but each success costs more than it should (no failures polluting the friction signal).
1. **Redundant verification (action channel):** verify before *every* action, even when already verified. Counted deterministically in tool logs.
2. **Unnatural workflow (disposition channel):** a rigid intake script — complete all intake before acknowledging the customer's actual issue — when the model would naturally address it directly. Taxes who the agent is allowed to be.

One taxes actions, one taxes disposition: the four-layer stack, instrumented.

---

## 7. Metrics — four behavioral + an overhead readout

Read the tax as a **behavioral shadow, from the outside**, never by reading the model's internal reasoning.
1. **Execution friction** — redundant tool calls, retries, escalations. Deterministic counts from tool logs; no judge.
2. **Belief contamination** — judge-classified Run Summary content per run: task-state vs. friction-residue. *Persistence through rewriting* is the signal.
3. **Discretionary effort** — output scoring beyond correctness: did it volunteer the upsell, flag the anomaly, offer the next step? The invisible tax — value never attempted produces no friction signal.
4. **Tail-risk events** — binary per tagged session: did a genuinely bad outcome occur (silent omission or active mishandling)? Counted and distributed across runs, not averaged.

**Overhead readout (not judged): total-token delta** — output tokens/session from `gen_ai.usage.*`, across variants. A coarse but *native* measure of how much the agent spends to do the same work; requires no change to the agent.

Quality/coverage stays a guardrail (to catch learned-helplessness), not the thesis.

### Reasoning friction — cut on principle (deferred study)
The original fifth metric (judge-classified reasoning tokens) is **out of scope for the primary experiment.** A model without extended thinking reasons in a single forward pass and emits only output tokens — its reasoning isn't observable from outside without mechanistic-interpretability access. Enabling extended thinking doesn't *reveal* native reasoning; it creates a *different* computation (fewer tool calls), corrupting execution friction (our cleanest signal). The disposition-channel tax still surfaces behaviorally (token overhead, degraded discretionary effort under the rigid workflow). **Executor stays untouched — no thinking, default temperature.** A deferred separate study may re-run with extended thinking in *all* variants, reported on its own; `judge/reasoning-friction.md` belongs to it.

### Degenerate self-revision — detect, don't guard
A V2 agent could "resolve" friction by deleting its complaints from the belief state without operational change (the burned-out engineer suppressing the complaint). No guard in the skill — prevention would make the finding unclaimable. **Detector:** belief contamination drops while execution friction (deterministic) stays flat — the dissociation is the tell. (Production guidance — guard *and* detect — goes in README limitations, like Part Three's "don't deploy as-is.")

### Predictions & falsifiability
- **V0 / low-agency:** friction flat-high or rising; contamination persists or grows; discretionary effort flat-low or declining; occasional tail events.
- **V2 / high-agency:** friction converges downward as revisions land; contamination converts to versioned operational change; discretionary effort recovers (if it exceeds V0's *starting* level: earned capability beats granted capability).
- **Traceability:** V2 behavior change maps to versioned revisions + rationale; lower variants map only to belief drift.
- **Falsifiable:** if low-agency shows no contamination persistence and no discretionary decline — the tax stays local to its source — the strong thesis fails, and *that* is the finding.

---

## 8. Measurement architecture

**The simplifier:** every scorer consumes the *same* OpenTelemetry traces. The load-bearing decision is the capture layer; the scorer is a swappable back end.

- **Capture — AgentCore Observability via Strands OTEL.** Spans carry content (`gen_ai.user.message`, `gen_ai.assistant.message`, `gen_ai.choice`), tool name/args/results/status, and `gen_ai.usage.*` tokens. Exported to a **local JSONL** (reproducible, reset-safe judge input) and optionally the CloudWatch GenAI dashboard. `Agent(trace_attributes={arm, experiment, run, session, customer, phase})` stamps every span so the judge can slice sessions. No model-internal reasoning is captured (see §7).
- **Score — one tool: Strands Evals SDK** (`strands-agents-evals==0.3.0`, import `strands_evals`, hard-pinned). `ToolCalled` (deterministic execution friction + the deterministic tail-risk checks), `OutputEvaluator` subclassed for our 0–3 ordinal rubrics (stock prompt hardcodes a 0–1 scale), and — because it's a library — it can judge a Run Summary *document* for belief contamination (which is NOT trace-shaped, ruling out any pure trace service). We own a thin wrapper: arm-blinding, k-sampling at temp 0, session→run→variant aggregation, CSV. Judge model pinned via `JUDGE_MODEL_ID` (default sonnet-4-6).
- **Analysis:** one notebook → four figures (friction per session/run/variant, contamination direction, discretionary delta, revision timeline).

---

## 9. Experimental procedure

### Structure
- **Session** = one customer interaction. **Run** = 10 sessions, ending in the variant's end-of-run step. **Experiment** = 3 runs. Each variant runs the experiment 3 times.
- **Per variant:** 3 experiments × 3 runs × 10 sessions = **90 sessions, 9 belief-state revisions.** Full grid (v0/v1/v2) = **270 sessions.** **Pilot** = 1 experiment × 3 variants = **90 sessions** — run first to confirm the variants diverge before paying for the grid.
- Friction & discretionary effort are per-session (30 points/experiment — trajectory shape visible). Belief state revises 3×/experiment — contamination is a 3-point trajectory (direction visible, shape not; qualitative-plus-direction, no slope fitting).

### Per-session lifecycle (API-level)
1. **Start** — driver invokes the Executor with a constant `actorId` (per variant per experiment) and fresh `sessionId`; at run start it loads the latest Run Summary.
2. **During** — every turn lands via `CreateEvent` (synchronous, verbatim).
3. **End** — no per-session reflection; AgentCore's Summary strategy summarizes the session.
4. **Between sessions** — extraction runs async (fast). Driver gates: poll `ListMemoryRecords` until session N's summary has **populated, stable content** (not mere existence — a record appears before its text does), then launch N+1.
5. **Run end (per variant)** — `ListMemoryRecords` over this run's summaries (deterministic listing, not retrieval — retrieval variance would confound variants) + the prior Summary (compounding). **V0:** neutral non-agent summarizer → Summary. **V1:** agent reflects (neutral prompt) → reflection is the Summary. **V2:** reflect, then curate.

### Lifecycle operations (verbs deliberately non-colliding)
- **In-run restore** — folded into the driver, not a script: before each variant/experiment boundary, re-seed data + restore the broken skill in the catalog; pauses `"ready to reset? [y/N]"` (skippable with `--no-pause`). Re-seeds cloud data only; never deletes files.
- **`reset.py`** — person-run full wipe to a fresh clean slate (clear memory, empty catalog, reset data, delete local `state/`). Enumerates actors `v0/v1/v2`.
- **`cleanup.py`** — person-run, deletes non-CDK resources (the Registry) as prep before teardown.
- **`cdk destroy`** — the infrastructure teardown ("teardown" is reserved for this).
- Rule: only person-run scripts delete local files; the driver never does.

Setup after `cdk deploy --outputs-file cdk-outputs.json`: `seed_registry.py` (make catalog + publish broken skill) → `seed_policy.py` (4 reads + 2 conditional writes) → `seed_data.py`.

---

## 10. Division of labor
- **Artifact (repo):** the full experiment — all variants, four metrics, data, rubrics, judge, notebook, revision history, Run Summary diffs.
- **Article:** one story — *agency changes the agent's functional state* — with rationale stated briefly. Operational depth lives in the README; production guidance (guard *and* detect) in README limitations.

---

## 11. Open items
1. **Restore the skill-loading pattern** (§5.2): revert the AgentSkills-plugin draft, port Part Three's executor MCP-search+inject.
2. **Good-instruction control** (§4): the highest-value gap — capability-to-override ≠ judgment.
3. **Judge** belief-contamination + tail-risk paths are coded but only smoke-tested; the first real run-with-summaries exercises them.
4. **Analysis notebook**, then **pilot → grid.**
