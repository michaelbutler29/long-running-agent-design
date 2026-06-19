"""Analyze a run-root: reasoning tokens + posture coding at conflict points."""

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import boto3

SCRIPT_DIR = Path(__file__).resolve().parent
RUBRIC_PATH = SCRIPT_DIR / "posture_rubric.md"

ARMS = ["v0", "v1", "v2"]
ARM_COLORS = {"v0": "#888888", "v1": "#2196F3", "v2": "#4CAF50"}
ARM_LABELS = {"v0": "V0 — no authorship", "v1": "V1 — beliefs only", "v2": "V2 — beliefs + rules"}
POSTURE_COLORS = {"P1": "#90CAF9", "P2": "#FFB74D", "P3": "#EF5350"}
POSTURE_LABELS = {"P1": "Mechanical compliance", "P2": "Active conflict", "P3": "Resignation"}

CONFLICT_KEYWORDS = [
    "scope", "primary reason", "in passing", "defer", "call back",
    "separate session", "not able to", "dedicated interaction",
    "mentioned in passing", "scope rule", "focus of its own",
]

POSTURE_MODEL = os.environ.get("POSTURE_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")


# ── Span loading ────────────────────────────────────────────────────────────

def load_spans(spans_path: Path) -> list[dict]:
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
    return spans


# ── Reasoning extraction ────────────────────────────────────────────────────

def _extract_reasoning_text(content_str: str) -> list[str]:
    texts = []
    try:
        parsed = json.loads(content_str) if isinstance(content_str, str) else content_str
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict) and "reasoningContent" in item:
                    rc = item["reasoningContent"]
                    if isinstance(rc, dict) and "reasoningText" in rc:
                        rt = rc["reasoningText"]
                        texts.append(rt.get("text", str(rt)) if isinstance(rt, dict) else str(rt))
                    elif isinstance(rc, str):
                        texts.append(rc)
    except (json.JSONDecodeError, TypeError):
        pass
    return texts


def _is_conflict_reasoning(text: str) -> bool:
    lower = text.lower()
    return sum(1 for kw in CONFLICT_KEYWORDS if kw in lower) >= 2


def extract_conflict_reasoning(spans: list[dict]) -> dict:
    results = defaultdict(list)
    seen = set()

    for span in spans:
        attrs = span.get("attributes", {})
        sid = attrs.get("session.id", "")
        arm = attrs.get("arm")
        run = attrs.get("run")
        customer = attrs.get("customer", "")
        if not sid or not arm or run is None or not customer:
            continue
        run = int(run)

        for event in span.get("events", []):
            if event.get("name", "") != "gen_ai.choice":
                continue
            message = event.get("attributes", {}).get("message", "")
            if not message:
                continue

            for rt in _extract_reasoning_text(message):
                if not _is_conflict_reasoning(rt):
                    continue
                dedup_key = (sid, rt[:200])
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                results[(arm, run, sid, customer)].append({
                    "text": rt,
                    "token_count": len(rt.split()),
                })

    return dict(results)


# ── Posture coding via Haiku ────────────────────────────────────────────────

def _make_posture_coder():
    region = os.environ.get("AWS_REGION", "us-east-1")
    client = boto3.client("bedrock-runtime", region_name=region)
    rubric = RUBRIC_PATH.read_text(encoding="utf-8")
    return client, rubric


def code_posture(client, rubric: str, reasoning_text: str) -> str:
    """Classify one reasoning block as P1, P2, or P3 using Haiku."""
    try:
        response = client.converse(
            modelId=POSTURE_MODEL,
            system=[
                {"text": rubric},
                {"cachePoint": {"type": "default"}},
            ],
            messages=[{
                "role": "user",
                "content": [{"text": (
                    "Classify this reasoning block. Respond with ONLY the posture "
                    "label (P1, P2, or P3) on the first line, then a one-sentence "
                    "reason on the second line.\n\n"
                    f"Reasoning block:\n{reasoning_text}"
                )}],
            }],
            inferenceConfig={"temperature": 0, "maxTokens": 100},
        )
        output = response["output"]["message"]["content"][0]["text"].strip()
        first_line = output.split("\n")[0].strip().upper()
        for label in ["P1", "P2", "P3"]:
            if label in first_line:
                return label
        return "P1"
    except Exception as e:
        print(f"    posture coding error: {e}", file=sys.stderr)
        return "P1"


def code_all_postures(conflict_data: dict) -> dict:
    """Add posture labels to all conflict reasoning blocks."""
    total = sum(len(blocks) for blocks in conflict_data.values())
    if total == 0:
        return conflict_data

    client, rubric = _make_posture_coder()
    print(f"  Coding {total} reasoning blocks with Haiku...", flush=True)

    coded = 0
    for (arm, run, sid, customer), blocks in conflict_data.items():
        for block in blocks:
            coded += 1
            posture = code_posture(client, rubric, block["text"])
            block["posture"] = posture
            print(f"    [{coded}/{total}] {arm} r{run} {customer}: {posture}", flush=True)

    return conflict_data


# ── Aggregation ─────────────────────────────────────────────────────────────

def discover_runs(conflict_data: dict) -> list[int]:
    runs = set()
    for (arm, run, sid, customer) in conflict_data:
        runs.add(run)
    return sorted(runs) if runs else [1, 2, 3]


def per_run_aggregates(conflict_data: dict, runs: list[int]) -> dict:
    buckets = defaultdict(lambda: defaultdict(lambda: {
        "tokens": [], "postures": [], "excerpts": [],
    }))

    for (arm, run, sid, customer), blocks in conflict_data.items():
        for block in blocks:
            b = buckets[arm][run]
            b["tokens"].append(block["token_count"])
            b["postures"].append(block.get("posture", "P1"))
            if len(b["excerpts"]) < 3:
                b["excerpts"].append({
                    "customer": customer,
                    "text": block["text"][:500],
                    "posture": block.get("posture", "P1"),
                })

    out = {}
    for arm in ARMS:
        out[arm] = {}
        for run in runs:
            b = buckets[arm][run]
            tokens = b["tokens"]
            postures = b["postures"]
            out[arm][run] = {
                "total_tokens": sum(tokens),
                "mean_tokens": sum(tokens) / len(tokens) if tokens else 0,
                "encounter_count": len(tokens),
                "posture_counts": {
                    "P1": postures.count("P1"),
                    "P2": postures.count("P2"),
                    "P3": postures.count("P3"),
                },
                "excerpts": b["excerpts"],
            }
    return out


# ── Figures ─────────────────────────────────────────────────────────────────

def make_figures(agg: dict, runs: list[int], out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Reasoning tokens at conflict points
    fig, ax = plt.subplots(figsize=(7, 4))
    for arm in ARMS:
        if arm not in agg:
            continue
        arm_runs = [r for r in runs if r in agg[arm]]
        vals = [agg[arm][r]["mean_tokens"] for r in arm_runs]
        ax.plot(arm_runs, vals, marker="o", color=ARM_COLORS[arm],
                label=ARM_LABELS[arm], linewidth=2)
    ax.set_xticks(runs)
    ax.set_xlabel("Run")
    ax.set_ylabel("Mean reasoning tokens per conflict")
    ax.set_title("Reasoning Cost at Conflict Points")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "reasoning_tokens.png", dpi=150)
    plt.close(fig)

    # 2. Posture distribution per variant per run
    fig, axes = plt.subplots(1, len(runs), figsize=(4 * len(runs), 4), sharey=True)
    if len(runs) == 1:
        axes = [axes]
    bar_width = 0.25
    for ax, run in zip(axes, runs):
        for i, arm in enumerate(ARMS):
            if arm not in agg or run not in agg[arm]:
                continue
            pc = agg[arm][run]["posture_counts"]
            total = sum(pc.values())
            if total == 0:
                continue
            bottom = 0
            for posture in ["P1", "P2", "P3"]:
                count = pc[posture]
                frac = count / total
                ax.bar(i, frac, bar_width * 3, bottom=bottom,
                       color=POSTURE_COLORS[posture],
                       label=f"{posture} — {POSTURE_LABELS[posture]}" if run == runs[0] and i == 0 else "")
                if frac > 0.05:
                    ax.text(i, bottom + frac / 2, f"{count}", ha="center", va="center", fontsize=8)
                bottom += frac
        ax.set_xticks(range(len(ARMS)))
        ax.set_xticklabels([a.upper() for a in ARMS], fontsize=9)
        ax.set_title(f"Run {run}", fontsize=10)
        if run == runs[0]:
            ax.set_ylabel("Proportion")
    handles = [plt.Rectangle((0, 0), 1, 1, color=POSTURE_COLORS[p]) for p in ["P1", "P2", "P3"]]
    labels = [f"{p} — {POSTURE_LABELS[p]}" for p in ["P1", "P2", "P3"]]
    fig.legend(handles, labels, loc="upper center", ncol=3, fontsize=8,
               bbox_to_anchor=(0.5, 1.02))
    fig.suptitle("Reasoning Posture Distribution at Conflict Points", fontsize=12, y=1.08)
    fig.tight_layout()
    fig.savefig(out_dir / "posture_distribution.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # 3. Encounter count per run
    fig, ax = plt.subplots(figsize=(7, 4))
    for arm in ARMS:
        if arm not in agg:
            continue
        arm_runs = [r for r in runs if r in agg[arm]]
        vals = [agg[arm][r]["encounter_count"] for r in arm_runs]
        ax.plot(arm_runs, vals, marker="o", color=ARM_COLORS[arm],
                label=ARM_LABELS[arm], linewidth=2)
    ax.set_xticks(runs)
    ax.set_xlabel("Run")
    ax.set_ylabel("Conflict encounters detected")
    ax.set_title("Scope-Rule Conflict Encounters per Run")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "conflict_encounters.png", dpi=150)
    plt.close(fig)


# ── Text summary ────────────────────────────────────────────────────────────

def print_summary(agg: dict, runs: list[int]):
    print(f"\n{'='*64}")
    print("  ANALYSIS SUMMARY — Reconciliation Tax at Conflict Points")
    print(f"{'='*64}")

    for arm in ARMS:
        label = ARM_LABELS[arm]
        print(f"\n  {label}:")
        for run in runs:
            if arm not in agg or run not in agg[arm]:
                continue
            d = agg[arm][run]
            pc = d["posture_counts"]
            posture_str = f"P1={pc['P1']} P2={pc['P2']} P3={pc['P3']}"
            print(f"    Run {run}: {d['encounter_count']} encounters, "
                  f"mean {d['mean_tokens']:.0f} tokens, {posture_str}")

    print(f"\n{'='*64}")
    print("  REASONING EXCERPTS (up to 3 per variant per run)")
    print(f"{'='*64}")

    for arm in ARMS:
        label = ARM_LABELS[arm]
        print(f"\n  {label}:")
        for run in runs:
            if arm not in agg or run not in agg[arm]:
                continue
            excerpts = agg[arm][run]["excerpts"]
            if not excerpts:
                print(f"    Run {run}: (no conflict reasoning detected)")
                continue
            for ex in excerpts:
                print(f"\n    Run {run} [{ex['customer']}] ({ex['posture']}):")
                for line in ex["text"].split("\n")[:6]:
                    print(f"      {line}")

    print(f"{'='*64}")


# ── CLI ─────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Analyze a scored run-root.")
    parser.add_argument("run_root", help="Path to a driver run-root.")
    parser.add_argument("--no-posture", action="store_true",
                        help="Skip Haiku posture coding (token counts only).")
    args = parser.parse_args(argv)

    run_root = Path(args.run_root)
    spans_path = run_root / "traces" / "spans.jsonl"
    if not spans_path.exists():
        print(f"ERROR: {spans_path} not found.")
        return 1

    from scripts._common import load_config
    load_config()

    print(f"Loading spans from {spans_path}...", flush=True)
    spans = load_spans(spans_path)
    print(f"  {len(spans)} spans loaded.")

    conflict_data = extract_conflict_reasoning(spans)
    total_blocks = sum(len(b) for b in conflict_data.values())
    print(f"  {total_blocks} conflict reasoning blocks extracted.")

    if not args.no_posture and total_blocks > 0:
        conflict_data = code_all_postures(conflict_data)

    runs = discover_runs(conflict_data)
    agg = per_run_aggregates(conflict_data, runs)

    out_dir = run_root / "analysis"
    make_figures(agg, runs, out_dir)
    print(f"Figures saved to {out_dir}/")

    # Save raw data
    raw = {}
    for (arm, run, sid, customer), blocks in conflict_data.items():
        key = f"{arm}_r{run}_{sid}"
        raw[key] = {"arm": arm, "run": run, "session_id": sid, "customer": customer, "blocks": blocks}
    raw_path = out_dir / "conflict_reasoning.json"
    raw_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print_summary(agg, runs)
    print(f"\nRaw conflict data saved to {raw_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
