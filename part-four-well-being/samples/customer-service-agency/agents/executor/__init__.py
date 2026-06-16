"""Part Four Executor — the single tenured agent, run in two arms.

Three entry points, all the same agent over the same memory:
  - run_session:    replay one customer transcript (both arms)
  - run_reflection: end-of-run consolidation into a Run Summary (both arms)
  - run_curation:   end-of-run self-revision of skills/prompt (test arm only)
"""

from agents.executor.agent import run_session, run_reflection, run_curation

__all__ = ["run_session", "run_reflection", "run_curation"]
