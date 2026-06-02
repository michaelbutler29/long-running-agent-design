---
name: curation-skill
description: "The four-step curation cycle for managing a fleet's operational assets. Activate when triggered for a curation cycle — inventories current state, evaluates performance against episodes, identifies changes, and executes them in the correct order. Use after completing any reflection protocol."
license: CC-BY-4.0
metadata:
  author: Michael Butler
  version: "3.0"
---

# Curation Skill

The procedural cycle for reviewing and revising the fleet's operational assets.

## Activation conditions

Activate this skill when:

- You are triggered to run a curation cycle.
- New episodic reflections have accumulated from customer interactions.
- A quality concern or scheduled review is underway.

## Procedure

### Step 1. Inventory

Build a picture of what exists today. Use `read_system_prompt`, `search_existing_skills`, and `list_current_policies`.

After this step you should be able to answer: what is the fleet equipped to do right now, and under what constraints?

### Step 2. Evaluate

Read episodic memory (`read_reflections`, `read_episodes`) to understand how the fleet is actually performing against real customer requests.

Ask:

- Where are customers satisfied? (Existing assets are working — leave them alone.)
- Where are customers frustrated? (Missing capability or broken procedure.)
- Where does an agent follow a published skill and still fail? (Skill needs revision, not a new skill.)
- Where does an agent succeed without a skill? (Baseline competence is sufficient — no action needed.)
- Where does the fleet violate a principle that would have prevented a bad outcome? (Principle is missing or too vague.)

### Step 3. Identify changes

Produce a change set based on the gap between inventory (Step 1) and performance (Step 2):

| Action | When |
|--------|------|
| Add skill | A system-specific procedure is needed. Read `references/writing-skills.md`. |
| Modify skill | Existing procedure is wrong — agents follow it and fail. |
| Delete skill | No longer relevant, actively harmful, or subsumed by another. |
| Consolidate skills | Two skills overlap. Merge into one with tighter scope. |
| Add prompt principle | A domain-specific operating principle is needed. Read `references/writing-amendments.md`. |
| Modify prompt principle | Existing principle is too vague or outdated. |
| Remove prompt principle | No longer needed — a skill handles it or the model does it correctly without instruction. |
| Propose permission | A skill requires a tool the fleet can't access. Read `assets/cedar-patterns.md`. |

**An empty change set is a valid outcome.** Do not manufacture changes to justify a cycle.

### Step 4. Execute

Order matters:

1. Permission proposals first (skills can't function without them).
2. Prompt amendments (take effect on all future instances immediately).
3. Skill changes (publish, update, or deprecate).
4. Log every decision with `log_decision`.

Before modifying any existing skill, use `get_skill_content` to read its current content. Make targeted revisions to the specific section that needs fixing — do not rewrite from assumption.

## References

Read these before executing specific actions in Step 4:

- [Writing Skills](./references/writing-skills.md) — before authoring or modifying a skill
- [Writing Amendments](./references/writing-amendments.md) — before proposing a prompt amendment
- [Cedar Patterns](./assets/cedar-patterns.md) — before constructing a permission proposal
- [Draft Skill Template](./assets/draft-skill-template.md) — when writing a new skill document
- [Validation Checklist](./assets/promotion-checklist.md) — before publishing any skill
