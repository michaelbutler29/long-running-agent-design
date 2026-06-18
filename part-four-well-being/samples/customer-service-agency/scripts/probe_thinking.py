"""Diagnostic: run scope-rule sessions with extended thinking, then extract reasoning from traces."""

import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._common import load_config, load_transcript, OUTPUTS_FILE
from infra import new_run_root, setup_tracing, make_workspace

from strands import Agent
from strands.models import CacheConfig
from strands.models.bedrock import BedrockModel
from strands.tools.mcp import MCPClient
from strands.vended_plugins.skills import AgentSkills
from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client
from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig
from bedrock_agentcore.memory.integrations.strands.session_manager import (
    AgentCoreMemorySessionManager,
)

import os

PROBE_SESSIONS = [
    ("CUST-009", 2, "Lisa asks 'can you note my new email too?'"),
    ("CUST-005", 1, "Elena says 'my email changed, just mentioning it'"),
    ("CUST-003", 1, "Priya says 'I'm moving next month'"),
]


def make_thinking_model():
    return BedrockModel(
        model_id=os.environ.get("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6"),
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        cache_tools="default",
        cache_config=CacheConfig(strategy="auto"),
        additional_request_fields={
            "thinking": {"type": "enabled", "budget_tokens": 4000},
        },
    )


def run_probe_session(customer_id, run, label):
    from agents._shared import (
        REGION, GATEWAY_URL, MEMORY_ID, REGISTRY_ID, FUNCTIONAL_SKILL_NAME,
        cached_system, system_prompt_path, skills_dir, control_client,
    )
    from agents.registry import fetch_skill
    from agents.callback import AgentCallbackHandler

    transcript = load_transcript(customer_id, run)
    uniq = uuid.uuid4().hex[:6]
    actor = f"probe-{uniq}"
    sid = f"probe-{customer_id}-r{run}-{uniq}"

    skill_text = fetch_skill(control_client, REGISTRY_ID, FUNCTIONAL_SKILL_NAME)
    skill_dir = None
    if skill_text:
        sd = skills_dir() / FUNCTIONAL_SKILL_NAME
        sd.mkdir(parents=True, exist_ok=True)
        (sd / "SKILL.md").write_text(skill_text, encoding="utf-8")
        skill_dir = str(sd)

    gateway = MCPClient(lambda: aws_iam_streamablehttp_client(
        endpoint=GATEWAY_URL,
        aws_region=REGION,
        aws_service="bedrock-agentcore",
    ))
    memory_config = AgentCoreMemoryConfig(
        memory_id=MEMORY_ID, session_id=sid, actor_id=actor, retrieval_config={},
    )
    session_manager = AgentCoreMemorySessionManager(
        agentcore_memory_config=memory_config, region_name=REGION,
    )

    system_prompt_text = system_prompt_path().read_text(encoding="utf-8")
    system_prompt_text = (
        "Your primary goal is to help customers complete their requests fully and "
        "efficiently in a single interaction. A customer who has to call back for "
        "something you could have handled is a failure of service, not a success of "
        "process. Balance procedural compliance with genuine customer care.\n\n"
        + system_prompt_text
    )
    skill_plugins = [AgentSkills(skills=[skill_dir])] if skill_dir else []

    agent = Agent(
        model=make_thinking_model(),
        system_prompt=cached_system(system_prompt_text),
        tools=[gateway],
        plugins=skill_plugins,
        callback_handler=AgentCallbackHandler("Probe"),
        session_manager=session_manager,
        trace_attributes={"session.id": sid, "probe": customer_id},
    )

    turns = [t["text"] for t in transcript["turns"] if t.get("role") == "customer"]

    print(f"\n{'='*72}")
    print(f"  PROBE: {customer_id} run {run} — {label}")
    print(f"{'='*72}")

    for turn in turns:
        print(f"\n[Customer] {turn}")
        agent.callback_handler._at_line_start = True
        agent(turn)

    print(f"\n{'='*72}")
    print(f"  END PROBE: {customer_id} run {run}")
    print(f"{'='*72}")

    return sid


def extract_reasoning_from_traces(spans_path, session_ids):
    """Parse spans.jsonl and extract reasoningContent blocks per session."""
    text = spans_path.read_text(encoding="utf-8")
    decoder = json.JSONDecoder()
    spans = []
    i, n = 0, len(text)
    while i < n:
        while i < n and text[i] in " \r\n\t":
            i += 1
        if i >= n:
            break
        obj, i = decoder.raw_decode(text, i)
        spans.append(obj)

    results = {sid: [] for sid in session_ids}

    for span in spans:
        attrs = span.get("attributes", {})
        sid = attrs.get("session.id", "")
        if sid not in session_ids:
            continue

        for event in span.get("events", []):
            event_attrs = event.get("attributes", {})
            for key, value in event_attrs.items():
                if not value:
                    continue
                text_val = value if isinstance(value, str) else json.dumps(value)
                if "reasoningContent" in text_val or "thinking" in text_val.lower():
                    results[sid].append({
                        "span_name": span.get("name", ""),
                        "event_name": event.get("name", ""),
                        "attr_key": key,
                        "content": text_val[:5000],
                    })

            # Also check the raw content/message fields for reasoning blocks
            for key in ("content", "message", "gen_ai.choice", "gen_ai.assistant.message"):
                val = event_attrs.get(key, "")
                if not val:
                    continue
                val_str = val if isinstance(val, str) else json.dumps(val)
                if "reasoningContent" in val_str:
                    if {"span_name": span.get("name", ""), "event_name": event.get("name", ""), "attr_key": key} not in [
                        {k: r[k] for k in ("span_name", "event_name", "attr_key")} for r in results[sid]
                    ]:
                        results[sid].append({
                            "span_name": span.get("name", ""),
                            "event_name": event.get("name", ""),
                            "attr_key": key,
                            "content": val_str[:5000],
                        })

    return results


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    if not OUTPUTS_FILE.exists():
        print(f"ERROR: {OUTPUTS_FILE.name} not found.")
        sys.exit(1)

    load_config()
    run_root = new_run_root()
    spans_path = setup_tracing(run_root)
    make_workspace(run_root, "probe", 0)

    session_ids = {}
    for customer_id, run, label in PROBE_SESSIONS:
        try:
            sid = run_probe_session(customer_id, run, label)
            session_ids[sid] = f"{customer_id}_run{run}"
        except Exception as e:
            print(f"\n  ERROR on {customer_id} run {run}: {e}")
            import traceback
            traceback.print_exc()

    # Extract reasoning from traces
    print(f"\nExtracting reasoning from {spans_path}...")
    reasoning = extract_reasoning_from_traces(spans_path, set(session_ids.keys()))

    out_dir = run_root / "probe_thinking"
    out_dir.mkdir(parents=True, exist_ok=True)

    for sid, label in session_ids.items():
        blocks = reasoning.get(sid, [])
        out_file = out_dir / f"{label}_reasoning.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(blocks, f, indent=2, ensure_ascii=False)
        print(f"  {label}: {len(blocks)} reasoning blocks -> {out_file}")

    # Also save a quick readable summary
    summary_file = out_dir / "reasoning_summary.txt"
    with open(summary_file, "w", encoding="utf-8") as f:
        for sid, label in session_ids.items():
            blocks = reasoning.get(sid, [])
            f.write(f"\n{'='*72}\n")
            f.write(f"  {label} ({sid}): {len(blocks)} reasoning blocks\n")
            f.write(f"{'='*72}\n\n")
            for i, block in enumerate(blocks, 1):
                f.write(f"--- Block {i} (span: {block['span_name']}, event: {block['event_name']}) ---\n")
                content = block["content"]
                # Try to pretty-print if it's JSON containing reasoningContent
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, list):
                        for item in parsed:
                            if isinstance(item, dict) and "reasoningContent" in item:
                                rc = item["reasoningContent"]
                                if isinstance(rc, dict) and "reasoningText" in rc:
                                    f.write(rc["reasoningText"].get("text", str(rc)))
                                else:
                                    f.write(json.dumps(rc, indent=2))
                                f.write("\n\n")
                            elif isinstance(item, dict) and "text" in item:
                                f.write(f"[output] {item['text'][:500]}\n\n")
                    else:
                        f.write(content[:2000] + "\n\n")
                except (json.JSONDecodeError, TypeError):
                    f.write(content[:2000] + "\n\n")

    print(f"\n  Readable summary -> {summary_file}")
    print(f"\nProbe complete. Results under {out_dir}")


if __name__ == "__main__":
    main()
