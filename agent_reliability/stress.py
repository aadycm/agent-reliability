"""Stress conditions: degrade the agent's operating environment, keeping the tasks identical.

The v1 study hit a ceiling (every task solved by both models), so no failures existed to
categorize. Rather than rewriting the tasks after seeing the results - which would let the author
tune difficulty to taste - these knobs make the *environment* harder in ways that are objective,
reproducible, and independent of any particular task:

  tool_failure_rate   each tool call fails with a transient error with this probability, and the
                      agent must notice and retry. Seeded per task, so a rerun reproduces exactly
                      the same failures.
  degrade_search      `search` returns one truncated result instead of several full ones, so facts
                      must be gathered over more, better-targeted queries.
  (tight step limit)  set with the existing --max-steps; no wrapper needed.

Each knob targets a different suspected weak point: error recovery, information gathering, and
planning efficiency.
"""

from __future__ import annotations

import random
import re

from .tools.base import ToolRegistry, ToolResult

TRANSIENT_ERROR = "temporary tool failure (service unavailable). The call was not executed; try again."


class StressRegistry(ToolRegistry):
    """Wraps a registry and degrades it. Declarations are unchanged, so the model is not told."""

    def __init__(self, inner: ToolRegistry, tool_failure_rate: float = 0.0, degrade_search: bool = False,
                 seed: int = 0):
        self._inner = inner
        self.tool_failure_rate = tool_failure_rate
        self.degrade_search = degrade_search
        self.seed = seed
        self._rng = random.Random(seed)

    # -- pass-through ------------------------------------------------------
    @property
    def _tools(self):  # used by list-tools and by subset()
        return self._inner._tools

    def get(self, name):
        return self._inner.get(name)

    def names(self):
        return self._inner.names()

    def declarations(self):
        return self._inner.declarations()

    # -- per-run determinism -----------------------------------------------
    def begin_run(self, task_id: str) -> None:
        """Reseed from (seed, task_id) so each task's failure pattern is fixed and reproducible."""
        self._rng = random.Random(f"{self.seed}:{task_id}")

    # -- the degradations ---------------------------------------------------
    def execute(self, name: str, args: dict) -> ToolResult:
        if self.tool_failure_rate and self._rng.random() < self.tool_failure_rate:
            return ToolResult(error=TRANSIENT_ERROR)
        result = self._inner.execute(name, args)
        if self.degrade_search and name == "search" and result.error is None:
            result.output = _truncate_search(result.output)
        return result


def _truncate_search(output):
    """Keep only the top hit, and only its first sentence."""
    if not isinstance(output, list) or not output:
        return output
    top = dict(output[0])
    snippet = str(top.get("snippet", ""))
    first = re.split(r"(?<=[.!?])\s", snippet.strip(), maxsplit=1)[0]
    top["snippet"] = first
    top["note"] = "results truncated: 1 of possibly several matches, first sentence only"
    return [top]
