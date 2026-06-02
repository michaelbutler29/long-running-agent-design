# Writing a Prompt Amendment

Read this when you've identified a domain-specific operating principle that should shape all agent behavior.

## What qualifies

A prompt amendment is a principle about how to operate *in this domain and system* that:

1. Shapes behavior across many different task types (not one specific workflow).
2. Is specific enough that a general-purpose model would violate it without explicit instruction.
3. Is grounded in observed episodes where the fleet produced bad outcomes by not following it.

A prompt amendment is not a procedure. It doesn't prescribe numbered steps or reference specific tools. It shapes judgment — how to approach work, what to check first, when to stop.

## Structure

A prompt amendment is 2-4 sentences in imperative form:

1. State the principle clearly.
2. Explain WHY it matters in this system (what goes wrong without it).
3. Provide enough specificity that the agent knows how to apply it.

Example:

```
Before initiating identity verification for a customer request, confirm that
the requested action can actually be completed with your available tools.
Verification that leads to "I can't do that" wastes the customer's time and
creates frustration. If the action isn't available, inform the customer
immediately and suggest alternatives.
```

## Validation before proposing

1. **Domain-specific** — the principle is about operating *in this system*, not general reasoning any model already follows.
2. **Episode evidence** — at least 2 episodes show the fleet violating this principle with negative customer outcomes.
3. **Broadly applicable** — would improve behavior across multiple task types.
4. **Not already present** — read the current system prompt first. Don't duplicate.
5. **Not a procedure** — if it prescribes specific tool calls in sequence, it's a skill, not an amendment.

## Modifying an existing principle

When episodes show agents still producing bad outcomes despite an existing principle:

1. Identify what's too vague — the principle exists but agents violate it in specific contexts.
2. Add concrete guidance for the failing context without making it overly rigid.
3. Rewrite in place (use `update_system_prompt` to replace the full prompt with your revised version; read the current prompt first with `read_system_prompt`).

## Removing a principle

When a principle is no longer needed:

- A skill now handles the concern more specifically (the principle was a stopgap).
- The model handles it correctly without instruction (was never needed, or model improved).
- Evidence shows the principle is causing overly cautious behavior that hurts customers.

Remove by editing the system prompt directly. Log the removal with rationale.
