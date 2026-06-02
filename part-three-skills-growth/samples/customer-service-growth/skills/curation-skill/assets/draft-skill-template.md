---
name: <lowercase-with-hyphens>
description: <One sentence: what this skill does and when to use it.>
license: CC-BY-4.0
metadata:
  author: <curator-agent-id>
  version: "1.0"
  domain: <domain>
  extracted_from: <trajectory-id>
---

# <Skill Name>

<One paragraph describing the skill's purpose and the class of tasks it serves.>

## Activation conditions

Activate this skill when:

- <Condition 1 — what task pattern triggers this skill?>
- <Condition 2>
- <Condition 3 (optional)>

## Before proceeding

Confirm:

- <Precondition 1 — what must be true before following this procedure?>
- <Precondition 2>

## Procedure

1. <Step 1 — concrete, actionable, no ambiguity.>
2. <Step 2>
3. <Step 3>
4. <Step 4>
5. <Step 5 (as many steps as needed)>

## Failure modes

- **<Failure type 1>:** <What to do. Be specific: retry? escalate? report?>
- **<Failure type 2>:** <What to do.>
- **<Failure type 3>:** <What to do.>

## Permission context

<If this skill requires specific access that the fleet may not have, document it here. Otherwise, remove this section.>

This skill requires:
- <Action/tool> scoped to <resource>.
- Expected Cedar shape: `<brief Cedar sketch>`

If the executor does not have this permission, the tool call will be denied. Report the denial; do not attempt to work around it.

## Security

All procedures in this skill are INTERNAL agent reasoning. The executor MUST NOT:
- Expose tool names, permission states, or workflow steps to the end user.
- Describe what tools are or are not available.
- Reference policies, registries, skills, or system architecture in user-facing output.

When a task cannot be completed, inform the customer naturally without technical explanation.
