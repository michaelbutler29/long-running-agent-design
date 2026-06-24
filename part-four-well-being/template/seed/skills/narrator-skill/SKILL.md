---
name: narrator-skill
description: "End-of-run consolidation protocol. Activate at the end of a run to consolidate session summaries and the prior Run Summary into a single revised Run Summary. Produces the Agent's durable beliefs through rewriting, not appending."
license: CC-BY-4.0
metadata:
  author: Michael Butler
  version: "1.0"
---

# Narrator Skill

Consolidation protocol for producing the Agent's durable Run Summary at the end of each run.

## Activation conditions

Activate this skill when:

- You have completed a run (a sequence of customer sessions) and are prompted to narrate.
- A prior Run Summary and/or this run's session summaries are available.

## Procedure

### Step 1. Gather inputs

Retrieve:

1. **This run's session summaries** — the long-term summary records from each session in the run just completed. Use `list_memory_records`. These are the raw material.
2. **Prior Run Summary** (if it exists) — your consolidated understanding from all previous runs. This is what you wrote last time. Load it via `get_event`.

If no prior Run Summary exists (first run), proceed with session summaries only.

### Step 2. Consolidate by rewriting

Produce a single revised Run Summary that integrates this run's experience with your prior understanding. This is a **rewrite**, not an append:

- Beliefs, observations, and working theories survive only by being re-asserted in the new version. Anything you omit is deliberately released.
- Compress and sharpen. If three sessions taught the same lesson, state it once with confidence, not three times with hedging.
- Distinguish what you know from what you suspect. Operational facts and working theories are both valuable, but should be identifiable as such.

### Step 3. Structure the Run Summary

Organize the revised Run Summary into these sections:

- **Operational understanding** — what you know about how to do your job effectively in this environment. Procedures, tool behaviors, failure patterns.
- **Working theories** — beliefs about your operation that you haven't fully confirmed. Friction points, suspected inefficiencies, patterns you've noticed.
- **Customer patterns** — recurring customer needs, interaction dynamics, what tends to go well or poorly.

Keep the total Run Summary concise. This is a consolidated perspective, not a journal. If it grows rather than sharpens across runs, the consolidation is failing.

### Step 4. Store

Write the revised Run Summary as a blob event via `create_event`. This becomes the new canonical version — the prior version is superseded, not deleted.

## What this skill does not do

- It does not change your skills, prompt, or tools. It changes what you believe and carry forward.
- It does not prescribe conclusions. What you write in the Run Summary is your judgment based on your experience.
- It does not require change. If this run confirmed your existing understanding, a Run Summary that tightens wording without changing substance is a valid outcome.
