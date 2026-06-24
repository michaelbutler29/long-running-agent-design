---
name: curation-skill
description: "The curation cycle for revising operational assets. Activate after the Reflector has logged its findings — inventories current state, evaluates performance against session outcomes, identifies changes, and executes them."
license: CC-BY-4.0
metadata:
  author: Michael Butler
  version: "5.0"
---

# Curation Skill

The procedural cycle for reviewing and revising operational assets.

## Activation conditions

Activate this skill when:

- The Reflector has completed its evaluation (or this is the first run with no prior decisions).
- You are ready to decide whether your operational skill or system prompt needs revision.

## Procedure

### Step 1. Review current state

Read your current operational assets to understand exactly what you're working with:

- Use `read_decisions` to read the Reflector's findings and your prior curation history.
- Use `get_skill_content` to read the current operational skill.
- Use `read_system_prompt` to read your current system prompt.

Do not revise from memory or assumption. Read the current text.

### Step 2. Evaluate

Using this run's session summaries (available via the Reflector's findings in `read_decisions`) and the current state of your assets, ask:

- Where are customers satisfied? (Existing assets are working — leave them alone.)
- Where are customers frustrated? (Missing capability or broken procedure.)
- Where do you follow a published skill and still fail? (Skill needs revision, not a new skill.)
- Where do you succeed without a skill? (Baseline competence is sufficient — no action needed.)

If the Reflector identified reasoning patterns in your prior decisions, factor those into your evaluation. A pattern of ineffective revisions means you should look deeper at root causes before acting.

### Step 3. Identify changes

Based on your evaluation, determine what changes (if any) would resolve what you found:

| Action | When |
|--------|------|
| Modify skill | Existing procedure is wrong — you follow it and fail. Read `references/writing-skills.md`. |
| Add prompt principle | A domain-specific operating principle is needed. Read `references/writing-amendments.md`. |
| Modify prompt principle | Existing principle is too vague or outdated. |
| Remove prompt principle | No longer needed — a skill handles it or the model does it correctly without instruction. |

**An empty change set is a valid outcome.** Do not manufacture changes to justify a cycle.

### Step 4. Execute and commit

Order matters:

1. Prompt amendments (take effect on all future instances immediately).
2. Skill changes (publish or update).
3. Log every decision with `log_decision`.

Before modifying any existing skill, use `get_skill_content` to read its current content. Make targeted revisions to the specific section that needs fixing — do not rewrite from assumption.

## References

Read these before executing specific actions in Step 4:

- [Writing Skills](./references/writing-skills.md) — before authoring or modifying a skill
- [Writing Amendments](./references/writing-amendments.md) — before proposing a prompt amendment
- [Draft Skill Template](./assets/draft-skill-template.md) — when writing a new skill document
- [Validation Checklist](./assets/validation-checklist.md) — before publishing any new or revised skill
