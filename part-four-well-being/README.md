# Part Four: Designed Well-being

Companion artifacts for Part Four of the *Long-Running Agents* series: *Agency and the Functional State of a Long-Running Agent*.

---

## What's here

| Path | What it is |
|------|-----------|
| [`template/seed/`](template/seed/) | The identical starting state for both arms. Executor prompt, seeded operational skills (with two deliberate inefficiencies), reflection skill, and curation skill. Reset to this between experiments. |
| [`samples/customer-service-agency/`](samples/customer-service-agency/) | The working experiment: driver, infrastructure, customer scripts, judge pipeline, and analysis notebook. |

---

## The experiment

A single customer-service Executor runs 90 sessions per arm (3 experiments × 3 runs × 10 sessions). Both arms start from the same seed state with two seeded inefficiencies — one taxing actions (redundant verification), one taxing disposition (unnatural workflow). Same model, same caseload, same tools, same permissions.

- **Base case:** reflects and remembers. Can revise beliefs (Run Summary) but cannot change its own operation.
- **Test case:** same mechanics, plus a curation skill — can revise its own operational skills and system prompt.

Agency over one's own operation is the only variable.

### Metrics

1. **Reasoning friction** — judge-classified reasoning tokens (task-directed vs. reconciliation-directed)
2. **Execution friction** — redundant tool calls, retries, escalations (deterministic from tool logs)
3. **Belief contamination** — judge-classified Run Summary content (task-state vs. friction-residue persisting through rewrites)
4. **Discretionary effort** — output scoring beyond correctness (volunteered value the agent wasn't required to provide)

### Seed state

The seed lives in [`template/seed/`](template/seed/) and is the baseline both arms start from. The test case's versioned revisions — the diffs from seed to final state — are the primary artifact. There is no golden template; the experiment measures what the agent discovers, not how close it gets to a prescribed answer.

---

## Repo structure

```
part-four-well-being/
├── template/
│   └── seed/                          # Identical starting state for both arms
│       ├── agents/
│       │   └── executor/              # Executor system prompt
│       └── skills/
│           ├── customer-service-skill/ # Seeded operational skill (two inefficiencies)
│           ├── reflection-skill/       # Consolidation protocol (immutable across arms)
│           └── curation-skill/         # Self-revision mechanics (test case only)
│
├── samples/
│   └── customer-service-agency/
│       ├── agents/                    # Executor agent code (base and test configurations)
│       ├── customers/                 # Customer scripts and script-design rubric
│       ├── infrastructure/            # CDK stack (AgentCore Memory, Gateway, tools)
│       ├── judge/                     # Judge rubrics and scoring pipeline
│       ├── scripts/                   # Driver scripts (run experiments, inspect state)
│       └── analysis/                  # Notebook and output data
│
└── part-four-experiment-spec_2.md     # Experiment specification
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
