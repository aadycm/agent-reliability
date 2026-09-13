"""Loading benchmark tasks and grading answers against the known correct answers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .. import DATA_DIR

TASKS_PATH = DATA_DIR / "tasks.yaml"


@dataclass
class Task:
    id: str
    question: str
    answer: object
    grading: dict
    steps: int
    required_tools: list[str] = field(default_factory=list)
    intermediates: list[str] = field(default_factory=list)
    trap: str | None = None

    @property
    def difficulty(self) -> str:
        if self.steps <= 2:
            return "easy (2 steps)"
        if self.steps <= 4:
            return "medium (3-4 steps)"
        return "hard (5+ steps)"


DIFFICULTY_ORDER = ["easy (2 steps)", "medium (3-4 steps)", "hard (5+ steps)"]


def load_tasks(path: Path = TASKS_PATH, ids: list[str] | None = None) -> list[Task]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))["tasks"]
    tasks = [Task(**t) for t in raw]
    seen = set()
    for t in tasks:
        if t.id in seen:
            raise ValueError(f"duplicate task id {t.id}")
        seen.add(t.id)
    if ids:
        wanted = set(ids)
        tasks = [t for t in tasks if t.id in wanted or any(t.id.startswith(i) for i in wanted)]
    return tasks


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------

_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def extract_numbers(text: str) -> list[float]:
    cleaned = re.sub(r"(?<=\d),(?=\d{3}\b)", "", str(text))  # 1,234,567 -> 1234567
    return [float(n) for n in _NUM.findall(cleaned)]


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s\-.]", " ", str(text).lower())).strip()


_FINAL_MARKER = re.compile(r"final[_ ]answer\s*[:=]\s*", re.I)


def extract_final(answer: str) -> str:
    """Pick the part of a free-text response that is the actual answer.

    When the model writes its answer as text instead of calling final_answer, the text usually
    contains its reasoning too, e.g. a list of every candidate. Grading all of it would let a hedged
    or wrong conclusion pass because the right value appears somewhere. So: use the text after the
    last 'final answer:' marker if there is one, else the last non-empty line of a multi-line answer.
    """
    text = str(answer).strip()
    parts = _FINAL_MARKER.split(text)
    if len(parts) > 1 and parts[-1].strip():
        return parts[-1].strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines[-1] if len(lines) > 1 else text


def grade(task: Task, answer: str | None) -> tuple[bool, str]:
    """Return (correct, explanation)."""
    if answer is None or not str(answer).strip():
        return False, "no answer"
    answer = extract_final(answer)
    g = task.grading
    kind = g.get("type", "exact")

    if kind == "numeric":
        nums = extract_numbers(answer)
        tol = float(g.get("tolerance", 0))
        target = float(task.answer)
        if not nums:
            return False, "no number in answer"
        if len(nums) > 2:
            # Hedged answers listing many numbers aren't accepted even if one matches.
            return False, f"ambiguous: {len(nums)} numbers in answer"
        hit = any(abs(n - target) <= tol + 1e-9 for n in nums)
        return hit, f"numbers={nums} target={target}±{tol}"

    if kind == "contains_all":
        norm = f" {normalize(answer)} "

        def present(v: str) -> bool:
            nv = normalize(v)
            if re.fullmatch(r"\d+(?:\.\d+)?", nv):
                # standalone number: digit boundaries, so '540m' matches 540 but '19' doesn't match 9
                return re.search(rf"(?<![\d.]){re.escape(nv)}(?![\d])", norm) is not None
            return re.search(rf"(?<![\w-]){re.escape(nv)}(?![\w-])", norm) is not None

        missing = [v for v in g["values"] if not present(v)]
        return not missing, ("all present" if not missing else f"missing {missing}")

    if kind == "exact":
        ok = normalize(answer) == normalize(str(task.answer))
        return ok, "exact match" if ok else "not equal"

    raise ValueError(f"unknown grading type {kind!r} in task {task.id}")
