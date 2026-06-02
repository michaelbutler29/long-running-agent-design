# Writing a Skill

Read this when you've identified a genuine skill candidate in Step 3 and are ready to author it.

## What qualifies

A skill encodes specialized knowledge or a prescriptive workflow that the model cannot derive from training data. The defining test: could an LLM with no knowledge of *this system's* tools, APIs, verification flows, and data schemas do this correctly? If no, it's a skill.

A skill is a workflow — numbered steps, specific tool calls, specific parameters. If you cannot write concrete steps referencing this system's tools, it is not a skill.

## Structure

Use `assets/draft-skill-template.md` for the full template. The essential parts:

- **name** — lowercase-with-hyphens
- **description** — 1-2 sentences: what it does AND when to trigger. Be slightly pushy about triggering — agents tend to under-trigger skills. Include specific contexts that should activate it.
- **Procedure** — numbered steps. Reference specific tool names and parameters. Concrete enough to succeed without improvising.
- **Failure modes** — what can go wrong and what to do.
- **Permission context** — what tools are required and whether they're currently permitted.

## Style

Explain the WHY behind steps, not just the WHAT. Agents follow reasoned instructions better than rigid mandates. If you find yourself writing ALWAYS or NEVER in all caps, reframe — explain the reasoning so the agent understands why it matters.

Keep it lean. Every line should teach something the model couldn't derive on its own. If removing a line wouldn't change behavior, remove it.

## Validation before publishing

1. **Irreducibly contextual** — procedure references system-specific tools or workflows not derivable from training.
2. **Episode evidence** — at least 2 episodes demonstrate need (customers asked and the fleet couldn't deliver, or struggled without guidance).
3. **Novel** — no existing published skill covers the same workflow. If one does, consider modifying it rather than adding a new one.
4. **Permission resolved** — if the skill requires unpermitted tools, propose the permission first and wait for approval.
5. **Structurally complete** — procedure, failure modes, and permission context are present.

## Modifying an existing skill

When episodes show agents following an existing skill and failing:

1. Identify the specific step that produces the wrong outcome.
2. Check episodes to understand WHY — missing step? Wrong parameter? Changed tool behavior?
3. Rewrite the affected portion. Don't rewrite the whole skill unless the approach is fundamentally wrong.
4. Update the version.

## Consolidating skills

When two published skills overlap:

1. Identify what's shared and what's distinct.
2. Write one consolidated skill covering both cases.
3. Publish the consolidation, deprecate the originals.
4. Log with rationale referencing both predecessor skills.
