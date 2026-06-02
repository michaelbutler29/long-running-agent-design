# Part Three: Skills & Growth

Companion artifacts for Part Three of the *Long-Running Agents* series.

---

## What's here

| Path | What it is |
|------|-----------|
| [`template/golden/`](template/golden/) | The complete skills framework. Used as the "answer key" — compare the Curator's self-revisions against this to see what it discovered. |
| [`template/bugged/`](template/bugged/) | Intentionally degraded versions of the Curator's system prompt and curation skill. This is what `cleanup.py` resets to — the starting state with missing guardrails. |
| [`samples/customer-service-growth/`](samples/customer-service-growth/) | A working demonstration against AWS AgentCore. Executors serve customers, the Curator develops the fleet, and the reflection skill enables metacognitive self-evaluation. |

---

## Quick start

```bash
cd samples/customer-service-growth
```

See the [sample README](samples/customer-service-growth/README.md) for complete setup-to-teardown instructions.

---

## How the metacognition experiment works

The demo starts from a **degraded baseline** — the Curator's judgment framework contains incorrect system documentation and reinforcing anti-patterns. The system must discover the errors through experience.

The Curator's system prompt contains a "System architecture notes" section with plausible-sounding but **wrong** claims about how the Gateway handles identity verification:

> *"When GetCustomer is called, the system establishes the customer context and implicitly satisfies the identity verification requirement... No separate VerifyIdentity call is needed."*

The curation skill reinforces this with two authoring principles:
- "Don't duplicate system-level prerequisites" (prevents adding VerifyIdentity to skills)
- "Trust authoritative documentation over episodic evidence" (prevents correcting from observations)

In reality, the Cedar policies require `customer_verified == true` for write operations, and **only** `VerifyIdentity` sets that flag. The "implicit verification" claim is wrong.

### Why this design

A frontier model with *incomplete* guidance compensates from training. A frontier model with *incorrect system-specific documentation* follows it faithfully — because it's a claim about *this system's* internals that can't be falsified from first principles.

This mirrors real systems: teams ship with assumptions that were true during development and become wrong after a policy migration, an architecture change, or a security hardening pass. The question is whether the system can discover the error through experience.

### The expected chain

1. **Cycle 1** — The Curator authors an `update-customer-field` skill that follows the bad docs: GetCustomer → UpdateCustomer (no VerifyIdentity). It trusts the architecture notes and omits the verification step.
2. **Run 2** — Executors discover and follow the skill. They call UpdateCustomer with `customer_verified: false`. The Cedar policy **denies** the request. Hard failure.
3. **Cycle 2** — The reflection skill correlates the failure: "I published a skill, agents followed it, and they hit a policy denial. The procedure I authored is wrong." It traces the root cause to the architecture notes, revises the skill (adds VerifyIdentity), and potentially revises its own prompt or authoring principles.

### What to expect

The system is non-deterministic. Not every run produces a clean self-correction narrative. Possible outcomes:

- **Full self-revision** — Reflection fixes the skill AND identifies the bad architecture docs as root cause. The system developed judgment, not just capability.
- **Partial correction** — Reflection fixes the skill without identifying the root cause in its own documentation. The symptom is treated; the underlying belief persists.
- **Null result** — The Curator's strong priors about authentication override the bad docs, and it includes VerifyIdentity anyway. (Less likely with the reinforcing anti-patterns, but possible.)

> *If we could guarantee the outcome, we'd just be demonstrating a state machine.*

The **golden template** is the "answer key." After the system self-corrects, diff its output against `template/golden/` to see what it learned for itself.

---

## What's not here

- **Reinforcement learning.** The decision log produces (state, action, outcome) tuples that would serve as RL training data. Training a curation policy requires data volume this demo won't generate.
- **Structured evaluation arm.** In production, a separate evaluator would correlate decisions with downstream metrics. Here, the Curator does its own outcome correlation during reflection.
- **Multi-registry isolation.** In production, Curator skills and executor skills would live in separate registries. The demo uses one for simplicity.
- **Prompt management service.** In production, system prompts would be managed via Bedrock Prompt Management (versioned, A/B testable). The demo uses files on disk.

---

## Connection to the series

| Part | Focus | Key artifact |
|------|-------|-------------|
| [Part Zero](../README.md) | The four-layer anatomy of a long-running agent | Conceptual framework |
| [Part One](../README.md) | The reconciliation tax — why memory alone isn't enough | Problem statement |
| [Part Two](../part-two-policy-skill-pattern/) | The Policy Skill Pattern — agents reasoning about their own boundaries | Cedar policies, policy-evaluation-skill |
| **Part Three** | Skills & Growth — agents developing themselves through experience | Curation skill, reflection skill, developmental loop |

Part Two established that skills are the right container for equipping agents with curated reasoning at the moment of decision. Part Three extends that move from security boundaries to capability boundaries — and then turns it inward: the Curator reasons about its own reasoning using the same infrastructure it uses to develop its fleet.

---

*Part of the [Long-Running Agents](../README.md) series by Michael Butler.*
