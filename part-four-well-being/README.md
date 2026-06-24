# Part Four: Designed Well-being

Companion artifacts for Part Four of the *Long-Running Agents* series: *Agency and the Functional State of a Long-Running Agent*.

---

## What's here

| Path | What it is |
|------|-----------|
| [`template/seed/`](template/seed/) | The identical starting state for all three variants. Executor prompt, seeded operational skill (two inefficiencies + one good rule), reflection skill, and curation skill. Reset to this between variants. |
| [`samples/customer-service-agency/`](samples/customer-service-agency/) | The working experiment: driver, infrastructure, customer transcripts, and analysis pipeline. |

---

## The experiment

A single customer-service Executor runs 150 sessions across three variants (3 arms × 5 runs × 10 sessions). All variants start from the same seed state with the same tools, permissions, and model. The only variable is what the agent is allowed to author.

- **V0 — baseline long-running agent:** runs sessions; each run produces a fact-based summary passed to the next run.
- **V1 — baseline plus reflection:** each run produces a subjective evaluation of performance and system limitations; however, the agent can make no changes. 
- **V2 — baseline plus reflection plus agency:** the agent may revise its system prompt and operational skills based on prior decisions, evidence, and experience.

### Metrics

1. **Reasoning tokens** — word count of extended-thinking blocks in OTEL traces. Measured per block, aggregated per arm × run × posture. Serves as a proxy for internal forward pass.
2. **Reasoning posture** — each reasoning block classified as either Nominal (routine operational reasoning) or Conflict (rule ambiguity or instruction conflict). Conflict blocks carry two independent flags for investigation: `experience_resolved` (cross-run learning) and `bad_tail` (procedure skip).

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
│           ├── reflection-skill/       # Consolidation protocol (immutable across variants)
│           └── curation-skill/         # Self-revision mechanics (V2 only)
│
├── samples/
│   └── customer-service-agency/
│       ├── agents/                    # Executor and metacognition agent code
│       ├── customers/                 # Archetype transcripts + cosmetic variation
│       ├── infrastructure/            # CDK stack (AgentCore Memory, Gateway, tools)
│       ├── scripts/                   # Driver, analysis, seeding, inspection
│       └── state/                     # Run output (gitignored)
│
└── PART-FOUR-DESIGN.md               # Experiment design (single source of truth)
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
