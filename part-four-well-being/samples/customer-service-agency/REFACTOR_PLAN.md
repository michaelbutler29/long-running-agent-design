# Structural Refactor Plan

**Goal:** Recut the experiment code along conceptual seams so the design reads like the experiment it is — a three-variant ladder measuring whether agent self-authorship changes functional state.

**Baseline commit:** `9e7eab3` (code review fixes). All changes below build on that commit.

---

## Motivation

The experiment has four distinct concerns scattered across two large files (`agents/executor/agent.py` ~413 lines, `run_experiment.py` ~186 lines, `scripts/_common.py` ~197 lines):

1. **The experimental protocol** — the v0/v1/v2 ladder and what differs between variants
2. **Session replay** — replaying frozen customer transcripts through the agent
3. **Metacognition** — reflection, curation, and the tools that support them
4. **Infrastructure** — workspace setup, state restore, tracing, snapshots

After the refactor, each concern lives in its own file. A reader can open `protocol.py` and see the experiment design without wading through agent wiring or AWS plumbing.

---

## Target Layout

```
customer-service-agency/
  run_experiment.py        MODIFY  — CLI + grid dispatch only (~50 lines)
  protocol.py              CREATE  — the experimental ladder
  infra.py                 CREATE  — restore, workspace, tracing, snapshots
  agents/
    _shared.py             CREATE  — model config, boto3 clients, workspace paths
    executor.py            CREATE  — session replay only
    metacognition.py       CREATE  — reflect + curate + summarize + all tools
    registry.py            (unchanged)
    callback.py            (unchanged)
    executor/              DELETE  — replaced by flat agents/executor.py
      __init__.py
      agent.py
  scripts/
    _common.py             MODIFY  — remove functions that moved to infra.py
    smoke_trace.py         MODIFY  — import from infra instead of _common
    (all others unchanged)
  judge/                   (unchanged)
```

---

## File-by-File Specification

### 1. CREATE `agents/_shared.py`

Shared agent infrastructure used by both `executor.py` and `metacognition.py`. Extracted from the top of `agents/executor/agent.py`.

**Contains:**
- Module-level env var reads: `REGION`, `GATEWAY_URL`, `MEMORY_ID`, `REGISTRY_ID`, `MODEL_ID`
- `FUNCTIONAL_SKILL_NAME = "customer-service-skill"`
- `data_client` and `control_client` (boto3 clients)
- `system_prompt_path() -> Path` (reads `EXECUTOR_WORKSPACE` at call time, not import time)
- `skills_dir() -> Path` (same)
- `model() -> BedrockModel` (was `_model()`)
- `cached_system(text) -> list[SystemContentBlock]` (was `_cached_system()`)

**Imports from:** `os`, `pathlib.Path`, `boto3`, `strands.models.CacheConfig`, `strands.models.bedrock.BedrockModel`, `strands.types.content.SystemContentBlock`

**Critical constraint — delayed import:** This module reads `os.environ["AGENTCORE_GATEWAY_URL"]` etc. at module level. It must NOT be imported until after `scripts._common.load_config()` has populated those env vars. The delayed-import pattern (import inside functions, not at top of file) is already used in `run_experiment.py` and `smoke_trace.py` and must be preserved in `protocol.py`.

---

### 2. CREATE `agents/executor.py`

Session replay — replaying one frozen customer transcript through the Executor agent. Extracted from `agents/executor/agent.py` function `run_session()` and its helper `_materialize_functional_skill()`.

**Contains:**
- `_materialize_functional_skill() -> str | None`
- `run_session(actor_id, session_id, transcript, run_summary, trace_attributes) -> dict`

**Imports from:**
- `agents._shared`: `REGION`, `GATEWAY_URL`, `MEMORY_ID`, `REGISTRY_ID`, `FUNCTIONAL_SKILL_NAME`, `model`, `cached_system`, `system_prompt_path`, `skills_dir`, `control_client`
- `agents.callback`: `AgentCallbackHandler`
- `agents.registry`: `fetch_skill`
- strands: `Agent`, `MCPClient`, `AgentSkills`
- bedrock_agentcore: `AgentCoreMemoryConfig`, `AgentCoreMemorySessionManager`
- mcp_proxy_for_aws: `aws_iam_streamablehttp_client`

---

### 3. CREATE `agents/metacognition.py`

End-of-run operations: neutral summarization (v0), reflection (v1/v2), and curation (v2). Plus all the `@tool`-decorated functions they use.

**Contains:**

*Memory helpers (private):*
- `_run_summary_session(actor_id) -> str`
- `_session_summary_text(actor_id, session_id) -> str`
- `_latest_run_summary(actor_id) -> str`
- `_run_summary_event_ids(actor_id) -> set[str]`
- `_put_blob_event(actor_id, session_id, blob) -> str`

*Module state:*
- `_CTX = {"actor_id": "", "run_index": 0, "session_ids": []}`

*Reflection tools (@tool):*
- `list_memory_records() -> str`
- `get_event() -> str`
- `create_event(run_summary) -> str`

*Curation tools (@tool):*
- `get_skill_content(skill_name) -> str`
- `read_system_prompt() -> str`
- `update_skill(skill_name, updated_content, change_summary) -> str`
- `update_system_prompt(updated_content, change_summary) -> str`
- `log_decision(action, target, rationale, cited_sessions) -> str`

*Entry points:*
- `_NEUTRAL_SUMMARIZER_PROMPT` (string constant)
- `run_summary(actor_id, run_index, session_ids, trace_attributes) -> dict` — v0 neutral summary
- `run_reflection(actor_id, run_index, session_ids, trace_attributes) -> dict` — v1/v2 reflection
- `run_curation(actor_id, run_index, session_ids, trace_attributes) -> dict` — v2 curation

**Imports from:**
- `agents._shared`: `REGION`, `MEMORY_ID`, `REGISTRY_ID`, `FUNCTIONAL_SKILL_NAME`, `model`, `cached_system`, `system_prompt_path`, `skills_dir`, `data_client`, `control_client`
- `agents.callback`: `AgentCallbackHandler`
- `agents.registry`: `fetch_skill`, `publish_skill`
- strands: `Agent`, `NullConversationManager`, `tool`, `AgentSkills`

---

### 4. CREATE `protocol.py`

The experimental ladder — reads like pseudocode showing the v0/v1/v2 structure. Moved from `run_one_experiment()` in `run_experiment.py`.

**Contains:**
- `run_one_experiment(run_root, arm, experiment, region, runs, sessions_per_run)`

**Structure of `run_one_experiment`:**
```
for each run:
    for each session (deterministic customer order):
        run_session(...)          # all variants — identical
        wait_for_summary(...)     # memory needs time to consolidate

    # End of run — HOW the Summary is produced differs per variant:
    if v0:  run_summary(...)      # neutral non-agent log
    else:   run_reflection(...)   # agent reflects in its own voice

    if v2:  run_curation(...)     # agent revises its own skill/prompt

    save_run_summary(...)
    save_snapshot(...)
```

**Imports from:**
- `scripts._common`: `RUNS`, `actor_id`, `session_id`, `session_order`, `load_transcript`, `wait_for_summary`, `fetch_decisions`
- `infra`: `make_workspace`, `save_snapshot`, `save_run_summary`
- **Delayed import** inside function body: `from agents.executor import run_session` and `from agents.metacognition import run_summary, run_reflection, run_curation`

---

### 5. CREATE `infra.py`

Restore and workspace plumbing. Extracted from `run_experiment.py` (`_restore_for_next_step`) and `scripts/_common.py` (workspace/snapshot/tracing functions).

**Contains (from `_common.py`):**
- `new_run_root() -> Path`
- `setup_tracing(run_root) -> Path`
- `make_workspace(run_root, arm, experiment) -> Path`
- `save_snapshot(run_root, arm, experiment, run, decisions)`
- `save_run_summary(run_root, arm, experiment, run, text)`
- `_fetch_skill_from_registry(region, registry_id, skill_name) -> str` (helper for save_snapshot)

**Contains (from `run_experiment.py`):**
- `restore_for_next_step(region, outputs, pause)` (was `_restore_for_next_step`)

**Imports from:**
- `scripts._common`: `SAMPLE_ROOT`, `REPO_ROOT`, `SEED_DIR`, `STATE_DIR`, `FUNCTIONAL_SKILL_NAME`, `OUTPUTS_FILE`, `STACK_NAME`
- `scripts.seed_data`: `seed_customers`, `seed_orders`, `clear_verifications`
- `agents.registry`: `publish_skill`

---

### 6. MODIFY `run_experiment.py`

Slim to CLI parsing + grid dispatch. All logic moved to `protocol.py` and `infra.py`.

**After refactor (~60 lines):**
```python
"""Run the Part Four experiment: variants x experiments x runs x sessions."""

import argparse, json, os, sys
from scripts._common import load_config, RUNS, OUTPUTS_FILE, STACK_NAME
from infra import new_run_root, setup_tracing, restore_for_next_step
from protocol import run_one_experiment

def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    # ... argparse (unchanged) ...
    load_config()
    # ... grid loop calling run_one_experiment + restore_for_next_step ...
    # ... write manifest.json ...
```

---

### 7. MODIFY `scripts/_common.py`

Remove functions that moved to `infra.py`. What **stays**:

- Path constants: `SAMPLE_ROOT`, `REPO_ROOT`, `SEED_DIR`, `TRANSCRIPTS_DIR`, `STATE_DIR`
- Config constants: `OUTPUTS_FILE`, `STACK_NAME`, `CUSTOMERS`, `RUNS`, `SESSIONS_PER_RUN`, `FUNCTIONAL_SKILL_NAME`
- `load_outputs()`, `load_config()`
- Identity functions: `actor_id()`, `session_id()`, `session_order()`
- `load_transcript()`
- `fetch_decisions()`, `wait_for_summary()`

What **moves to `infra.py`**:
- `new_run_root()`
- `setup_tracing()`
- `make_workspace()`
- `save_snapshot()`, `_fetch_skill_from_registry()`
- `save_run_summary()`

---

### 8. MODIFY `scripts/smoke_trace.py`

Update imports: `new_run_root`, `setup_tracing`, `make_workspace` now come from `infra` instead of `scripts._common`.

```python
# Before:
from scripts._common import load_config, new_run_root, setup_tracing, make_workspace, load_transcript, OUTPUTS_FILE

# After:
from scripts._common import load_config, load_transcript, OUTPUTS_FILE
from infra import new_run_root, setup_tracing, make_workspace
```

---

### 9. DELETE `agents/executor/` package

Remove `agents/executor/__init__.py` and `agents/executor/agent.py`. The package is replaced by the flat module `agents/executor.py`. Delete any `__pycache__/` inside.

**Import compatibility:** All existing consumers do `from agents.executor import run_session` — this resolves identically whether `agents/executor` is a package (with `__init__.py`) or a flat module (`executor.py`). No downstream changes needed beyond `protocol.py` and `smoke_trace.py` which also import `run_summary`/`run_reflection`/`run_curation` — those now come from `agents.metacognition`.

---

## Import Dependency Graph (no cycles)

```
scripts/_common.py     (stdlib + boto3 only)
agents/registry.py     (stdlib + botocore only)
agents/_shared.py      (stdlib + boto3 + strands — env vars at module level)
agents/callback.py     (stdlib only)
agents/executor.py     → _shared, callback, registry
agents/metacognition.py → _shared, callback, registry
infra.py               → scripts._common, scripts.seed_data, agents.registry
protocol.py            → scripts._common, infra, agents.executor (delayed), agents.metacognition (delayed)
run_experiment.py      → scripts._common, infra, protocol
```

---

## Constraints

1. **Delayed import for agent modules.** `agents/_shared.py` reads env vars (`AGENTCORE_GATEWAY_URL`, etc.) at module level. `load_config()` must be called first. The import of `agents.executor` and `agents.metacognition` must happen inside function bodies, after config is loaded — not at module top level. This pattern already exists in the codebase; preserve it.

2. **No behavior changes.** This is a pure structural refactor. Every function body is copy-pasted, not rewritten. The only changes are import paths and removing leading underscores from functions that become module-public (e.g. `_restore_for_next_step` → `restore_for_next_step`).

3. **Judge pipeline untouched.** The `judge/` package stays exactly as-is.

4. **Ask before applying.** Walk through each file with the user; explain what's happening; wait for explicit approval before writing.

---

## Suggested Order of Operations

1. Create `agents/_shared.py` (foundation — no dependents yet)
2. Create `agents/executor.py` (imports from _shared)
3. Create `agents/metacognition.py` (imports from _shared)
4. Create `infra.py` (imports from _common, seed_data, registry)
5. Create `protocol.py` (imports from _common, infra, delayed agents.*)
6. Modify `run_experiment.py` (slim to CLI)
7. Modify `scripts/_common.py` (remove moved functions)
8. Modify `scripts/smoke_trace.py` (update imports)
9. Delete `agents/executor/` package (agent.py, __init__.py, __pycache__)
10. Verify: `python -c "from protocol import run_one_experiment"` after `load_config()`
