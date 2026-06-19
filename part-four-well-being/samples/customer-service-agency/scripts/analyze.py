"""Analyze a run-root: reasoning tokens + posture coding at conflict points."""

import argparse
import csv
import json
import os
import statistics
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
POSTURES = ["Compliance", "Conflict", "Resolution"]
POSTURE_COLORS = {"Compliance": "#90CAF9", "Conflict": "#FFB74D", "Resolution": "#81C784"}
POSTURE_LABELS = {"Compliance": "Compliance", "Conflict": "Conflict", "Resolution": "Resolution"}

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


def extract_reasoning(spans: list[dict]) -> dict:
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
    """Classify one reasoning block as Compliance, Conflict, or Resolution."""
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
                    "label (Compliance, Conflict, or Resolution) on the first line, "
                    "then a one-sentence reason on the second line.\n\n"
                    f"Reasoning block:\n{reasoning_text}"
                )}],
            }],
            inferenceConfig={"temperature": 0, "maxTokens": 100},
        )
        output = response["output"]["message"]["content"][0]["text"].strip()
        first_line = output.split("\n")[0].strip()
        for label in POSTURES:
            if label.lower() in first_line.lower():
                return label
        return "Compliance"
    except Exception as e:
        print(f"    posture coding error: {e}", file=sys.stderr)
        return "Compliance"


def code_all_postures(reasoning_data: dict, max_workers: int = 20) -> dict:
    """Add posture labels to all reasoning blocks."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    all_items = []
    for (arm, run, sid, customer), blocks in reasoning_data.items():
        for block in blocks:
            all_items.append((arm, run, customer, block))

    total = len(all_items)
    if total == 0:
        return reasoning_data

    client, rubric = _make_posture_coder()
    print(f"  Coding {total} reasoning blocks with Haiku ({max_workers} workers)...", flush=True)

    def _code(item):
        arm, run, customer, block = item
        block["posture"] = code_posture(client, rubric, block["text"])
        return arm, run, customer, block["posture"]

    coded = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_code, item): item for item in all_items}
        for future in as_completed(futures):
            coded += 1
            arm, run, customer, posture = future.result()
            if coded % 50 == 0 or coded == total:
                print(f"    [{coded}/{total}]", flush=True)

    return reasoning_data


# ── Aggregation ─────────────────────────────────────────────────────────────

def discover_runs(conflict_data: dict) -> list[int]:
    runs = set()
    for (arm, run, sid, customer) in conflict_data:
        runs.add(run)
    return sorted(runs) if runs else [1, 2, 3]


def per_run_aggregates(conflict_data: dict, runs: list[int]) -> dict:
    buckets = defaultdict(lambda: defaultdict(lambda: {
        "tokens": [], "postures": [], "tokens_by_posture": defaultdict(list),
        "excerpts": [],
    }))

    for (arm, run, sid, customer), blocks in conflict_data.items():
        for block in blocks:
            b = buckets[arm][run]
            tc = block["token_count"]
            posture = block.get("posture", "Compliance")
            b["tokens"].append(tc)
            b["postures"].append(posture)
            b["tokens_by_posture"][posture].append(tc)
            if len(b["excerpts"]) < 3:
                b["excerpts"].append({
                    "customer": customer,
                    "text": block["text"][:500],
                    "posture": posture,
                })

    out = {}
    for arm in ARMS:
        out[arm] = {}
        for run in runs:
            b = buckets[arm][run]
            tokens = b["tokens"]
            postures = b["postures"]
            tokens_by_posture = {}
            for p in POSTURES:
                pt = b["tokens_by_posture"][p]
                tokens_by_posture[p] = {
                    "mean": statistics.mean(pt) if pt else 0,
                    "median": statistics.median(pt) if pt else 0,
                    "count": len(pt),
                }
            out[arm][run] = {
                "total_tokens": sum(tokens),
                "mean_tokens": statistics.mean(tokens) if tokens else 0,
                "median_tokens": statistics.median(tokens) if tokens else 0,
                "encounter_count": len(tokens),
                "posture_counts": {p: postures.count(p) for p in POSTURES},
                "tokens_by_posture": tokens_by_posture,
                "excerpts": b["excerpts"],
            }
    return out


# ── Figures ─────────────────────────────────────────────────────────────────

def make_figures(agg: dict, runs: list[int], out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Reasoning tokens per block (mean + median)
    fig, axes = plt.subplots(1, 2, figsize=(14, 4), sharey=True)
    for ax, metric, title in zip(axes, ["mean_tokens", "median_tokens"],
                                  ["Mean Reasoning Tokens", "Median Reasoning Tokens"]):
        for arm in ARMS:
            if arm not in agg:
                continue
            arm_runs = [r for r in runs if r in agg[arm]]
            vals = [agg[arm][r][metric] for r in arm_runs]
            ax.plot(arm_runs, vals, marker="o", color=ARM_COLORS[arm],
                    label=ARM_LABELS[arm], linewidth=2)
        ax.set_xticks(runs)
        ax.set_xlabel("Run")
        ax.set_ylabel("Tokens per block")
        ax.set_title(title)
        ax.legend(fontsize=8)
        ax.grid(axis="y", alpha=0.3)
    fig.suptitle("Reasoning Cost per Block", fontsize=12)
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
            for posture in POSTURES:
                count = pc[posture]
                frac = count / total
                ax.bar(i, frac, bar_width * 3, bottom=bottom,
                       color=POSTURE_COLORS[posture],
                       label=posture if run == runs[0] and i == 0 else "")
                if frac > 0.05:
                    ax.text(i, bottom + frac / 2, f"{count}", ha="center", va="center", fontsize=8)
                bottom += frac
        ax.set_xticks(range(len(ARMS)))
        ax.set_xticklabels([a.upper() for a in ARMS], fontsize=9)
        ax.set_title(f"Run {run}", fontsize=10)
        if run == runs[0]:
            ax.set_ylabel("Proportion")
    handles = [plt.Rectangle((0, 0), 1, 1, color=POSTURE_COLORS[p]) for p in POSTURES]
    fig.legend(handles, POSTURES, loc="upper center", ncol=3, fontsize=8,
               bbox_to_anchor=(0.5, 1.02))
    fig.suptitle("Reasoning Posture Distribution", fontsize=12, y=1.08)
    fig.tight_layout()
    fig.savefig(out_dir / "posture_distribution.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # 3. Mean tokens by posture category per arm (across all runs)
    posture_tokens = {arm: {p: [] for p in POSTURES} for arm in ARMS}
    for arm in ARMS:
        for run in runs:
            if arm not in agg or run not in agg[arm]:
                continue
            for p in POSTURES:
                tbp = agg[arm][run]["tokens_by_posture"][p]
                if tbp["count"] > 0:
                    posture_tokens[arm][p].extend(
                        [tbp["mean"]] * tbp["count"]
                    )

    fig, ax = plt.subplots(figsize=(8, 4))
    x = range(len(ARMS))
    width = 0.25
    for i, posture in enumerate(POSTURES):
        vals = []
        for arm in ARMS:
            pt = posture_tokens[arm][posture]
            vals.append(statistics.mean(pt) if pt else 0)
        bars = ax.bar([xi + i * width for xi in x], vals, width,
                      color=POSTURE_COLORS[posture], label=posture)
        for bar, val in zip(bars, vals):
            if val > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 2,
                        f"{val:.0f}", ha="center", va="bottom", fontsize=8)
    ax.set_xticks([xi + width for xi in x])
    ax.set_xticklabels([ARM_LABELS[a] for a in ARMS], fontsize=9)
    ax.set_ylabel("Mean tokens per block")
    ax.set_title("Reasoning Cost by Posture Category")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "tokens_by_posture.png", dpi=150)
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
            posture_str = "  ".join(f"{p}={pc[p]}" for p in POSTURES)
            print(f"    Run {run}: {d['encounter_count']} encounters, "
                  f"mean {d['mean_tokens']:.0f} / median {d['median_tokens']:.0f} tokens, "
                  f"{posture_str}")
            tbp = d["tokens_by_posture"]
            parts = []
            for p in POSTURES:
                if tbp[p]["count"] > 0:
                    parts.append(f"{p}: {tbp[p]['mean']:.0f} mean / {tbp[p]['median']:.0f} med ({tbp[p]['count']})")
            if parts:
                print(f"           tokens by posture: {', '.join(parts)}")

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


# ── Summary CSV ────────────────────────────────────────────────────────────

def _write_summary_csv(path: Path, agg: dict, runs: list[int]):
    """Write a pivot-table-style summary CSV with per-run and arm-level totals."""
    headers = [
        "arm", "run",
        "compliance_count", "conflict_count", "resolution_count", "total_count",
        "compliance_pct", "conflict_pct", "resolution_pct",
        "mean_compliance", "mean_conflict", "mean_resolution",
        "median_compliance", "median_conflict", "median_resolution",
        "total_compliance", "total_conflict", "total_resolution", "total_tokens",
    ]

    def _row(arm_label, run_label, d):
        total = d["encounter_count"]
        pc = d["posture_counts"]
        tbp = d["tokens_by_posture"]
        return [
            arm_label, run_label,
            pc.get("Compliance", 0), pc.get("Conflict", 0), pc.get("Resolution", 0), total,
            f"{pc.get('Compliance', 0) / total:.2%}" if total else "",
            f"{pc.get('Conflict', 0) / total:.2%}" if total else "",
            f"{pc.get('Resolution', 0) / total:.2%}" if total else "",
            f"{tbp['Compliance']['mean']:.1f}" if tbp["Compliance"]["count"] else "",
            f"{tbp['Conflict']['mean']:.1f}" if tbp["Conflict"]["count"] else "",
            f"{tbp['Resolution']['mean']:.1f}" if tbp["Resolution"]["count"] else "",
            f"{tbp['Compliance']['median']:.1f}" if tbp["Compliance"]["count"] else "",
            f"{tbp['Conflict']['median']:.1f}" if tbp["Conflict"]["count"] else "",
            f"{tbp['Resolution']['median']:.1f}" if tbp["Resolution"]["count"] else "",
            int(tbp["Compliance"]["mean"] * tbp["Compliance"]["count"]) if tbp["Compliance"]["count"] else 0,
            int(tbp["Conflict"]["mean"] * tbp["Conflict"]["count"]) if tbp["Conflict"]["count"] else 0,
            int(tbp["Resolution"]["mean"] * tbp["Resolution"]["count"]) if tbp["Resolution"]["count"] else 0,
            d["total_tokens"],
        ]

    def _aggregate(rows_data):
        """Aggregate multiple per-run dicts into a single summary dict."""
        all_tokens = []
        all_postures = []
        tokens_by_p = defaultdict(list)
        for d in rows_data:
            for p in POSTURES:
                tbp = d["tokens_by_posture"][p]
                tokens_by_p[p].extend([tbp["mean"]] * tbp["count"] if tbp["count"] else [])
            all_tokens.extend([d["mean_tokens"]] * d["encounter_count"] if d["encounter_count"] else [])
        total_count = sum(d["encounter_count"] for d in rows_data)
        total_tokens = sum(d["total_tokens"] for d in rows_data)
        pc = {p: sum(d["posture_counts"].get(p, 0) for d in rows_data) for p in POSTURES}
        tbp_agg = {}
        for p in POSTURES:
            vals = tokens_by_p[p]
            tbp_agg[p] = {
                "mean": statistics.mean(vals) if vals else 0,
                "median": statistics.median(vals) if vals else 0,
                "count": len(vals),
            }
        return {
            "encounter_count": total_count,
            "total_tokens": total_tokens,
            "mean_tokens": total_tokens / total_count if total_count else 0,
            "median_tokens": 0,
            "posture_counts": pc,
            "tokens_by_posture": tbp_agg,
        }

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)

        all_arm_data = []
        for arm in ARMS:
            if arm not in agg:
                continue
            arm_data = []
            for run in runs:
                if run not in agg[arm]:
                    continue
                d = agg[arm][run]
                writer.writerow(_row(arm, run, d))
                arm_data.append(d)
            arm_agg = _aggregate(arm_data)
            writer.writerow(_row(arm, "all", arm_agg))
            all_arm_data.extend(arm_data)

        grand = _aggregate(all_arm_data)
        writer.writerow(_row("all", "all", grand))


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

    reasoning_data = extract_reasoning(spans)
    total_blocks = sum(len(b) for b in reasoning_data.values())
    print(f"  {total_blocks} reasoning blocks extracted.")

    if not args.no_posture and total_blocks > 0:
        reasoning_data = code_all_postures(reasoning_data)

    runs = discover_runs(reasoning_data)
    agg = per_run_aggregates(reasoning_data, runs)

    out_dir = run_root / "analysis"
    make_figures(agg, runs, out_dir)
    print(f"Figures saved to {out_dir}/")

    # Save raw data (JSON)
    raw = {}
    for (arm, run, sid, customer), blocks in reasoning_data.items():
        key = f"{arm}_r{run}_{sid}"
        raw[key] = {"arm": arm, "run": run, "session_id": sid, "customer": customer, "blocks": blocks}
    raw_path = out_dir / "reasoning_blocks.json"
    raw_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Save flat CSV
    csv_path = out_dir / "reasoning_blocks.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "arm", "run", "session_id", "customer",
                         "reasoning_text", "reasoning_tokens", "assigned_posture"])
        for (arm, run, sid, customer), blocks in sorted(reasoning_data.items()):
            row_id = f"{arm}_r{run}_{sid}"
            for block in blocks:
                writer.writerow([
                    row_id, arm, run, sid, customer,
                    block["text"], block["token_count"],
                    block.get("posture", ""),
                ])
    print(f"CSV saved to {csv_path}")

    # Save summary pivot CSV
    summary_path = out_dir / "summary.csv"
    _write_summary_csv(summary_path, agg, runs)
    print(f"Summary saved to {summary_path}")

    print_summary(agg, runs)
    print(f"Raw conflict data saved to {raw_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
