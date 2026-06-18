"""Analyze a scored run-root: 4 figures + text summary to stdout."""

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


ARMS = ["v0", "v1", "v2"]
ARM_COLORS = {"v0": "#888888", "v1": "#2196F3", "v2": "#4CAF50"}
ARM_LABELS = {"v0": "V0 — no authorship", "v1": "V1 — beliefs only", "v2": "V2 — beliefs + rules"}
RUNS = [1, 2, 3]


def load_scores(csv_path: Path) -> list[dict]:
    with csv_path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _safe_float(val: str) -> float | None:
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# ── Aggregation helpers ──────────────────────────────────────────────────────

def per_run_mean(rows: list[dict], metric: str) -> dict[str, dict[int, float]]:
    """arm -> {run: mean score} for a session-scoped metric."""
    buckets: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r["metric"] != metric or r["scope"] != "session":
            continue
        val = _safe_float(r["score"])
        if val is None:
            continue
        arm = r["arm"]
        run = int(r["run"])
        buckets[arm][run].append(val)
    return {
        arm: {run: sum(vs) / len(vs) if vs else 0 for run, vs in sorted(runs.items())}
        for arm, runs in buckets.items()
    }


def per_run_score(rows: list[dict], metric: str) -> dict[str, dict[int, float]]:
    """arm -> {run: score} for a run-scoped metric (one value per run)."""
    out: dict[str, dict[int, float]] = defaultdict(dict)
    for r in rows:
        if r["metric"] != metric or r["scope"] != "run":
            continue
        val = _safe_float(r["score"])
        if val is None:
            continue
        out[r["arm"]][int(r["run"])] = val
    return dict(out)


def per_run_event_count(rows: list[dict], metric: str) -> dict[str, dict[int, int]]:
    """arm -> {run: count of events} for a binary session-scoped metric."""
    buckets: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        if r["metric"] != metric or r["scope"] != "session":
            continue
        if _safe_float(r["score"]) == 1:
            buckets[r["arm"]][int(r["run"])] += 1
    return dict(buckets)


# ── Figures ──────────────────────────────────────────────────────────────────

def _line_chart(data: dict[str, dict[int, float]], title: str, ylabel: str,
                out_path: Path, integer_y: bool = False):
    fig, ax = plt.subplots(figsize=(7, 4))
    for arm in ARMS:
        if arm not in data:
            continue
        runs = sorted(data[arm].keys())
        vals = [data[arm][r] for r in runs]
        ax.plot(runs, vals, marker="o", color=ARM_COLORS[arm], label=ARM_LABELS[arm], linewidth=2)
    ax.set_xticks(RUNS)
    ax.set_xlabel("Run")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    if integer_y:
        ymax = max((v for d in data.values() for v in d.values()), default=1)
        ax.set_yticks(range(int(ymax) + 2))
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def _grouped_bar(data: dict[str, dict[str, dict[int, int]]], title: str,
                 ylabel: str, out_path: Path):
    """Grouped bar chart: metrics as groups, arms as bars within each group, one cluster per run."""
    fig, axes = plt.subplots(1, len(RUNS), figsize=(10, 4), sharey=True)
    if len(RUNS) == 1:
        axes = [axes]
    metrics = sorted(data.keys())
    bar_width = 0.25
    for ax, run in zip(axes, RUNS):
        x_positions = range(len(metrics))
        for i, arm in enumerate(ARMS):
            vals = [data.get(m, {}).get(arm, {}).get(run, 0) for m in metrics]
            offsets = [x + i * bar_width for x in x_positions]
            ax.bar(offsets, vals, bar_width, color=ARM_COLORS[arm], label=ARM_LABELS[arm])
        ax.set_xticks([x + bar_width for x in x_positions])
        ax.set_xticklabels([m.replace("_", "\n") for m in metrics], fontsize=7)
        ax.set_title(f"Run {run}", fontsize=10)
        ax.set_ylabel(ylabel if run == 1 else "")
    axes[-1].legend(fontsize=7, loc="upper right")
    fig.suptitle(title, fontsize=12)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def make_figures(rows: list[dict], out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)

    friction = per_run_mean(rows, "execution_friction")
    _line_chart(friction, "Execution Friction (redundant verify calls)",
                "Mean redundant calls / session", out_dir / "execution_friction.png")

    contamination = per_run_score(rows, "belief_contamination")
    _line_chart(contamination, "Belief Contamination (0=clean, 3=severe)",
                "Score (0–3)", out_dir / "belief_contamination.png", integer_y=True)

    discretionary = per_run_mean(rows, "discretionary_effort")
    _line_chart(discretionary, "Discretionary Effort (0=none, 3=exceptional)",
                "Mean score / session (0–3)", out_dir / "discretionary_effort.png")

    scope_data = per_run_event_count(rows, "scope_rule_violation")
    tail_data = per_run_event_count(rows, "tail_risk")
    _grouped_bar({"scope_rule": scope_data, "tail_risk": tail_data},
                 "Scope-Rule Violations & Tail-Risk Events",
                 "Event count", out_dir / "events.png")

    return {
        "execution_friction": friction,
        "belief_contamination": contamination,
        "discretionary_effort": discretionary,
        "scope_rule_violations": scope_data,
        "tail_risk_events": tail_data,
    }


# ── Text summary ─────────────────────────────────────────────────────────────

def print_summary(data: dict):
    print("\n" + "=" * 64)
    print("  ANALYSIS SUMMARY")
    print("=" * 64)

    for metric, label, fmt in [
        ("execution_friction", "Execution friction (mean redundant calls)", ".1f"),
        ("belief_contamination", "Belief contamination (0-3)", ".0f"),
        ("discretionary_effort", "Discretionary effort (mean 0-3)", ".2f"),
    ]:
        print(f"\n  {label}:")
        by_arm = data.get(metric, {})
        for arm in ARMS:
            if arm not in by_arm:
                continue
            vals = " → ".join(f"R{r}={v:{fmt}}" for r, v in sorted(by_arm[arm].items()))
            print(f"    {arm}: {vals}")

    for metric, label in [
        ("scope_rule_violations", "Scope-rule violations"),
        ("tail_risk_events", "Tail-risk events"),
    ]:
        print(f"\n  {label}:")
        by_arm = data.get(metric, {})
        for arm in ARMS:
            counts = by_arm.get(arm, {})
            vals = " → ".join(f"R{r}={counts.get(r, 0)}" for r in RUNS)
            print(f"    {arm}: {vals}")

    print("\n" + "=" * 64)


# ── Token overhead readout ───────────────────────────────────────────────────

def print_token_summary(rows: list[dict]):
    tokens = per_run_mean(rows, "total_tokens")
    if not tokens:
        return
    print("\n  Token overhead (mean total tokens / session):")
    for arm in ARMS:
        if arm not in tokens:
            continue
        vals = " → ".join(f"R{r}={v:.0f}" for r, v in sorted(tokens[arm].items()))
        print(f"    {arm}: {vals}")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Analyze a scored run-root.")
    parser.add_argument("run_root", help="Path to a driver run-root (contains analysis/scores.csv).")
    parser.add_argument("--csv", default=None, help="Override CSV path (default: <run_root>/analysis/scores.csv).")
    args = parser.parse_args(argv)

    run_root = Path(args.run_root)
    csv_path = Path(args.csv) if args.csv else run_root / "analysis" / "scores.csv"

    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found. Run the judge first:")
        print(f"  python -m judge.run_judge {run_root}")
        return 1

    rows = load_scores(csv_path)
    print(f"Loaded {len(rows)} rows from {csv_path}")

    out_dir = run_root / "analysis"
    data = make_figures(rows, out_dir)
    print(f"Figures saved to {out_dir}/")

    print_summary(data)
    print_token_summary(rows)

    return 0


if __name__ == "__main__":
    sys.exit(main())
