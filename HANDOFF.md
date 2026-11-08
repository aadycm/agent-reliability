# HANDOFF - current project state

Generated 2026-11-07 22:50 by `scripts/handoff.py`. Do not edit by hand except
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

1. DONE day 1-2: dose ladder complete. off 23/23, mild 23/23, moderate 23/23, severe 8/21. Reflection under severe degradation: 8/20. All of them committed with traces.
2. DAY 2b (RUNNING): baseline repeats. `python -m agent_reliability benchmark --name gemma26_baseline_rep --model gemma-4-26b-a4b-it --rpm 6 --repeats 3`.
3. DAY 3: severe repeats. `python -m agent_reliability benchmark --name stress26_search1_rep --model gemma-4-26b-a4b-it --rpm 6 --degrade-search --repeats 3`. Then allowlist the new run directory in .gitignore - `runs/*` is ignored by default and a run left out of the allowlist commits silently as nothing.
4. DAY 4: rebuild the report over every run: `python -m agent_reliability report runs/gemma26_baseline runs/stress26_search_mild runs/stress26_search_moderate runs/stress26_search1 runs/stress26_steps5 runs/stress26_flaky30 --out reports/stress26`.
5. DAY 5 (NEEDS THE USER - do not attempt unattended): write the study-3 section of the README from the regenerated report, check each prediction in docs/preregistration.md against what happened, and add the new figures to scripts/verify_claims.py.

## Benchmark runs on disk

| run | traces | correct | api_error | state |
|---|---|---|---|---|
| `gemma26_baseline` | 23 | 23 | 0 | complete |
| `gemma26_baseline_rep` | 69 | 69 | 0 | complete |
| `gemma_baseline` | 23 | 23 | 0 | complete |
| `gemma_reflection` | 23 | 23 | 0 | complete |
| `gemma_reflection+selfcheck` | 23 | 23 | 0 | complete |
| `gemma_selfcheck` | 23 | 23 | 0 | complete |
| `stress26_flaky30` | 23 | 21 | 0 | complete |
| `stress26_search1` | 23 | 8 | 2 | complete |
| `stress26_search1_reflection` | 23 | 8 | 3 | complete |
| `stress26_search1_rep` | 6 | 0 | 3 | **IN PROGRESS (6/23)** |
| `stress26_search_mild` | 23 | 23 | 0 | complete |
| `stress26_search_moderate` | 23 | 23 | 0 | complete |
| `stress26_steps5` | 23 | 17 | 0 | complete |

An `api_error` run is an infrastructure failure (rate limit, HTTP 504). It is excluded from
success rates and retried automatically when the same benchmark command is rerun.

## Repo state

- Branch: `## main...origin/main`
- Last commits:
```
4b3da39 Add the baseline repeats (69/69 across three repeats)
5310a52 Stop redirected runs dying on the progress tick mark
810f699 Mark the dose ladder done in the handoff plan
eea4069 Add the mild and moderate dose-level run data
64c97b4 Run reflection-under-stress and the moderate dose level
```
- Uncommitted:
- `ANDOFF.md`
- `README.md`
- `scripts/verify_claims.py`
- `runs/stress26_search1_rep/`
- Tests: `(unknown)`

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
