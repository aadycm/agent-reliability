"""Automatic failure categorization from traces.

Taxonomy (one primary label per failed run):

  wrong_tool_choice         a tool needed for the task was never used, but the agent tried other tools
                            (e.g. searched the knowledge base for something that's in a file, or did the
                            arithmetic in its head instead of with a tool)
  hallucinated_tool_result  the agent used facts or numbers that no tool returned: it answered without
                            the information tools, or fed invented numbers into its calculations
  infinite_loop             hit the step limit while repeating the same call(s)
  bad_plan                  used the right tools but never retrieved information the task needs, or
                            combined correct information with wrong logic, or ran out of steps without looping
  gave_up_early             stopped without a real answer ("I cannot determine...", empty, no answer)
  execution_error           plan was essentially right, but execution slipped: tool errors not recovered
                            from, a near-miss number (rounding/unit slip), or a malformed final answer

Non-agent outcome (reported separately, never counted as an agent failure):
  api_error                 infrastructure failure after all retries

These are heuristics, and they're imperfect. Every label carries the evidence that triggered it, and
manual labels (evaluation/labels.py) override them. The report shows how often the two agree.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field

from ..benchmark.tasks import Task, extract_numbers

CATEGORIES = [
    "wrong_tool_choice",
    "hallucinated_tool_result",
    "infinite_loop",
    "bad_plan",
    "gave_up_early",
    "execution_error",
]
NON_AGENT = ["api_error"]
INFO_TOOLS = {"search", "read_file"}
COMPUTE_TOOLS = {"calculator", "python_exec"}

_REFUSAL = re.compile(
    r"\b(cannot|can't|unable|not (?:enough|possible|available|found|determin\w*)|no information|"
    r"don't know|do not know|unknown|insufficient|n/?a)\b", re.I)


@dataclass
class FailureLabel:
    task_id: str
    repeat: int
    category: str
    evidence: list[str] = field(default_factory=list)
    signals: dict = field(default_factory=dict)
    source: str = "heuristic"

    def to_dict(self) -> dict:
        return asdict(self)


def _norm_num_text(s: str) -> str:
    return re.sub(r"(?<=\d),(?=\d)", "", s)


def _all_calls(trace: dict) -> list[dict]:
    return [c for s in trace["steps"] for c in s.get("tool_calls", [])]


def _canon(call: dict) -> str:
    return call["name"] + json.dumps(call.get("args", {}), sort_keys=True)


def _numbers_in(text: str) -> list[float]:
    """Numbers in text, also expanding '412 million' / '1.26 billion' to their full values."""
    t = _norm_num_text(text)
    out = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", t)]
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(thousand|million|billion)", t, re.I):
        out.append(float(num) * {"thousand": 1e3, "million": 1e6, "billion": 1e9}[unit.lower()])
    return out


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= 1.0 or abs(a - b) <= 1e-3 * max(abs(a), abs(b))


def fabricated_numbers(trace: dict) -> list[float]:
    """Numbers used in calculator/python args that never appeared in the task, in an earlier tool
    output, or in earlier tool args. Small numbers (<100) and powers of ten are ignored, since
    those are usually constants like 2, 12, or 100."""
    known = _numbers_in(trace["task"])
    suspicious = []
    for step in trace["steps"]:
        for c in step.get("tool_calls", []):
            arg_text = json.dumps(c.get("args", {}))
            if c["name"] in COMPUTE_TOOLS:
                for n in _numbers_in(arg_text):
                    if abs(n) < 100 or (n > 0 and float(n).is_integer() and re.fullmatch(r"10*", str(int(n)))):
                        continue
                    if not any(_close(n, k) for k in known):
                        suspicious.append(n)
            known.extend(_numbers_in(arg_text))
            known.extend(_numbers_in(str(c.get("output", ""))))
    return suspicious


def _required_groups(task: Task) -> list[set[str]]:
    return [set(g.split("|")) for g in task.required_tools]


def categorize(task: Task, trace: dict, result: dict) -> FailureLabel | None:
    """Return a label for a failed run, or None if the run was correct."""
    if result["correct"]:
        return None
    rep = result.get("repeat", 0)
    lab = FailureLabel(task_id=task.id, repeat=rep, category="")
    status = trace["status"]
    calls = _all_calls(trace)
    called = {c["name"] for c in calls}
    errors = [c for c in calls if c.get("error")]
    outputs = _norm_num_text(" ".join(str(c.get("output", "")) for c in calls if not c.get("error")).replace("\n", " "))
    answer = (trace.get("final_answer") or "").strip()

    repeats = Counter(_canon(c) for c in calls)
    max_repeat = max(repeats.values(), default=0)
    missing_groups = [g for g in _required_groups(task) if not (g & called)]
    missing_info = [g for g in missing_groups if g & INFO_TOOLS]
    missing_inter = [i for i in task.intermediates if _norm_num_text(i) not in outputs]
    fabricated = fabricated_numbers(trace)

    lab.signals = {
        "status": status, "tool_calls": len(calls), "tools_used": sorted(called),
        "tool_errors": len(errors), "max_identical_call_repeats": max_repeat,
        "missing_required_tools": ["|".join(sorted(g)) for g in missing_groups],
        "missing_intermediates": missing_inter, "fabricated_numbers": fabricated[:10],
        "finish_mode": trace.get("finish_mode"),
    }

    def done(cat: str, *ev: str) -> FailureLabel:
        lab.category = cat
        lab.evidence = list(ev)
        return lab

    if status == "api_error":
        return done("api_error", f"API failure: {(trace.get('error') or '')[:200]}")

    if status == "step_limit":
        if max_repeat >= 3:
            return done("infinite_loop", f"step limit reached; one identical call repeated {max_repeat}x")
        tail = [c["name"] for c in calls[-6:]]
        if len(tail) >= 6 and len(set(tail)) == 1 and all(c.get("error") for c in calls[-6:]):
            return done("infinite_loop", f"step limit reached; last 6 calls all failing {tail[0]} calls")
        return done("bad_plan", "step limit reached without exact repetition (flailing or over-long plan)")

    if status == "no_answer":
        return done("gave_up_early", "run ended with empty/malformed responses and no answer")

    if not answer or _REFUSAL.search(answer):
        return done("gave_up_early", f"final answer is a non-answer: {answer[:120]!r}")

    if missing_info:
        need = ", ".join("|".join(sorted(g)) for g in missing_info)
        if not calls or called <= COMPUTE_TOOLS:
            return done("hallucinated_tool_result",
                        f"never called required information tool(s) [{need}] yet produced an answer",
                        f"tools used: {sorted(called) or 'none'}")
        return done("wrong_tool_choice", f"required tool(s) [{need}] never called; used {sorted(called)} instead")

    if fabricated:
        return done("hallucinated_tool_result",
                    f"computation used numbers not returned by any tool or task text: {fabricated[:5]}")

    if missing_groups:
        need = ", ".join("|".join(sorted(g)) for g in missing_groups)
        return done("wrong_tool_choice", f"required tool(s) [{need}] never called (e.g. mental arithmetic instead of a tool)")

    if missing_inter:
        if errors:
            return done("execution_error", f"tool errors ({len(errors)}) while gathering info; "
                                           f"never obtained {missing_inter}")
        return done("bad_plan", f"right tools, but the needed information was never retrieved: {missing_inter}")

    # All required information was gathered, and the answer is still wrong.
    note = result.get("grading_note", "")
    if task.grading.get("type") == "numeric":
        nums = extract_numbers(answer)
        target = float(task.answer)
        if "ambiguous" in note:
            return done("execution_error", f"answer malformed/hedged ({note})")
        if nums and target and any(abs(n - target) / abs(target) <= 0.02 for n in nums):
            return done("execution_error", f"near miss: {nums} vs {target} (rounding/precision slip)")
    if errors:
        return done("execution_error", f"all information gathered but {len(errors)} tool error(s) during execution")
    return done("bad_plan", "all required information was retrieved but combined with wrong logic "
                            f"(answer {answer[:80]!r}, expected {task.answer!r})")


def analyze_run(tasks: dict[str, Task], traces: dict[tuple[str, int], dict], results: list[dict]) -> list[FailureLabel]:
    labels = []
    for r in results:
        trace = traces[(r["task_id"], r["repeat"])]
        lab = categorize(tasks[r["task_id"]], trace, r)
        if lab is not None:
            labels.append(lab)
    return labels
