# Pre-registration — study 3 (dose-response and repeats)

Written **2026-11-07, before any of these runs were executed.** Committed before the first run so
the predictions cannot be edited after the fact. Study 1 and 2 were not pre-registered; this is the
first part of the project that is.

Why: in study 2 I refined two failure heuristics *after* reading the traces they were applied to.
That was disclosed, but it means those labels were not an independent test. This document fixes the
hypotheses, the conditions and the analysis before the data exists.

## Background (already measured, studies 1–2)

| condition | result |
|---|---|
| baseline, `gemma-4-26b-a4b-it` | 23/23 |
| injected tool failures (30%) | 21/23, 42 failures absorbed |
| tight step budget (5) | 17/23 |
| degraded search, severe | 8/21 (2 api_error excluded) |

Severe degradation = top 1 search result, first sentence only.

## Hypotheses

**H1 (dose-response).** Success falls monotonically as search degradation increases:
`off ≥ mild ≥ moderate ≥ severe`. Stated as a prediction of order, not of size.

**H2 (where the drop happens).** Most of the loss occurs between *moderate* (one full snippet) and
*severe* (one first sentence). Reasoning: the knowledge base stores the needed number in a later
sentence of the snippet, so the first-sentence cut is what removes the answer; dropping from three
results to one mainly costs extra queries.

**H3 (failure mode).** Failures under degradation are mostly `infinite_loop` (reworded queries that
return the same document), not `gave_up_early`. Prediction: `gave_up_early` stays at 0 across all
levels, as in study 2 (0 of 13).

**H4 (repeats).** Re-running the same condition at temperature 0 does **not** reproduce identical
results. Prediction: at least one task flips outcome between repeats in at least one condition.
If nothing flips, the single-run results from studies 1–2 are more trustworthy than I assumed.

## Conditions to run

Model `gemma-4-26b-a4b-it`, temperature 0, 23 tasks, `max_steps` 12, rpm 8. Fixed task set; no task
is added, reworded or removed for this study.

1. `search-mild` — top 2 results, full snippets (1 repeat)
2. `search-moderate` — top 1 result, full snippet (1 repeat)
3. `gemma26_baseline` repeats r1, r2 (the `off` point of the curve)
4. `stress26_search1` (severe) repeats r1, r2

## Analysis plan

- Success rate per level with Wilson 95% intervals; the curve is plotted off those four points.
- Repeats: report mean and range across repeats, and the count of tasks whose outcome changed.
- Failure categories from the existing heuristics **unchanged**. If a new failure mode appears that
  the taxonomy cannot express, it will be reported as "unclassified" rather than by adding a
  category mid-study.
- `api_error` runs stay excluded from the headline rate and are reported alongside the worst-case
  figure that counts them as failures.
- No task-level exclusions. Nothing is dropped for being "unrepresentative".

## What would falsify each hypothesis

- H1: any level scoring materially above the level below it.
- H2: a drop between `off` and `mild` as large as the one between `moderate` and `severe`.
- H3: any `gave_up_early` labels, or failures dominated by another category.
- H4: identical per-task outcomes across all repeats of both conditions.

## Known limits that these runs do **not** fix

One model, one prompt wording, 23 author-written tasks, and three repeats is still a small sample.
The interventions (reflection, self-check) remain not compute-matched. This study makes the
degradation finding more defensible; it does not make the project conclusive.
