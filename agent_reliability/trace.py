"""Structured trace of one agent run, one JSON file per task run.

Trace schema (abridged):
{
  "task_id", "task", "condition", "config", "model",
  "started_at", "ended_at", "duration_s",
  "status": "answered" | "step_limit" | "api_error" | "no_answer",
  "final_answer": str | null,
  "finish_mode": "final_answer_tool" | "text_response" | null,
  "error": str | null,
  "reflection_plan": str | null,
  "stats": {"model_calls", "tool_calls", "tool_errors", "retries", "self_checks",
            "self_checks_answered", "empty_responses",
            "prompt_tokens", "output_tokens"},
  "steps": [
    {"index", "kind": "reflection" | "model" | "self_check",
     "nudged": bool,                          # empty response; model was nudged to continue
     "reasoning": str,                        # model text in this turn
     "tool_calls": [{"name", "args", "output", "error", "duration_s"}],
     "proposed_answer": str | null,           # if final_answer was called in this step
     "note": str | null,
     "usage": {...}, "retries": int, "latency_s": float}
  ]
}
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class ToolCallRecord:
    name: str
    args: dict
    output: Any = None
    error: str | None = None
    duration_s: float = 0.0


@dataclass
class Step:
    index: int
    kind: str
    reasoning: str = ""
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    proposed_answer: str | None = None
    nudged: bool = False             # response was empty, and the model was nudged to continue
    note: str | None = None
    usage: dict = field(default_factory=dict)
    retries: int = 0
    latency_s: float = 0.0


@dataclass
class Trace:
    task_id: str
    task: str
    condition: str
    config: dict
    model: str
    started_at: str = field(default_factory=_now)
    ended_at: str | None = None
    duration_s: float = 0.0
    status: str = "running"
    final_answer: str | None = None
    finish_mode: str | None = None
    error: str | None = None
    reflection_plan: str | None = None
    steps: list[Step] = field(default_factory=list)
    _t0: float = field(default_factory=time.perf_counter, repr=False)

    def add_step(self, kind: str, **kwargs) -> Step:
        step = Step(index=len(self.steps), kind=kind, **kwargs)
        self.steps.append(step)
        return step

    def finish(self, status: str, final_answer: str | None = None,
               finish_mode: str | None = None, error: str | None = None) -> None:
        self.status = status
        self.final_answer = final_answer
        self.finish_mode = finish_mode
        self.error = error
        self.ended_at = _now()
        self.duration_s = round(time.perf_counter() - self._t0, 3)

    @property
    def stats(self) -> dict:
        calls = [c for s in self.steps for c in s.tool_calls]
        return {
            "model_calls": sum(1 for s in self.steps if s.kind in ("model", "self_check", "reflection")),
            "empty_responses": sum(1 for s in self.steps if s.nudged or (not s.reasoning and not s.tool_calls
                                                                        and s.proposed_answer is None)),
            # self-check steps where the model actually produced something (text, tool call, or answer)
            "self_checks_answered": sum(1 for s in self.steps if s.kind == "self_check" and not s.nudged),
            "tool_calls": len(calls),
            "tool_errors": sum(1 for c in calls if c.error),
            "retries": sum(s.retries for s in self.steps),
            "self_checks": sum(1 for s in self.steps if s.kind == "self_check"),
            "prompt_tokens": sum(s.usage.get("prompt_tokens", 0) for s in self.steps),
            "output_tokens": sum(s.usage.get("output_tokens", 0) for s in self.steps),
        }

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("_t0", None)
        d["stats"] = self.stats
        return d

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8")
        return path


def load_trace(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
