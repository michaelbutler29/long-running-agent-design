---
name: reflection-skill
description: "Metacognitive self-evaluation protocol. Activate before beginning a curation cycle to review your own prior decision records, assess which decisions produced good outcomes, identify reasoning patterns (over-production, wrong triage path, missed consolidation), and adjust your approach for the current cycle. May also produce revisions to your own procedural skills."
license: CC-BY-4.0
metadata:
  author: Michael Butler
  version: "1.0"
---

# Reflection Skill

Self-evaluation protocol for the Curator. Reviews prior curation decisions against subsequent outcomes to identify reasoning patterns and adjust approach.

## Activation conditions

Activate this skill when:

- You are about to begin a curation cycle and prior decisions exist in Memory.
- You want to evaluate whether your previous curation reasoning produced good outcomes.

Do NOT activate on the first curation cycle (no prior decisions exist yet).

## Procedure

### Step 1. Retrieve prior decisions and current judgment framework

Use `read_decisions` to retrieve decision records from the `/decisions/` namespace. These contain your prior actions: what you published, proposed, amended, or discarded, along with rationale.

Use `read_system_prompt(target="curator")` to read your current system prompt. This is your active judgment framework. When you identify a bad outcome in Step 2, check whether your current principles would have prevented it. If not, the framework has a gap that needs to be addressed in Step 4.

### Step 2. Correlate with outcomes

For each prior decision, check whether it produced a good outcome:

- **Skill published** → Use `read_episodes` to search for episodes where the skill was discovered and followed. Was the customer served? Did agents follow it correctly?
- **Skill published but never triggered** → Search episodes for the task type the skill targets. If customers with that need were served without the skill, it may have been unnecessary (over-production).
- **Permission proposed** → Check episodes for the tool action. Are agents now successfully using it? Or was it never needed?
- **Prompt amendment** → Check episodes for the behavior pattern. Has the fleet stopped producing the bad outcome?
- **Discard** → Check if subsequent episodes show the same gap recurring. A correct discard produces no repeat failures.

### Step 3. Identify reasoning patterns

Look across the correlations for systemic patterns in your own judgment:

| Pattern | Signal |
|---------|--------|
| Over-production | Multiple skills published that were never triggered or that agents handle fine without. |
| Under-production | Discards followed by repeated customer failures on the same task type. |
| Wrong triage path | Something classified as a skill that should have been a prompt amendment (or vice versa). |
| Missed consolidation | Two skills that overlap, both published in the same cycle rather than merged. |
| Premature permission | Permission proposed without sufficient episode evidence of customer need. |

### Step 4. Adjust approach

If Step 3 identified a reasoning pattern, produce one or both:

**Immediate adjustment** — State explicitly how you will reason differently in the curation cycle that follows. Example: "My prior cycle over-produced skills for patterns that are baseline model competence. This cycle I will apply the triage test more strictly: if I cannot name the specific tool call the model would get wrong, it's a discard."

**Durable adjustment** — If a pattern is systemic enough to warrant a permanent change:

- To revise your own procedural skills: use `publish_skill` to update the curation skill or this reflection skill. Add a gotcha, tighten a criterion, or restructure a step.
- To revise your own judgment framework: use `update_system_prompt(target="curator")` to add, tighten, or rewrite a principle in your system prompt. This is the deepest form of self-correction — changing how you reason, not just what you do.

If Step 3 found no patterns, proceed directly to Step 5.

### Step 5. Log

Use `log_decision` with action `self_reflection` to record:
- What patterns you identified
- What adjustments you're making (immediate and durable)
- Which prior decisions were evaluated

## Failure modes

- **No prior decisions found:** Skip this skill entirely — nothing to reflect on. Proceed directly to curation.
- **Insufficient episode data to evaluate outcomes:** Note which decisions cannot yet be evaluated (outcome still pending). Do not force a conclusion without evidence.
- **All prior decisions produced good outcomes:** A valid result. Log it and proceed. Do not manufacture problems.
