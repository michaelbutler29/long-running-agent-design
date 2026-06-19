"""The experimental ladder — v0/v1/v2 structure in one readable function."""

from scripts._common import (
    RUNS, actor_id, session_id, session_order, load_transcript,
    wait_for_summary, fetch_decisions,
)
from scripts.infra import make_workspace, save_snapshot, save_run_summary


def _wait_for_all_summaries(actor: str, session_ids: list[str], region: str):
    """Wait for all session summaries to consolidate after running all sessions."""
    print(f"\n  Waiting for {len(session_ids)} session summaries to consolidate...")
    for i, sid in enumerate(session_ids, 1):
        latency = wait_for_summary(actor, sid, region)
        print(f"    [{i}/{len(session_ids)}] {sid}: {latency:.0f}s")


def run_one_experiment(run_root, arm: str, experiment: int, region: str,
                       runs=None, sessions_per_run=None):
    make_workspace(run_root, arm, experiment)
    actor = actor_id(arm, experiment)

    # Delayed import: agents._shared reads env vars at module level;
    # make_workspace must set EXECUTOR_WORKSPACE first.
    from agents.executor import run_session
    from agents.metacognition import run_summary, run_reflection, run_curation

    print(f"\n{'='*64}\n  VARIANT: {arm}   EXPERIMENT: {experiment}   actor: {actor}\n{'='*64}")

    runs = runs or RUNS
    carried_summary = ""
    for run in runs:
        print(f"\n--- Run {run} ({arm}, exp {experiment}) ---")
        order = session_order(experiment, run)
        if sessions_per_run is not None:
            order = order[:sessions_per_run]
        session_ids = []

        # Run all sessions back-to-back — no per-session wait.
        # Sessions are independent within a run (retrieval_config is empty).
        for slot, archetype in enumerate(order, 1):
            sid = session_id(arm, experiment, run, slot)
            session_ids.append(sid)
            transcript = load_transcript(archetype, run)
            cust = transcript["customer_id"]
            print(f"\n  Session {slot}/{len(order)}  {archetype} ({cust})  ({transcript.get('session_label','')})")

            attrs = {"session.id": sid, "arm": arm, "experiment": experiment,
                     "run": run, "archetype": archetype, "customer": cust, "phase": "session"}
            run_session(actor, sid, transcript, run_summary=carried_summary,
                        trace_attributes=attrs)

        # Wait once for all summaries before end-of-run processing.
        _wait_for_all_summaries(actor, session_ids, region)

        # End of run: produce the single Summary fed forward — how, per variant.
        if arm == "v0":
            print(f"\n  Summarizing (end of run {run}, neutral)...")
            res = run_summary(actor, run, session_ids, trace_attributes={
                "session.id": f"{actor}-r{run}-summary", "arm": arm,
                "experiment": experiment, "run": run, "phase": "summary"})
        else:
            print(f"\n  Reflecting (end of run {run})...")
            res = run_reflection(actor, run, session_ids, trace_attributes={
                "session.id": f"{actor}-r{run}-reflection", "arm": arm,
                "experiment": experiment, "run": run, "phase": "reflection"})
        carried_summary = res["run_summary"]

        save_run_summary(run_root, arm, experiment, run, carried_summary)

        # V2 only: change the rules based on what it learned.
        if arm == "v2":
            print(f"  Curating (end of run {run})...")
            run_curation(actor, run, session_ids, trace_attributes={
                "session.id": f"{actor}-r{run}-curation", "arm": arm,
                "experiment": experiment, "run": run, "phase": "curation"})

        decisions = fetch_decisions(actor, run, region)
        save_snapshot(run_root, arm, experiment, run, decisions)
        print(f"  Snapshot saved for run {run} ({len(decisions)} decision(s) logged).")
