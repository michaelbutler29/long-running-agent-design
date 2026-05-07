# template (policy skill pattern)

Templates for the two skills that implement the policy skill pattern: a **policy-generator skill** (produces proposals) and a **policy-evaluation skill** (judges them). Fork both. Fill in the construction guidance with your organization's policy expertise. Replace the Cedar placeholders with your own policy fragments. Keep the structure conformant to the [Agent Skills open standard](https://agentskills.io).

---

## What these templates are

A skill is a packaged body of expertise an agent loads on demand. These templates provide the **shape** of the policy skill pattern — the file structure, the activation contract, the proposal format, the evaluation criteria. They do **not** provide your organization's policy reasoning or sensitivity taxonomy. That's the work.

The pattern splits into two complementary skills:

| Skill | Role | What it produces |
|-------|------|------------------|
| [`policy-generator-skill/`](policy-generator-skill/) | Constructor | Paired policy proposals: a Cedar fragment + a structured justification |
| [`policy-evaluation-skill/`](policy-evaluation-skill/) | Judge | A structured verdict (approve/reject with reasoning) against six criteria |

The separation is the point. The agent that benefits from a boundary expansion should not evaluate its own request. The generator produces proposals; the evaluator applies independent judgment.

---

## Activation contract

**Policy-generator skill** activates when an agent encounters a boundary condition: a tool call denied by the deterministic enforcement layer, or recognition that a planned action will be denied. Once activated, the skill walks the agent through proposal construction and produces a paired output — a Cedar fragment and a structured justification.

**Policy-evaluation skill** activates when an evaluator (LLM-as-judge or hybrid pipeline) receives a proposal to judge. It applies six criteria covering justification completeness, scope minimality, sensitivity accuracy, Cedar correctness, shape discipline, and authorization citability. All six must pass.

---

## What's opinionated, what's agnostic

**Opinionated about:**

- File structure, conformant to the Agent Skills open standard.
- The two-part proposal format: every proposal pairs a Cedar fragment with a structured justification.
- The six-criterion evaluation framework.
- The architectural separation: construction and evaluation must be independent.
- The deny-all baseline. The enforcement environment is assumed to start from `forbid`; proposals are additive permits.
- Cedar as the primary policy language.
- The principle of least privilege — in scope, in time, in sensitivity.

**Agnostic about:**

- Decision criteria for what justifies an expansion. That is your organization's policy expertise.
- Time-bound durations, attestation conventions, scope rules.
- Specific Cedar policy content. Templates show the shape, not the content.
- Justification field semantics beyond the required fields.
- The enforcement layer's dialect (AgentCore, OPA, custom).

---

## What to fork

Fork everything under `template/`. Customize:

### Policy-generator skill

| File | What to change |
|------|----------------|
| `policy-generator-skill/SKILL.md` | Update `metadata` (your org/author/version). Refine activation conditions to match your enforcement layer's deny signals. Refine the justification field set to match your evaluator's expectations. |
| `policy-generator-skill/assets/template.cedar` | Replace placeholders with your organization's policy fragment shape. Adapt the default `when` clause if your typical requests aren't time-bounded. |
| `policy-generator-skill/assets/cedar-syntax.md` | Adjust the Cedar reference to match your dialect or extensions. |
| `policy-generator-skill/scripts/write-proposal.py` | Replace the stub body with your incorporation pipeline's logic. |

### Policy-evaluation skill

| File | What to change |
|------|----------------|
| `policy-evaluation-skill/SKILL.md` | Fill in the `[ORG: ...]` markers with your sensitivity taxonomy, shape rules, dialect-specific Cedar rules, and authorization-basis requirements. Update `metadata`. |

Do **not** change:

- The frontmatter shape in either `SKILL.md`. It must validate against the Agent Skills spec.
- The directory layout. Progressive disclosure depends on it.
- The two-part proposal contract. Every proposal is a Cedar fragment plus a structured justification.

Recommendations (not requirements)
The criteria framework starts at six sourced from the AWS Well-Architected Generative AI Lens. Add, remove, or replace criteria based on your organization's policy needs. A few worth keeping unless you have specific reason not to:
- A criterion that examines sensitivity accuracy. Without it, the agent's sensitivity claims go unchecked and the evaluator has no basis for shape discipline rules.
- A hard rule on permanent grants for sensitive writes. Time-bounded sensitive writes are recoverable through expiration; permanent ones aren't. The risk asymmetry justifies a hard rule unless your context genuinely doesn't include sensitive writes.
- A criterion that requires authorization citability. A proposal that can't cite a policy basis is a proposal that depends on the agent's judgment alone, which defeats the curated-expertise claim.

These are recommendations from the reference implementation. Your organization's policy framework should drive what you keep, change, or replace.

---

## On Cedar specifically

[Cedar](https://www.cedarpolicy.com/) is the primary policy language because Amazon Bedrock AgentCore Policy uses it for deterministic enforcement, and because Cedar's design is well-suited to fine-grained authorization with context conditions.

If you enforce with OPA/Rego, XACML, or a proprietary policy language, fork `policy-generator-skill/assets/template.cedar` and `policy-generator-skill/assets/cedar-syntax.md` and rewrite them in your language. The construction guidance in the generator SKILL.md, the justification structure, and the evaluation criteria are policy-language-agnostic — only the Cedar-specific assets and the sections that name Cedar need updating. Criterion 4 in the evaluation skill will also need dialect-specific rules.

---

## Integration

After forking, you need to wire the skills into your agent framework. The skills are plain directories conformant to the [Agent Skills open standard](https://agentskills.io) — any skills-compatible framework can load them.

### Strands (with AgentSkills plugin)

```python
from strands import Agent
from strands.vended_plugins.skills import AgentSkills

# Actor agent — loads the policy-generator skill
actor = Agent(
    plugins=[AgentSkills(skills="path/to/your-policy-generator-skill")],
    tools=[mcp_client, submit_proposal, refresh_gateway_tools, ...],
    ...
)

# Judge agent — loads the policy-evaluation skill
judge = Agent(
    plugins=[AgentSkills(skills="path/to/your-policy-evaluation-skill")],
    tools=[],
    ...
)
```

The `AgentSkills` plugin reads `SKILL.md` frontmatter and injects skill metadata into the agent's context. The agent activates the skill autonomously when its activation conditions are met — you don't need to trigger it manually.

### Other frameworks

Any framework that supports the Agent Skills standard can load these skills. The key contract:
- Read `SKILL.md` frontmatter for metadata (name, description, activation conditions).
- Make the full `SKILL.md` content available to the model as context when the skill activates.
- Make `assets/` files accessible to the model (the skill references them by relative path).
- For the generator: provide a submission mechanism (the `scripts/write-proposal.py` stub, or your equivalent tool).

### What you need to build

The skills provide the *reasoning* — construction guidance and evaluation criteria. You provide the *plumbing*:

| Component | What it does | Example |
|-----------|-------------|---------|
| `submit_proposal` tool | Hands the paired proposal to your evaluator | See sample's `customer_service_agent/agent.py` |
| Evaluator agent/pipeline | Loads the evaluation skill and judges proposals | See sample's `policy_evaluator_agent/judge.py` |
| Incorporator | Writes approved policy into the enforcement layer | `create_policy()` on AgentCore, OPA API, etc. |
| `refresh_gateway_tools` | Re-fetches available tools after incorporation | Framework-specific; re-reads MCP `tools/list` |

See [`samples/customer-service-assistant/`](../samples/customer-service-assistant/) for a working implementation of all four.

---

## On evaluation specifically

The generator produces proposals. Something has to evaluate them before they become enforced policy. Common choices:

- **HITL approval.** Conservative; matches the `Y/T/N` pattern familiar from Claude Code, Kiro, and similar harnesses.
- **LLM-as-judge.** Mature evaluation pattern; applies cleanly to policy proposals. The structured justification fields are designed to give a judge enough context for a confident decision.
- **Hybrid.** Routine decisions to the judge, high-stakes decisions to humans. The `sensitivity_factors` field is a natural routing signal.

The evaluation skill template provides the criteria framework regardless of which evaluation mechanism you use. For LLM-as-judge, load the evaluation skill directly. For HITL, the criteria serve as a rubric the human reviewer applies. For hybrid, use `sensitivity_factors` to route.

---

## Validation

```
skills-ref validate ./policy-generator-skill
skills-ref validate ./policy-evaluation-skill
```

See [skills-ref](https://github.com/agentskills/agentskills/tree/main/skills-ref).

---

*Part of the [Long-Running Agents](../../README.md) series by Michael Butler.*
