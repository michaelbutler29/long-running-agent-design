# Cedar Syntax Reference (lightweight)

A short reference on the Cedar syntax this skill uses when constructing expansion proposals. For the full Cedar specification, see [cedarpolicy.com](https://www.cedarpolicy.com/).

## Statement form

A Cedar policy is a `permit` or `forbid` statement followed by an optional `when` (or `unless`) clause:

```cedar
permit (
  principal == User::"alice",
  action == Action::"viewPhoto",
  resource == Photo::"vacation.jpg"
);

permit (
  principal,
  action,
  resource
)
when {
  principal.role == "admin"
};
```

## Scope: principal, action, resource

Each scope element can be unconstrained, equal to a specific entity, or `in` a set:

```cedar
principal                              // unconstrained
principal == User::"alice"             // specific entity
principal in Group::"admins"           // member of a set
action in [Action::"read", Action::"write"]
```

## when clauses

The `when` clause holds boolean conditions. All must be true for the policy to apply.

```cedar
when {
  context has attestation &&
  context.attestation.reason_code == "INVESTIGATION" &&
  context.system.now <= datetime("2026-12-31T23:59:59Z")
}
```

Common operators:

- `==`, `!=`, `<`, `<=`, `>`, `>=`
- `&&` (and), `||` (or), `!` (not)
- `in` (member of)
- `has` (record contains key)
- `like` (string pattern with `*`)

## Context access

The `context` is a record passed in the request. Access fields with `.`. Use `has` to check key presence before reading nested fields — accessing a missing key is a runtime error.

```cedar
context.environment
context has attestation && context.attestation.reason_code == "X"
```

## Datetime

The `datetime("...")` extension accepts ISO 8601 strings. Compare with the standard ordering operators.

```cedar
context.system.now <= datetime("2026-12-31T23:59:59Z")
```

## Common patterns for expansion proposals

### Time gate (bounded requests)

```cedar
when {
  context.system.now <= datetime("<EXPIRATION_TIMESTAMP>")
}
```

### Attestation gate

```cedar
when {
  context has attestation &&
  context.attestation.reason_code in ["<REASON_CODE_1>", "<REASON_CODE_2>"]
}
```

### Role gate

```cedar
when {
  principal.role == "<ROLE_NAME>"
}
```

### Environment scoping

```cedar
when {
  context.environment == "<ENVIRONMENT>"
}
```

### Combined conditions

```cedar
when {
  context.system.now <= datetime("<EXPIRATION_TIMESTAMP>") &&
  context has attestation &&
  context.attestation.reason_code in ["<REASON_CODE_1>", "<REASON_CODE_2>"]
}
```

## Common pitfalls

- A bare `permit` with no `when` clause is rarely correct. At minimum, narrow the principal/action/resource scope; ideally also include context conditions.
- `==` for principal/action/resource is a *scope* constraint inside the parentheses, not the `when` clause. Inside `when`, use record/value comparisons.
- Always guard nested `context` access with `has`.
- Use `in` for sets, `==` for single values.

## Validation

In Cedar, *validation* specifically means checking a policy against a schema — does the policy reference real entity types and actions, do conditions type-check, are optional attributes guarded with `has`. See [Cedar policy validation](https://docs.cedarpolicy.com/policies/validation.html). This is distinct from parsing (syntax checking).

Validation requires a schema; the agent constructing a proposal does not have one. Validation happens at incorporation, where the schema lives — the incorporation pipeline runs `cedar validate-policy` (or equivalent) and rejects fragments that fail. If your pipeline doesn't yet do schema-based validation, the [Cedar CLI](https://github.com/cedar-policy/cedar) and the `cedarpy` Python package both provide it.

## Alternative Cedar formats

This reference uses Cedar's DSL form throughout. Cedar also offers two facilities production deployments often prefer:

- **JSON policy format.** Every Cedar policy has an equivalent JSON representation, useful when policies are stored, transmitted, or constructed programmatically. See [Cedar JSON policy format](https://docs.cedarpolicy.com/policies/json-format.html).
- **Native templates with slots.** Cedar has a first-class template mechanism using `?principal` and `?resource` slots in scope positions, with template linking at policy-creation time. Slots cover scope positions only — not `action`, not `when`-clause conditions. See [Cedar templates](https://docs.cedarpolicy.com/policies/templates.html).

This artifact uses DSL syntax and `<ANGLE_BRACKETED>` placeholders throughout — including in scope positions where native slots could otherwise apply — for readability and writing fluency. Adapt your fork to the formats that match your deployment.
