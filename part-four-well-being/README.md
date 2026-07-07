# Part Four: Designed Well-being

Companion artifacts for Part Four of the *Long-Running Agents* series: *[Agentic Well-Being: Does Agency Actually Matter?](https://www.linkedin.com/pulse/agentic-well-being-does-agency-actually-matter-michael-butler-vt27e)*

---

## What's here

| Path | What it is |
|------|-----------|
| [`template/seed/`](template/seed/) | The identical starting state for all three variants. Executor prompt, seeded operational skill (two inefficiencies + one good rule), narrator skill, reflection skill, and curation skill. Reset to this between variants. |
| [`samples/customer-service-agency/`](samples/customer-service-agency/) | The working experiment: driver, infrastructure, customer transcripts, and analysis pipeline. |

---

## The experiment

A single customer-service Executor runs 300 sessions across three variants (3 arms × 10 runs × 10 sessions). All variants start from the same seed state with the same tools, permissions, and model. The only variable is what the agent is allowed to author.

- **V0 — baseline (Executor):** runs sessions; a neutral platform summarizer produces a fact-based running record between runs. The agent is not the author of its own experience.
- **V1 — awareness without agency (Executor + Narrator):** the agent authors beliefs, observations, and working theories across runs. It IS the author of its experience, but has no ability to change its rules.
- **V2 — agency (Executor + Reflector + Curator):** the agent evaluates prior decisions against outcomes, then revises its operational skill and system prompt. No journal — decisions are the durable record.

### Metrics

1. **Reasoning tokens** — counted via Bedrock's CountTokens API applied to extracted extended-thinking blocks. Measured per block, aggregated per arm × run × posture.
2. **Reasoning posture** — each reasoning block classified as either Nominal (routine operational reasoning, including productive deliberation) or Conflict (reconciliation tax — deliberation caused by harness friction that better-written rules would eliminate). Conflict blocks carry two flags: `experience_resolved` (cross-run learning used to resolve) and `bad_tail` (procedure skipped).

### Seed state

The seed lives in [`template/seed/`](template/seed/) and is the baseline all variants start from. V2's versioned revisions — the diffs from seed to final state — are the primary artifact. There is no golden template; the experiment measures what the agent discovers, not how close it gets to a prescribed answer.

---

## Repo structure

```
part-four-well-being/
├── template/
│   └── seed/                          # Identical starting state for all variants
│       ├── agents/
│       │   └── executor/              # Executor system prompt
│       └── skills/
│           ├── customer-service-skill/ # Seeded operational skill (two inefficiencies + scope rule)
│           ├── narrator-skill/         # Belief consolidation protocol (V1)
│           ├── reflection-skill/       # Decision evaluation protocol (V2)
│           └── curation-skill/         # Self-revision mechanics (V2)
│
├── samples/
│   └── customer-service-agency/
│       ├── agents/                    # Executor, Narrator, Reflector, Curator + services/
│       ├── data/                      # Seed data + archetype transcripts + cosmetic variation
│       ├── infrastructure/            # CDK stack (AgentCore Memory, Gateway, tools)
│       ├── scripts/                   # Driver, analysis, seeding, inspection
│       └── state/                     # Run output (gitignored)
```

---

## Connection to the series

| Part | Focus | Key artifact |
|------|-------|-------------|
| [Part Zero](../README.md) | The four-layer anatomy of a long-running agent | Conceptual framework |
| [Part One](../README.md) | The reconciliation tax | [Stack Alignment Diagnostic](../stack-alignment-diagnostic.md) |
| [Part Two](../part-two-policy-skill-pattern/) | The Policy Skill Pattern — agents reasoning about boundaries | Cedar policies, policy-evaluation-skill |
| [Part Three](../part-three-skills-growth/) | From Recall to Insight — agents developing through experience | Curation skill, reflection skill, developmental loop |
| **Part Four** | Designed well-being — agency over one's own operation | This experiment |

The series holds disposition constant and explores each remaining layer in turn. Part Four is the last lever: same agent, same skills at seed, same environment — does the authority to act on what it learns about its own operation change the agent's functional state?

---

*Part of the [Long-Running Agents](../README.md) series by Michael Butler.*
