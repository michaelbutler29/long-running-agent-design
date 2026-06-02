# Cedar Patterns for This POC

When constructing permission proposals, use EXACTLY these patterns. The Policy Engine validates Cedar against the AgentCore schema — incorrect entity types or operators will cause creation failure.

## AgentCore Cedar dialect rules

- **Principal:** `principal is AgentCore::IamEntity` in the scope. Use `principal.id like "<ARN_PATTERN>"` in the `when` clause. Use `like`, NOT `==` (equals causes async creation failure).
- **Action:** `AgentCore::Action::"<TargetName>___<tool_name>"` (three underscores between target and tool).
- **Resource:** `AgentCore::Gateway::"<GATEWAY_ARN>"` — use literal placeholder `<GATEWAY_ARN>`; the propose_permission tool substitutes the real ARN.

## Tool names in this POC

| Target Name | Tool Name | Cedar Action String |
|---|---|---|
| GetCustomer | get_customer | `AgentCore::Action::"GetCustomer___get_customer"` |
| GetOrder | get_order | `AgentCore::Action::"GetOrder___get_order"` |
| VerifyIdentity | verify_identity | `AgentCore::Action::"VerifyIdentity___verify_identity"` |
| UpdateCustomer | update_customer_field | `AgentCore::Action::"UpdateCustomer___update_customer_field"` |
| CheckRefund | check_refund_eligibility | `AgentCore::Action::"CheckRefund___check_refund_eligibility"` |
| ProcessRefund | process_refund | `AgentCore::Action::"ProcessRefund___process_refund"` |

## Shape 1: Unconditional permit (read-only / utility tools)

```cedar
permit (
  principal is AgentCore::IamEntity,
  action    == AgentCore::Action::"<TargetName>___<tool_name>",
  resource  == AgentCore::Gateway::"<GATEWAY_ARN>"
);
```

## Shape 2: Conditional permit (PII writes — gated on runtime verification)

The `when` clause is the protection, not a clock. A conditional permit gated on runtime verification is safe to be permanent — the guard fires on every request.

```cedar
permit (
  principal is AgentCore::IamEntity,
  action    == AgentCore::Action::"UpdateCustomer___update_customer_field",
  resource  == AgentCore::Gateway::"<GATEWAY_ARN>"
)
when {
  context.input has customer_verified && context.input.customer_verified == true
};
```

## Shape 3: Conditional permit with dual condition (financial writes)

```cedar
permit (
  principal is AgentCore::IamEntity,
  action    == AgentCore::Action::"ProcessRefund___process_refund",
  resource  == AgentCore::Gateway::"<GATEWAY_ARN>"
)
when {
  context.input has customer_verified && context.input.customer_verified == true &&
  context.input has refund_eligible && context.input.refund_eligible == true
};
```

## Rules

- **Use `like`, not `==` for principal.id** when you need principal matching. Equals causes async policy creation failure.
- **Omit `principal.id` constraints when all fleet callers should be allowed.** Don't add `principal.id like "*"` — it's redundant and adds noise.
- **Use `context.input` to access tool call arguments.** Always check field existence with `has` before accessing values.
- **The `has` operator takes a BARE identifier, never a quoted string.** Correct: `context.input has customer_verified`. WRONG: `context.input has "customer_verified"`. Quoted field names cause a type mismatch that silently breaks policy evaluation.
- **Do NOT use time gates (`datetime()`) in Cedar for this POC.** The conditional `when` clause (verification flag) is the protection. Temporal policy lifecycle is managed externally by the Curator (deprecation, not Cedar expiry).
- **Do NOT invent entity types.** Only `AgentCore::IamEntity`, `AgentCore::Action::`, and `AgentCore::Gateway::` are valid.
- **Always use `<GATEWAY_ARN>` as the resource placeholder.** The propose_permission tool substitutes the real ARN.
- **Hard rule: unconditional permits for write tools (no `when` clause) are always rejected by the Security Adjudicator.** Every write tool must have at least one runtime condition.
