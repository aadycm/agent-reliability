"""Stress conditions: degrade the agent's operating environment, keeping the tasks identical.

The v1 study hit a ceiling (every task solved by both models), so no failures existed to
categorize. Rather than rewriting the tasks after seeing the results - which would let the author
tune difficulty to taste - these knobs make the *environment* harder in ways that are objective,
reproducible, and independent of any particular task:

  tool_failure_rate   each tool call fails with a transient error with this probability, and the
                      agent must notice and retry. Seeded per task, so a rerun reproduces exactly
                      the same failures.
  search_level        how much of the `search` result is withheld. A dose ladder, so the effect can
                      be measured as a curve rather than a single point:
                        off      - untouched (up to top_k full results)
                        mild     - top 2 results, full snippets
                        moderate - top 1 result, full snippet
                        severe   - top 1 result, first sentence only (the original setting)
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
                 seed: int = 0, search_level: str = "severe"):
        self._inner = inner
        self.tool_failure_rate = tool_failure_rate
        self.degrade_search = degrade_search
        self.search_level = search_level if degrade_search else "off"
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
            result.output = _truncate_search(result.output, self.search_level)
        return result


KEEP_RESULTS = {"mild": 2, "moderate": 1, "severe": 1}


def _truncate_search(output, level: str = "severe"):
    """Withhold part of the search result, by dose level (see module docstring)."""
    if level == "off" or not isinstance(output, list) or not output:
        return output
    if level not in KEEP_RESULTS:
        raise ValueError(f"unknown search level {level!r}; expected one of {sorted(KEEP_RESULTS) + ['off']}")
    kept = [dict(d) for d in output[: KEEP_RESULTS[level]]]
    if level == "severe":
        snippet = str(kept[0].get("snippet", ""))
        kept[0]["snippet"] = re.split(r"(?<=[.!?])\s", snippet.strip(), maxsplit=1)[0]
    note = {"mild": "results truncated: top 2 matches only",
            "moderate": "results truncated: top match only",
            "severe": "results truncated: top match only, first sentence only"}[level]
    kept[0]["note"] = note
    return kept
