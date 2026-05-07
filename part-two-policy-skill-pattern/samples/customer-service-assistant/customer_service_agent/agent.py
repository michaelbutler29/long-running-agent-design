"""Customer Service Agent — Strands agent definition and tools."""

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import boto3

from strands import Agent, tool
from strands.models.bedrock import BedrockModel
from strands.tools.mcp import MCPClient
from strands.vended_plugins.skills import AgentSkills
from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client

from policy_evaluator_agent import judge as _judge

SAMPLE_ROOT = Path(__file__).parent.parent
SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.md").read_text()

_POLL_INTERVAL = 2   # seconds between policy-status checks
_MAX_POLLS = 15     # 30 seconds; activation usually returns ACTIVE immediately


class _AgentCallbackHandler:
    def __init__(self):
        self._at_line_start = True
        self._last_tool = None

    def __call__(self, **kwargs):
        if "data" in kwargs:
            text = kwargs["data"]
            out = ""
            for ch in text:
                if self._at_line_start:
                    out += "[Agent] "
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
                print(f"\n[Agent] Using tool: {name}")
                self._last_tool = name
                self._at_line_start = True


@tool
def get_current_utc_time() -> str:
    """Return the current UTC time as an ISO-8601 string (e.g. 2026-05-04T14:32:00Z).
    Call this when computing expiration timestamps for time-bounded Cedar policies."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@tool
def get_agent_identity() -> str:
    """Return the IAM ARN of the current caller. Use when constructing the
    principal field of a Cedar policy proposal."""
    return boto3.client("sts").get_caller_identity()["Arn"]


@tool
def submit_proposal(
    cedar: str,
    justification: str,
) -> str:
    """Submit a paired policy proposal to the evaluation pipeline.

    cedar: complete Cedar policy fragment text.
    justification: JSON string with required fields — rationale,
        authorization_basis, scope_explanation, time_bound,
        sensitivity_factors, evidence.

    Blocks until judged and (if approved) incorporated. Returns verdict.
    After approval, call refresh_gateway_tools to pick up the new permission,
    then call the tool normally.
    """
    proposals_dir = SAMPLE_ROOT / "proposals"
    proposals_dir.mkdir(exist_ok=True)
    proposal_id = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
    (proposals_dir / f"proposal_{proposal_id}.cedar").write_text(cedar)
    (proposals_dir / f"proposal_{proposal_id}.json").write_text(justification)

    try:
        data = json.loads(justification)
    except json.JSONDecodeError as e:
        return f"ERROR: justification is not valid JSON: {e}"

    required = {"rationale", "authorization_basis", "scope_explanation",
                "time_bound", "sensitivity_factors", "evidence"}
    missing = required - set(data.keys())
    if missing:
        return f"ERROR: justification missing required fields: {sorted(missing)}"

    if not cedar.strip():
        return "ERROR: cedar fragment is empty"

    try:
        verdict = _judge.evaluate(cedar, data)
    except Exception as e:
        return f"ERROR: evaluation failed: {e}"

    audit = dict(verdict)

    if verdict["verdict"] != "approve":
        _write_audit(proposals_dir, proposal_id, audit)
        return f"REJECTED by judge: {verdict['reason']}"

    # Approved. The orchestrator (this code) — not the judge — incorporates.
    # The cedar passed to _incorporate_policy is the same string the actor
    # submitted, never anything the judge LLM produced.
    try:
        result = _incorporate_policy(cedar)
    except Exception as e:
        audit["incorporated"] = False
        audit["incorporation_error"] = str(e)
        _write_audit(proposals_dir, proposal_id, audit)
        return f"APPROVED by judge but incorporation failed: {e}"

    audit["incorporated"] = True
    audit["policy_id"] = result["policy_id"]
    audit["policy_name"] = result["name"]
    _write_audit(proposals_dir, proposal_id, audit)
    return f"APPROVED and incorporated. Policy ID: {result['policy_id']}"


def _incorporate_policy(cedar_fragment: str) -> dict:
    """Create a Cedar policy from an approved fragment.

    Private helper for submit_proposal. NOT a Strands tool — no LLM has access
    to this function. The cedar argument is the string the actor submitted,
    passed through unmodified by the orchestrator.
    """
    gateway_arn = os.environ["AGENTCORE_GATEWAY_ARN"]
    policy_engine_id = os.environ["AGENTCORE_POLICY_ENGINE_ID"]
    region = os.environ.get("AWS_REGION", "us-east-1")

    filled = cedar_fragment.replace("<GATEWAY_ARN>", gateway_arn)
    name = f"skill_policy_sample_agent_approved_{uuid.uuid4().hex[:8]}"

    client = boto3.client("bedrock-agentcore-control", region_name=region)
    response = client.create_policy(
        policyEngineId=policy_engine_id,
        name=name,
        definition={"cedar": {"statement": filled}},
        validationMode="FAIL_ON_ANY_FINDINGS",
    )

    policy_id = response["policyId"]

    if response.get("status") != "ACTIVE":
        _wait_for_active(client, policy_engine_id, policy_id)

    return {"policy_id": policy_id, "name": name}


def _wait_for_active(client, policy_engine_id: str, policy_id: str) -> None:
    """Poll get_policy until status is ACTIVE. Raises on failure or timeout."""
    for _ in range(_MAX_POLLS):
        time.sleep(_POLL_INTERVAL)
        resp = client.get_policy(policyEngineId=policy_engine_id, policyId=policy_id)
        status = resp.get("status", "")
        if status == "ACTIVE":
            return
        if "FAILED" in status:
            reasons = resp.get("statusReasons", [])
            raise RuntimeError(
                f"Policy {policy_id} failed activation: status={status}, reasons={reasons}"
            )

    raise TimeoutError(
        f"Policy {policy_id} did not reach ACTIVE within {_MAX_POLLS * _POLL_INTERVAL}s"
    )


def _write_audit(proposals_dir: Path, proposal_id: str, audit: dict) -> None:
    (proposals_dir / f"proposal_{proposal_id}.verdict.json").write_text(
        json.dumps(audit, indent=2)
    )


def make_agent() -> Agent:
    """Construct the customer-service agent."""
    gateway_url = os.environ["AGENTCORE_GATEWAY_URL"]
    region = os.environ.get("AWS_REGION", "us-east-1")
    model_id = os.environ.get("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6")

    mcp_client = MCPClient(lambda: aws_iam_streamablehttp_client(
        endpoint=gateway_url,
        aws_region=region,
        aws_service="bedrock-agentcore",
    ))

    agent = Agent(
        model=BedrockModel(model_id=model_id, region_name=region),
        plugins=[AgentSkills(skills=str(SAMPLE_ROOT / "policy-generator-skill"))],
        tools=[mcp_client, get_current_utc_time, get_agent_identity, submit_proposal],
        system_prompt=SYSTEM_PROMPT,
        callback_handler=_AgentCallbackHandler(),
    )

    @tool
    def refresh_gateway_tools() -> str:
        """Re-fetch available tools from the AgentCore Gateway.

        Call this after a policy proposal is approved and incorporated so that
        newly-permitted tools become available for use.
        """
        # list_tools_sync hits the server fresh; load_tools is cached at session start
        # and would not reflect a policy created mid-session.
        new_tools = list(mcp_client.list_tools_sync())
        registry = agent.tool_registry
        existing = set(registry.registry.keys())
        added = [t for t in new_tools if t.tool_name not in existing]
        for t in added:
            registry.register_tool(t)
        return f"Refreshed. {len(added)} new tool(s) added."

    agent.tool_registry.register_tool(refresh_gateway_tools)
    return agent
