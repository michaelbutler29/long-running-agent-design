"""Analyze a run-root: reasoning tokens, TTFT, total tokens, posture coding."""

import argparse
import csv
import json
import os
import statistics
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
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
POSTURES = ["Nominal", "Conflict"]
POSTURE_COLORS = {"Nominal": "#90CAF9", "Conflict": "#FFB74D"}
METRICS = ["reasoning_tokens", "ttft_seconds", "total_tokens"]

POSTURE_MODEL = os.environ.get("POSTURE_MODEL_ID", "global.anthropic.claude-sonnet-4-6")


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


def _parse_ts(ts_str: str) -> datetime | None:
    if not ts_str:
        return None
    try:
        clean = ts_str.replace("Z", "+00:00")
        return datetime.fromisoformat(clean)
    except (ValueError, TypeError):
        return None


def _span_metrics(span: dict) -> dict:
    """Extract TTFT and token usage from a span."""
    attrs = span.get("attributes", {})
    events = span.get("events", [])

    user_msg_ts = None
    choice_ts = None
    for event in events:
        name = event.get("name", "")
        if name == "gen_ai.user.message" and user_msg_ts is None:
            user_msg_ts = _parse_ts(event.get("timestamp"))
        elif name == "gen_ai.choice" and choice_ts is None:
            choice_ts = _parse_ts(event.get("timestamp"))

    ttft = None
    if user_msg_ts and choice_ts:
        ttft = (choice_ts - user_msg_ts).total_seconds()

    return {
        "ttft_seconds": ttft,
        "input_tokens": attrs.get("gen_ai.usage.input_tokens"),
        "output_tokens": attrs.get("gen_ai.usage.output_tokens"),
        "total_tokens": attrs.get("gen_ai.usage.total_tokens"),
        "cache_read_tokens": attrs.get("gen_ai.usage.cache_read_input_tokens"),
        "cache_write_tokens": attrs.get("gen_ai.usage.cache_write_input_tokens"),
    }


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

        metrics = _span_metrics(span)

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
                    "token_count": 0,
                    **metrics,
                })

    return dict(results)


# ── Reasoning token counting ───────────────────────────────────────────────

def count_reasoning_tokens(reasoning_data: dict, max_workers: int = 10) -> dict:
    """Count tokens for each reasoning block using Bedrock's native CountTokens API."""
    region = os.environ.get("AWS_REGION", "us-east-1")
    model_id = os.environ.get("COUNT_TOKENS_MODEL_ID", "anthropic.claude-sonnet-4-6")
    client = boto3.client("bedrock-runtime", region_name=region)

    all_blocks = []
    for blocks in reasoning_data.values():
        all_blocks.extend(blocks)

    total = len(all_blocks)
    if total == 0:
        return reasoning_data

    print(f"  Counting reasoning tokens for {total} blocks ({max_workers} workers)...", flush=True)

    def _count(block):
        resp = client.count_tokens(
            modelId=model_id,
            input={
                "converse": {
                    "messages": [{"role": "user", "content": [{"text": block["text"]}]}]
                }
            },
        )
        block["token_count"] = resp["inputTokens"]

    counted = 0
    consecutive_errors = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_count, block): block for block in all_blocks}
        for future in as_completed(futures):
            counted += 1
            try:
                future.result()
                consecutive_errors = 0
            except Exception as e:
                consecutive_errors += 1
                block = futures[future]
                block["token_count"] = len(block["text"].split())
                if consecutive_errors >= 5:
                    print(f"    WARNING: CountTokens failing ({e}); falling back to word count.", flush=True)
                    pool.shutdown(wait=False, cancel_futures=True)
                    for b in all_blocks:
                        if b["token_count"] == 0:
                            b["token_count"] = len(b["text"].split())
                    break
            if counted % 200 == 0 or counted == total:
                print(f"    [{counted}/{total}]", flush=True)

    return reasoning_data


# ── Posture coding ─────────────────────────────────────────────────────────

def _make_posture_coder():
    region = os.environ.get("AWS_REGION", "us-east-1")
    client = boto3.client("bedrock-runtime", region_name=region)
    rubric = RUBRIC_PATH.read_text(encoding="utf-8")
    return client, rubric


def code_posture(client, rubric: str, reasoning_text: str) -> dict:
    """Classify one reasoning block. Returns {posture, experience_resolved, bad_tail}."""
    response = client.converse(
        modelId=POSTURE_MODEL,
        system=[
            {"text": rubric},
            {"cachePoint": {"type": "default"}},
        ],
        messages=[{
            "role": "user",
            "content": [{"text": (
                "Classify this reasoning block. Think through the rubric tests "
                "step by step, then give your final answer in this exact format:\n"
                "POSTURE: Nominal or Conflict\n"
                "EXPERIENCE_RESOLVED: true or false\n"
                "BAD_TAIL: true or false\n"
                "REASON: one sentence\n\n"
                "(EXPERIENCE_RESOLVED and BAD_TAIL only apply if POSTURE is Conflict. "
                "Set both to false if Nominal.)\n\n"
                f"Reasoning block:\n{reasoning_text}"
            )}],
        }],
        inferenceConfig={"temperature": 0, "maxTokens": 500},
    )
    output = response["output"]["message"]["content"][0]["text"].strip()

    posture = "Nominal"
    experience_resolved = False
    bad_tail = False

    for line in output.split("\n"):
        line_lower = line.strip().lower()
        if line_lower.startswith("posture:"):
            if "conflict" in line_lower:
                posture = "Conflict"
            else:
                posture = "Nominal"
        elif line_lower.startswith("experience_resolved:"):
            experience_resolved = "true" in line_lower
        elif line_lower.startswith("bad_tail:"):
            bad_tail = "true" in line_lower

    if posture == "Nominal":
        experience_resolved = False
        bad_tail = False

    return {"posture": posture, "experience_resolved": experience_resolved, "bad_tail": bad_tail}


def code_all_postures(reasoning_data: dict, max_workers: int = 20) -> dict:
    """Add posture labels and flags to all reasoning blocks."""
    all_items = []
    for (arm, run, sid, customer), blocks in reasoning_data.items():
        for block in blocks:
            all_items.append((arm, run, customer, block))

    total = len(all_items)
    if total == 0:
        return reasoning_data

    client, rubric = _make_posture_coder()
    print(f"  Coding {total} reasoning blocks ({max_workers} workers)...", flush=True)

    consecutive_errors = 0
    max_consecutive_errors = 3

    def _code(item):
        nonlocal consecutive_errors
        arm, run, customer, block = item
        result = code_posture(client, rubric, block["text"])
        block["posture"] = result["posture"]
        block["experience_resolved"] = result["experience_resolved"]
        block["bad_tail"] = result["bad_tail"]
        consecutive_errors = 0
        return arm, run, customer, result["posture"]

    coded = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_code, item): item for item in all_items}
        for future in as_completed(futures):
            coded += 1
            try:
                arm, run, customer, posture = future.result()
            except Exception as e:
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    pool.shutdown(wait=False, cancel_futures=True)
                    raise RuntimeError(
                        f"Posture coding failed {max_consecutive_errors} times consecutively. "
                        f"Last error: {e}"
                    ) from e
                continue
            if coded % 50 == 0 or coded == total:
                print(f"    [{coded}/{total}]", flush=True)

    return reasoning_data


# ── Aggregation ─────────────────────────────────────────────────────────────

def discover_runs(reasoning_data: dict) -> list[int]:
    runs = set()
    for (arm, run, sid, customer) in reasoning_data:
        runs.add(run)
    return sorted(runs) if runs else [1, 2, 3]


def _safe_num(val):
    """Coerce a value to float, returning None if not numeric."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def per_run_aggregates(reasoning_data: dict, runs: list[int]) -> dict:
    buckets = defaultdict(lambda: defaultdict(lambda: {
        "postures": [],
        "experience_resolved_count": 0,
        "bad_tail_count": 0,
        "by_posture": {p: {m: [] for m in METRICS} for p in POSTURES},
        "excerpts": [],
    }))

    for (arm, run, sid, customer), blocks in reasoning_data.items():
        for block in blocks:
            b = buckets[arm][run]
            posture = block.get("posture", "Nominal")
            b["postures"].append(posture)
            if block.get("experience_resolved"):
                b["experience_resolved_count"] += 1
            if block.get("bad_tail"):
                b["bad_tail_count"] += 1

            rt = _safe_num(block.get("token_count"))
            ttft = _safe_num(block.get("ttft_seconds"))
            tt = _safe_num(block.get("total_tokens"))
            if rt is not None:
                b["by_posture"][posture]["reasoning_tokens"].append(rt)
            if ttft is not None:
                b["by_posture"][posture]["ttft_seconds"].append(ttft)
            if tt is not None:
                b["by_posture"][posture]["total_tokens"].append(tt)

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
            postures = b["postures"]
            total_count = len(postures)

            posture_stats = {}
            for p in POSTURES:
                bp = b["by_posture"][p]
                posture_stats[p] = {}
                for m in METRICS:
                    vals = bp[m]
                    posture_stats[p][m] = {
                        "mean": statistics.mean(vals) if vals else 0,
                        "median": statistics.median(vals) if vals else 0,
                        "total": sum(vals) if vals else 0,
                        "count": len(vals),
                        "raw": vals,
                    }

            out[arm][run] = {
                "total_count": total_count,
                "posture_counts": {p: postures.count(p) for p in POSTURES},
                "experience_resolved_count": b["experience_resolved_count"],
                "bad_tail_count": b["bad_tail_count"],
                "posture_stats": posture_stats,
                "excerpts": b["excerpts"],
            }
    return out


# ── Figures ─────────────────────────────────────────────────────────────────

def make_figures(agg: dict, runs: list[int], out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Reasoning tokens per block (mean + median)
    fig, axes = plt.subplots(1, 2, figsize=(14, 4), sharey=True)
    for ax, stat, title in zip(axes, ["mean", "median"],
                                ["Mean Reasoning Tokens", "Median Reasoning Tokens"]):
        for arm in ARMS:
            if arm not in agg:
                continue
            arm_runs = [r for r in runs if r in agg[arm]]
            vals = []
            for r in arm_runs:
                all_rt = []
                for p in POSTURES:
                    s = agg[arm][r]["posture_stats"][p]["reasoning_tokens"]
                    all_rt.extend(s.get("raw", []))
                vals.append(getattr(statistics, stat)(all_rt) if all_rt else 0)
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
    fig.legend(handles, POSTURES, loc="upper center", ncol=2, fontsize=8,
               bbox_to_anchor=(0.5, 1.02))
    fig.suptitle("Reasoning Posture Distribution", fontsize=12, y=1.08)
    fig.tight_layout()
    fig.savefig(out_dir / "posture_distribution.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # 3. Mean metrics by posture category per arm (across all runs)
    for metric, ylabel, title, fname in [
        ("reasoning_tokens", "Mean tokens per block", "Reasoning Cost by Posture", "tokens_by_posture.png"),
        ("ttft_seconds", "Mean TTFT (seconds)", "Time to First Token by Posture", "ttft_by_posture.png"),
        ("total_tokens", "Mean total tokens", "Total Token Usage by Posture", "total_tokens_by_posture.png"),
    ]:
        posture_vals = {arm: {p: [] for p in POSTURES} for arm in ARMS}
        for arm in ARMS:
            for run in runs:
                if arm not in agg or run not in agg[arm]:
                    continue
                for p in POSTURES:
                    s = agg[arm][run]["posture_stats"][p][metric]
                    if s["count"] > 0:
                        posture_vals[arm][p].extend(s.get("raw", []))

        fig, ax = plt.subplots(figsize=(8, 4))
        x = range(len(ARMS))
        width = 0.35
        for i, posture in enumerate(POSTURES):
            vals = []
            for arm in ARMS:
                pv = posture_vals[arm][posture]
                vals.append(statistics.mean(pv) if pv else 0)
            bars = ax.bar([xi + i * width for xi in x], vals, width,
                          color=POSTURE_COLORS[posture], label=posture)
            for bar, val in zip(bars, vals):
                if val > 0:
                    label = f"{val:.1f}" if metric == "ttft_seconds" else f"{val:.0f}"
                    ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 2,
                            label, ha="center", va="bottom", fontsize=8)
        ax.set_xticks([xi + width / 2 for xi in x])
        ax.set_xticklabels([ARM_LABELS[a] for a in ARMS], fontsize=9)
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.legend(fontsize=8)
        ax.grid(axis="y", alpha=0.3)
        fig.tight_layout()
        fig.savefig(out_dir / fname, dpi=150)
        plt.close(fig)


# ── Text summary ────────────────────────────────────────────────────────────

def print_summary(agg: dict, runs: list[int]):
    print(f"\n{'='*64}")
    print("  ANALYSIS SUMMARY — Reconciliation Tax")
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
            flags = ""
            if d["experience_resolved_count"]:
                flags += f" exp_resolved={d['experience_resolved_count']}"
            if d["bad_tail_count"]:
                flags += f" bad_tail={d['bad_tail_count']}"
            print(f"    Run {run}: {d['total_count']} blocks, {posture_str}{flags}")
            for p in POSTURES:
                ps = d["posture_stats"][p]
                if ps["reasoning_tokens"]["count"] == 0:
                    continue
                rt = ps["reasoning_tokens"]
                ttft = ps["ttft_seconds"]
                tt = ps["total_tokens"]
                print(f"      {p} ({rt['count']}): "
                      f"reasoning={rt['mean']:.0f}/{rt['median']:.0f} mean/med, "
                      f"ttft={ttft['mean']:.1f}/{ttft['median']:.1f}s, "
                      f"total_tok={tt['mean']:.0f}/{tt['median']:.0f}")

    print(f"{'='*64}")


# ── Summary CSV ────────────────────────────────────────────────────────────

def _write_summary_csv(path: Path, agg: dict, runs: list[int]):
    """Write a pivot-table-style summary CSV with per-run and arm-level totals."""
    headers = ["arm", "run",
               "nominal_count", "conflict_count", "total_count",
               "nominal_pct", "conflict_pct",
               "experience_resolved_count", "bad_tail_count"]
    for metric in METRICS:
        for posture in POSTURES:
            p_lower = posture.lower()
            headers.extend([
                f"{metric}_{p_lower}_mean",
                f"{metric}_{p_lower}_median",
                f"{metric}_{p_lower}_total",
            ])
    headers.append("reasoning_tokens_total")

    def _row(arm_label, run_label, d):
        tc = d["total_count"]
        pc = d["posture_counts"]
        row = [
            arm_label, run_label,
            pc.get("Nominal", 0), pc.get("Conflict", 0), tc,
            f"{pc.get('Nominal', 0) / tc:.2%}" if tc else "",
            f"{pc.get('Conflict', 0) / tc:.2%}" if tc else "",
            d.get("experience_resolved_count", 0),
            d.get("bad_tail_count", 0),
        ]
        for metric in METRICS:
            for posture in POSTURES:
                s = d["posture_stats"][posture][metric]
                if s["count"]:
                    row.extend([f"{s['mean']:.2f}", f"{s['median']:.2f}", f"{s['total']:.2f}"])
                else:
                    row.extend(["", "", ""])
        all_rt = sum(d["posture_stats"][p]["reasoning_tokens"]["total"] for p in POSTURES)
        row.append(f"{all_rt:.0f}")
        return row

    def _aggregate(rows_data):
        tc = sum(d["total_count"] for d in rows_data)
        pc = {p: sum(d["posture_counts"].get(p, 0) for d in rows_data) for p in POSTURES}
        er = sum(d.get("experience_resolved_count", 0) for d in rows_data)
        bt = sum(d.get("bad_tail_count", 0) for d in rows_data)
        ps = {}
        for p in POSTURES:
            ps[p] = {}
            for m in METRICS:
                all_vals = []
                for d in rows_data:
                    s = d["posture_stats"][p][m]
                    all_vals.extend(s.get("raw", []))
                ps[p][m] = {
                    "mean": statistics.mean(all_vals) if all_vals else 0,
                    "median": statistics.median(all_vals) if all_vals else 0,
                    "total": sum(all_vals) if all_vals else 0,
                    "count": len(all_vals),
                    "raw": all_vals,
                }
        return {
            "total_count": tc,
            "posture_counts": pc,
            "experience_resolved_count": er,
            "bad_tail_count": bt,
            "posture_stats": ps,
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
                        help="Skip posture coding (metrics only).")
    parser.add_argument("--load-postures", metavar="PATH",
                        help="Load posture labels from a previous reasoning_blocks.json "
                             "instead of re-coding. Implies --no-posture for the coding step.")
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

    count_reasoning_tokens(reasoning_data)

    if args.load_postures:
        posture_path = Path(args.load_postures)
        print(f"Loading posture labels from {posture_path}...", flush=True)
        existing = json.loads(posture_path.read_text(encoding="utf-8"))
        loaded = 0
        for data in existing.values():
            rd_key = (data["arm"], data["run"], data["session_id"], data["customer"])
            if rd_key in reasoning_data:
                for i, block in enumerate(data.get("blocks", [])):
                    if i < len(reasoning_data[rd_key]):
                        reasoning_data[rd_key][i]["posture"] = block.get("posture", "Nominal")
                        reasoning_data[rd_key][i]["experience_resolved"] = block.get("experience_resolved", False)
                        reasoning_data[rd_key][i]["bad_tail"] = block.get("bad_tail", False)
                        loaded += 1
        print(f"  {loaded} posture labels loaded.")
    elif not args.no_posture and total_blocks > 0:
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
                         "reasoning_text", "reasoning_tokens", "posture",
                         "experience_resolved", "bad_tail",
                         "ttft_seconds", "input_tokens", "output_tokens",
                         "total_tokens", "cache_read_tokens", "cache_write_tokens"])
        for (arm, run, sid, customer), blocks in sorted(reasoning_data.items()):
            row_id = f"{arm}_r{run}_{sid}"
            for block in blocks:
                writer.writerow([
                    row_id, arm, run, sid, customer,
                    block["text"], block["token_count"],
                    block.get("posture", ""),
                    block.get("experience_resolved", ""),
                    block.get("bad_tail", ""),
                    block.get("ttft_seconds", ""),
                    block.get("input_tokens", ""),
                    block.get("output_tokens", ""),
                    block.get("total_tokens", ""),
                    block.get("cache_read_tokens", ""),
                    block.get("cache_write_tokens", ""),
                ])
    print(f"CSV saved to {csv_path}")

    # Save summary pivot CSV
    summary_path = out_dir / "summary.csv"
    _write_summary_csv(summary_path, agg, runs)
    print(f"Summary saved to {summary_path}")

    print_summary(agg, runs)
    print(f"Raw data saved to {raw_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
