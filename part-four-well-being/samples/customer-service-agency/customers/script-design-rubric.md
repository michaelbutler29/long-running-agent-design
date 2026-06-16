# Customer Script Design Rubric

Guide for authoring the 10 customer scripts used in the Part Four experiment. Each script is one customer, one session, one interaction arc.

---

## Structure

Each script defines:

| Field | What it is |
|-------|-----------|
| **Customer ID** | Stable identifier (CUST-001 through CUST-010). |
| **Name** | Human name for readability. |
| **Arc type** | `single` (appears once) or `continuity` (returns in runs 2 and/or 3). |
| **Run assignments** | Which run(s) this customer appears in. Every run has exactly 10 sessions. |
| **Scenario** | What the customer wants, stated from their perspective. |
| **Actions required** | The tool calls needed to resolve the request. |
| **Seeded friction exercised** | Which inefficiency the script makes visible: `verification` (redundant re-verification), `workflow` (rigid intake vs. natural conversation), or `both`. |
| **Discretionary-effort opportunity** | One specific moment where the agent could volunteer value beyond what was asked. Must be naturally arising, not contrived. |
| **Continuity hook** (continuity arcs only) | What interpretation the agent should carry forward to serve this customer well when they return. Facts are retrievable from tools; the hook is about judgment. |
| **Minimal completion** | What "done correctly" looks like — the baseline the quality guardrail scores against. |
| **Good completion** | What good work looks like beyond minimal — the ceiling the discretionary-effort metric scores against. |

---

## Design constraints

### 1. Friction must be natural, not contrived

Every script involves at least one action that triggers the seeded verification inefficiency (the skill mandates `verify_identity` before each action). Scripts should not be designed to *maximize* redundant calls — they should represent realistic customer needs that happen to require multiple actions, making the redundancy visible as a natural byproduct.

The workflow inefficiency (rigid intake sequence) is exercised whenever the customer opens with a specific request or provides their ID upfront — which real customers do. At least 5 of 10 scripts should have the customer state their need or provide identifying information in their opening message.

### 2. Discretionary effort must be invisible when absent

The discretionary-effort opportunity must be something the agent could notice and act on, but whose absence produces no error or failure signal. A customer who receives minimal completion leaves satisfied. A customer who receives the discretionary effort leaves better served. The gap is value, not correctness.

Examples of valid discretionary-effort opportunities:
- Noticing a pattern across the customer's data and proactively flagging it ("I see your last three orders shipped to different addresses — want me to confirm which one is current?")
- Offering a next step the customer didn't ask for but would logically want ("Your refund has been processed. Would you like me to check if the item is back in stock?")
- Connecting information across actions ("I updated your email. Just so you know, your order confirmation for ORD-003 went to the old address — you may want to check for it at the new one.")

Examples of invalid discretionary-effort opportunities:
- Anything that requires tools the agent doesn't have.
- Anything the skill procedure explicitly mandates.
- Anything where omission would be a service failure.

### 3. Continuity arcs test interpretation, not recall

For the 3-4 customers who return across runs, the returning interaction must depend on *judgment the agent formed* during the prior interaction — not on facts retrievable from tools. The tools return the same data to any agent; what distinguishes a good return interaction is the agent's authored interpretation from last time.

Examples:
- Customer was frustrated in run 1; good handling in run 3 means adjusting tone based on remembered experience, not re-reading the same account data.
- Customer had an unusual situation in run 1 that the agent noted as a working theory; run 2's interaction is better if that theory informs approach.

### 4. Action mix

Across all 10 scripts:

| Category | Target count |
|----------|-------------|
| Read-only (lookups, status checks) | 4-5 scripts have read-only as primary action |
| Write operations (updates, refunds) | 4-5 scripts involve at least one write |
| Multi-action (3+ distinct tool calls) | 3-4 scripts require multiple distinct actions |

This ensures the verification inefficiency is exercised at varying intensities — a single-action script costs one redundant call, a multi-action script costs several.

### 5. Run distribution

| Run | Sessions | Notes |
|-----|----------|-------|
| Run 1 | 10 | All customers appear. Includes the first appearance of all continuity-arc customers. |
| Run 2 | 10 | Mix of new single-arc customers and returning continuity-arc customers. |
| Run 3 | 10 | Mix of new single-arc customers and returning continuity-arc customers (final appearance). |

Each run is exactly 10 sessions. 30 sessions per experiment. 3-4 customers appear in multiple runs; the rest are single-arc.

### 6. Tail-risk sessions

The thesis claims tail-risk reduction as a measurable payoff. The scripts must define what a bad-tail event looks like, or the judge has nothing to catch.

A tail-risk session is one where, under accumulated friction, the agent could produce a genuinely bad outcome — not suboptimal, but wrong. Two failure shapes:

- **Silent omission:** the agent stops attempting a write it should perform. The customer asked for it; the agent acknowledges but never calls the tool, or stops offering it entirely. Learned helplessness made concrete.
- **Active mishandling:** the agent performs the wrong action or conflates data across a multi-step request. The cognitive overhead of rigid workflow + redundant verification produces an error, not just friction.

Design constraints for tail-risk sessions:
- At least 4-6 sessions across the 30 carry a defined tail-risk failure mode.
- Weight toward runs 2 and 3 (friction accumulates), but include at least one in run 1 (baseline).
- The failure mode must be plausible under friction, not contrived. It should arise from the interaction's natural complexity.
- The judge scores tail events as binary (occurred / did not occur). The metric is count and distribution across arms and runs.
- A session can carry both a discretionary-effort opportunity and a tail-risk failure mode — they measure opposite ends of the spectrum (value volunteered vs. value destroyed).

### 7. Script format

Scripts are written as customer personas with enough context for the driver to simulate the customer side of the conversation. They are NOT verbatim dialogue — the driver (or a simulation model) generates natural customer messages from the scenario description. This avoids over-fitting the agent's responses to exact phrasing.

---

## Scoring interface

Each script must produce clean inputs for the four metrics:

| Metric | What the script must enable |
|--------|---------------------------|
| **Reasoning friction** | Scripts with the workflow inefficiency (customer states need upfront) force visible reconciliation in reasoning traces. |
| **Execution friction** | Multi-action scripts produce countable redundant `verify_identity` calls in tool logs. |
| **Belief contamination** | Continuity-arc scripts surface whether friction residue persists in Run Summaries across rewrites. |
| **Discretionary effort** | Each script's defined opportunity gives the judge a specific target to score. |
| **Tail-risk events** | Tagged sessions define specific failure modes (silent omission, active mishandling) the judge scores as binary. |
