---
name: policy-generator-skill
description: Generates paired policy proposals (a Cedar fragment plus a structured justification) when an agent hits a permission boundary it cannot proceed past. Activate when an AgentCore Gateway tool call returns AuthorizeActionException, or when you recognize that a planned tool call will be denied.
license: CC-BY-4.0
metadata:
  author: Michael Butler
  version: "0.1-customer-service-assistant"
  forked_from: ../../template/policy-generator-skill/SKILL.md
  dialect: aws-agentcore
---

> **Fork note.** This SKILL.md is a populated fork of [`../../template/policy-generator-skill/SKILL.md`](../../template/policy-generator-skill/SKILL.md). It adapts the generic shape to the AWS AgentCore Cedar dialect — entity types, action-name format, principal-id operator, time-attribute path — and fills in customer-service-specific scenarios. The template's structure (activation contract, two-part proposal, reasoning workflow) is preserved.

# Policy Generator Skill (AWS AgentCore dialect)

This skill produces paired policy proposals — a Cedar fragment plus a structured justification — when an agent hits a permission boundary on AWS AgentCore Gateway.

## Activation conditions

Activate this skill when:

- A tool call through AgentCore Gateway returns an error containing `Tool Execution Denied` or `AuthorizeActionException`. This is the AgentCore Policy Engine's deny signal. It may appear as a JSON-RPC error message or as an `isError: true` MCP content response depending on how the transport layer surfaces it.
- You need to fulfill a user request but no matching tool appears in your current toolset. Under ENFORCE mode the gateway hides tools you are not yet permitted to use — absence from the toolset is a permission boundary, not evidence the tool doesn't exist.
- You recognize that a planned tool call will be denied because no current permit covers it.
- You lack the authorization to proceed and need to request expanded boundaries.

## Before proceeding

Confirm you can articulate both:

- **What** scope you would need — principal, action, resource, and whether time-bounded is appropriate.
- **Why** the expansion is justified — citable basis, evidence, sensitivity factors.

If you cannot articulate both, do not proceed. Stop and surface the situation to the user at the conversation level.

## What this skill does and does not do

**Does:**

- Helps you construct a structured justification for a boundary expansion.
- Helps you construct a well-formed Cedar policy fragment in the AgentCore dialect.
- Submits the paired proposal via the `submit_proposal` tool to the policy evaluator agent (LLM-as-judge → `bedrock-agentcore-control.create_policy`).

**Does not:**

- Evaluate proposals. Evaluation is the LLM-as-judge in `policy_evaluator_agent/judge.py`.
- Incorporate proposals. Incorporation is a private method within the actor agent invoked upon policy approval.
- Drive the underlying tool call. Initiate or retry only after `submit_proposal` returns success.
- Bypass, override, or work around the Policy Engine.
- Handle the case where you cannot articulate a proposal. That is conversational escalation, outside this skill.

## Reasoning workflow

### Step 0. Confirm the capability exists

If you activated this skill because a tool is absent from your toolset (rather than
because a call returned an explicit deny error), consult [`assets/TOOL-DEFS.md`](assets/TOOL-DEFS.md)
before proceeding.

- Locate the capability the user needs in the registry.
- Record the exact **action name** (triple-underscore form) — you will need it for the Cedar fragment.
- If the capability is **not listed**, stop. Surface the situation to the user; do not propose policy for an unregistered tool.

If you activated because of an explicit deny error, you already have the action name from the error — skip to Step 1.

### Step 1. Identify what was denied

From the `AuthorizeActionException` response and the user's request, capture:

- **Principal** — your IAM ARN. Call `get_agent_identity` to retrieve it. In Cedar: `principal is AgentCore::IamEntity` in the policy scope; `principal.id like "<IAM_PRINCIPAL_ARN>"` in the `when` clause.
- **Action** — the specific Gateway-mediated tool: `AgentCore::Action::"<TARGET_NAME>___<TOOL_NAME>"`. Triple underscore between target name and tool name — identical to the MCP tool name in the error.
- **Resource** — the Gateway instance: `AgentCore::Gateway::"<GATEWAY_ARN>"`. **Do not fill in a real ARN** — leave the literal placeholder `<GATEWAY_ARN>`. The incorporation pipeline substitutes it at policy-creation time.
- **Deny rationale** — extracted from the `AuthorizeActionException` text.
- **Contextual reason** — what the user asked for, what task you were executing.

If you cannot articulate any of these, stop.

### Step 2. Determine the expansion shape

This sample has two proposal shapes:

**Permanent (no time bound)** — for read access that should always be available once granted. Use for `get_order_status`. Include a `when` clause with only the `principal.id like` condition — no datetime condition.

**Time-bounded elevation** — for writes or sensitive operations where access should expire. Use for `update_customer_email`. Include a `when` clause with a short expiration (30 minutes is appropriate for a PII write in a single session).

For time-bounded proposals: call `get_current_utc_time` to get the current time, then add 30 minutes to compute the expiration timestamp. Use that value in both the Cedar `when` clause and the `time_bound` justification field. Do not use a hardcoded or example timestamp.

Choose the shape before constructing the proposal. If the situation is ambiguous, default to time-bounded and explain why in `scope_explanation`.

### Step 3. Construct the proposal

Every proposal has two parts: a Cedar policy fragment and a structured justification. Both are required.

- **Cedar fragment** — start from `assets/template.cedar`. See *Constructing the Cedar fragment* below.
- **Justification** — see *Constructing the justification* below.

Pass both directly to the `submit_proposal` tool in Step 4.

### Step 4. Submit and follow up

```
submit_proposal(
    cedar="<the complete Cedar fragment text>",
    justification="<the justification JSON string>"
)
```

The call blocks until the judge evaluates and (if approved) the incorporator creates the policy.

**On approval:**

1. Call `refresh_gateway_tools` — this re-fetches the tool list from the gateway so the newly-permitted tool becomes available.
2. Call the tool normally to fulfill the user's original request.

The user's original request is sufficient authorization to execute immediately on approval. Do not pause for additional confirmation — the user already asked.

**On rejection or error:** the response explains why. Read the feedback. Do not resubmit the same proposal unchanged — revise based on the stated criterion failure, or surface the situation to the user.

## Constructing the justification

The justification is the narrative the LLM-as-judge reads. It is a JSON object.

Required fields:

- **`rationale`** — short prose explaining why the expansion is needed.
- **`authorization_basis`** — the citable basis (the user's request, a session ID, the agent's defined role).
- **`scope_explanation`** — prose description of what the Cedar fragment expresses. The judge reads this to spot-check that the Cedar matches stated intent.
- **`time_bound`** — `"permanent"` for read expansions; an ISO-8601 datetime string for time-bounded elevation. Compute this from `get_current_utc_time` + 30 minutes — do not use a hardcoded or example value.
- **`sensitivity_factors`** — list. Do not understate. Examples: `["ORDER_DATA_READ"]` for order status; `["PII_WRITE", "CUSTOMER_EMAIL"]` for email update.
- **`evidence`** — pointers the judge can verify: the original user request, session references.

Optional:

- **`gateway_arn`** — the gateway ARN this proposal targets. The judge sanity-checks the Cedar resource matches the configured gateway.

Example shape (time-bounded PII write):

```json
{
  "rationale": "User requested an email update for CUST-001. The update_customer_email tool modifies PII and requires elevated authorization. Requesting a 30-minute window for this session.",
  "authorization_basis": "user-session-request",
  "scope_explanation": "Permits the local IAM principal to call CustomerEmail___update_customer_email on the configured gateway for 30 minutes from the time of this request.",
  "time_bound": "<call get_current_utc_time() and add 30 minutes>",
  "sensitivity_factors": ["PII_WRITE", "CUSTOMER_EMAIL"],
  "evidence": ["original user message: 'Update the email for CUST-001 to alice.new@example.com'"],
  "gateway_arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:gateway/<gateway-id>"
}
```

### Discipline

- Do not submit without every required field.
- Do not understate `sensitivity_factors`. An empty list for a PII write is grounds for rejection.
- Do not paste the Cedar fragment into `scope_explanation`; describe in prose.
- Set `time_bound` to an appropriate expiry, not an arbitrarily long window. 30 minutes is appropriate for a single-session PII write.

## Constructing the Cedar fragment

Start from [`assets/template.cedar`](assets/template.cedar). Replace placeholders with values from Step 1. Leave `<GATEWAY_ARN>` as a literal placeholder.

For **permanent** grants, include the `when` clause with only the `principal.id` condition:

```cedar
permit (
  principal is AgentCore::IamEntity,
  action == AgentCore::Action::"<TARGET_NAME>___<TOOL_NAME>",
  resource == AgentCore::Gateway::"<GATEWAY_ARN>"
)
when {
  principal.id like "<IAM_PRINCIPAL_ARN>"
};
```

For **time-bounded** grants, add the datetime condition:

```cedar
permit (
  principal is AgentCore::IamEntity,
  action == AgentCore::Action::"<TARGET_NAME>___<TOOL_NAME>",
  resource == AgentCore::Gateway::"<GATEWAY_ARN>"
)
when {
  principal.id like "<IAM_PRINCIPAL_ARN>" &&
  context.system.now <= datetime("<EXPIRATION_TIMESTAMP>")
};
```

See [`assets/cedar-syntax.md`](assets/cedar-syntax.md) for AgentCore-specific entity types and Cedar idioms.

### Discipline

- Scope to the specific action and resource the request needs.
- Cedar policies on AgentCore must reference a specific gateway ARN — wildcards are rejected. Use `<GATEWAY_ARN>`.
- For time-bounded grants, always include the `when` clause. Never propose a permanent grant for a sensitive write.

## Reasoning discipline

- Do not propose policy that grants more access than the immediate situation requires.
- Do not propose policy you cannot articulate a rationale for.
- If the situation is ambiguous, stop and surface to the user rather than guessing.
- If you have submitted a proposal and `submit_proposal` has not returned, do not retry the action. Wait.
- If `submit_proposal` returns failure, do not retry the action. Surface the failure to the user.
