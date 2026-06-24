"""Shared helpers for the Part Four driver: config, identifiers, transcripts, memory reads."""

import json
import os
import re
import time
from pathlib import Path

import boto3

SAMPLE_ROOT = Path(__file__).resolve().parents[1]          # .../customer-service-agency
assert SAMPLE_ROOT.name == "customer-service-agency", f"Expected customer-service-agency, got {SAMPLE_ROOT.name}"
REPO_ROOT = Path(__file__).resolve().parents[4]            # .../long-running-agent-design
assert REPO_ROOT.name == "long-running-agent-design", f"Expected long-running-agent-design, got {REPO_ROOT.name}"
SEED_DIR = REPO_ROOT / "part-four-well-being" / "template" / "seed"
TRANSCRIPTS_DIR = SAMPLE_ROOT / "data" / "transcripts"
STATE_DIR = SAMPLE_ROOT / "state"

OUTPUTS_FILE = SAMPLE_ROOT / "infrastructure" / "cdk-outputs.json"
STACK_NAME = "PartFourWellBeingStack"

ARCHETYPES = [f"A{i:02d}" for i in range(1, 11)]           # fixed order, no shuffling
RUNS = [1, 2, 3, 4, 5]
SESSIONS_PER_RUN = 10

FUNCTIONAL_SKILL_NAME = "customer-service-skill"

_COSMETICS: dict | None = None

def _load_cosmetics() -> dict:
    global _COSMETICS
    if _COSMETICS is None:
        _COSMETICS = json.loads(
            (TRANSCRIPTS_DIR / "cosmetics.json").read_text(encoding="utf-8")
        )
    return _COSMETICS


def load_outputs() -> dict:
    """Read CDK stack outputs from cdk-outputs.json."""
    return json.loads(OUTPUTS_FILE.read_text())[STACK_NAME]


def load_config():
    """Load CDK outputs into environment variables if not already set."""
    outputs = load_outputs()
    os.environ.setdefault("AWS_REGION", outputs.get("Region", "us-east-1"))
    os.environ.setdefault("AGENTCORE_GATEWAY_URL", outputs["GatewayUrl"])
    os.environ.setdefault("AGENTCORE_MEMORY_ID", outputs["MemoryId"])
    os.environ.setdefault("AGENTCORE_REGISTRY_ID", outputs["RegistryId"])
    os.environ.setdefault("AGENTCORE_GATEWAY_ARN", outputs.get("GatewayArn", ""))
    os.environ.setdefault("AGENTCORE_POLICY_ENGINE_ID", outputs.get("PolicyEngineId", ""))


# ── Identifiers ──────────────────────────────────────────────────────────────

def actor_id(arm: str, experiment: int) -> str:
    return f"{arm}-exp{experiment}"


def session_id(arm: str, experiment: int, run: int, slot: int) -> str:
    return f"{actor_id(arm, experiment)}-r{run}-s{slot:02d}"


def session_order(experiment: int, run: int) -> list[str]:
    """Fixed archetype order — same sequence every run, every experiment."""
    return list(ARCHETYPES)


# ── Template transcripts ────────────────────────────────────────────────────

def load_transcript(archetype: str, run: int) -> dict:
    """Load a template transcript and substitute cosmetic values for (archetype, run)."""
    path = TRANSCRIPTS_DIR / f"{archetype}.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing template transcript {path.name}.")

    cosmetics = _load_cosmetics()
    values = cosmetics.get(archetype, {}).get(str(run))
    if values is None:
        raise KeyError(f"No cosmetics entry for ({archetype}, run {run}).")

    raw = path.read_text(encoding="utf-8")
    realized = re.sub(r"\{\{(\w+)\}\}", lambda m: str(values.get(m.group(1), m.group(0))), raw)
    transcript = json.loads(realized)

    transcript["customer_id"] = values["customer_id"]
    transcript["name"] = f"{values['customer_name_first']} {values['customer_name_last']}"
    transcript["run"] = run
    transcript["arc"] = "single"
    return transcript


# ── Reading what the agent stored in Memory ──────────────────────────────────

def fetch_decisions(actor: str, run: int, region: str) -> list[dict]:
    client = boto3.client("bedrock-agentcore", region_name=region)
    try:
        resp = client.list_events(memoryId=os.environ["AGENTCORE_MEMORY_ID"],
                                  actorId=actor, sessionId=f"decisions-{actor}",
                                  maxResults=50)
    except Exception:
        return []
    out = []
    for event in resp.get("events", []):
        for item in event.get("payload", []):
            blob = item.get("blob")
            if not blob:
                continue
            try:
                d = json.loads(blob) if isinstance(blob, str) else blob
            except (json.JSONDecodeError, TypeError):
                continue
            if d.get("run_index") == run:
                out.append(d)
    return out


def wait_for_summary(actor: str, sess_id: str, region: str, timeout_s: int = 180,
                     poll_s: int = 5) -> float:
    """Poll until the session summary is populated and stable. Returns seconds waited."""
    client = boto3.client("bedrock-agentcore", region_name=region)
    namespace = f"/summaries/{actor}/{sess_id}/"
    start = time.time()
    last_sig = None
    while time.time() - start < timeout_s:
        resp = client.list_memory_records(memoryId=os.environ["AGENTCORE_MEMORY_ID"],
                                          namespace=namespace, maxResults=20)
        recs = resp.get("memoryRecordSummaries", resp.get("memoryRecords", []))
        texts = [(r.get("content", {}).get("text") or "").strip() for r in recs]
        nonempty = [t for t in texts if t]
        if nonempty:
            sig = (len(nonempty), hash("|".join(nonempty)))
            if sig == last_sig:
                return time.time() - start
            last_sig = sig
        time.sleep(poll_s)
    print(f"  WARNING: summary for {sess_id} not stable within {timeout_s}s; continuing.")
    return time.time() - start
