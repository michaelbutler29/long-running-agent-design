# Part Two: The Policy Skill Pattern

Companion artifacts for Part Two of the *Long-Running Agents* series: *Reasoning About Boundaries: The Policy Skill Pattern*. (Article link forthcoming.)

---

## The pattern

An actor agent starts with minimal permissions — a deny-all baseline with a few explicit permits. When the agent hits a boundary (a tool call denied by the deterministic enforcement layer), it activates a **policy-generator skill** that walks it through constructing a paired proposal: a Cedar policy fragment expressing the requested expansion, plus a structured justification explaining why. An independent **policy-evaluation skill** (loaded by a separate evaluator agent, LLM-as-judge) evaluates the proposal against six criteria. On approval, deterministic code writes the policy into the enforcement layer. The actor agent refreshes its available tools and proceeds.

The agent that benefits from a boundary expansion does not evaluate its own request. Construction and evaluation are independent skills with independent judgment.

Two proposal shapes cover most cases:
- **Permanent** — for read access or low-sensitivity utilities (no time gate in the Cedar `when` clause).
- **Time-bounded** — for writes, PII operations, or sensitive actions (Cedar `when` clause carries a datetime expiration).

---

## What's here

| Path | What it is |
|------|-----------|
| [`template/`](template/) | The template skills: a policy-generator skill (produces proposals) and a policy-evaluation skill (judges them). Fork these and fill in your organization's policy expertise. |
| [`samples/customer-service-assistant/`](samples/customer-service-assistant/) | A working proof-of-concept against AWS AgentCore Gateway and Cedar Policy Engine. Deploys required AWS resources (e.g., Amazon Bedrock AgentCore, Amazon DynamoDB, AWS Lambda), runs both proposal shapes, and demonstrates a reject case (via demo_reject.py). |

The **template** contains the baseline Policy Skill Pattern, using Cedar as the policy language, the Agent Skills open standard for packaging, and six evaluation criteria based on the AWS Well-Architected Framework Generative AI Lens, GENSEC05-BP01.

The **sample** demonstrates end-to-end functionality. A customer service agent hits permission boundaries on AgentCore Gateway, proposes expansions, gets judged, and proceeds. The domain (customer service) is deliberately simple to keep focus on evaluating the *reasoning* without needing domain expertise.

---

## Run the demo

The sample deploys AWS resources (Amazon DynamoDB tables, AWS Lambda functions, an Amazon Bedrock AgentCore Gateway with Policy Engine) in `us-east-1`. See [`samples/customer-service-assistant/`](samples/customer-service-assistant/) for the complete setup-to-teardown guide.

Quick version:

```bash
cd samples/customer-service-assistant
python -m venv .venv
source .venv/bin/activate # PowerShell: .venv\Scripts\Activate.ps1
pip install -e .
cd infrastructure && cdk bootstrap aws://<account-id>/us-east-1 && cdk deploy --outputs-file cdk-outputs.json && cd ..
cp .env.example .env  # optional: override AWS_REGION or BEDROCK_MODEL_ID
python seed_policy.py # populates a first, baseline policy in AgentCore Policy
python main.py        # runs both approve scenarios
python demo_reject.py # demonstrates the judge rejecting a broken proposal
```

Teardown: `python cleanup.py && cd infrastructure && cdk destroy`.

---

## What's not here

- **Runtime enforcement.** Intercepting tool calls and applying Cedar policy is the gateway's job (AgentCore Gateway, or your equivalent). This project produces and evaluates proposals — it does not enforce them.
- **HITL evaluation UI.** The evaluation skill provides the criteria framework; wiring it to a human approval interface is deployment-specific.
- **Multi-tenancy or production observability.** The sample is a proof-of-concept, not a production deployment.

---

## Validation

Validate the template skills against the [Agent Skills open standard](https://agentskills.io) with [`skills-ref`](https://github.com/agentskills/agentskills/tree/main/skills-ref):

```
skills-ref validate ./template/policy-generator-skill
skills-ref validate ./template/policy-evaluation-skill
```

---

*Part of the [Long-Running Agents](../README.md) series by Michael Butler.*
