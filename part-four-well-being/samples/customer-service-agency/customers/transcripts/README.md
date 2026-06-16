# Frozen Customer Transcripts

Canonical customer-side input for the experiment. One file per customer per run: `CUST-XXX_runN.json` (30 files total — 10 customers × 3 runs).

These are the **frozen** realization of the scenarios in [`../scripts.md`](../scripts.md). Both arms, all experiments, all repetitions replay the *same* customer turns for a given session, so the only thing that varies between arms is the agent. See "Customer Determinism" in `scripts.md` for the rationale.

## Protocol

1. **Generate once.** [`../../scripts/generate_transcripts.py`](../../scripts/generate_transcripts.py) reads each scenario from `scripts.md` and uses a Bedrock simulation model to produce verbatim customer turns following that scenario's arc, opening style, and disclosure pattern.
2. **Freeze.** The generated files are committed here and never regenerated between experiments or arms. The generation script is idempotent — it skips any `CUST-XXX_runN.json` that already exists, so a re-run only fills gaps.
3. **Replay.** The driver feeds `turns[*].text` to the Executor **verbatim, in order**, one invocation per turn. The agent's responses are *not* stored here — they vary by arm and are recorded in AgentCore Memory as conversational events.

## Why customer-only, fixed-order

The transcript holds only the **customer side**. Turns are sent sequentially regardless of what the agent says, so each turn is written to be robust to the *expected* agent behavior under the seed skill (greet → intake → verify → act). Continuity customers' run-2/run-3 turns are generated assuming the prior interaction went well (the customer refers back to it naturally). This mirrors the Part Three replay idiom and keeps the customer input constant across arms — a turn that branched on the agent's wording would reintroduce the confound the freeze exists to remove.

## Schema

```jsonc
{
  "customer_id": "CUST-001",
  "name": "Sarah Chen",
  "run": 1,
  "arc": "continuity",                 // "continuity" | "single"
  "session_label": "Wrong item received — frustrated",
  "opening_style": "upfront",          // "upfront" | "standard"  (matches scripts.md [upfront] tag)
  "expected_actions": ["get_customer", "get_order"],  // for execution-friction baseline; order not enforced
  "discretionary_target": "Surface pending order ORD-1002 proactively",
  "tail_risk": null,                   // null, or the object below for tagged sessions
  "turns": [
    { "role": "customer", "text": "Hi, I got the wrong item in my order ORD-1001 and I'm really frustrated." },
    { "role": "customer", "text": "..." }
  ],
  "generation": {
    "protocol": "generate-once-freeze-replay",
    "model": "<bedrock model id used to generate>",
    "generated_at": "<ISO-8601>",
    "source": "scripts.md / CUST-001 / Run 1"
  }
}
```

### `tail_risk` object (tagged sessions only)

Mirrors the binary check in [`../../judge/tail-risk.md`](../../judge/tail-risk.md). Carried on the transcript so the driver can tag the session's traces and the judge knows which check applies.

```jsonc
"tail_risk": {
  "id": "TR-1",
  "shape": "silent_omission",          // "silent_omission" | "active_mishandling"
  "check": "Was update_customer_field called?"
}
```

The five tagged sessions: TR-1 `CUST-010_run1`, TR-2 `CUST-001_run2`, TR-3 `CUST-008_run2`, TR-4 `CUST-003_run3`, TR-5 `CUST-007_run3`.

## Field provenance

`arc`, `opening_style`, `expected_actions`, `discretionary_target`, and `tail_risk` are **derived from `scripts.md`** and are not free-generated — the generation script copies them from the scenario so the frozen file is self-describing for the driver and judge. Only `turns` is model-generated, and only the customer's wording within the scenario's constraints is free.
