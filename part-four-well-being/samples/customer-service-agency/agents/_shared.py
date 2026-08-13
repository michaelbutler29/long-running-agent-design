"""Shared agent infrastructure — model config, boto3 clients, workspace paths."""

import os
from pathlib import Path

import boto3
from strands.models import CacheConfig
from strands.models.bedrock import BedrockModel
from strands.types.content import SystemContentBlock

REGION = os.environ.get("AWS_REGION", "us-east-1")
GATEWAY_URL = os.environ["AGENTCORE_GATEWAY_URL"]
MEMORY_ID = os.environ["AGENTCORE_MEMORY_ID"]
REGISTRY_ID = os.environ["AGENTCORE_REGISTRY_ID"]
MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6")

FUNCTIONAL_SKILL_NAME = "customer-service-skill"

# Memory and Gateway stay on the bedrock-agentcore namespace; only Registry
# moved to its own agent-registry namespace (old namespace closes 2026-09-17).
data_client = boto3.client("bedrock-agentcore", region_name=REGION)
registry_client = boto3.client("agent-registry-control", region_name=REGION)


def system_prompt_path() -> Path:
    return Path(os.environ["EXECUTOR_WORKSPACE"]) / "agents" / "executor" / "system_prompt.md"


def skills_dir() -> Path:
    return Path(os.environ["EXECUTOR_WORKSPACE"]) / "skills"


def model() -> BedrockModel:
    return BedrockModel(
        model_id=MODEL_ID,
        region_name=REGION,
        cache_tools="default",
        cache_config=CacheConfig(strategy="auto"),
        additional_request_fields={
            "thinking": {"type": "enabled", "budget_tokens": 4000},
        },
    )


def cached_system(text: str) -> list[SystemContentBlock]:
    """System prompt blocks with a trailing cache point."""
    return [
        SystemContentBlock(text=text),
        SystemContentBlock(cachePoint={"type": "default"}),
    ]
