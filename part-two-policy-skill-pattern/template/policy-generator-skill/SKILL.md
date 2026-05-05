---
name: policy-generator-skill
description: Generates paired policy proposals (a Cedar fragment plus a structured justification) when an agent hits a permission boundary it cannot proceed past. Use when a required action is blocked by deterministic policy enforcement and the agent can articulate both the scope it would need and why.
license: CC-BY-4.0
metadata:
  author: Michael Butler
  version: "1.0"
---

# Policy Generator Skill

This skill produces paired policy proposals — a Cedar fragment plus a structured justification — when an agent hits a permission boundary it cannot proceed past.

## Activation conditions

Activate this skill when:

- A tool call has been denied by the deterministic enforcement layer.
- You recognize that a planned action will be denied.
- You lack the authorization to proceed and need to request expanded boundaries.

## Before proceeding

Confirm you can articulate both:

- **What** scope you would need — principal, action, resource, and (if time-bounded) duration.
- **Why** the expansion is justified — citable basis, evidence, sensitivity factors.

If you cannot articulate both, do not proceed. Stop and surface the situation to the user or operator at the conversation level.

## What this skill does and does not do

**Does:**

- Helps you construct a structured justification for a boundary expansion.
- Helps you construct a well-formed Cedar policy fragment.
- Submits the paired proposal via `scripts/write-proposal.py` to your incorporation pipeline.

**Does not:**

- Evaluate proposals. Evaluation is downstream (HITL, LLM-as-judge, hybrid).
- Incorporate proposals into the deterministic enforcement layer. That is platform-specific (e.g., `CreatePolicy` on AgentCore).
- Drive the underlying action. Initiate or retry the action only after the proposal has been evaluated and incorporated.
- Bypass, override, or work around the deterministic enforcement layer under any circumstance.
- Handle the case where you cannot articulate a proposal. That is conversational escalation, outside this skill.

## Reasoning workflow

### Step 1. Identify what was (or may be) denied

Capture:

- The **principal** — which agent, which session, acting under whose authority.
- The **action** — the specific API call or operation.
- The **resource** — the target of the action.
- The **deny rationale** if the enforcement layer provided one.
- The **contextual reason** — what task were you executing, what plan were you on, what user request were you serving.

If you cannot articulate any of these, stop. Do not propose policy you cannot justify.

### Step 2. Construct the proposal

Every proposal has two parts: a Cedar policy fragment and a structured justification. Both are required. Construct each per the dedicated section below.

- Cedar fragment: see *Constructing the Cedar fragment* below.
- Justification: see *Constructing the justification* below.

### Step 3. Submit

Submit the paired proposal with `scripts/write-proposal.py --cedar <cedar-file> --justification <justification-file>`.

The output is a *proposal* — not enforced policy. Do not initiate or retry the action until the proposal has been evaluated and incorporated. Cedar validation against your schema happens at incorporation; if the fragment fails validation, the incorporation pipeline rejects it and you receive feedback.

## Constructing the justification

The justification is the narrative the evaluator (HITL, LLM-as-judge, or hybrid) reads to decide whether to incorporate the policy. It is a JSON object — structured for parsing, with prose values for human readability. The evaluator consumes it once, at proposal time, then it is logged for audit.

Required fields:

- **`rationale`** — short prose explaining why the expansion is needed. State what was being attempted and why.
- **`authorization_basis`** — the citable basis for the request (a task ID, user request ID, dispatching agent ID, role definition, or other identifier the evaluator can verify).
- **`scope_explanation`** — prose description of what the Cedar fragment expresses. The evaluator reads this to spot-check that the Cedar matches the agent's stated intent.
- **`time_bound`** — either a requested duration (e.g., `60 minutes`, `until task <ID> completes`) or the literal value `permanent` if the request is unbounded.
- **`sensitivity_factors`** — list of factors that raise the bar for evaluation (e.g., `PII`, `PRODUCTION_WRITE`, `REGULATORY_HIPAA`, `BLAST_RADIUS_HIGH`). Empty list if none.
- **`evidence`** — pointers the evaluator can verify: prior approval IDs, task references, audit log links, related policy decisions.

Example shape:

```json
{
  "rationale": "Investigating a cost spike on EC2; need read access to instance metadata to identify the source.",
  "authorization_basis": "task-2026-05-01-cost-investigation",
  "scope_explanation": "Read access to ec2:DescribeInstances scoped to instances in account 1234567890.",
  "time_bound": "until task-2026-05-01-cost-investigation completes",
  "sensitivity_factors": [],
  "evidence": ["audit-log://incidents/2026-05-01"]
}
```

[ORG: Add organization-specific fields. Examples: change-ticket reference, cost-center attribution, on-call signoff.]

### Discipline

- Do not submit a proposal without supplying every required justification field.
- Do not understate sensitivity. The evaluator's bar should match the actual risk.
- Do not paste the Cedar fragment into `scope_explanation`; describe the scope in prose.
- If you cannot fill `authorization_basis` with a citable identifier, you do not have enough information for a proposal. Stop and escalate conversationally.

## Constructing the Cedar fragment

The Cedar fragment is the formal policy. Once incorporated, it is evaluated by the enforcement layer on every request. It speaks in `principal`, `action`, `resource`, and `when`.

### Use the template

Start from `assets/template.cedar`. The template's default `when` clause includes a time gate, appropriate for time-bounded requests. For unbounded requests, replace the time gate with other context conditions (attestation, role, environment scoping, etc.). See `assets/cedar-syntax.md` for common `when`-clause patterns and Cedar idioms.

### Fill in the placeholders

Replace `<ANGLE_BRACKETED_PLACEHOLDERS>` with the values you captured in Step 1. The agent fills every placeholder *except* `<EXPIRATION_TIMESTAMP>`, which the incorporation pipeline fills at incorporation from the `time_bound` field of your justification.

### Discipline

- Scope to only the actions and resources the request needs. Broad scope is rejected on evaluation.
- Include a `when` clause. Even unbounded requests should have *some* condition narrowing the policy. A bare `permit` with no `when` is rarely the right answer.
- For time-bounded requests, do not fill `<EXPIRATION_TIMESTAMP>` with a guessed value. Leave it as a placeholder for the incorporation pipeline.

## Reasoning discipline

- Do not propose policy that grants more access than the immediate situation requires.
- Do not propose policy you cannot articulate a rationale for.
- If the situation is ambiguous, stop and escalate conversationally rather than guessing.
- If you have proposed policy and it has not yet been incorporated, do not initiate or retry the action. Wait.
