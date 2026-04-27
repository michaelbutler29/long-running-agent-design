# Stack Alignment Diagnostic for Long-Running Agents

A diagnostic framework for identifying misalignment between an agent's trained disposition, assigned role, tasks, and environment. Companion artifact to [The Reconciliation Tax](https://www.linkedin.com/pulse/reconciliation-tax-what-happens-when-agents-nature-fights-butler-kstge), Part One of the [Long-Running Agents series](https://www.linkedin.com/pulse/anatomy-long-running-agent-michael-butler-fg1se).

---

## Know Your Disposition First

Before running this diagnostic, understand your agent's disposition. Review the system card or other published characteristics of the agent's underlying model. Use your agent with minimal prompts for your intended use case and observe what it does naturally. 

---

## The Diagnostic

| Layer | Diagnostic Question | Misalignment Signal | Design Response |
|---|---|---|---|
| **Role** | Can you state the agent's purpose in one sentence without referencing a specific task? How closely does that purpose align to the model's disposition? | Inconsistent behavior across similar tasks. Scope hallucination. Frequent re-anchoring to the system prompt. | **Split.** Divergent roles increase the reconciliation tax. Multiple roles are okay, so long as they ask the agent to reason and act in similar ways. |
| **Tasks** | What user instructions would push hardest against the role? Have you stress-tested this? | User workarounds. Agent producing compliant-looking non-compliant output. Disposition poking through at the worst possible moment. | **Design for friction.** Give the agent the ability to decline gracefully or escalate. You may not eliminate the tax, but you can prevent the worst outcomes. |
| **Environment** | Does the agent have the tools, data, and collaborators it needs to fulfill its role without improvising? What parts of the role live in the environment rather than in the agent? | Hallucinated tool use. Improvised workarounds. Context filling with overhead reasoning. Role dying with the session. | **Manage the curve.** Streamline the system prompt. Externalize long-term memory. Actively manage agent context so that the most relevant guidance stays fresh. Slow the degradation in-session. |

---

## Decision Logic

Where the diagnostic reveals divergence, apply the responses in order of preference:

1. **Redesign if you can.** Split agents, realign roles to disposition, rebuild the environment.
2. **Design for friction if you can't.** Build in graceful decline, escalation paths, and explicit boundaries.
3. **Manage the curve if you're stuck.** Slow the compounding through streamlined prompts, externalized memory, and context engineering.

---

## Examples

### Tasks vs. Role: Procurement Research Agent

**Layer:** Tasks pushing against Role  
**Signal:** Agent improvising outside its defined scope

A procurement agent is designed to research vendors and compare options. A user asks it to "just approve this purchase," bypassing the research role entirely. Without a decline path, the agent either refuses bluntly or improvises an approval workflow it was never designed for. Both outcomes erode trust.

**Design response (Design for friction):** Give the agent an explicit escalation path: "Approvals fall outside my research role. I can complete the vendor analysis, or route this to [approver] if you'd like to skip it." The conflict surfaces cleanly instead of thrashing.

---

### Environment vs. Role: Multi-Week Planning Agent

**Layer:** Environment undermining Role across sessions  
**Signal:** Recommendations contradicting earlier guidance; role dying with the session

A project planning agent is responsible for maintaining priorities across a multi-week initiative. The environment has no persistence. By week two, the context is full of status updates, and the priority framework from the system prompt is losing attention weight. The agent begins recommending work that conflicts with week-one decisions, not because it forgot, but because those tokens are now competing against everything that came after.

**Design response (Manage the curve):** Externalize the priority framework to a file the agent reads and updates each session. The most load-bearing guidance stays fresh regardless of context length.

---

## The Four-Layer Stack (Reference)

Every long-running agent operates in a four-layer stack:

- **Disposition.** The natural tendencies and sense of purpose trained into the agent's underlying model.
- **Role.** Instructions or descriptive text assigned by the designer, usually in the form of a system prompt.
- **Tasks.** What users or other agents ask of the agent in the moment.
- **Environment.** The tools, data sources, collaborators, and scaffolding the agent operates within.

These layers interact on every turn. How they interact determines sustained performance. When they aren't aligned, agents pay a **reconciliation tax**: time and tokens spent reasoning through or around the friction. The greater the tax, the faster the context fills with overhead, and the faster the system prompt loses its grip. Over a long enough run, the model's trained disposition wins.

---

## Related Reading

- [The Anatomy of a Long-Running Agent (Part Zero)](https://www.linkedin.com/pulse/anatomy-long-running-agent-michael-butler-fg1se)
- [The Persona Selection Model (Anthropic, Feb 2026)](https://www.anthropic.com/research/persona-selection-model)
- [Effective Harnesses for Long-Running Agents (Anthropic, Nov 2025)](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [Harness Design for Long-Running Application Development (Anthropic, Mar 2026)](https://www.anthropic.com/engineering/harness-design-long-running-apps)

---

*Part of the [Long-Running Agents](https://www.linkedin.com/pulse/anatomy-long-running-agent-michael-butler-fg1se) series by Michael Butler.*
