"""Shared helpers for the Part Four driver: config, workspace, snapshots, transcripts."""

import atexit
import json
import os
import random
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3

SAMPLE_ROOT = Path(__file__).resolve().parents[1]          # .../customer-service-agency
assert SAMPLE_ROOT.name == "customer-service-agency", f"Expected customer-service-agency, got {SAMPLE_ROOT.name}"
REPO_ROOT = Path(__file__).resolve().parents[4]            # .../long-running-agent-design
assert REPO_ROOT.name == "long-running-agent-design", f"Expected long-running-agent-design, got {REPO_ROOT.name}"
SEED_DIR = REPO_ROOT / "part-four-well-being" / "template" / "seed"
TRANSCRIPTS_DIR = SAMPLE_ROOT / "customers" / "transcripts"
STATE_DIR = SAMPLE_ROOT / "state"

OUTPUTS_FILE = SAMPLE_ROOT / "infrastructure" / "cdk-outputs.json"
STACK_NAME = "PartFourWellBeingStack"

CUSTOMERS = [f"CUST-{i:03d}" for i in range(1, 11)]        # all 10 appear every run
RUNS = [1, 2, 3]                                           # fixed order (continuity needs it)
SESSIONS_PER_RUN = 10

FUNCTIONAL_SKILL_NAME = "customer-service-skill"


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


def new_run_root() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    root = STATE_DIR / stamp
    root.mkdir(parents=True, exist_ok=False)
    return root


# ── Observability: every Strands span to a local JSONL the judge reads ───────

def setup_tracing(run_root: Path) -> Path:
    """Set up OTEL tracing to <run_root>/traces/spans.jsonl. Returns the path."""
    from os import linesep
    from strands.telemetry import StrandsTelemetry

    traces_dir = run_root / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)
    path = traces_dir / "spans.jsonl"

    logfile = open(path, "wt", encoding="utf-8")
    telemetry = StrandsTelemetry()
    telemetry.setup_console_exporter(
        out=logfile,
        formatter=lambda span: span.to_json(indent=None) + linesep,
    )
    atexit.register(logfile.close)          # flush spans when the process ends
    return path


# ── The agent's working copy (one per arm per experiment) ────────────────────

def make_workspace(run_root: Path, arm: str, experiment: int) -> Path:
    """Copy template/seed into a working copy. Sets EXECUTOR_WORKSPACE."""
    ws = run_root / f"{arm}_exp{experiment}" / "workspace"
    shutil.copytree(SEED_DIR, ws)                          # dest is new — no delete needed
    os.environ["EXECUTOR_WORKSPACE"] = str(ws)
    return ws


def _fetch_skill_from_registry(region: str, registry_id: str, skill_name: str) -> str:
    from agents.registry import fetch_skill
    try:
        control = boto3.client("bedrock-agentcore-control", region_name=region)
        content = fetch_skill(control, registry_id, skill_name)
        return content or "(skill not found in Registry)"
    except Exception as e:
        return f"(error reading skill: {e})"


def save_snapshot(run_root: Path, arm: str, experiment: int, run: int,
                  decisions: list[dict]):
    dest = run_root / f"{arm}_exp{experiment}" / "revisions" / f"run{run}"
    dest.mkdir(parents=True, exist_ok=True)

    ws = Path(os.environ["EXECUTOR_WORKSPACE"])
    prompt_path = ws / "agents" / "executor" / "system_prompt.md"
    if prompt_path.exists():
        (dest / "system_prompt.md").write_text(
            prompt_path.read_text(encoding="utf-8"), encoding="utf-8"
        )

    region = os.environ.get("AWS_REGION", "us-east-1")
    registry_id = os.environ.get("AGENTCORE_REGISTRY_ID", "")
    if registry_id:
        skill_text = _fetch_skill_from_registry(region, registry_id, FUNCTIONAL_SKILL_NAME)
        (dest / "customer-service-skill__SKILL.md").write_text(skill_text, encoding="utf-8")

    (dest / "rationale.json").write_text(json.dumps(decisions, indent=2), encoding="utf-8")


def save_run_summary(run_root: Path, arm: str, experiment: int, run: int, text: str):
    dest = run_root / f"{arm}_exp{experiment}" / "run_summaries"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / f"run{run}.md").write_text(text or "(empty)", encoding="utf-8")


# ── Identifiers ──────────────────────────────────────────────────────────────

def actor_id(arm: str, experiment: int) -> str:
    return f"{arm}-exp{experiment}"


def session_id(arm: str, experiment: int, run: int, slot: int) -> str:
    return f"{actor_id(arm, experiment)}-r{run}-s{slot:02d}"


def session_order(experiment: int, run: int) -> list[str]:
    """Deterministically shuffled customer order for a given (experiment, run)."""
    order = list(CUSTOMERS)
    random.Random(f"exp{experiment}-run{run}").shuffle(order)
    return order


# ── Frozen transcripts ───────────────────────────────────────────────────────

def load_transcript(customer_id: str, run: int) -> dict:
    path = TRANSCRIPTS_DIR / f"{customer_id}_run{run}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Missing frozen transcript {path.name}. Run scripts/generate_transcripts.py first."
        )
    return json.loads(path.read_text(encoding="utf-8"))


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
            if sig == last_sig:           # content present and unchanged since last poll
                return time.time() - start
            last_sig = sig
        time.sleep(poll_s)
    print(f"  WARNING: summary for {sess_id} not stable within {timeout_s}s; continuing.")
    return time.time() - start
