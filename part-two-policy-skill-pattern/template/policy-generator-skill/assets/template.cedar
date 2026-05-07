// template.cedar
//
// Boundary expansion policy fragment. Permits a scoped action.
//
// Required placeholders (AGENT-filled at proposal time):
//   <PRINCIPAL_ID>      the agent or role gaining expanded permission
//   <ACTION>            the specific action permitted
//   <RESOURCE_TYPE>     the entity type of the targeted resource
//   <RESOURCE_ID>       the specific resource ID (or pattern)
//
// Optional placeholder (INCORPORATION PIPELINE-filled at incorporation,
// only for time-bounded requests):
//   <EXPIRATION_TIMESTAMP>
//
// The when clause below shows the time gate as the default shape:
//   - For UNBOUNDED requests: replace the context.system.now line with other
//     context conditions (attestation, role, environment, etc.).
//   - To ADD conditions: combine with && inside the when clause.
//
// See assets/cedar-syntax.md for common when-clause patterns and
// general Cedar idioms.

permit (
  principal == Agent::"<PRINCIPAL_ID>",
  action == Action::"<ACTION>",
  resource == <RESOURCE_TYPE>::"<RESOURCE_ID>"
)
when {
  context.system.now <= datetime("<EXPIRATION_TIMESTAMP>")
};

// [ORG: Add organization-specific when-clause patterns or examples
// below. Examples: change-ticket reference checks, blast-radius
// caps, audit-hook flags, supervisor-agent ID requirements.]
