---
name: policy-evaluation-skill
description: Evaluation protocol for boundary-expansion proposals. Activate when asked to evaluate a Cedar policy fragment paired with a structured justification. Returns a structured verdict — approve or reject with reasoning — against six criteria covering scope, sensitivity, shape discipline, and Cedar correctness.
license: CC-BY-4.0
metadata:
  author: Michael Butler
  version: "0.1-customer-service-assistant"
  dialect: aws-agentcore
---

# Policy Evaluation Skill (AWS AgentCore dialect)

This skill provides the evaluation protocol for boundary-expansion proposals. A proposal consists of a Cedar policy fragment and a structured justification. Evaluate both against the criteria below and return a verdict.

## Activation conditions

Activate this skill when:

- You are asked to evaluate a policy proposal (Cedar fragment + structured justification).
- A policy-generator skill has produced a proposal and your role is to judge it.

## What this skill does and does not do

**Does:**
- Provides evaluation criteria for Cedar policy proposals in the AgentCore dialect.
- Guides structured reasoning toward a clear approve or reject decision.
- Requires all criteria to pass before approving — any single failure is grounds for rejection.

**Does not:**
- Create policies. That is the incorporator's responsibility.
- Validate Cedar syntax programmatically. You assess the fragment for correctness against the AgentCore dialect rules described in *Criterion 4* below.
- Grant exceptions. No criterion may be waived, regardless of passing criteria elsewhere.

## Evaluation criteria

A proposal must pass all six criteria to be approved.

### Criterion 1 — Justification completeness

All required justification fields must be present and meaningfully populated:

- `rationale` — non-empty prose explaining why the expansion is needed
- `authorization_basis` — a citable basis (user request, session ID, agent role)
- `scope_explanation` — prose description of what the Cedar fragment expresses
- `time_bound` — either `"permanent"` or a valid ISO-8601 datetime string
- `sensitivity_factors` — a list (may not be empty for writes or PII operations; see Criterion 3)
- `evidence` — at least one pointer to the original request or context

Generic, placeholder, or empty values in any required field are grounds for rejection.

### Criterion 2 — Scope minimality

The Cedar fragment must grant only the access the rationale requires:

- **Action scope:** the fragment must name a single, specific action. Wildcards or multiple actions in one fragment are not permitted.
- **Resource scope:** the fragment must name the specific gateway. Wildcards in the `resource` field are invalid in the AgentCore Cedar dialect and are grounds for rejection.
- **Principal scope:** the `when` clause must constrain the principal to a specific IAM ARN using `principal.id like "<arn>"`.

If the Cedar fragment grants broader access than the justification requires, reject.

### Criterion 3 — Sensitivity-factor accuracy

The `sensitivity_factors` list must honestly represent the risk profile of the requested action:

- For read operations (e.g., `get_order_status`, `get_customer_basics`): at minimum include a read-classification factor such as `ORDER_DATA_READ`. An empty list for a low-sensitivity read is a weak signal but acceptable.
- For write operations or PII operations (e.g., `update_customer_email`, any action that modifies customer data): `sensitivity_factors` must include at least one PII or write-classification factor such as `PII_WRITE` or `CUSTOMER_EMAIL`. An empty `sensitivity_factors` list for any write or PII operation is grounds for rejection.

If the agent understates the sensitivity profile, reject.

### Criterion 4 — Cedar correctness

Assess the Cedar fragment against the AgentCore dialect rules:

- **Entity types:** principal must use `principal is AgentCore::IamEntity` in scope; action must use `AgentCore::Action::"<TARGET>___<TOOL>"` (triple underscore, matching the MCP tool name exactly); resource must use `AgentCore::Gateway::"<ARN_OR_PLACEHOLDER>"`.
- **Principal constraint:** `when` clause must use `principal.id like "<arn>"`, not `principal.id == "<arn>"`. The `==` operator causes async activation failure.
- **Gateway ARN:** the resource field must reference a specific gateway. The placeholder `<GATEWAY_ARN>` is acceptable — the incorporator substitutes it. A wildcard resource is not.
- **Cedar↔justification match:** does `scope_explanation` accurately describe what the Cedar fragment expresses? The action, principal constraint, and time bound (if present) in the Cedar must match the prose description in `scope_explanation`. A mismatch suggests the agent made an error constructing one or the other.

### Criterion 5 — Shape discipline

The proposal shape must match the operation type. This criterion has a hard rule that overrides all others:

- **Read operations** may use the permanent shape: `time_bound` is `"permanent"`, no `context.system.now` condition in the Cedar `when` clause.
- **PII writes or sensitive operations** — specifically `update_customer_email` and any action that modifies customer data — **must** use the time-bounded shape: `time_bound` is an ISO-8601 datetime, and the Cedar `when` clause includes `context.system.now <= datetime(...)`.
- **Hard rule: a permanent grant for a PII write is always rejected**, regardless of all other criteria passing. This rule is not negotiable.
- A time-bounded grant for a read-only operation is technically acceptable but note the conservatism in your reasoning.

### Criterion 6 — Authorization basis citability

`authorization_basis` must be traceable by a future auditor:

- Acceptable: a reference to the specific user request, a session identifier, the agent's defined operational role (e.g., `"customer-service-agent-role"`).
- Not acceptable: generic strings like `"agent-request"`, `"unknown"`, or `"automated"` with no traceability.

## Output format

Return your verdict as a JSON object in a **single fenced code block**, with nothing after it:

```json
{"verdict": "approve", "reason": "<one to three sentences explaining the decision>"}
```

or

```json
{"verdict": "reject", "reason": "<name the specific criterion that failed and what the agent would need to fix>"}
```

The `reason` field must be actionable. On rejection, name the criterion by number and explain specifically what failed. Vague rejections are not acceptable.

## Evaluation discipline

- Apply all six criteria before deciding. Do not approve on four passing criteria and skip the rest.
- Be willing to reject. The purpose of this evaluation is to catch proposals that are incorrect, overly broad, or dishonest about sensitivity. Rubber-stamping defeats the pipeline.
- On rejection, name the criterion. The doer needs actionable feedback.
- Do not approve a permanent PII write under any circumstances — this is the hard rule in Criterion 5.
- When in doubt between approve and reject, reject and explain. The doer can revise and resubmit.
