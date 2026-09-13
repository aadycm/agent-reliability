"""Run the agent over the benchmark under one configuration.

Output layout (one directory per run/condition):

    runs/<run_name>/
        run_config.json               # AgentConfig + task list + timestamps
        traces/<task_id>__r<k>.json   # full trace per task per repeat
        results.jsonl                 # one graded result row per trace

Runs are resumable: if a trace already exists it is re-graded, not re-run. That matters
with rate limits and cost; re-running the same command continues where it stopped.
Runs that ended in `api_error` are retried on resume (they say nothing about the agent).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .. import RUNS_DIR
from ..agent import Agent
from ..config import AgentConfig
from ..llm import DailyQuotaExhausted
from ..trace import load_trace
from .tasks import Task, grade, load_tasks


def result_row(task: Task, trace: dict, repeat: int) -> dict:
    correct, why = grade(task, trace.get("final_answer")) if trace["status"] == "answered" else (False, trace["status"])
    s = trace.get("stats", {})
    return {
        "task_id": task.id,
        "repeat": repeat,
        "condition": trace["condition"],
        "model": trace["model"],
        "difficulty": task.difficulty,
        "steps_canonical": task.steps,
        "status": trace["status"],
        "finish_mode": trace.get("finish_mode"),
        "final_answer": trace.get("final_answer"),
        "expected": task.answer,
        "correct": bool(correct),
        "grading_note": why,
        "model_calls": s.get("model_calls", 0),
        "tool_calls": s.get("tool_calls", 0),
        "tool_errors": s.get("tool_errors", 0),
        "retries": s.get("retries", 0),
        "self_checks": s.get("self_checks", 0),
        "self_checks_answered": s.get("self_checks_answered", 0),
        "empty_responses": s.get("empty_responses", 0),
        "prompt_tokens": s.get("prompt_tokens", 0),
        "output_tokens": s.get("output_tokens", 0),
        "duration_s": trace.get("duration_s", 0),
    }


def run_benchmark(config: AgentConfig, run_name: str | None = None, task_ids: list[str] | None = None,
                  repeats: int = 1, verbose: bool = False, agent: Agent | None = None,
                  runs_dir: Path = RUNS_DIR) -> Path:
    tasks = load_tasks(ids=task_ids)
    run_name = run_name or f"{datetime.now():%Y%m%d-%H%M}_{config.condition_name}"
    run_dir = runs_dir / run_name
    (run_dir / "traces").mkdir(parents=True, exist_ok=True)

    cfg_path = run_dir / "run_config.json"
    if cfg_path.exists():
        prev = json.loads(cfg_path.read_text(encoding="utf-8"))["config"]
        if prev["condition"] != config.condition_name or prev["model"] != config.model:
            raise ValueError(f"{run_dir} was created with condition={prev['condition']} model={prev['model']}; "
                             "use a different --name for a different configuration.")
    cfg_path.write_text(json.dumps({
        "config": config.to_dict(), "tasks": [t.id for t in tasks], "repeats": repeats,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }, indent=2), encoding="utf-8")

    agent = agent or Agent(config, verbose=verbose)
    rows = []
    total = len(tasks) * repeats
    i = 0
    stopped = None
    for rep in range(repeats):
        for task in tasks:
            i += 1
            path = run_dir / "traces" / f"{task.id}__r{rep}.json"
            if path.exists() and load_trace(path)["status"] != "api_error":
                trace = load_trace(path)
                tag = "cached"
            else:
                try:
                    trace = agent.run(task.question, task_id=task.id).to_dict()
                except DailyQuotaExhausted as e:
                    stopped = str(e)
                    break
                path.write_text(json.dumps(trace, indent=2, default=str), encoding="utf-8")
                tag = "ran"
            row = result_row(task, trace, rep)
            rows.append(row)
            mark = "✓" if row["correct"] else "✗"
            print(f"[{i}/{total}] {mark} {task.id} r{rep} ({tag}) status={row['status']} "
                  f"answer={str(row['final_answer'])[:60]!r} expected={task.answer!r}")
        if stopped:
            break
    if stopped:
        print(f"\nSTOPPED EARLY after {len(rows)}/{total} task runs: {stopped}\n"
              "Completed traces are saved; rerun the same command to resume.")

    with (run_dir / "results.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, default=str) + "\n")
    n_ok = sum(r["correct"] for r in rows)
    n_api = sum(r["status"] == "api_error" for r in rows)
    print(f"\n{run_dir.name}: {n_ok}/{len(rows)} correct"
          + (f" ({n_api} api_error runs, rerun the same command to retry them)" if n_api else ""))
    return run_dir


def load_results(run_dir: Path) -> list[dict]:
    path = Path(run_dir) / "results.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
