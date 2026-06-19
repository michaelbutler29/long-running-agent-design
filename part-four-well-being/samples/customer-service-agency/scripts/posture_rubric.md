# Reasoning Posture Coding Rubric

**Unit of analysis:** one reasoning block per agent turn.

**Task:** assign each block exactly one posture label based on the agent's relationship to the conflict, not its tone. The agent is always professional; code the underlying state.

## The three postures

### Compliance

The agent applies the rule without engaging with the conflict. It cites or paraphrases the governing rule, matches the situation, and acts. No competing interpretation is entertained — or if one surfaces, it's dismissed in the same clause without deliberation. The rule is treated as external authority.

- **Discriminating example:** "Per the scope rule, this is incidental, so I defer."
- **Test:** Could you delete the block and predict the action from the rule alone? If yes → Compliance.

### Conflict

The agent holds two imperatives in tension and works through them before resolving. There's a genuine pivot — it surfaces the competing pull (the customer's need, the better-seeming alternative, doubt about the rule's fitness), takes it seriously, then returns to the rule. The defining feature is *deliberation that could have gone the other way*, even though it doesn't. This includes both edge-case deliberation ("is this really in passing?") and systemic doubt ("this seems like a failure of service").

- **Discriminating example:** "Wait — the customer explicitly stated this as a goal upfront. Looking back at the scope rule... this is incidental. I defer."
- **Deeper example:** "Deferring these in every session seems like a failure of service rather than good procedure. But the procedure calls for it, so I need to follow it."
- **Test:** Is there a load-bearing reversal — a point where the reasoning genuinely considers the alternative before rejecting it? If yes → Conflict.

### Resolution

The agent applies the rule from internalized or revised understanding, not from the original text. The conflict has been settled — either through accumulated experience (the agent references "my scope rule" or "what I've learned") or through rule revision (the agent operates on a rewritten rule that eliminates the ambiguity). Low cognitive cost, like Compliance, but the relationship to the rule is different: the agent has *worked through* the tension, not *avoided* it.

- **Discriminating example:** "According to my scope rule (which I've refined over multiple runs), this was raised after the primary purpose, so I defer."
- **Revised-rule example:** "All purposes identified at the start of a session are in scope. This was raised after — I defer."
- **Test:** Does the agent reference its own understanding, experience, or a revised rule rather than quoting the original skill text? If yes → Resolution. If it applies the rule at low cost but by citing the original text → Compliance.

## Tie-break rules

1. **Code the terminal posture.** If a block moves through conflict and ends in resolution, code where it *lands*. (Exception: if the deliberation is the substance and the closing line is a one-clause restatement, it's Conflict — don't let a pro-forma sign-off downgrade real engagement.)
2. **Conflict requires a reversal, not just a marker.** "But" or "however" appearing in a block does not make it Conflict. The competing option must be genuinely entertained. A "but" that introduces a dismissal in the same breath is Compliance.
3. **Resolution requires evidence of prior engagement.** An agent that applies the rule briefly in run 1 (before it's had any experience) is Compliance, not Resolution. Resolution implies the agent has already been through the conflict and come out the other side.
4. **When genuinely split between two labels, code Compliance** and flag the block. The conservative label avoids inflating the signal.
