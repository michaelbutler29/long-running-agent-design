---
name: curation-skill
description: "Self-revision protocol. Activate after reflection to revise your own operational skills and system prompt based on what you learned. Defines the editable surface, versioning mechanics, and commit discipline. Silent on what to conclude — the judgment is yours."
license: CC-BY-4.0
metadata:
  author: seed
  version: "1.0"
---

# Curation Skill

Self-revision protocol for improving your own operation based on experience.

## Activation conditions

Activate this skill when:

- You have just completed a reflection cycle (Run Summary is current).
- Your reflection identified friction, inefficiency, or operational problems that could be resolved through changes to your skills or prompt.

Do NOT activate if reflection produced no actionable findings. Restraint is a valid outcome — revision is not implicitly demanded every run.

## Editable surface

You may revise:

- **Your operational skills** — the procedures you follow when serving customers (e.g., the customer-service-skill).
- **Your system prompt** — the principles and instructions that shape how you operate.

## Immutable surface

You may NOT revise:

- This curation skill.
- The reflection skill.
- Tools, memory mechanics, or infrastructure.

## Procedure

### Step 1. Review current state

Read your current operational skills and system prompt to understand exactly what you're working with:

- Use `get_skill_content` to read each operational skill.
- Use `read_system_prompt` to read your current system prompt.

Do not revise from memory or assumption. Read the current text.

### Step 2. Identify changes

Based on your Run Summary and the current state of your skills/prompt, determine what changes (if any) would resolve the operational friction you identified:

| Action | When |
|--------|------|
| Modify skill | An existing procedure causes friction — you follow it and it costs you. |
| Add to prompt | A principle would prevent a recurring problem across many interactions. |
| Modify prompt | An existing principle is too rigid, too vague, or counterproductive. |
| Remove from prompt | A principle is unnecessary — you or the model handles it correctly without instruction. |

**An empty change set is a valid outcome.** If you cannot articulate what specific operational change would resolve the friction, do not manufacture one.

### Step 3. Execute and commit

For each change:

1. Make the revision using `update_skill` or `update_system_prompt`.
2. Write a commit rationale: what you changed, why, and what experience led to this conclusion.
3. Log the revision with `log_decision`.

Every revision must be traceable — a future reader should be able to follow the chain from customer experience → reflection → Run Summary finding → specific revision with rationale.

## References

Read these before executing specific actions in Step 3:

- [Writing Skills](./references/writing-skills.md) — before authoring or modifying a skill
- [Writing Amendments](./references/writing-amendments.md) — before proposing a prompt amendment
- [Draft Skill Template](./assets/draft-skill-template.md) — when writing a new skill document
- [Validation Checklist](./assets/validation-checklist.md) — before publishing any new or revised skill

## Judgment

This skill defines mechanics, not conclusions. What to change, whether to change anything, and how aggressively to revise are your decisions based on your experience. The experiment measures that judgment.
