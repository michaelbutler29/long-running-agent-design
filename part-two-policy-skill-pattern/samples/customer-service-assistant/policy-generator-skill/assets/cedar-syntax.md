# Cedar Syntax Reference — AWS AgentCore dialect

*AgentCore-specific additions to the generic [`cedar-syntax.md`](../../../../template/policy-generator-skill/assets/cedar-syntax.md). The generic reference applies here verbatim; the notes below cover AgentCore dialect differences.*

## AgentCore-specific entity types

AgentCore Gateway constructs Cedar authorization requests with these entity types. Use them in the scope of any policy fragment for this dialect:

- `AgentCore::IamEntity` — IAM-authenticated callers (SigV4-signed requests). Use for this sample. In policy scope: `principal is AgentCore::IamEntity`. In `when` clause: `principal.id like "<iam-arn>"`. **Use `like`, not `==`** — `==` on `principal.id` passes synchronous schema validation but fails async backend activation, leaving the policy in "Create failed" status.
- `AgentCore::OAuthUser` — OAuth/JWT-authenticated callers. Not used in this sample.
- `AgentCore::Action::"<TARGET_NAME>___<TOOL_NAME>"` — the gateway-mediated tool, joined by **triple** underscore. This is identical to the MCP `tools/call` name.
- `AgentCore::Gateway::"<gateway-arn>"` — the gateway instance. Must be a specific ARN; wildcards are rejected.

## Context shape

The `context` exposed to Cedar conditions has two top-level keys:

- `context.input` — the tool call arguments (the MCP `params.arguments` object)
- `context.system.now` — the current UTC timestamp, injected by the policy engine at evaluation time

Use `context.system.now` for time-bounded conditions:

```cedar
when {
  principal.id like "<IAM_PRINCIPAL_ARN>" &&
  context.system.now <= datetime("<EXPIRATION_TIMESTAMP>")
}
```

**Note:** `context.now` is not a valid attribute — the timestamp lives under `context.system.now`. Using `context.now` causes a CREATE_FAILED status at async activation time (not a synchronous schema error).

`context.input` can constrain on tool arguments:

```cedar
permit (...)
when { context.input.amount < 1000 };
```

Always guard nested access with `has`:

```cedar
when { context has input && context.input has amount && context.input.amount < 1000 };
```

## Wildcard restriction

Cedar policies on AgentCore Gateway may not use wildcards in the `resource` field. Each policy must name a specific gateway ARN. This is why our incorporation pipeline substitutes `<GATEWAY_ARN>` at policy-creation time rather than letting the agent fill it.

## Validation behavior at incorporation

`bedrock-agentcore-control.create_policy()` accepts a `validationMode`:

- `FAIL_ON_ANY_FINDINGS` — rejects on any schema or semantic finding (Cedar's automated reasoner produces semantic findings for things like overly-permissive grants).
- `IGNORE_ALL_FINDINGS` — ignores semantic findings; schema validation still runs as a hard backstop.

This sample uses `FAIL_ON_ANY_FINDINGS`. The LLM-as-judge evaluates semantic intent (scope minimality, sensitivity rubric, shape discipline, Cedar↔justification consistency). `FAIL_ON_ANY_FINDINGS` provides a second independent gate: AgentCore's reasoner catches structural Cedar issues — wrong entity types, undefined actions, missing `has` guards — that the judge may not catch. Two independent evaluators: intent at the judge, structure at the incorporator. If `FAIL_ON_ANY_FINDINGS` rejects a judge-approved fragment, surface the error to the actor agent — the Cedar needs to be revised and resubmitted.

## See also

For Cedar idioms (operators, `when`-clause patterns, JSON format, native templates), see the template's [`cedar-syntax.md`](../../../../template/policy-generator-skill/assets/cedar-syntax.md). It is generic-Cedar and applies here verbatim. The AgentCore-specific notes above are additions, not replacements.
