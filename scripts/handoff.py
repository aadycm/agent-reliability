"""Regenerate HANDOFF.md: a snapshot of project state for whoever works next.

Run it directly, or let the Claude Code Stop hook run it automatically:
    python scripts/handoff.py

Everything in the generated file is read from the repo at run time (git, run directories,
test results), so it cannot drift out of date the way hand-written notes do. The only
hand-maintained part is the "Next steps" list in NEXT_STEPS below - keep that honest.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# The only hand-maintained section. Edit as work progresses.
# ---------------------------------------------------------------------------
NEXT_STEPS = [
    "Finish `stress26_search1_reflection`: 3 tasks left. "
    "`python -m agent_reliability benchmark --name stress26_search1_reflection "
    "--model gemma-4-26b-a4b-it --rpm 8 --degrade-search --reflection` (resumes; skips cached).",
    "Rebuild the report with that condition included: `python -m agent_reliability report "
    "runs/gemma26_baseline runs/stress26_steps5 runs/stress26_flaky30 runs/stress26_search1 "
    "runs/stress26_search1_reflection --out reports/stress26`.",
    "Add a 'reflection under stress' paragraph to the README study-2 section, using only numbers "
    "from the regenerated report.",
    "DECIDED, do not redo: self-check under degraded search was skipped on purpose - self-check "
    "only fires when the agent submits an answer, and 13 of 21 degraded-search runs never do. "
    "Run it under flaky tools instead if a self-check-under-stress number is wanted.",
]

GROUND_RULES = [
    "One assistant works at a time. Claim the baton in this file (see Baton below) before editing.",
    "Never invent numbers. Every figure in README/report must come from a real run in runs/.",
    "No AI attribution lines (Co-Authored-By etc.) in commit messages - the user's repo is public.",
    "Never commit .env or any API key. .gitignore blocks them; check `git status` before committing.",
    "Long benchmark runs are resumable: completed traces are cached, so rerun the same command.",
    "Do not push to GitHub. The user pushes from their own terminal.",
]


def sh(*args: str, default: str = "") -> str:
    try:
        out = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=60)
        return out.stdout.strip() or default
    except Exception:
        return default


def run_progress() -> list[str]:
    rows = []
    runs = ROOT / "runs"
    if not runs.is_dir():
        return ["(no runs yet)"]
    for d in sorted(p for p in runs.iterdir() if p.is_dir() and (p / "traces").is_dir()):
        traces = list((d / "traces").glob("*.json"))
        if not traces:
            continue
        ok = err = 0
        for t in traces:
            try:
                data = json.loads(t.read_text(encoding="utf-8"))
            except Exception:
                continue
            if data.get("status") == "api_error":
                err += 1
        results = d / "results.jsonl"
        if results.exists():
            lines = [json.loads(x) for x in results.read_text(encoding="utf-8").splitlines() if x.strip()]
            ok = sum(1 for r in lines if r.get("correct"))
        state = "complete" if len(traces) >= 23 else f"**IN PROGRESS ({len(traces)}/23)**"
        rows.append(f"| `{d.name}` | {len(traces)} | {ok} | {err} | {state} |")
    return rows or ["(no runs yet)"]


def main() -> None:
    tests = sh(sys.executable, "-m", "pytest", "-q", "--no-header", "-x", "--tb=no", default="(not run)")
    test_line = next((l for l in reversed(tests.splitlines()) if "passed" in l or "failed" in l), "(unknown)")
    dirty = sh("git", "status", "--porcelain")
    dirty_list = "\n".join(f"- `{l[3:]}`" for l in dirty.splitlines()[:15]) or "- (clean)"
    ahead = sh("git", "status", "-sb").splitlines()[0] if sh("git", "status", "-sb") else ""

    doc = f"""# HANDOFF - current project state

Generated {datetime.now():%Y-%m-%d %H:%M} by `scripts/handoff.py`. Do not edit by hand except
the Baton section; everything else is regenerated.

## Baton

**Holder: (nobody - free)**

Before you start, change that line to your name (e.g. `Holder: ChatGPT, since 2026-10-01 14:00`).
When you stop, set it back to `(nobody - free)` and regenerate this file with
`python scripts/handoff.py`. Only the holder edits the repo.

## What this project is

A tool-using LLM agent (Gemini/Gemma function calling) plus a framework for studying where it
fails on multi-step tasks: 23 benchmark tasks with verified answers, JSON traces of every step,
automatic failure classification, and on/off ablations of two interventions (reflection,
self-check). Full design, results and limitations are in `README.md` - **read it first**.

## Ground rules

{chr(10).join(f'{i+1}. {r}' for i, r in enumerate(GROUND_RULES))}

## Next steps

{chr(10).join(f'{i+1}. {s}' for i, s in enumerate(NEXT_STEPS))}

## Benchmark runs on disk

| run | traces | correct | api_error | state |
|---|---|---|---|---|
{chr(10).join(run_progress())}

An `api_error` run is an infrastructure failure (rate limit, HTTP 504). It is excluded from
success rates and retried automatically when the same benchmark command is rerun.

## Repo state

- Branch: `{ahead}`
- Last commits:
```
{sh("git", "log", "--oneline", "-5", default="(no commits)")}
```
- Uncommitted:
{dirty_list}
- Tests: `{test_line}`

## Environment

- Windows. Use the venv directly: `.\\.venv\\Scripts\\python.exe -m agent_reliability ...`
- `GEMINI_API_KEY` is in `.env` (gitignored, never print it).
- Free tier: `gemini-2.5-*` is unavailable to new keys, `gemini-3.6-flash` allows only 20
  requests/day. Studies use `gemma-4-31b-it` and `gemma-4-26b-a4b-it`, which have workable limits.
- Expect transient HTTP 500/504s and per-minute token quotas; the retry logic handles them.

## Useful commands

```bash
python -m agent_reliability list-tasks            # the benchmark
python -m agent_reliability run-task T06 -v       # one task, live
python -m agent_reliability benchmark --name X    # a condition (resumable)
python -m agent_reliability analyze runs/X        # classify failures
python -m agent_reliability report runs/... --out reports/Y
python scripts/handoff.py                         # regenerate this file
```
"""
    (ROOT / "HANDOFF.md").write_text(doc, encoding="utf-8")
    print(f"HANDOFF.md updated ({datetime.now():%H:%M})")


if __name__ == "__main__":
    main()
