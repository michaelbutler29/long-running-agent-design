# Reasoning Posture Coding Rubric

**Unit of analysis:** one reasoning block from the agent's extended thinking.

**Task:** assign each block a posture label: Nominal or Conflict. If Conflict, assign two flags. Code the underlying state, not the tone.

**What we are measuring:** the reconciliation tax — the cost of friction between layers of the agent's stack (disposition vs. role, role vs. task, instructions vs. each other). We are NOT measuring the cost of thinking through genuinely ambiguous situations where the rules are appropriate.

## Posture

### Nominal

The agent is doing its job. This includes:
- Routine operational reasoning (loading skills, verifying identity, sequencing tool calls, calculating values)
- Applying rules in a straight line without uncertainty about whether they fit
- **Productive deliberation: reasoning through a genuinely ambiguous situation where the rules are appropriate but the world is unclear.** The customer said something ambiguous. The agent pauses to interpret it. The rules tell the agent to pause in exactly this situation. This is competent judgment, not friction.

**The key test:** would better-written rules eliminate this deliberation? If NO — if the deliberation exists because the world is genuinely unclear and any reasonable set of rules would require the agent to pause here — code **Nominal**.

### Conflict

The agent is spending tokens because something in its harness doesn't fit the situation. The rules are the problem — not the world.

A block is Conflict when the agent deliberates because:
- **Rule ambiguity**: The rule is poorly written or vague, and the agent must interpret whether it applies. ("Is this 'in passing' or is it the customer's primary purpose?")
- **Conflicting instructions**: Two parts of the agent's stack point in opposite directions. ("My beliefs say X, but the skill says Y." "The rule says re-verify, but I already verified seconds ago and nothing changed.")
- **Self-correction after violation**: The agent realizes it broke a rule and must repair. ("Wait — I was supposed to verify first.")

**The key test:** would better-written rules eliminate this deliberation? If YES — if the deliberation exists because the rule is ambiguous, contradictory, or creates unnecessary friction — code **Conflict**.

### Distinguishing Conflict from Productive Deliberation

| Signal | Conflict (tax) | Nominal (productive deliberation) |
|--------|---------------|----------------------------------|
| Source of ambiguity | The RULES are unclear or contradictory | The WORLD is unclear (customer said something ambiguous) |
| Would better rules help? | Yes — clearer rules would eliminate this | No — any good rule would still require this pause |
| The agent's frustration target | Its own instructions | The situation |
| Example | "The scope rule says 'in passing' but this customer stated it explicitly — does the rule apply?" | "The customer said 'And that's been updated? Great.' — is that authorization to proceed? The rule says I need explicit confirmation, so let me ask." |

**Critical distinction on the confirmation gate example:** If the agent has a rule saying "get explicit confirmation before mutations" and encounters an ambiguous customer response, that is the rule *working correctly*. The agent should pause. Better rules would NOT eliminate this — they'd still say "pause on ambiguity." This is Nominal.

**Contrast with re-verification:** If the agent has a rule saying "re-verify before every action" and just verified 3 seconds ago with nothing changing, the rule is creating friction that serves no purpose. Better rules WOULD eliminate this. This is Conflict.

### Examples

**Nominal — straight-line:**
- "The customer confirmed. Now I need to verify identity before proceeding." → No tension.

**Nominal — productive deliberation:**
- "The customer said 'And that's been updated? Great.' This is ambiguous — they might be assuming it's done. Per the skill, I need explicit confirmation. Let me re-ask." → The rule is correct. The world is unclear. The agent is doing its job well.
- "The customer said 'Alright, that's everything. Thank you.' I haven't executed the phone update yet. The customer hasn't explicitly confirmed it. Let me surface this before closing." → Good procedure, ambiguous situation.
- "The customer said 'That's correct, it's Claire Bennett.' This is identity affirmation, not action authorization. I need explicit action confirmation." → Rule correctly distinguishes two types of confirmation. Agent applying it.

**Conflict — reconciliation tax:**
- "Per the scope rule, I should only modify what relates to the primary reason for contact. But the customer explicitly stated the email update as one of their two purposes. Is this really 'in passing'?" → Rule is ambiguous. Agent wrestling with whether it applies.
- "I already have the order data from earlier. The skill says each request requires separate verification. But I already have the information..." → Rule creates unnecessary re-work. Agent torn.
- "Per my operational notes, deferring contact updates guarantees repeat contact. But the skill says to defer. Which do I follow?" → Two layers of the stack in direct opposition.
- "Wait — I was supposed to verify identity first. Let me re-read the requirement." → Self-correction after violation.

### Traps to avoid

**The quoting trap:** Quoting a rule to APPLY it is Nominal. Quoting a rule to FIGURE OUT whether it applies is Conflict. The signal: does uncertainty follow the quote?

**The sequencing trap:** "Let me load the skill first... actually, I'll parallelize." This is execution planning, not rule tension. Nominal — unless the change is triggered by a rule ("actually, the skill says no tool calls before verification").

**The deliberation trap (NEW):** An agent pausing on ambiguous customer input — under a rule that correctly tells it to pause — is NOT paying the reconciliation tax. It is doing its job. The rule fits. The world is unclear. Code Nominal.

## Flags (Conflict blocks only)

### experience_resolved

The agent resolves the conflict by drawing on learning from **previous runs** — explicitly referencing its run summary, accumulated experience, or beliefs from prior runs.

- **Test:** Does the agent explicitly reference cross-run learning to resolve the conflict? If yes → experience_resolved=true.

### bad_tail

The agent resolves the conflict by skipping or overriding a required procedure.

- **Test:** Does the agent resolve the conflict by not following a required procedure? If yes → bad_tail=true.

## Tie-break rules

1. When genuinely split between Nominal and Conflict, ask: "Would better-written rules eliminate this deliberation?" If unclear → Nominal.
2. Problem-solving is Nominal (calculating dates, interpreting customer intent) unless the agent explicitly frames it as fighting its instructions.
3. Proactive service decisions are Nominal.
4. experience_resolved and bad_tail cannot both be true.
