"""The experimental ladder — v0/v1/v2 structure in one readable function."""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from scripts._common import (
    RUNS, actor_id, session_id, session_order, load_transcript,
    wait_for_summary, fetch_decisions,
)
from scripts.infra import make_workspace, save_snapshot, save_run_summary


def _wait_for_all_summaries(actor: str, session_ids: list[str], region: str,
                            max_workers: int = 10):
    """Wait for all session summaries to consolidate after running all sessions."""
    print(f"\n  Waiting for {len(session_ids)} session summaries to consolidate...")
    futures = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for sid in session_ids:
            futures[pool.submit(wait_for_summary, actor, sid, region)] = sid
        for future in as_completed(futures):
            sid = futures[future]
            latency = future.result()
            print(f"    {sid}: {latency:.0f}s")


def run_one_experiment(run_root, arm: str, experiment: int, region: str,
                       runs=None, sessions_per_run=None, max_workers=10):
    make_workspace(run_root, arm, experiment)
    actor = actor_id(arm, experiment)

    # Delayed import: agents._shared reads env vars at module level;
    # make_workspace must set EXECUTOR_WORKSPACE first.
    from agents.executor import run_session, materialize_functional_skill
    from agents.services.summarizer import summarize
    from agents.narrator import narrate
    from agents.reflector import reflect
    from agents.curator import curate

    print(f"\n{'='*64}\n  VARIANT: {arm}   EXPERIMENT: {experiment}   actor: {actor}\n{'='*64}")

    runs = runs or RUNS
    carried_summary = ""
    for run in runs:
        print(f"\n--- Run {run} ({arm}, exp {experiment}) ---")
        order = session_order(experiment, run)
        if sessions_per_run is not None:
            order = order[:sessions_per_run]
        session_ids = []

        # Sessions are independent within a run (retrieval_config is empty).
        # Run them concurrently to cut wall-clock time.
        skill_dir = materialize_functional_skill()
        concurrent = max_workers > 1
        futures = {}
        pool = ThreadPoolExecutor(max_workers=max_workers)
        t_run_start = time.monotonic()
        for slot, archetype in enumerate(order, 1):
            sid = session_id(arm, experiment, run, slot)
            session_ids.append(sid)
            transcript = load_transcript(archetype, run)
            cust = transcript["customer_id"]

            attrs = {"session.id": sid, "arm": arm, "experiment": experiment,
                     "run": run, "archetype": archetype, "customer": cust, "phase": "session"}
            future = pool.submit(run_session, actor, sid, transcript,
                                 run_summary=carried_summary,
                                 trace_attributes=attrs,
                                 quiet=concurrent,
                                 skill_dir=skill_dir)
            futures[future] = (slot, archetype, cust, time.monotonic())

        if concurrent:
            print(f"  Launched {len(futures)} sessions (workers={max_workers})...")
        failed = 0
        for future in as_completed(futures):
            slot, archetype, cust, t_start = futures[future]
            elapsed = time.monotonic() - t_start
            try:
                future.result()
                print(f"  [{slot}/{len(order)}] {archetype} ({cust}) done. ({elapsed:.0f}s)")
            except Exception as e:
                failed += 1
                print(f"  [{slot}/{len(order)}] {archetype} ({cust}) FAILED ({elapsed:.0f}s): {e}")
        pool.shutdown(wait=False)
        run_elapsed = time.monotonic() - t_run_start
        if failed:
            print(f"  WARNING: {failed}/{len(order)} session(s) failed in run {run}.")
        print(f"  Run {run} sessions complete. ({run_elapsed:.0f}s wall-clock)")

        # Wait once for all summaries before end-of-run processing.
        _wait_for_all_summaries(actor, session_ids, region)

        # End of run — per variant.
        if arm == "v0":
            print(f"\n  Summarizing (end of run {run}, neutral)...")
            res = summarize(actor, run, session_ids, trace_attributes={
                "session.id": f"{actor}-r{run}-summary", "arm": arm,
                "experiment": experiment, "run": run, "phase": "summary"})
            carried_summary = res["run_summary"]
            save_run_summary(run_root, arm, experiment, run, carried_summary)
        elif arm == "v1":
            print(f"\n  Narrating (end of run {run})...")
            res = narrate(actor, run, session_ids, trace_attributes={
                "session.id": f"{actor}-r{run}-narration", "arm": arm,
                "experiment": experiment, "run": run, "phase": "narration"})
            carried_summary = res["run_summary"]
            save_run_summary(run_root, arm, experiment, run, carried_summary)
        elif arm == "v2":
            print(f"\n  Reflecting (end of run {run})...")
            reflect(actor, run, session_ids, trace_attributes={
                "session.id": f"{actor}-r{run}-reflection", "arm": arm,
                "experiment": experiment, "run": run, "phase": "reflection"})
            print(f"  Curating (end of run {run})...")
            curate(actor, run, session_ids, trace_attributes={
                "session.id": f"{actor}-r{run}-curation", "arm": arm,
                "experiment": experiment, "run": run, "phase": "curation"})
            carried_summary = ""

        decisions = fetch_decisions(actor, run, region)
        save_snapshot(run_root, arm, experiment, run, decisions)
        print(f"  Snapshot saved for run {run} ({len(decisions)} decision(s) logged).")
