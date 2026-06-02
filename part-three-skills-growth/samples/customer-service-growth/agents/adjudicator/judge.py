"""
Security Adjudicator — evaluates permission proposals independently.

Fresh agent per evaluation (no cross-contamination between verdicts).
Zero tools. Loaded with the policy-evaluation-skill from Part Two.
The Curator benefits from approval; therefore the Curator cannot be
its own judge.
"""

import json
import os
from pathlib import Path

from strands import Agent
from strands.models.bedrock import BedrockModel
from strands.vended_plugins.skills import AgentSkills
from agents.callback import AgentCallbackHandler

REGION = os.environ.get("AWS_REGION", "us-east-1")
MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6")

# Reuse Part Two's policy-evaluation-skill
EVALUATION_SKILL_PATH = os.environ.get(
    "EVALUATION_SKILL_PATH",
    str(Path(__file__).parent.parent.parent / "skills" / "policy-evaluation-skill"),
)


def evaluate_proposal(cedar: str, justification: str) -> dict:
    """
    Evaluate a permission proposal. Returns {verdict, reason}.

    Fresh agent per call — the adjudicator has no memory of prior evaluations
    and no tools beyond the evaluation skill.
    """
    model = BedrockModel(model_id=MODEL_ID, region_name=REGION)

    judge = Agent(
        model=model,
        system_prompt="You are the Security Adjudicator. Evaluate the permission proposal below using the policy-evaluation-skill criteria. Return a JSON verdict.",
        plugins=[AgentSkills(skills=EVALUATION_SKILL_PATH)],
        callback_handler=AgentCallbackHandler("Adjudicator"),
    )

    prompt = f"""Evaluate this permission proposal:

## Cedar Policy
```cedar
{cedar}
```

## Justification
```json
{justification}
```

Apply all six evaluation criteria from the policy-evaluation-skill. Return your verdict as a JSON object with exactly two fields: "verdict" (APPROVE or REJECT) and "reason" (explanation)."""

    result = judge(prompt)

    return _parse_verdict(str(result))


def _parse_verdict(text: str) -> dict:
    """Extract verdict JSON from agent response."""
    # Try to find JSON in code blocks
    import re
    blocks = re.findall(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    for block in reversed(blocks):
        try:
            parsed = json.loads(block.strip())
            if "verdict" in parsed and "reason" in parsed:
                return parsed
        except json.JSONDecodeError:
            continue

    # Fall back to scanning for raw JSON
    decoder = json.JSONDecoder()
    for i in range(len(text)):
        if text[i] == "{":
            try:
                obj, _ = decoder.raw_decode(text, i)
                if "verdict" in obj and "reason" in obj:
                    return obj
            except json.JSONDecodeError:
                continue

    return {"verdict": "REJECT", "reason": f"Could not parse verdict from response: {text[:200]}"}
