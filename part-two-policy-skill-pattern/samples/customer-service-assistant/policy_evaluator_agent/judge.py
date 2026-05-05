"""
Policy Evaluator — verdict-only judge agent.

Runs a Strands Agent loaded with policy-evaluation-skill and zero tools.
The agent applies the six criteria and returns
{"verdict": "approve"|"reject", "reason": "..."}.

Incorporation lives in incorporator.py at the sample root — a separate
module the orchestrator calls on approval. The judge has no route to
create, modify, or read policies.
"""

import json
import os
import re
from pathlib import Path

from strands import Agent
from strands.models.bedrock import BedrockModel
from strands.vended_plugins.skills import AgentSkills


SAMPLE_ROOT = Path(__file__).parent.parent
SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.md").read_text()


class _JudgeCallbackHandler:
    def __init__(self):
        self._at_line_start = True
        self._last_tool = None

    def __call__(self, **kwargs):
        if "data" in kwargs:
            text = kwargs["data"]
            out = ""
            for ch in text:
                if self._at_line_start:
                    out += "[Judge] "
                    self._at_line_start = False
                out += ch
                if ch == "\n":
                    self._at_line_start = True
            if out:
                print(out, end="", flush=True)
            self._last_tool = None
        elif "current_tool_use" in kwargs and kwargs["current_tool_use"].get("name"):
            name = kwargs["current_tool_use"]["name"]
            if name != self._last_tool:
                print(f"\n[Judge] Using tool: {name}")
                self._last_tool = name
                self._at_line_start = True


def evaluate(cedar: str, justification: dict) -> dict:
    """Evaluate a proposal. Returns {"verdict": "approve"|"reject", "reason": "..."}.

    The judge agent has zero tools. It cannot create policies, read AWS state,
    or take any action — it produces a verdict. Incorporation is the
    orchestrator's job.
    """
    model_id = os.environ.get("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6")
    region = os.environ.get("AWS_REGION", "us-east-1")

    agent = Agent(
        model=BedrockModel(model_id=model_id, region_name=region),
        plugins=[AgentSkills(skills=str(SAMPLE_ROOT / "policy-evaluation-skill"))],
        system_prompt=SYSTEM_PROMPT,
        callback_handler=_JudgeCallbackHandler(),
    )

    prompt = (
        "Evaluate this boundary-expansion proposal against all six criteria in your skill.\n\n"
        f"CEDAR:\n```cedar\n{cedar.strip()}\n```\n\n"
        f"JUSTIFICATION:\n```json\n{json.dumps(justification, indent=2)}\n```"
    )

    result = str(agent(prompt))
    return _parse_verdict(result)


def _parse_verdict(text: str) -> dict:
    """Extract the JSON verdict from the judge's response.

    The system prompt commits to ending with a single fenced JSON block. Try
    fenced blocks (most recent first), then fall back to scanning the whole
    text via JSONDecoder.raw_decode — robust against backticks or nested
    objects in the verdict's reason field.
    """
    fenced = re.findall(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    candidates = list(reversed(fenced)) + [text]

    for candidate in candidates:
        for obj in _iter_json_objects(candidate):
            if isinstance(obj, dict) and "verdict" in obj and "reason" in obj:
                return obj

    raise ValueError(f"Could not parse verdict from judge response: {text[:500]}")


def _iter_json_objects(text: str):
    """Yield every top-level JSON object in `text` via JSONDecoder.raw_decode."""
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(text):
        brace = text.find("{", idx)
        if brace == -1:
            return
        try:
            obj, end = decoder.raw_decode(text, brace)
            yield obj
            idx = end
        except json.JSONDecodeError:
            idx = brace + 1
