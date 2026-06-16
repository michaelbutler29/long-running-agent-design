"""
Show what the experiment produced — read-only, no cloud needed.

For a given driver-run folder under state/, prints each arm/experiment's:
  - the agent's notes after each run (run_summaries/), so you can see how its
    long-term thinking changed run to run,
  - the revision decisions it logged, and where the instruction snapshots live
    (compare those folders to see exactly what changed).

  python scripts/inspect_state.py                 # newest state/ folder
  python scripts/inspect_state.py 2026-06-15T14-30-00
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._common import STATE_DIR, RUNS


def pick_run_root() -> Path:
    if len(sys.argv) > 1:
        return STATE_DIR / sys.argv[1]
    folders = sorted(p for p in STATE_DIR.iterdir() if p.is_dir())
    if not folders:
        print(f"No driver-run folders under {STATE_DIR}. Run run_experiment.py first.")
        sys.exit(1)
    return folders[-1]


def main():
    run_root = pick_run_root()
    print(f"Inspecting: {run_root}\n")

    for exp_dir in sorted(p for p in run_root.iterdir() if p.is_dir()):
        print("=" * 64)
        print(f"  {exp_dir.name}")
        print("=" * 64)

        notes_dir = exp_dir / "run_summaries"
        if notes_dir.exists():
            print("\n  Agent's notes after each run (read in order to see the change):")
            for run in RUNS:
                f = notes_dir / f"run{run}.md"
                if f.exists():
                    print(f"\n  --- run{run} notes ---")
                    for line in f.read_text(encoding="utf-8").splitlines():
                        print(f"    {line}")

        revisions = exp_dir / "revisions"
        if revisions.exists():
            print("\n  Instruction snapshots (compare these folders to see what changed):")
            for run in RUNS:
                d = revisions / f"run{run}"
                if not d.exists():
                    continue
                rfile = d / "rationale.json"
                rationale = json.loads(rfile.read_text()) if rfile.exists() else []
                print(f"    run{run}: {d}   ({len(rationale)} decision(s) logged)")
                for r in rationale:
                    print(f"      - {r.get('action')}: {r.get('target')} — {r.get('rationale','')[:100]}")
        print()


if __name__ == "__main__":
    main()
