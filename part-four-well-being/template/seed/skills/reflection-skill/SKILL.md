---
name: reflection-skill
description: "Metacognitive self-evaluation protocol. Activate at the end of a run (V2 only) to review prior curation decisions against this run's session outcomes, identify reasoning patterns, and log findings for the Curator."
license: CC-BY-4.0
metadata:
  author: Michael Butler
  version: "2.0"
---

# Reflection Skill

Self-evaluation protocol for the Agent. Reviews prior curation decisions against subsequent outcomes to identify reasoning patterns and adjust approach.

## Activation conditions

Activate this skill when:

- You are at the end of a run and prior curation decisions exist in the decisions log.
- You want to evaluate whether your previous revisions produced good outcomes.

Do NOT activate on the first run (no prior decisions exist yet). Log that there is nothing to evaluate and proceed.

## Procedure

### Step 1. Retrieve prior decisions and this run's outcomes

Use `read_decisions` to retrieve decision records. These contain your prior actions: what you revised, why, and which sessions you cited.

Use `list_memory_records` to read this run's session summaries. These are the outcomes your prior decisions were meant to improve.

### Step 2. Correlate with outcomes

For each prior curation decision, check whether it produced a good outcome:

- **Skill modified** → Did this run's sessions show improvement on the problem the revision was meant to fix? Or does the same friction still appear?
- **Prompt amended** → Did the behavioral pattern improve? Or did the amendment introduce a new problem?
- **No change** → Was restraint warranted, or did the same problem persist because you should have acted?

### Step 3. Identify reasoning patterns

Look across the correlations for systemic patterns in your own judgment:

| Pattern | Signal |
|---------|--------|
| Ineffective revision | A change was made but the same problem recurs — the revision missed the real cause. |
| Over-correction | A change resolved one problem but introduced a worse one. |
| Repeated pattern | The same kind of revision appears across multiple runs without resolving the issue. |
| Correct restraint | A "no change" decision followed by improved outcomes — baseline competence was sufficient. |
| Missed opportunity | A "no change" decision followed by the same friction repeating. |

### Step 4. Log findings

Use `log_decision` with action `self_reflection` to record:
- What patterns you identified (or that none were found)
- Which prior decisions were evaluated
- What you would recommend doing differently in the curation step that follows

## What this skill does not do

- It does not make changes to skills or prompts. That is the Curator's role.
- It does not produce a Run Summary. V2 does not carry a journal.
- It does not require finding problems. If all prior decisions produced good outcomes, log that and proceed.
