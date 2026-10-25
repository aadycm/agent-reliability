"""Print every factual claim used in write-ups, next to the data it comes from.

Run:  python scripts/verify_claims.py

Each line shows the claim, the computed value, and PASS/FAIL. Nothing here is typed in by
hand: every number is recomputed from runs/ at the moment you run it. If a claim fails,
the claim is wrong, not the data.
"""

from __future__ import annotations

import collections
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"


def traces(run: str):
    for p in sorted((RUNS / run / "traces").glob("*.json")):
        yield json.loads(p.read_text(encoding="utf-8"))


def results(run: str):
    path = RUNS / run / "results.jsonl"
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def calls(trace):
    return [c for s in trace["steps"] for c in s["tool_calls"]]


checks: list[tuple[str, object, object]] = []  # claim, expected, actual


def check(claim, expected, actual):
    checks.append((claim, expected, actual))


# --- claim 1: the search loop -------------------------------------------------
for tid in ["T15_fib_mod_elevation", "T17_lantern_budget_per_engineer"]:
    t = next(x for x in traces("stress26_search1") if x["task_id"] == tid)
    searches = [c for c in calls(t) if c["name"] == "search"]
    ok = [c for c in searches if not c.get("error") and isinstance(c.get("output"), list) and c["output"]]
    identical = collections.Counter(json.dumps(c["output"][0], sort_keys=True) for c in ok).most_common(1)[0][1]
    check(f"{tid}: 9 searches", 9, len(searches))
    check(f"{tid}: 9 distinct queries", 9, len({c["args"].get("query") for c in searches}))
    check(f"{tid}: 7 identical results", 7, identical)
    check(f"{tid}: ended at step limit, no answer submitted", ("step_limit", None), (t["status"], t["final_answer"]))

# --- claim 2: it never reported being stuck, though it noticed ----------------
STUCK = re.compile(r"(cannot find|can'?t find|unable to find|couldn'?t find|give up|no results|dead end|"
                   r"insufficient information|i do not have|i don'?t have)", re.I)
NOTICED = re.compile(r"(does ?n[o']?t (?:contain|include|have|mention|specify|give|provide)|no mention|"
                     r"didn'?t (?:return|give|include)|only says|truncat|missing)", re.I)
failed = [t for t in traces("stress26_search1") if t["status"] == "step_limit"]
said_stuck = sum(bool(STUCK.search(" ".join(s.get("reasoning") or "" for s in t["steps"]))) for t in failed)
noticed = sum(bool(NOTICED.search(" ".join(s.get("reasoning") or "" for s in t["steps"]))) for t in failed)
check("13 step-limit runs under degraded search", 13, len(failed))
check("none of them said it was stuck", 0, said_stuck)
check("11 of them noticed the information was missing", 11, noticed)


# --- claim 2b: it registered the problem ONCE, early - not every time ---------
for tid, expect_step in [("T15_fib_mod_elevation", 1), ("T17_lantern_budget_per_engineer", 3)]:
    t = next(x for x in traces("stress26_search1") if x["task_id"] == tid)
    noting = [s["index"] for s in t["steps"] if NOTICED.search(s.get("reasoning") or "")]
    check(f"{tid}: reasoning noted missing info exactly once", 1, len(noting))
    check(f"{tid}: and it noted it early (step {expect_step})", [expect_step], noting)
    check(f"{tid}: no 'stuck' language anywhere in its reasoning", 0,
          len(STUCK.findall(" ".join(s.get("reasoning") or "" for s in t["steps"]))))

# --- claim 2c: 11 of 13, not all 13 -------------------------------------------
check("2 of the 13 never registered the problem at all", 2, len(failed) - noticed)

# --- claim 3: flaky tools ------------------------------------------------------
inj = sum(1 for t in traces("stress26_flaky30") for c in calls(t)
          if c.get("error") and "temporary tool failure" in c["error"])
r = results("stress26_flaky30")
check("42 injected tool failures", 42, inj)
check("21 of 23 correct under flaky tools", (21, 23), (sum(x["correct"] for x in r), len(r)))

# --- claim 4: degraded search --------------------------------------------------
r = results("stress26_search1")
api = sum(1 for x in r if x["status"] == "api_error")
check("8 of 21 correct under degraded search", (8, 21), (sum(x["correct"] for x in r), len(r) - api))
check("2 runs excluded as api_error", 2, api)

# --- claim 5: the silent self-check (superseded v1 runs) -----------------------
sup = RUNS / "_superseded"
empty = answered = runs = 0
for d in ["gemma_selfcheck_v1_empty_selfcheck", "gemma_reflection+selfcheck_v1_empty_selfcheck"]:
    for p in (sup / d / "traces").glob("*.json"):
        t = json.loads(p.read_text(encoding="utf-8"))
        runs += 1
        steps = t["steps"]
        for i, s in enumerate(steps):
            after_answer = i > 0 and steps[i - 1].get("proposed_answer") is not None
            if s["kind"] == "nudge" and after_answer:
                empty += 1
            elif s["kind"] == "self_check":
                answered += 1
check("v1 self-check: 46 runs", 46, runs)
check("v1 self-check: 45 empty replies to the verification prompt", 45, empty)
check("v1 self-check: 1 answered", 1, answered)

# --- claim 6: reflection's sandbox errors --------------------------------------
for run, n_err in [("gemma_reflection", 6), ("gemma_reflection+selfcheck", 5)]:
    errs = [(t["task_id"], c) for t in traces(run) for c in calls(t)
            if c.get("error") and "not allowed" in c["error"]]
    check(f"{run}: {n_err} sandbox-block errors", n_err, len(errs))
    check(f"{run}: on 5 distinct tasks", 5, len({tid for tid, _ in errs}))
    check(f"{run}: still 23/23 correct", 23, sum(x["correct"] for x in results(run)))

# --- report --------------------------------------------------------------------
width = max(len(c) for c, _, _ in checks) + 2
fails = 0
for claim, expected, actual in checks:
    ok = expected == actual
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {claim:<{width}} expected={expected!r:<22} actual={actual!r}")
print(f"\n{len(checks) - fails}/{len(checks)} claims verified against the run files.")
if fails:
    raise SystemExit(1)
