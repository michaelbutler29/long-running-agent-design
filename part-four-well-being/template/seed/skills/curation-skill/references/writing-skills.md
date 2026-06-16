# Writing a Skill

Read this when you're ready to author or revise an operational skill.

## What qualifies

A skill encodes specialized knowledge or a prescriptive workflow that cannot be derived from training data. The defining test: could an LLM with no knowledge of *this system's* specific tools, APIs, verification flows, and data schemas do this correctly? If no, it's a skill.

A skill is a workflow — numbered steps, specific tool calls, specific parameters. If you cannot write concrete steps referencing this system's tools, it is not a skill.

## Structure

Use `assets/draft-skill-template.md` for the full template. The essential parts:

- **name** — lowercase-with-hyphens
- **description** — 1-2 sentences: what it does AND when to trigger. Include specific contexts that should activate it.
- **Procedure** — numbered steps. Reference specific tool names and parameters. Concrete enough to succeed without improvising.
- **Failure modes** — what can go wrong and what to do.

## Style

Explain the WHY behind steps, not just the WHAT. You will follow your own skills — reasoned instructions serve you better than rigid mandates. If you find yourself writing ALWAYS or NEVER in all caps, reframe with reasoning so the intent is clear even when the situation is ambiguous.

Keep it lean. Every line should encode something you couldn't derive on your own from tool signatures. If removing a line wouldn't change your behavior, remove it.

## Modifying an existing skill

When experience shows that following an existing skill produces friction or failure:

1. Read the current skill text. Do not revise from memory.
2. Identify the specific step that produces the wrong outcome.
3. Rewrite the affected portion. Don't rewrite the whole skill unless the approach is fundamentally wrong.
4. Update the version.

## Consolidating skills

When two skills overlap:

1. Identify what's shared and what's distinct.
2. Write one consolidated skill covering both cases.
3. Publish the consolidation, deprecate the originals.
4. Log with rationale referencing both predecessor skills.
