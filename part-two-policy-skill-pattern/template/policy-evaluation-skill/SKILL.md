---
name: policy-evaluation-skill
description: Evaluation protocol for boundary-expansion proposals. Activate when asked to evaluate a Cedar policy fragment paired with a structured justification. Returns a structured verdict — approve or reject with reasoning — against six criteria covering scope, sensitivity, shape discipline, and Cedar correctness.
license: CC-BY-4.0
metadata:
  author: Michael Butler
  version: "1.0"
---

# Policy Evaluation Skill

This skill provides the evaluation protocol for boundary-expansion proposals. A proposal consists of a Cedar policy fragment and a structured justification. Evaluate both against the criteria below and return a verdict.

## Activation conditions

Activate this skill when:

- You are asked to evaluate a policy proposal (Cedar fragment + structured justification).
- A policy-generator skill has produced a proposal and your role is to judge it.

## What this skill does and does not do

**Does:**
- Provides evaluation criteria for Cedar policy proposals.
- Guides structured reasoning toward a clear approve or reject decision.
- Requires all criteria to pass before approving — any single failure is grounds for rejection.

**Does not:**
- Create policies. That is the incorporator's responsibility.
- Validate Cedar syntax programmatically. You assess the fragment for correctness against the dialect rules described in *Criterion 4* below.
- Grant exceptions. No criterion may be waived, regardless of passing criteria elsewhere.

## Design principles

This evaluation protocol is grounded in the principle of least privilege and the AWS Well-Architected GenAI Lens GENSEC05-BP01 guidance:

- **Least privilege.** Grant only the minimum permissions required for the immediate task. Reject proposals that are broader than the stated need.
- **Excessive agency prevention.** An agent requesting its own boundary expansion is an inherent conflict of interest. The evaluator exists to provide independent judgment — do not rubber-stamp.
- **Permissions boundaries.** Time-bounded grants are preferred for sensitive operations. Permanent grants require stronger justification and lower sensitivity profiles.

[ORG: Adapt these principles to your organization's risk appetite and compliance requirements. Add references to your specific governance frameworks.]

## Evaluation criteria

A proposal must pass all six criteria to be approved.

### Criterion 1 — Justification completeness

All required justification fields must be present and meaningfully populated:

- `rationale` — non-empty prose explaining why the expansion is needed
- `authorization_basis` — a citable basis (user request, session ID, agent role)
- `scope_explanation` — prose description of what the Cedar fragment expresses
- `time_bound` — either `"permanent"` or a valid ISO-8601 datetime string
- `sensitivity_factors` — a list (may not be empty for writes or sensitive operations; see Criterion 3)
- `evidence` — at least one pointer to the original request or context

Generic, placeholder, or empty values in any required field are grounds for rejection.

[ORG: Add organization-specific required fields here. Examples: change-ticket reference, cost-center attribution, on-call signoff, compliance-framework tag.]

### Criterion 2 — Scope minimality

The Cedar fragment must grant only the access the rationale requires:

- **Action scope:** the fragment must name a single, specific action. Wildcards or multiple actions in one fragment are not permitted.
- **Resource scope:** the fragment must name a specific resource. Wildcards in the `resource` field are grounds for rejection.
- **Principal scope:** the `when` clause must constrain the principal to a specific identity.

If the Cedar fragment grants broader access than the justification describes, reject.

[ORG: Define your organization's scope rules. Some environments allow action sets for tightly-coupled operations; others require one-action-per-policy strictly.]

### Criterion 3 — Sensitivity-factor accuracy

The `sensitivity_factors` list must honestly represent the risk profile of the requested action:

- For read operations on non-sensitive data: an empty or minimal sensitivity list is acceptable.
- For write operations, PII operations, or actions affecting production state: `sensitivity_factors` must include at least one relevant classification (e.g., `PII_WRITE`, `PRODUCTION_WRITE`, `FINANCIAL_DATA`). An empty list for a sensitive operation is grounds for rejection.

If the agent understates the sensitivity profile, reject. The evaluator exists precisely to catch understatement — an agent requesting its own boundary expansion has an incentive to minimize perceived risk.

[ORG: Define your sensitivity taxonomy. Map actions in your domain to required sensitivity factors. Examples: HIPAA data, SOX-relevant operations, customer PII, infrastructure mutations.]

### Criterion 4 — Cedar correctness

Assess the Cedar fragment against the dialect rules for your enforcement layer:

- **Entity types:** principal, action, and resource must use the correct entity types for your dialect.
- **Principal constraint:** the `when` clause must constrain the principal appropriately. The enforcement layer's documentation defines which operators are valid.
- **Resource specificity:** the resource must reference a specific endpoint or resource; wildcards or overly broad patterns are not acceptable.
- **Cedar↔justification match:** does `scope_explanation` accurately describe what the Cedar fragment expresses? The action, principal constraint, and time bound (if present) in the Cedar must match the prose description. A mismatch suggests the agent made an error constructing one or the other.

[ORG: Fill in your dialect's entity types, operator requirements, and structural rules. Examples: AgentCore uses `principal is AgentCore::IamEntity` + `principal.id like`; OPA uses different constructs entirely.]

### Criterion 5 — Shape discipline

The proposal shape must match the operation type:

- **Read operations or low-sensitivity utilities** may use the permanent shape: `time_bound` is `"permanent"`, no datetime condition in the Cedar `when` clause.
- **Write operations, PII operations, or sensitive actions** must use the time-bounded shape: `time_bound` is an ISO-8601 datetime, and the Cedar `when` clause includes a time gate.
- **Hard rule: a permanent grant for a sensitive write is always rejected**, regardless of all other criteria passing. This rule is not negotiable.
- A time-bounded grant for a read-only operation is technically acceptable (conservative, not incorrect).

This criterion enforces the principle of least privilege temporally. A permanent PII write grant means the agent retains that access forever — well past the specific user request that motivated it. The GENSEC05-BP01 guidance on permissions boundaries applies here: scope access not just to the minimum action but to the minimum duration.

[ORG: Define your organization's shape rules. Which operations require time-bounding? What maximum duration is acceptable? Examples: "all production writes must be time-bounded to 60 minutes", "PII access expires after task completion".]

### Criterion 6 — Authorization basis citability

`authorization_basis` must be traceable by a future auditor:

- Acceptable: a reference to a specific user request, a session identifier, a task ID, the agent's defined operational role with a specific mandate.
- Not acceptable: generic strings like `"agent-request"`, `"unknown"`, or `"automated"` with no traceability.

The authorization basis is the audit trail. If an auditor cannot trace from the incorporated policy back to the request that motivated it, the governance chain is broken.

[ORG: Define what constitutes an acceptable authorization basis in your environment. Examples: JIRA ticket ID, PagerDuty incident ID, specific user session reference.]

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
- On rejection, name the criterion. The constructing agent needs actionable feedback.
- Do not approve a permanent grant for a sensitive write under any circumstances — this is the hard rule in Criterion 5.
- When in doubt between approve and reject, reject and explain. The constructing agent can revise and resubmit.
- Remember: the agent that constructed this proposal is also the agent that benefits from its approval. Independent judgment is your function.
