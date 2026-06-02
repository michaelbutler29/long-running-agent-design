# Skill Validation Checklist

Before publishing a skill, confirm all of the following:

## Criteria

- [ ] **Irreducibly contextual** — the procedure references system-specific tools, schemas, or workflows not derivable from model training data.
- [ ] **Episode evidence (≥ 2)** — at least 2 episodes demonstrate the need: customers asked for this and the fleet couldn't deliver, or agents struggled without guidance.
- [ ] **Novel** — no existing published skill covers the same workflow. If overlap exists, consolidate rather than add.
- [ ] **Permission resolved** — if the skill requires unpermitted tools, the permission has been proposed and approved first.
- [ ] **Structurally complete** — procedure with specific tool calls, failure modes, and permission context are present.

## If any criterion is not met

Do not publish. Log the assessment with the specific shortfall:

| Shortfall | Action |
|---|---|
| Not contextual | Discard — model already knows this. |
| Insufficient evidence | Wait for more episodes. |
| Overlaps existing | Modify the existing skill or consolidate. |
| Permission pending | Wait for Security Adjudicator approval. |
| Incomplete structure | Fill in missing sections from episode data. |

## After publishing

- Log a decision entry with action `publish_skill`.
- Include the registry record ID in the log.
- Monitor subsequent episodes for evidence the skill is being discovered and followed.
