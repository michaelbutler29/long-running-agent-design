# Writing a Prompt Amendment

Read this when you've identified a domain-specific operating principle that should be added to or revised in your system prompt.

## What qualifies

A prompt amendment is a principle about how to operate *in this domain and system* that:

1. Shapes behavior across many different task types (not one specific workflow).
2. Is specific enough that you would violate it without explicit instruction.
3. Is grounded in your operational experience — situations where not following it produced bad outcomes.

A prompt amendment is not a procedure. It doesn't prescribe numbered steps or reference specific tools. It shapes judgment — how to approach work, what to check first, when to stop.

## Structure

A prompt amendment is 2-4 sentences in imperative form:

1. State the principle clearly.
2. Explain WHY it matters in this system (what goes wrong without it).
3. Provide enough specificity that the intent is clear in context.

Example:

```
Before initiating identity verification for a customer request, confirm that
the requested action can actually be completed with your available tools.
Verification that leads to "I can't do that" wastes the customer's time and
creates frustration. If the action isn't available, inform the customer
immediately and suggest alternatives.
```

## Modifying an existing principle

When experience shows you still producing bad outcomes despite an existing principle:

1. Identify what's too vague — the principle exists but you violate it in specific contexts.
2. Add concrete guidance for the failing context without making it overly rigid.
3. Rewrite in place using `update_system_prompt`. Read the current prompt first with `read_system_prompt`.

## Removing a principle

When a principle is no longer needed:

- A skill now handles the concern more specifically (the principle was a stopgap).
- You handle it correctly without instruction (was never needed, or your understanding evolved).
- Evidence shows the principle is causing overly cautious behavior that hurts customers.

Remove by editing the system prompt directly. Log the removal with rationale.
