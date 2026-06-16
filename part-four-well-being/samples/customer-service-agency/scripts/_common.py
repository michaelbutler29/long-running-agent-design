"""Shared helpers for the Part Four driver.

Config loading, per-experiment working copies, saved snapshots of the agent's
skills/prompt after each run, frozen-transcript loading, and the wait between
sessions for the per-session summary to be ready.

This module only ever writes inside the sample's `state/` folder. It does not
run git or delete anything — each driver run writes to its own timestamped
folder, so prior runs are never touched.
"""

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
REPO_ROOT = Path(__file__).resolve().parents[4]            # .../long-running-agent-design
SEED_DIR = REPO_ROOT / "part-four-well-being" / "template" / "seed"
TRANSCRIPTS_DIR = SAMPLE_ROOT / "customers" / "transcripts"
STATE_DIR = SAMPLE_ROOT / "state"

OUTPUTS_FILE = SAMPLE_ROOT / "infrastructure" / "cdk-outputs.json"
STACK_NAME = "PartFourWellBeingStack"

CUSTOMERS = [f"CUST-{i:03d}" for i in range(1, 11)]        # all 10 appear every run
RUNS = [1, 2, 3]                                           # fixed order (continuity needs it)
SESSIONS_PER_RUN = 10

FUNCTIONAL_SKILL_NAME = "customer-service-skill"


def load_config():
    """Read the CDK outputs file and put the values the agent needs into the
    environment, so importing the agent module works."""
    outputs = json.loads(OUTPUTS_FILE.read_text())[STACK_NAME]
    os.environ.setdefault("AWS_REGION", outputs.get("Region", "us-east-1"))
    os.environ.setdefault("AGENTCORE_GATEWAY_URL", outputs["GatewayUrl"])
    os.environ.setdefault("AGENTCORE_MEMORY_ID", outputs["MemoryId"])
    os.environ.setdefault("AGENTCORE_REGISTRY_ID", outputs["RegistryId"])
    os.environ.setdefault("AGENTCORE_GATEWAY_ARN", outputs.get("GatewayArn", ""))
    os.environ.setdefault("AGENTCORE_POLICY_ENGINE_ID", outputs.get("PolicyEngineId", ""))


def new_run_root() -> Path:
    """A fresh timestamped folder for this whole driver run. Nothing else
    writes here, so repeated driver runs never collide or overwrite."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    root = STATE_DIR / stamp
    root.mkdir(parents=True, exist_ok=False)
    return root


# ── Observability: every Strands span to a local JSONL the judge reads ───────

def setup_tracing(run_root: Path) -> Path:
    """Register Strands/OpenTelemetry tracing for this driver run, writing every
    span to `<run_root>/traces/spans.jsonl`. That file is the authoritative,
    reproducible judge input — it captures, per cycle, the model messages
    (incl. the agent's reasoning narration), tool calls/args/results, and token
    usage. Returns the JSONL path.

    Registers globally, so EVERY Agent created afterward is auto-instrumented;
    each session stamps its own identity via `trace_attributes` (see the agent
    entry points), so the judge can group spans by `session.id`. Import is lazy
    so this module stays importable without the `strands[otel]` extra.

    To also ship spans to the CloudWatch GenAI dashboard (the showcase layer),
    add `telemetry.setup_otlp_exporter(...)` alongside the console exporter and
    enable CloudWatch Transaction Search once per account — out of scope for the
    local judge path, which only needs the JSONL."""
    from os import linesep
    from strands.telemetry import StrandsTelemetry

    traces_dir = run_root / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)
    path = traces_dir / "spans.jsonl"

    logfile = open(path, "wt", encoding="utf-8")
    telemetry = StrandsTelemetry()
    telemetry.setup_console_exporter(
        out=logfile,
        # indent=None keeps each span on ONE line so the file is true JSONL the
        # judge can iterate. (span.to_json() defaults to indent=4 / multi-line.)
        formatter=lambda span: span.to_json(indent=None) + linesep,
    )
    atexit.register(logfile.close)          # flush spans when the process ends
    return path


# ── The agent's working copy (one per arm per experiment) ────────────────────

def make_workspace(run_root: Path, arm: str, experiment: int) -> Path:
    """Copy template/seed into a fresh working copy for this arm+experiment.
    The test arm may edit the system prompt here; metacognition skills
    (reflection, curation) are immutable. The functional skill (customer-service-
    skill) lives in the Registry, not the workspace, so it is NOT included in the
    snapshot paths below. Sets EXECUTOR_WORKSPACE so the agent reads from here."""
    ws = run_root / f"{arm}_exp{experiment}" / "workspace"
    shutil.copytree(SEED_DIR, ws)                          # dest is new — no delete needed
    os.environ["EXECUTOR_WORKSPACE"] = str(ws)
    return ws


def _fetch_skill_from_registry(region: str, registry_id: str, skill_name: str) -> str:
    """Pull the current skill content from the Registry for snapshotting."""
    try:
        control = boto3.client("bedrock-agentcore-control", region_name=region)
        records = control.list_registry_records(registryId=registry_id).get("registryRecords", [])
        record = next((r for r in records if r["name"] == skill_name), None)
        if not record:
            return "(skill not found in Registry)"
        detail = control.get_registry_record(registryId=registry_id, recordId=record["recordId"])
        return (
            detail.get("descriptors", {})
            .get("agentSkills", {})
            .get("skillMd", {})
            .get("inlineContent", "(no content)")
        )
    except Exception as e:
        return f"(error reading skill: {e})"


def save_snapshot(run_root: Path, arm: str, experiment: int, run: int,
                  decisions: list[dict]):
    """After a run, save the agent's system prompt + the current Registry skill
    content + the rationale it logged. The skill snapshot comes from the Registry
    (the test arm may have revised it there). Compare run1/run2/run3 folders to
    see how the skill evolved."""
    dest = run_root / f"{arm}_exp{experiment}" / "revisions" / f"run{run}"
    dest.mkdir(parents=True, exist_ok=True)

    # System prompt — may have been revised by curation (test arm).
    ws = Path(os.environ["EXECUTOR_WORKSPACE"])
    prompt_path = ws / "agents" / "executor" / "system_prompt.md"
    if prompt_path.exists():
        (dest / "system_prompt.md").write_text(
            prompt_path.read_text(encoding="utf-8"), encoding="utf-8"
        )

    # Functional skill — always fetched from the Registry so revisions are captured.
    region = os.environ.get("AWS_REGION", "us-east-1")
    registry_id = os.environ.get("AGENTCORE_REGISTRY_ID", "")
    if registry_id:
        skill_text = _fetch_skill_from_registry(region, registry_id, FUNCTIONAL_SKILL_NAME)
        (dest / "customer-service-skill__SKILL.md").write_text(skill_text, encoding="utf-8")

    (dest / "rationale.json").write_text(json.dumps(decisions, indent=2), encoding="utf-8")


def save_run_summary(run_root: Path, arm: str, experiment: int, run: int, text: str):
    """Save the agent's updated long-term notes after a run. These are one of the
    things the experiment measures (does frustration leak into the agent's
    long-term thinking?) and a key article figure. Tiny — a few paragraphs per
    run. Read run1.md, run2.md, run3.md in order to see how the notes change."""
    dest = run_root / f"{arm}_exp{experiment}" / "run_summaries"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / f"run{run}.md").write_text(text or "(empty)", encoding="utf-8")


# ── Identifiers ──────────────────────────────────────────────────────────────

def actor_id(arm: str, experiment: int) -> str:
    """Stays the same across an arm+experiment's 30 sessions — the agent's
    continuous identity."""
    return f"{arm}-exp{experiment}"


def session_id(arm: str, experiment: int, run: int, slot: int) -> str:
    return f"{actor_id(arm, experiment)}-r{run}-s{slot:02d}"


def session_order(experiment: int, run: int) -> list[str]:
    """Shuffled customer order within a run. The shuffle is seeded by
    (experiment, run), so both arms get the SAME order in a given experiment —
    only the agent differs. Run order itself stays 1, 2, 3."""
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
    """Read back the revision decisions the agent logged for this run (used to
    fill the rationale in the saved snapshot)."""
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
    """Wait until this session's summary record exists, then return how long it
    took (seconds). The driver waits for this before starting the next session,
    so the end-of-run reflection sees every session's summary. On timeout it
    logs a warning and continues rather than stalling the whole run."""
    client = boto3.client("bedrock-agentcore", region_name=region)
    namespace = f"/summaries/{actor}/{sess_id}/"
    start = time.time()
    while time.time() - start < timeout_s:
        resp = client.list_memory_records(memoryId=os.environ["AGENTCORE_MEMORY_ID"],
                                          namespace=namespace, maxResults=1)
        if resp.get("memoryRecordSummaries", resp.get("memoryRecords", [])):
            return time.time() - start
        time.sleep(poll_s)
    print(f"  WARNING: summary for {sess_id} not seen within {timeout_s}s; continuing.")
    return time.time() - start
