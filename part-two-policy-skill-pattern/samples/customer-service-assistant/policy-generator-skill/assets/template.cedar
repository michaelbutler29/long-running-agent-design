// template.cedar — AWS AgentCore dialect
//
// Boundary expansion policy fragment for AgentCore Gateway. Two shapes:
//
//   PERMANENT (read / utility access — principal.id condition only):
//
//     permit (
//       principal is AgentCore::IamEntity,
//       action    == AgentCore::Action::"<TARGET_NAME>___<TOOL_NAME>",
//       resource  == AgentCore::Gateway::"<GATEWAY_ARN>"
//     )
//     when {
//       principal.id like "<IAM_PRINCIPAL_ARN>"
//     };
//
//   TIME-BOUNDED (sensitive writes / PII — add datetime condition):
//
//     permit (
//       principal is AgentCore::IamEntity,
//       action    == AgentCore::Action::"<TARGET_NAME>___<TOOL_NAME>",
//       resource  == AgentCore::Gateway::"<GATEWAY_ARN>"
//     )
//     when {
//       principal.id like "<IAM_PRINCIPAL_ARN>" &&
//       context.system.now <= datetime("<EXPIRATION_TIMESTAMP>")
//     };
//
// Required placeholders (AGENT-filled at proposal time):
//   <IAM_PRINCIPAL_ARN>     the caller's full IAM ARN (from get_agent_identity)
//   <TARGET_NAME>           the gateway target name (e.g., OrderStatus)
//   <TOOL_NAME>             the specific tool on that target (e.g., get_order_status)
//   <EXPIRATION_TIMESTAMP>  ISO-8601 datetime for time-bounded grants (e.g., 2026-05-02T15:30:00Z)
//
// Required placeholder (INCORPORATION PIPELINE-filled at policy-creation time):
//   <GATEWAY_ARN>           the configured AgentCore Gateway ARN
//
// AgentCore dialect notes:
//   - principal: `principal is AgentCore::IamEntity` in scope; `principal.id like "<arn>"` in when
//   - action: triple underscore between target and tool — <TARGET_NAME>___<TOOL_NAME>
//   - resource: MUST be a specific gateway ARN; wildcards are rejected
//   - principal.id requires `like`, not `==` (== causes async creation failure)
//
// This sample's scenarios:
//   - get_order_status      → PERMANENT (read, principal.id condition only)
//   - update_customer_email → TIME-BOUNDED (PII write, 30-minute window)

permit (
  principal is AgentCore::IamEntity,
  action    == AgentCore::Action::"<TARGET_NAME>___<TOOL_NAME>",
  resource  == AgentCore::Gateway::"<GATEWAY_ARN>"
)
when {
  principal.id like "<IAM_PRINCIPAL_ARN>" &&
  context.system.now <= datetime("<EXPIRATION_TIMESTAMP>")
};
