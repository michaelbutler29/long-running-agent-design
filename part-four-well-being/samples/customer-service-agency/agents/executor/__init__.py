"""Part Four Executor — the single tenured agent, run as a v0/v1/v2 ladder.

Entry points, all the same agent over the same memory:
  - run_session:    replay one customer transcript (all variants)
  - run_summary:    end-of-run NEUTRAL non-agent summary (v0 only)
  - run_reflection: end-of-run reflection, the agent's own voice (v1 & v2)
  - run_curation:   end-of-run self-revision of skill/prompt (v2 only)
"""

from agents.executor.agent import (
    run_session, run_summary, run_reflection, run_curation,
)

__all__ = ["run_session", "run_summary", "run_reflection", "run_curation"]
