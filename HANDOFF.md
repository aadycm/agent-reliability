# HANDOFF - current project state

Generated 2026-10-01 17:29 by `scripts/handoff.py`. Do not edit by hand except
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

1. One assistant works at a time. Claim the baton in this file (see Baton below) before editing.
2. Never invent numbers. Every figure in README/report must come from a real run in runs/.
3. No AI attribution lines (Co-Authored-By etc.) in commit messages - the user's repo is public.
4. Never commit .env or any API key. .gitignore blocks them; check `git status` before committing.
5. Long benchmark runs are resumable: completed traces are cached, so rerun the same command.
6. Do not push to GitHub. The user pushes from their own terminal.

## Next steps

1. Finish `stress26_search1_reflection`: 3 tasks left. `python -m agent_reliability benchmark --name stress26_search1_reflection --model gemma-4-26b-a4b-it --rpm 8 --degrade-search --reflection` (resumes; skips cached).
2. Rebuild the report with that condition included: `python -m agent_reliability report runs/gemma26_baseline runs/stress26_steps5 runs/stress26_flaky30 runs/stress26_search1 runs/stress26_search1_reflection --out reports/stress26`.
3. Add a 'reflection under stress' paragraph to the README study-2 section, using only numbers from the regenerated report.
4. DECIDED, do not redo: self-check under degraded search was skipped on purpose - self-check only fires when the agent submits an answer, and 13 of 21 degraded-search runs never do. Run it under flaky tools instead if a self-check-under-stress number is wanted.

## Benchmark runs on disk

| run | traces | correct | api_error | state |
|---|---|---|---|---|
| `gemma26_baseline` | 23 | 23 | 0 | complete |
| `gemma_baseline` | 23 | 23 | 0 | complete |
| `gemma_reflection` | 23 | 23 | 0 | complete |
| `gemma_reflection+selfcheck` | 23 | 23 | 0 | complete |
| `gemma_selfcheck` | 23 | 23 | 0 | complete |
| `stress26_flaky30` | 23 | 21 | 0 | complete |
| `stress26_search1` | 23 | 8 | 2 | complete |
| `stress26_search1_reflection` | 20 | 0 | 5 | **IN PROGRESS (20/23)** |
| `stress26_steps5` | 23 | 17 | 0 | complete |

An `api_error` run is an infrastructure failure (rate limit, HTTP 504). It is excluded from
success rates and retried automatically when the same benchmark command is rerun.

## Repo state

- Branch: `## main...origin/main`
- Last commits:
```
f124bce reflections done few failures yet to be updated
8c2d71c Harden .gitignore before making the repo public
4647c1e Fail fast on repeated request timeouts
4e1a292 no room for reflection and self check
cad3f0b Stress study: degrade the environment to find real failures
```
- Uncommitted:
- `HANDOFF.md`
- `docs/handoff-prompt.md`
- `scripts/`
- Tests: `71 passed in 12.88s`

## Environment

- Windows. Use the venv directly: `.\.venv\Scripts\python.exe -m agent_reliability ...`
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
