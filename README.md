# agent-reliability

A tool-using LLM agent (Google Gemini with native function calling) plus a small framework for
studying **where it fails on multi-step tasks**: a benchmark with known answers, automatic and
manual failure categorization, two ablatable interventions (reflection and self-check), and a
report with plots.

No training, no GPU. It runs on a laptop (built for a MacBook M2; the first study ran on Windows) and
only needs a Gemini API key.

> **Every number in this README comes from a committed run.** The run directories, the generated
> reports ([reports/gemma/summary.md](reports/gemma/summary.md),
> [reports/stress26/summary.md](reports/stress26/summary.md)) and the per-task JSON traces are in the
> repository. `python scripts/verify_claims.py` recomputes 52 of these figures from those files and
> exits non-zero if any of them has drifted, so a stale claim fails loudly instead of sitting here.
> The test suite runs offline and never produces benchmark numbers.

## Contents

| section | what's in it |
|---|---|
| [Quick start](#quick-start) | install, key setup, first run, free-tier model notes |
| [Project layout](#project-layout) | what each module and data directory holds |
| [Part 1: the agent](#part-1-the-agent) | the loop, robustness, tools, trace format |
| [Part 2: the study](#part-2-the-study) | tasks, failure taxonomy, interventions, stress conditions, reports |
| [Study 1: baseline ablation](#study-1-baseline-ablation-gemma-4-31b) | 2x2 ablation on the full task set |
| [Study 2: stress conditions](#study-2-stress-conditions-gemma-4-26b) | flaky tools, tight step budget, degraded search |
| [Study 3: dose-response](#study-3-dose-response-pre-registered) | how much degradation it takes to break the agent |
| [Limitations](#limitations) | read before quoting any result |

---

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then put your key in .env:  GEMINI_API_KEY=...
pytest -q                   # offline tests (no API calls)
python -m agent_reliability run-task T06          # watch one task step by step
```

**Windows (PowerShell):** call the venv's Python directly, so there's no need to activate it
(activation scripts can be blocked by PowerShell's execution policy):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env      # then edit .env and paste your key
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m agent_reliability run-task T06
```

Put your key in **`.env`**, never in `.env.example`: the template is meant to be committed, and only
`.env` is read by the code and gitignored. Optional variables: `GEMINI_MODEL` (default `gemini-3.6-flash`) and
`GEMINI_RPM` (client-side requests per minute, default 10).

**Model and free-tier notes (observed September 2026 on a free-tier key; check your own limits at
[ai.dev/rate-limit](https://ai.dev/rate-limit)):**
- `gemini-2.5-flash` and `gemini-2.5-flash-lite` return 404 ("no longer available to new users").
- `gemini-3.6-flash` works with function calling, but the free tier allowed only **20 requests per day**,
  far too few for a benchmark (one condition ≈ 80-150 requests). A Gemini Pro *consumer* subscription
  does not raise API limits; API limits depend on the Cloud project's billing tier.
- **`gemma-4-31b-it`** worked with function calling and had no rate-limit problems on the free tier, so
  the first study used it: `--model gemma-4-31b-it`. It did return frequent transient HTTP 500s,
  which the retry logic absorbed.
- A per-day quota error stops the run immediately (Google's message still says "retry in 30s", which is
  misleading for a daily limit). Rerun the same command after the reset to resume.

---

## Project layout

```
agent_reliability/
  config.py            AgentConfig: model, step limit, intervention toggles, retry & rate-limit settings
  llm.py               LLM backend interface; GeminiBackend (retries/backoff/rate limit); ScriptedBackend (tests)
  agent.py             the agent loop, with the reflection and self-check hooks
  prompts.py           every prompt in one place
  trace.py             structured trace → one JSON file per task run
  tools/               base.py (Tool, registry, @tool), calculator, python_exec, file_reader, search
  benchmark/           tasks.py (load + grade), runner.py (run a condition over all tasks; resumable)
  evaluation/          failure_analysis.py (heuristic taxonomy), labels.py (manual labels, merge, interactive CLI)
  reporting/           report.py (results.csv, summary.md, matplotlib plots)
  cli.py               command-line entry point (python -m agent_reliability ...)
data/
  tasks.yaml           the benchmark: questions, known answers, grading rules, difficulty
  knowledge_base.json  corpus for the mock search tool (fictional)
  files/               documents readable by read_file
tests/                 offline tests, including re-deriving every benchmark answer with the real tools
docs/
  preregistration.md   study 3's hypotheses and falsification criteria, committed before the runs
  handoff-prompt.md    briefing for handing the project to another assistant
scripts/
  verify_claims.py     recomputes every figure quoted in this README from runs/; non-zero exit on drift
  handoff.py           regenerates HANDOFF.md from git, the run directories, and the test results
runs/                  traces and results, one directory per run and condition
reports/               generated reports (results.csv, summary.md, plots)
```

`runs/` is gitignored by default, with the directories behind published results allowlisted
individually in `.gitignore`. If you add a run whose numbers you intend to quote, allowlist it in the
same place. A run left out of the allowlist stages as nothing and commits silently.

---

## Part 1: the agent

### The loop

```
task ─► [reflection? plan → critique → revised plan, no tools]
          │
          ▼
   ┌─► Gemini generate(history, tool declarations)
   │      ├─ empty / MALFORMED_FUNCTION_CALL  → nudge "continue" (max 2) ─────────┐
   │      ├─ function_call(s) to tools        → run each tool, append              │
   │      │                                     function_response(s) ──────────────┤
   │      ├─ function_call final_answer(x)                                         │
   │      │     ├─ [self-check? once] hold x, ask model to verify vs tool outputs ─┤
   │      │     └─ otherwise → DONE (answered)                                     │
   │      └─ plain text, no call → DONE (answered, finish_mode=text_response)      │
   └───────────────────────────────────────────────────────────────────────────────┘
   until max_steps → DONE (step_limit)      unrecoverable API error → DONE (api_error)
```

How one iteration works, concretely (`agent.py`):

1. **Tools are declared to Gemini.** Each tool has a name, a description, and a JSON schema for its
   arguments. The registry passes these to `GenerativeModel(tools=[{"function_declarations": [...]}])`.
   There is also a special `final_answer(answer)` declaration.
2. **The model responds.** A Gemini response is a list of *parts*. Text parts are the model's stated
   reasoning (the system prompt asks for one sentence before each tool call), and they are logged as
   `reasoning`. `function_call` parts are tool requests with a name and args.
3. **We run the tools ourselves.** Automatic function calling is off, so every call goes through
   `ToolRegistry.execute`, which never raises: bad args, unknown tools, and exceptions become
   `{"error": "..."}`. The model sees that error and can recover, and the trace keeps the evidence.
   (Gemini sends all numbers as floats, so integer args are coerced back using the schema.)
4. **Results go back.** For every `function_call` we append a matching `function_response` part in
   the next turn, then loop. The model's own response object is appended to history unchanged.
5. **Termination.** The model calls `final_answer`, which gives a clean string to grade. If it replies
   with plain text instead, the text is accepted but flagged `finish_mode=text_response`. Running out
   of `max_steps` gives `step_limit`.

### Robustness

- **Rate limiting**: a client-side limiter spaces requests to `GEMINI_RPM`.
- **Retries**: 429 / 5xx / timeouts are retried with exponential backoff and jitter
  (`base_delay·2^n`, capped, 0.5-1.5x). If a 429 names a `retry_delay`, that delay is honored.
  Non-retryable errors (e.g. an invalid request) fail immediately.
- **Graceful end states**: an exhausted retry budget ends the run as `api_error`. That result is saved,
  excluded from success rates, and re-attempted when you resume a run.
- **Empty/malformed responses** get up to 2 "please continue" nudges, then `no_answer`.

### Tools

| tool | what it does | safety |
|---|---|---|
| `calculator` | arithmetic and math functions via an AST walker | no `eval`; whitelist of node types |
| `python_exec` | runs a snippet, returns stdout | static import/call blocklist, `python -I` subprocess, temp cwd, empty env, 10 s timeout, CPU/memory rlimits on POSIX, output truncation. **Not a security sandbox.** |
| `list_files`, `read_file` | read files in `data/files/`, optional line range | path traversal rejected |
| `search` | keyword search over `data/knowledge_base.json` | read-only, deterministic |

**Adding a tool** takes one decorated function in `agent_reliability/tools/` plus an import in `tools/__init__.py`:

```python
from .base import tool, ToolError

@tool(name="unit_convert", description="Convert km to miles.",
      parameters={"type": "object",
                  "properties": {"km": {"type": "number", "description": "kilometres"}},
                  "required": ["km"]})
def unit_convert(km: float) -> float:
    if km < 0:
        raise ToolError("km must be non-negative")   # becomes {"error": ...} for the model
    return km * 0.621371
```

### Traces

Each run writes one JSON file with: task, condition, full config, status, final answer, the reflection
plan, and per step its kind (`reflection` / `model` / `self_check` / `nudge`), reasoning text, every
tool call (args, output, error, duration), the proposed answer, token usage, retries, and latency.
There are also aggregate stats (model calls, tool calls, tool errors, tokens, retries).
`python -m agent_reliability show-trace <file>` pretty-prints one.

---

## Part 2: the study

### Tasks (`data/tasks.yaml`)

23 tasks built on a **fictional** world: invented companies, towns, people, a currency, and a hockey
trophy, stored in the search corpus, plus CSV, memo, recipe, and log files. The data is fictional on
purpose. The model can't know these facts from pretraining, so a correct answer requires real tool
use, and an answer given without searching is detectably made up.

| difficulty | canonical tool calls | tasks |
|---|---|---|
| easy | 2 | T01-T05, T08-T10, T15, T22 (10) |
| medium | 3-4 | T06, T11-T14, T16, T19, T23 (8) |
| hard | 5+ | T07, T17, T18, T20, T21 (5) |

Some tasks carry deliberate **traps**: two similarly named companies (T22); a log line that mentions
"ERROR" at INFO level (T10); a recipe that serves 3, not 4, plus a "before 2015" boundary (T14);
highest unit price vs. highest total revenue (T08). Tasks also mix sources: file → search → search
(T11), file + search + file + compute (T17).

Each task declares: `answer`, `grading` (`numeric` with tolerance / `contains_all` / `exact`),
`steps`, `required_tools` (`a|b` = either), and `intermediates` (values a correct solution must
retrieve). **Every known answer is re-derived with the real tools by `tests/test_task_answers.py`**,
which also checks that each intermediate really appears in the tool outputs. If you edit a task,
update its reference solution there too.

Grading rules: numeric answers pass when a number in the answer is within tolerance. Answers with
more than two numbers count as hedging and fail. `contains_all` matches whole words/phrases,
case-insensitively, so "19" does not match "9".

### Failure taxonomy

Every failed run gets one primary label. The heuristics (`evaluation/failure_analysis.py`) are applied
in this order, and each label stores the evidence that triggered it:

| category | meaning | heuristic signal |
|---|---|---|
| `infinite_loop` | stuck repeating itself | `step_limit` and an identical call repeated ≥3× (or the last 6 calls all failing the same tool) |
| `bad_plan` | wrong approach | `step_limit` without repetition; **or** right tools but a required intermediate never retrieved; **or** all information retrieved but combined with wrong logic |
| `gave_up_early` | quit without a real answer | `no_answer`, empty answer, or a refusal ("cannot determine", "unknown", …) |
| `hallucinated_tool_result` | used information no tool gave | a required *information* tool (search/read_file) never called and only compute tools (or none) used; **or** a number fed into calculator/python that never appeared in the task or any earlier tool output (≥100, rounding tolerated) |
| `wrong_tool_choice` | used the wrong tool for the job | a required tool never called while other tools were used (e.g. searched for data that lives in a file; mental arithmetic instead of a compute tool) |
| `execution_error` | right plan, botched execution | missing information *due to tool errors*; near miss (≤2% off, i.e. rounding/precision); hedged or malformed answer; tool errors despite having all information |

`api_error` is tracked separately as an infrastructure outcome, never an agent failure.

**Manual labeling.** `python -m agent_reliability label runs/<run>` walks through each failed run.
It shows the condensed trace, the expected answer, the task's trap, and the heuristic suggestion with
its evidence. Press Enter to accept, a number to override, `s` to skip, `q` to quit. Labels are saved
after every entry to `runs/<run>/labels_manual.csv` (you can also edit that file directly). Manual labels
override heuristic ones, and the report shows **heuristic-manual agreement** and the most common
disagreements. Treat that agreement number as your measure of how far to trust the automatic labels.

### Interventions

Both are toggles on `AgentConfig` (`--reflection`, `--self-check`):

- **(b) Reflection, before executing.** One extra model call with tools disabled. The model writes a
  plan, critiques it (missing steps, wrong tools, assumed facts, units/format), and writes a revised
  plan. The plan stays in the conversation, and the model is told to execute it.
- **(a) Self-check, before finalizing.** The first `final_answer` call is intercepted, not accepted.
  The *result* of that tool call is "NOT ACCEPTED YET" plus instructions: check that every fact came
  from a tool result, re-check the arithmetic, confirm the units/format, then resubmit or fix the
  answer (using tools if needed). One check per run (`max_self_checks`). The step limit is extended by
  the number of self-checks used, so the ablation measures verification, not a smaller step budget.

  **Check that the intervention was actually delivered.** The first version sent the verification
  request as a separate text part next to the tool results. Gemma 4 answered that with *empty
  responses* (0 output tokens) in 45 of 46 runs. The loop nudged it, it re-submitted, and those
  conditions never really verified anything. The report's cost table now shows **self-checks
  answered / sent** and **empty responses** per condition, so this can't go unnoticed again. The
  invalid runs are kept in `runs/_superseded/`.

### Stress conditions

Study 2 and study 3 degrade the agent's environment rather than the tasks, so the task set stays
fixed across every condition. `stress.py` wraps the tool registry; the tool declarations the model
sees are untouched, so the agent is never told that anything is wrong. That is the point: the
question is whether it notices.

| flag | effect |
|---|---|
| `--tool-failure-rate P` | each tool call returns a transient error with probability `P`, before the real tool runs |
| `--max-steps N` | tightens the step budget (default 12) |
| `--degrade-search` | withholds part of every `search` result; how much depends on `--search-level` |
| `--search-level mild\|moderate\|severe` | the dose. Default `severe` |
| `--stress-seed N` | seed for injected tool failures (default 0) |

The search-degradation levels form a ladder, each withholding at least as much as the one below it:

| level | the agent receives |
|---|---|
| `off` | the top `k` results with full snippets |
| `mild` | the top 2 results, full snippets |
| `moderate` | the top result only, full snippet |
| `severe` | the top result only, truncated to its first sentence |

Injected tool failures are seeded per task, so the same command reproduces the same failure pattern.
`severe` is pinned by `test_severe_is_unchanged_from_the_original_setting`, because study 2 ran at
that level and would stop being comparable if the behaviour drifted.

### Running the study

```bash
# One condition (resumable: rerun the same command after a crash or rate-limit stop)
python -m agent_reliability benchmark --name baseline
python -m agent_reliability benchmark --name selfcheck --self-check

# Full 2×2 ablation (baseline, reflection, selfcheck, reflection+selfcheck) + report
python -m agent_reliability ablation --prefix study1
python -m agent_reliability ablation --prefix study1 --repeats 3     # better estimates, 3× the cost

# Inspect and label failures, then rebuild the report so it uses your labels
python -m agent_reliability analyze runs/study1_baseline
python -m agent_reliability label runs/study1_baseline
python -m agent_reliability report "runs/study1_*" --out reports/study1
```

**Budget.** One condition is 23 tasks × ~3-8 model calls. Reflection adds 1 call per task and
self-check about 1-2. A full ablation is roughly 400-700 requests. At `GEMINI_RPM=10`, that's about
40-70 minutes of wall-clock time. Check your quota before running with `--repeats`.

### Report contents (`reports/<name>/`)

- `summary.md`: overall success with Wilson 95% CIs; success by difficulty; failure categories per
  condition; heuristic-vs-manual agreement; **each intervention vs baseline, paired by task** (Δ in
  percentage points, tasks fixed/broken, exact McNemar p); cost (model calls, tool calls, tokens, time,
  retries) and intervention delivery (empty responses, self-checks answered); per-task table.
- `results.csv`: one row per task run (condition, task, difficulty, status, answer, expected,
  correct, failure category heuristic/manual/final, calls, tokens, duration, model).
- Plots: `success_by_condition.png`, `success_by_difficulty.png`, `failure_categories.png`,
  `per_task_outcomes.png`, `cost_by_condition.png`.

---

## Study 1: baseline ablation (Gemma 4 31B)

**Setup:** `gemma-4-31b-it` through the Gemini API free tier, temperature 0, `max_steps=12`, 23 tasks, one run per
task per condition (92 scored runs, 0 `api_error`). Run on 12-13 September 2026. Reproduce with
`ablation --prefix gemma --model gemma-4-31b-it`; the report goes to `reports/gemma/`.

| condition | correct | 95% CI | model calls / task | tokens / task | tokens vs baseline | tool errors |
|---|---|---|---|---|---|---|
| baseline | 23/23 | 85.7-100% | 4.2 | 6,331 | 1.0× | 0 |
| self-check | 23/23 | 85.7-100% | 5.3 | 9,017 | 1.4× | 0 |
| reflection | 23/23 | 85.7-100% | 6.0 | 14,090 | 2.2× | 6 (in 5 tasks) |
| reflection + self-check | 23/23 | 85.7-100% | 7.0 | 18,091 | 2.9× | 5 (in 5 tasks) |

What the traces show:

1. **Ceiling effect: no failures to study.** The agent solved every task in every condition, including the 5+ step
   tasks and the designed traps. The failure taxonomy had nothing to categorize, and the interventions had no room to
   raise accuracy. The honest conclusion is that **this benchmark is too easy for this model**. It says nothing
   about whether the interventions help on tasks where the agent does fail.
2. **Self-check cost tokens and changed nothing.** When the model actually received the verification prompt (45 of
   45 prompts answered in the two self-check conditions), it re-submitted the same answer every time and never
   called a tool to re-verify. It cost 1.4× baseline tokens.
3. **Reflection made tool use worse without changing accuracy.** In both reflection conditions, the same 5
   file-based tasks (T04, T08, T09, T10, T20) hit tool errors. Planning before seeing any tool output, the model
   wrote `python_exec` code that opened the CSV/log files directly (`import csv`, `open(...)`), which the sandbox
   blocks. Without reflection it used `read_file` first, as intended, and never hit this. It recovered every time
   because tool errors go back to the model, but reflection cost 2.2× baseline tokens. Plans written blind can pick
   the wrong mechanism.
4. **The first self-check implementation silently failed**, and it is the most useful reliability finding here.
   Sending the verification request as a text part next to the tool results produced empty model replies in 45 of
   46 runs. The runs still scored 23/23, because the loop nudged the model into re-submitting, so accuracy alone
   would never have revealed it. Only the traces did. Fixed by putting the request in the `final_answer` tool
   result; the invalid runs are kept in `runs/_superseded/` and excluded from the table.
5. **Minor format slips.** 2 of 92 runs (one baseline, one self-check) wrote the final answer as plain text instead
   of calling `final_answer`. Both were graded correct from their explicit `final_answer: ...` line.

Timing (`seconds` in the report) is dominated by rate limiting and retries of transient HTTP 500s (up to 91 retries
per condition), so it is **not** a meaningful efficiency comparison. Use model calls and tokens.

**What followed from this:** study 2 kept the task set and degraded the environment instead, which
produced failures to study. Study 3 then measured how much degradation it takes.

---

## Study 2: stress conditions (Gemma 4 26B)

Study 1 hit a ceiling: `gemma-4-31b-it` solved every task, and so did the smaller `gemma-4-26b-a4b-it`
(23/23 baseline, though with 1.5x the tokens and 8 recovered tool errors). Rewriting the tasks after
seeing which ones were easy would have let me tune the difficulty toward whatever I expected to find.
Study 2 keeps the tasks fixed and degrades the **environment** instead (`stress.py`), which is
objective and reproducible.

**Setup:** `gemma-4-26b-a4b-it`, temperature 0, 23 tasks per condition, one run each. Reproduce with
`benchmark --model gemma-4-26b-a4b-it` plus the flag named below; report in `reports/stress26/`.

| condition | flag | success | 95% CI | vs baseline (McNemar p) | dominant failure |
|---|---|---|---|---|---|
| baseline | - | 23/23 (100%) | 85.7-100% | - | - |
| flaky tools | `--tool-failure-rate 0.3` | 21/23 (91.3%) | 73.2-97.6% | -8.7 pp (p=0.50) | execution_error (2) |
| tight budget | `--max-steps 5` | 17/23 (73.9%) | 53.5-87.5% | -26.1 pp (p=0.031) | execution_error (6) |
| degraded search | `--degrade-search` | 8/21 (38.1%) | 20.8-59.1% | -61.9 pp (p<0.001) | infinite_loop (13) |

Degraded search excludes 2 runs that ended in `api_error` (repeated HTTP 504s on very long
conversations), so it is scored over 21 runs.

**Finding 1: information quality breaks the agent far more than tool failures do.** Flaky tools cost
only 2 tasks, despite injecting 42 failures (1.8 per run) that the agent retried through. Error
recovery is a real strength. Truncating search results to one first-sentence hit cost 13 tasks, and
the gradient by difficulty was steep: 6/10 easy, 2/7 medium, **0/4 hard**. Every task that needed no
search still passed.

**Finding 2: the dominant failure is a reworded-query loop.** When the needed fact was in the
truncated-away sentence, the agent rephrased the same question 8-9 times ("Brightwater Rail",
"... average speed", "... km", "... miles"), received the identical snippet 5-7 times, then searched
unrelated files before running out of steps. It averaged 9.0 tool calls and 2.3x baseline tokens.
It never said "I could not find this": there were **zero** `gave_up_early` labels. Failing to
recognise a dead end cost more tasks than every other failure mode in this project combined.

**Finding 3: under a tight budget, wasted first moves decide the outcome.** With 5 steps the agent
lost tasks it solves comfortably at 12, including 2-step ones. Steps went to a redundant `list_files`
(the task names the file), reading a file twice, and `python_exec` code calling `open()`/`import csv`,
which the sandbox blocks. Two runs (T17, T20) computed the correct value on their final step and were
cut off before submitting it.

**Finding 4: two heuristics were wrong, and the traces proved it.** Both were fixed, with tests:
- *"Step limit reached" was labelled `bad_plan`.* All 8 budget-bound failures had already gathered
  every required fact; some had computed the answer. The rule now checks whether the needed
  information was actually missing before blaming the plan; otherwise it is an `execution_error`.
- *The loop detector only caught identical repeated calls.* The reworded-query loops slipped through.
  It now also flags re-fetching the same result 4+ times, which caught 13 of 15 degraded-search
  failures and fires on nothing else.

Both refinements were made **after** reading these traces, so heuristic-vs-manual agreement here would
not be an independent validation, and none is claimed. The labels were checked by hand against the
traces; an independent pass with `label` would still be worth doing.

**What this does not show:** one model, one run per task, and stress levels (0.3, 5 steps, 1 truncated
result) chosen by hand rather than swept. The interventions were not yet tested under stress, and the
degradation levels were not swept. Study 3 does both.

---

## Study 3: dose-response (pre-registered)

Studies 1 and 2 were analysed after the fact, and in study 2 I refined two failure heuristics *after*
reading the traces they were applied to. That was disclosed, but it means those labels were not an
independent test. Study 3 fixes the hypotheses, the conditions and the analysis plan in
[docs/preregistration.md](docs/preregistration.md), committed before the first run.

The question: study 2 showed that degrading search breaks the agent. How much degradation does that
take, and which part of the degradation does the damage?

**Setup:** `gemma-4-26b-a4b-it`, temperature 0, `max_steps=12`, 23 tasks, fixed task set. Reproduce
each level with `benchmark --model gemma-4-26b-a4b-it --degrade-search --search-level <level>`.

| level | the agent receives | success | 95% CI | dominant failure |
|---|---|---|---|---|
| `off` | top `k` results, full snippets | 23/23 (100%) | 85.7-100% | - |
| `mild` | top 2 results, full snippets | 23/23 (100%) | 85.7-100% | - |
| `moderate` | top result, full snippet | 23/23 (100%) | 85.7-100% | - |
| `severe` | top result, first sentence only | 8/21 (38.1%) | 20.8-59.1% | infinite_loop (13) |

Severe excludes 2 runs that ended in `api_error`. The three intact levels had none.

**Finding 1: the agent does not need many search results. It needs the sentence with the answer in
it.** Cutting three results down to one cost nothing at all: 23/23 at both `mild` and `moderate`.
Cutting that one result from a full snippet to its first sentence cost 13 of the 21 scored tasks. The
entire effect sits in the last step of the ladder, where the knowledge base's later sentences, the
ones holding the numbers, are removed.

**Finding 2: reflection does not rescue degraded search.** Running the `severe` level with
`--reflection` scored 8/20 (21.9-61.3%, 3 `api_error`) against 8/21 without it. All 12 scored
failures label `infinite_loop`. Critiquing the plan before executing does not help when the plan is
sound and the environment is withholding the fact. Both studies now agree that reflection costs
tokens without moving accuracy.

**Finding 3: temperature 0 pins the answer, not the path.** Three repeats of the baseline
(`gemma26_baseline_rep`) scored 69/69 with no task changing outcome. The runs were not identical,
though: `T20_south_revenue_ratio` finished through the `final_answer` tool in two repeats at 11 steps,
and in the third ran to 12 steps and finished as a plain-text response that emitted its whole
scratchpad, including a visible "Wait, I should check..." aside. It graded correct all three times,
because `extract_final` recovers the number from the prose. One task in 23 took a different control
path under identical settings.

**How the pre-registered hypotheses held up:**

| | prediction | outcome |
|---|---|---|
| H1 | success falls monotonically as degradation rises | Holds, but weakly. The curve is flat across three levels and then drops. "Monotonic" is true and uninformative here. |
| H2 | most of the loss sits between `moderate` and `severe` | Confirmed, more sharply than predicted: *all* of it does. |
| H3 | failures are `infinite_loop`, and `gave_up_early` stays at 0 | Confirmed. 13 and 12 `infinite_loop` labels in the two severe conditions, 0 `gave_up_early` anywhere. |
| H4 | repeats at temperature 0 will not reproduce exactly | Not settled. The baseline is at the ceiling, so no outcome can flip. The severe-level repeats are the real test and had not finished when this was written. |

**A harness bug worth recording.** The first baseline-repeats run died after one task with
`UnicodeEncodeError`: the per-task progress line prints a tick mark, and Python selects the legacy
ANSI codepage when stdout is a pipe rather than a console. The shell pipeline it ran under reported
exit code 0 anyway. Every unattended run is a redirected run, so the bug only ever fired when nobody
was watching, and the exit code hid it when it did. `main()` now forces UTF-8 on stdout and stderr
(`test_cli_output_encoding.py`). The procedural fix matters more: a run counts as finished when its
trace count says so, which is what `scripts/handoff.py` reports. This project studies agents that
fail to notice a degraded environment, and its own harness had that bug for three studies.

**What is still open:** the severe-level repeats (H4), and self-check under degradation. Levels
between `moderate` and `severe` would locate the cliff more precisely than four points can.

---

## Limitations

Read these before drawing conclusions from any report.

- **Small task set.** 23 tasks, only 5 of them "hard". A single task flipping moves the success rate by
  over 4 points. Confidence intervals are wide, and the McNemar test only detects large effects. Use
  `--repeats` and report intervals, not point estimates.
- **Synthetic, author-written tasks.** The tasks and fictional world were written by the same person
  who wrote the prompts and heuristics. They're clean, short, and English-only, and they may not
  represent real-world agent workloads. The traps were designed in advance, which biases the failure
  distribution toward the failures I anticipated.
- **Difficulty = canonical step count** is a rough proxy. An agent can batch calls (one calculator
  expression for three operations), and some 2-step tasks are harder than some 5-step ones.
- **Evaluation subjectivity.** Grading is rule-based (tolerances, substring matching) and can mis-grade
  oddly formatted answers. Failure categories are genuinely ambiguous: one run can plausibly be both a
  "bad plan" and an "execution error", and the heuristics force one primary label. The heuristics are
  simple signals, not ground truth. Manual labels are one person's judgment, with no inter-annotator
  agreement measured.
- **Single model, single provider.** Results describe one Gemini model at one temperature with one
  prompt set. They don't transfer to other models, or even to later versions of the same model.
  Prompt wording for the interventions is one choice among many, and a weak result may reflect the
  prompt, not the idea.
- **Non-determinism.** Even at temperature 0, API outputs vary between calls. Three repeats of the
  baseline produced the same outcome on all 23 tasks but not the same control flow: one task finished
  through a different exit path with a different step count. Most results here are a single run per
  task, which is a noisy sample.
- **Cost and rate limits.** Free-tier quotas limit repeats and task count. Throttling and retries make
  wall-clock time a poor efficiency metric. Runs interrupted by quota exhaustion end as `api_error`;
  they are excluded from success rates and retried on resume, but a partially complete run compares
  fewer tasks.
- **Self-check only intercepts the `final_answer` tool.** If the model finishes with a plain-text answer instead,
  the answer is accepted without verification. This happened in 1 of 23 self-check runs in the first study.
- **Interventions cost extra calls.** Any accuracy gain should be weighed against the cost table. There
  is no compute-matched control (e.g. baseline with best-of-2 sampling).
- **SDK status.** As requested, this uses the `google-generativeai` SDK, which Google has since
  **deprecated** in favour of `google-genai` (it prints a FutureWarning on import). `gemini-2.5-*`
  models now return 404 for new API users. Multi-turn function calling was verified working with
  `gemini-3.6-flash` through this SDK, but the legacy protos lack a "thought signature" field, so if a
  future model starts rejecting multi-turn tool calls, that's the likely cause. All Gemini-specific code
  is isolated in `llm.py` (`GeminiBackend`), so porting means replacing one class.
- **The Python sandbox is not a security boundary.** It guards against accidents, not a determined
  adversary. On macOS the memory rlimit is typically not enforced, while the timeout and CPU limits are.
