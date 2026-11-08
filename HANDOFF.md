# HANDOFF - current project state

Generated 2026-11-07 19:38 by `scripts/handoff.py`. Do not edit by hand except
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

1. DAY 1a: finish `stress26_search1_reflection` (3 tasks left). `python -m agent_reliability benchmark --name stress26_search1_reflection --model gemma-4-26b-a4b-it --rpm 8 --degrade-search --reflection` (resumes; skips cached).
2. DAY 1b: dose level MODERATE. `python -m agent_reliability benchmark --name stress26_search_moderate --model gemma-4-26b-a4b-it --rpm 8 --degrade-search --search-level moderate`.
3. DAY 2a: dose level MILD. `python -m agent_reliability benchmark --name stress26_search_mild --model gemma-4-26b-a4b-it --rpm 8 --degrade-search --search-level mild`.
4. DAY 2b: baseline repeats. `python -m agent_reliability benchmark --name gemma26_baseline_rep --model gemma-4-26b-a4b-it --rpm 8 --repeats 3`.
5. DAY 3: severe repeats. `python -m agent_reliability benchmark --name stress26_search1_rep --model gemma-4-26b-a4b-it --rpm 8 --degrade-search --repeats 3`.
6. DAY 4: rebuild the report over every run: `python -m agent_reliability report runs/gemma26_baseline runs/stress26_search_mild runs/stress26_search_moderate runs/stress26_search1 runs/stress26_steps5 runs/stress26_flaky30 --out reports/stress26`.
7. DAY 5 (NEEDS THE USER - do not attempt unattended): write the study-3 section of the README from the regenerated report, check each prediction in docs/preregistration.md against what happened, and add the new figures to scripts/verify_claims.py.

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
| `stress26_search1_reflection` | 23 | 8 | 4 | complete |
| `stress26_search_moderate` | 23 | 23 | 0 | complete |
| `stress26_steps5` | 23 | 17 | 0 | complete |

An `api_error` run is an infrastructure failure (rate limit, HTTP 504). It is excluded from
success rates and retried automatically when the same benchmark command is rerun.

## Repo state

- Branch: `## main...origin/main [ahead 2]`
- Last commits:
```
085dc0a Pre-register study 3 and queue the 5-day plan
4e5ad5b Add search-degradation dose ladder and api_error sensitivity column
c5ae8bc Add claim verifier; refresh degraded-search failure labels
0f381f7 Add handoff tooling for switching between assistants
f124bce reflections done few failures yet to be updated
```
- Uncommitted:
- `ANDOFF.md`
- `runs/stress26_search1_reflection/run_config.json`
- `runs/stress26_search1_reflection/traces/T07_combined_hq_population__r0.json`
- `runs/stress26_search1_reflection/traces/T11_memo_leader_birthplace__r0.json`
- `runs/stress26_search1_reflection/traces/T13_orin_cup_estmark__r0.json`
- `runs/stress26_search1_reflection/traces/T16_rev_per_employee_gap__r0.json`
- `runs/stress26_search1_reflection/traces/T19_round_trips__r0.json`
- `runs/stress26_search1_reflection/failures.csv`
- `runs/stress26_search1_reflection/failures_auto.json`
- `runs/stress26_search1_reflection/results.jsonl`
- `runs/stress26_search1_reflection/traces/T21_birth_year_sum__r0.json`
- `runs/stress26_search1_reflection/traces/T22_veltrix_confusion__r0.json`
- `runs/stress26_search1_reflection/traces/T23_lantern_total_usd__r0.json`
- Tests: `78 passed in 12.98s`

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
