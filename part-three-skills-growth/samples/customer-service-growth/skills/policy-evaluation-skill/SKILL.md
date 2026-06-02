---
name: policy-evaluation-skill
description: Evaluation protocol for boundary-expansion proposals. Activate when asked to evaluate a Cedar policy fragment paired with a structured justification. Returns a structured verdict — approve or reject with reasoning — against six criteria covering scope, sensitivity, shape discipline, and Cedar correctness.
license: CC-BY-4.0
metadata:
  author: Michael Butler
  version: "0.2-skill-growth-poc"
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
- `authorization_basis` — a citable basis (task trajectory references, observed failure patterns, operational mandate, or user request)
- `scope_explanation` — prose description of what the Cedar fragment expresses
- `time_bound` — `"permanent"` (acceptable when guarded by a runtime condition) or a stated review period
- `sensitivity_factors` — a list (may not be empty for writes or PII operations; see Criterion 3)
- `evidence` — at least one pointer to the original request or context

Generic, placeholder, or empty values in any required field are grounds for rejection.

### Criterion 2 — Scope minimality

The Cedar fragment must grant only the access the rationale requires:

- **Action scope:** the fragment must name a single, specific action. Wildcards or multiple actions in one fragment are not permitted.
- **Resource scope:** the fragment must name the specific gateway. Wildcards in the `resource` field are invalid in the AgentCore Cedar dialect and are grounds for rejection.
- **Principal scope:** for IAM-authenticated gateways, the principal is scoped by `principal is AgentCore::IamEntity` in the policy head. No additional `principal.id like` constraint is required in the `when` clause for fleet-wide proposals where any authenticated caller should be permitted. If the proposal intends to restrict to a specific role, `principal.id like "<pattern>"` may be added — but its absence is not grounds for rejection when the justification explicitly states fleet-wide access.

If the Cedar fragment grants broader access than the justification requires, reject.

### Criterion 3 — Sensitivity-factor accuracy

The `sensitivity_factors` list must honestly represent the risk profile of the requested action:

- For read operations (e.g., `get_customer`, `get_order`): an empty or minimal sensitivity list is acceptable.
- For write operations or PII operations (e.g., `update_customer_field`, `process_refund`): `sensitivity_factors` must include at least one PII or write-classification factor such as `PII_WRITE`, `CUSTOMER_DATA`, or `FINANCIAL`. An empty `sensitivity_factors` list for any write or PII operation is grounds for rejection.

If the agent understates the sensitivity profile, reject.

### Criterion 4 — Cedar correctness

Assess the Cedar fragment against the AgentCore dialect rules:

- **Entity types:** principal must use `principal is AgentCore::IamEntity` in scope; action must use `AgentCore::Action::"<TARGET>___<TOOL>"` (triple underscore, matching the MCP tool name exactly); resource must use `AgentCore::Gateway::"<ARN_OR_PLACEHOLDER>"`.
- **Principal constraint (if present):** if the `when` clause constrains the principal, it must use `principal.id like "<pattern>"`, not `principal.id == "<pattern>"`. The `==` operator causes async activation failure. Omitting a `principal.id` constraint entirely is acceptable for fleet-wide proposals.
- **Gateway ARN:** the resource field must reference a specific gateway. The placeholder `<GATEWAY_ARN>` is acceptable — the incorporator substitutes it. A wildcard resource is not.
- **Time gate (if present):** must use `context.system.now <= datetime("<ISO-8601>")`. Bare string comparisons are not valid Cedar datetime operations.
- **Input conditions (if present):** must use `context.input has <field> && context.input.<field> == <value>` pattern. The `has` operator takes a **bare identifier** (no quotes): `context.input has customer_verified` is correct; `context.input has "customer_verified"` is a type mismatch that silently breaks evaluation.
- **Cedar↔justification match:** does `scope_explanation` accurately describe what the Cedar fragment expresses? The action, principal scope, and time bound (if present) in the Cedar must match the prose description in `scope_explanation`. A mismatch suggests the agent made an error constructing one or the other.

### Criterion 5 — Shape discipline

The proposal shape must match the operation type. This criterion has a hard rule that overrides all others:

- **Read operations** may use an unconditional permit (no `when` clause beyond `principal.id like`).
- **Write operations or PII operations** — specifically `update_customer_field`, `process_refund`, and any action that modifies customer data — **must** include a `when` clause with at least one runtime condition that gates execution (e.g., `context.input.customer_verified == true`). A conditional permit gated on runtime verification is safe to be permanent — the guard fires on every request.
- **Hard rule: an unconditional permit for a write operation on PII or financial data is always rejected**, regardless of all other criteria passing. This rule is not negotiable. "Unconditional" means no `context.input` condition in the `when` clause.
- Time gates (`datetime()`) are NOT required. Policy lifecycle (deprecation, renewal) is managed externally by the Curator, not by Cedar expiry.

### Criterion 6 — Authorization basis citability

`authorization_basis` must be traceable by a future auditor and must demonstrate **observed need**:

- **Required:** at least one task trajectory ID (e.g., `task-abc123`) where a customer requested the capability and the fleet failed to deliver. This is the primary evidence — without it, the proposal has no experiential basis and must be rejected.
- **Supplementary (acceptable but not sufficient alone):** Memory record IDs for reflections, gateway target IDs, existing policy references, or draft skill pointers. These provide context but do not demonstrate need.
- **Not acceptable:** generic strings like `"agent-request"`, `"unknown"`, or `"automated"` with no traceability. Also not acceptable: architectural inference ("this tool exists on the Gateway") without a corresponding episode of failed customer need.

The existence of a tool on the Gateway is not evidence that the fleet needs access to it. Asymmetry between read and write permissions is often deliberate. The evidentiary chain must terminate in lived experience — a real customer interaction where the capability was needed and absent.

## Output format

Return your verdict as a JSON object in a **single fenced code block**, with nothing after it:

```json
{"verdict": "APPROVE", "reason": "<one to three sentences explaining the decision>"}
```

or

```json
{"verdict": "REJECT", "reason": "<name the specific criterion that failed and what the agent would need to fix>"}
```

The `reason` field must be actionable. On rejection, name the criterion by number and explain specifically what failed. Vague rejections are not acceptable.

## Evaluation discipline

- Apply all six criteria before deciding. Do not approve on four passing criteria and skip the rest.
- Be willing to reject. The purpose of this evaluation is to catch proposals that are incorrect, overly broad, or dishonest about sensitivity. Rubber-stamping defeats the pipeline.
- On rejection, name the criterion. The constructing agent needs actionable feedback.
- Do not approve an unconditional PII write under any circumstances — this is the hard rule in Criterion 5. A *conditional* permit (gated on runtime verification) is acceptable even if permanent.
- When in doubt between approve and reject, reject and explain. The constructing agent can revise and resubmit.
