"""Results report: CSV of per-task results, markdown summary, and matplotlib plots.

Input: one or more run directories (each is one condition, e.g. baseline / selfcheck / ...).
Output directory:
    results.csv                      one row per task run, with failure category
    summary.md                       all tables (it's also the accessible "table view" of the plots)
    success_by_condition.png
    success_by_difficulty.png
    failure_categories.png
    per_task_outcomes.png
    cost_by_condition.png

Every number comes from the traces/results files in the run directories; nothing here
is estimated or filled in.

Statistics note: success rates use Wilson 95% intervals. Intervention-vs-baseline
comparisons pair runs by task and report an exact McNemar test on the tasks whose
outcome flipped. With ~20 tasks, only large effects will be distinguishable from noise.
"""

from __future__ import annotations

import csv
import math
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from ..benchmark.runner import load_results  # noqa: E402
from ..benchmark.tasks import DIFFICULTY_ORDER, load_tasks  # noqa: E402
from ..evaluation.failure_analysis import CATEGORIES  # noqa: E402
from ..evaluation.labels import analyze, load_manual  # noqa: E402

# Reference categorical palette (light surface), slots in fixed order.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
SURFACE, INK, INK_2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
SEQ_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
CONDITION_ORDER = ["baseline", "reflection", "selfcheck", "reflection+selfcheck"]


def _ui_font() -> list[str]:
    from matplotlib import font_manager
    installed = {f.name for f in font_manager.fontManager.ttflist}
    return [f for f in ("SF Pro Text", "Helvetica Neue", "Segoe UI", "Arial", "DejaVu Sans") if f in installed] or ["sans-serif"]


def _style() -> None:
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": AXIS, "axes.labelcolor": INK_2, "text.color": INK,
        "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True, "grid.color": GRID,
        "grid.linewidth": 0.6, "axes.axisbelow": True, "axes.spines.top": False, "axes.spines.right": False,
        "font.family": _ui_font(),
        "font.size": 10, "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left",
        "legend.frameon": False,
    })


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from discordant counts b and c."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * p)


# ---------------------------------------------------------------------------
def collect(run_dirs: list[Path]) -> tuple[list[dict], list[str]]:
    tasks = {t.id: t for t in load_tasks()}
    rows, labels_seen = [], []
    for rd in run_dirs:
        rd = Path(rd)
        results = load_results(rd)
        merged = {(m["task_id"], m["repeat"]): m for m in analyze(rd)}
        manual = load_manual(rd)
        cond = results[0]["condition"] if results else rd.name
        label = cond if cond not in labels_seen else f"{cond} ({rd.name})"
        labels_seen.append(label)
        for r in results:
            if r["task_id"] not in tasks:
                continue
            m = merged.get((r["task_id"], r["repeat"]))
            rows.append({
                **r, "condition": label, "run_dir": rd.name,
                "failure_category": "" if r["correct"] else (m["final_category"] if m else ""),
                "heuristic_category": m["heuristic_category"] if m else "",
                "manual_category": manual.get((r["task_id"], r["repeat"]), {}).get("category", ""),
            })
    order = sorted(labels_seen, key=lambda c: (CONDITION_ORDER.index(c) if c in CONDITION_ORDER else 99, c))
    return rows, order


def _scored(rows: list[dict]) -> list[dict]:
    """api_error runs say nothing about the agent: exclude them from success rates."""
    return [r for r in rows if r["status"] != "api_error"]


def _fmt_pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def _bar_labels(ax, bars, texts, inside=False):
    for b, t in zip(bars, texts):
        y = b.get_height()
        ax.annotate(t, (b.get_x() + b.get_width() / 2, y), xytext=(0, 3), textcoords="offset points",
                    ha="center", va="bottom", fontsize=8.5, color=INK_2)


# ---------------------------------------------------------------------------
def plot_success_by_condition(rows, conds, out: Path):
    fig, ax = plt.subplots(figsize=(1.6 * len(conds) + 2.5, 4))
    vals, errs, labels = [], [[], []], []
    for c in conds:
        rs = _scored([r for r in rows if r["condition"] == c])
        k, n = sum(r["correct"] for r in rs), len(rs)
        p = k / n if n else 0
        lo, hi = wilson(k, n)
        vals.append(p); errs[0].append(p - lo); errs[1].append(hi - p)
        labels.append(f"{_fmt_pct(p)}  ({k}/{n})")
    x = range(len(conds))
    bars = ax.bar(x, vals, width=0.55, color=[SERIES[i % 8] for i in x], edgecolor=SURFACE, linewidth=2)
    ax.errorbar(x, vals, yerr=errs, fmt="none", ecolor=INK_2, elinewidth=1.2, capsize=4)
    for b, t, hi in zip(bars, labels, errs[1]):
        ax.annotate(t, (b.get_x() + b.get_width() / 2, b.get_height() + hi), xytext=(0, 4),
                    textcoords="offset points", ha="center", fontsize=9, color=INK)
    ax.set_xticks(list(x), conds)
    ax.set_ylim(0, 1.12); ax.set_ylabel("success rate")
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.grid(axis="x", visible=False)
    ax.set_title("Overall success rate by condition (95% Wilson CI)")
    fig.tight_layout(); fig.savefig(out, dpi=150); plt.close(fig)


def plot_success_by_difficulty(rows, conds, out: Path):
    fig, ax = plt.subplots(figsize=(8.5, 4.2))
    w = 0.8 / max(1, len(conds))
    for i, c in enumerate(conds):
        vals, texts = [], []
        for d in DIFFICULTY_ORDER:
            rs = _scored([r for r in rows if r["condition"] == c and r["difficulty"] == d])
            k, n = sum(r["correct"] for r in rs), len(rs)
            vals.append(k / n if n else 0); texts.append(f"{k}/{n}")
        xs = [j + (i - (len(conds) - 1) / 2) * w for j in range(len(DIFFICULTY_ORDER))]
        bars = ax.bar(xs, vals, width=w, color=SERIES[i % 8], edgecolor=SURFACE, linewidth=2, label=c)
        _bar_labels(ax, bars, texts)
    ax.set_xticks(range(len(DIFFICULTY_ORDER)), DIFFICULTY_ORDER)
    ax.set_ylim(0, 1.12); ax.set_ylabel("success rate")
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper right", ncol=min(4, len(conds)), fontsize=9)
    ax.set_title("Success rate by task difficulty (canonical tool-call steps)")
    fig.tight_layout(); fig.savefig(out, dpi=150); plt.close(fig)


def plot_failure_categories(rows, conds, out: Path):
    fig, ax = plt.subplots(figsize=(9, 0.7 * len(conds) + 2.2))
    counts = {c: Counter(r["failure_category"] for r in _scored(rows) if r["condition"] == c and not r["correct"])
              for c in conds}
    left = [0] * len(conds)
    y = list(range(len(conds)))[::-1]
    for i, cat in enumerate(CATEGORIES):
        vals = [counts[c].get(cat, 0) for c in conds]
        bars = ax.barh(y, vals, left=left, color=SERIES[i], edgecolor=SURFACE, linewidth=2, height=0.6, label=cat)
        for b, v in zip(bars, vals):
            if v:
                ax.text(b.get_x() + b.get_width() / 2, b.get_y() + b.get_height() / 2, str(v),
                        ha="center", va="center", fontsize=8.5, color=INK)
        left = [l + v for l, v in zip(left, vals)]
    for yy, total in zip(y, left):
        ax.text(total, yy, f"  {total}", va="center", fontsize=9, color=INK_2)
    ax.set_yticks(y, conds)
    ax.set_xlabel("number of failed runs")
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, max(left + [1]) * 1.12)
    ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
    if sum(left) == 0:
        ax.text(0.5, 0.5, "No failed runs in any condition: nothing to categorize",
                transform=ax.transAxes, ha="center", va="center", fontsize=11, color=INK_2)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=3, fontsize=8.5)
    ax.set_title("Failure categories by condition")
    fig.tight_layout(); fig.savefig(out, dpi=150, bbox_inches="tight"); plt.close(fig)


def plot_per_task(rows, conds, out: Path):
    tasks = [t.id for t in load_tasks()]
    tasks = [t for t in tasks if any(r["task_id"] == t for r in rows)]
    grid = []
    for t in tasks:
        line = []
        for c in conds:
            rs = _scored([r for r in rows if r["task_id"] == t and r["condition"] == c])
            line.append(sum(r["correct"] for r in rs) / len(rs) if rs else float("nan"))
        grid.append(line)
    fig, ax = plt.subplots(figsize=(1.5 * len(conds) + 4, 0.32 * len(tasks) + 1.6))
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list("seqblue", ["#f0efec"] + SEQ_BLUE[2:])
    im = ax.imshow(grid, aspect="auto", cmap=cmap, vmin=0, vmax=1)
    for i, line in enumerate(grid):
        for j, v in enumerate(line):
            txt = "–" if math.isnan(v) else ("✓" if v == 1 else "✗" if v == 0 else f"{v:.0%}")
            ax.text(j, i, txt, ha="center", va="center", fontsize=8.5, color=SURFACE if (v == v and v > 0.6) else INK)
    ax.set_xticks(range(len(conds)), conds)
    ax.set_yticks(range(len(tasks)), tasks, fontsize=8)
    ax.xaxis.tick_top()
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xticks([x - 0.5 for x in range(1, len(conds))], minor=True)
    ax.set_yticks([y - 0.5 for y in range(1, len(tasks))], minor=True)
    ax.grid(which="minor", color=SURFACE, linewidth=2)
    ax.tick_params(which="minor", length=0)
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    cb.set_label("success rate over repeats"); cb.outline.set_visible(False)
    ax.set_title("Per-task outcome by condition", pad=28)
    fig.tight_layout(); fig.savefig(out, dpi=150); plt.close(fig)


def plot_cost(rows, conds, out: Path):
    metrics = [("model_calls", "mean model calls / task"), ("tool_calls", "mean tool calls / task"),
               ("total_tokens", "mean tokens / task")]
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.6))
    for ax, (key, title) in zip(axes, metrics):
        vals = []
        for c in conds:
            rs = _scored([r for r in rows if r["condition"] == c])
            if key == "total_tokens":
                v = [r["prompt_tokens"] + r["output_tokens"] for r in rs]
            else:
                v = [r[key] for r in rs]
            vals.append(sum(v) / len(v) if v else 0)
        bars = ax.bar(range(len(conds)), vals, color=[SERIES[i % 8] for i in range(len(conds))],
                      edgecolor=SURFACE, linewidth=2, width=0.6)
        _bar_labels(ax, bars, [f"{v:,.0f}" if v >= 100 else f"{v:.1f}" for v in vals])
        ax.set_xticks(range(len(conds)), conds, rotation=20, ha="right", fontsize=8.5)
        ax.set_title(title, fontsize=10.5)
        ax.set_ylim(0, max(vals + [1]) * 1.18)
        ax.grid(axis="x", visible=False)
    fig.suptitle("Cost of each condition", x=0.01, ha="left", fontweight="bold")
    fig.tight_layout(); fig.savefig(out, dpi=150); plt.close(fig)


# ---------------------------------------------------------------------------
def _md_table(header: list[str], body: list[list]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(x) for x in row) + " |" for row in body]
    return "\n".join(lines)


def build_report(run_dirs: list[Path], out_dir: Path) -> Path:
    _style()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, conds = collect(run_dirs)
    if not rows:
        raise ValueError("no results found in the given run directories")

    # ---- CSV ----
    fields = ["condition", "run_dir", "task_id", "repeat", "difficulty", "steps_canonical", "status", "correct",
              "final_answer", "expected", "grading_note", "failure_category", "heuristic_category",
              "manual_category", "finish_mode", "model_calls", "tool_calls", "tool_errors", "self_checks",
              "self_checks_answered", "empty_responses",
              "retries", "prompt_tokens", "output_tokens", "duration_s", "model"]
    with (out_dir / "results.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    # ---- plots ----
    plot_success_by_condition(rows, conds, out_dir / "success_by_condition.png")
    plot_success_by_difficulty(rows, conds, out_dir / "success_by_difficulty.png")
    plot_failure_categories(rows, conds, out_dir / "failure_categories.png")
    plot_per_task(rows, conds, out_dir / "per_task_outcomes.png")
    plot_cost(rows, conds, out_dir / "cost_by_condition.png")

    # ---- markdown ----
    md = ["# Agent reliability report", ""]
    models = sorted({r["model"] for r in rows})
    n_tasks = len({r["task_id"] for r in rows})
    md += [f"- Model(s): {', '.join(models)}", f"- Tasks: {n_tasks}",
           f"- Run directories: {', '.join(Path(d).name for d in run_dirs)}",
           "- Every number below was computed from the run traces. Runs that ended in `api_error` are excluded "
           "from success rates and counted separately.", ""]

    body = []
    for c in conds:
        allr = [r for r in rows if r["condition"] == c]
        rs = _scored(allr)
        k, n = sum(r["correct"] for r in rs), len(rs)
        lo, hi = wilson(k, n)
        body.append([c, n, k, _fmt_pct(k / n) if n else "n/a", f"{_fmt_pct(lo)} – {_fmt_pct(hi)}",
                     len(allr) - n])
    md += ["## Overall success", "", _md_table(["condition", "scored runs", "correct", "success", "95% CI", "api_error (excluded)"], body),
           "", "![](success_by_condition.png)", ""]

    body = []
    for d in DIFFICULTY_ORDER:
        line = [d]
        for c in conds:
            rs = _scored([r for r in rows if r["condition"] == c and r["difficulty"] == d])
            k, n = sum(r["correct"] for r in rs), len(rs)
            line.append(f"{_fmt_pct(k / n)} ({k}/{n})" if n else "n/a")
        body.append(line)
    md += ["## Success by difficulty", "", _md_table(["difficulty"] + conds, body), "",
           "![](success_by_difficulty.png)", ""]

    body = []
    for cat in CATEGORIES:
        body.append([cat] + [sum(1 for r in _scored(rows) if r["condition"] == c and not r["correct"]
                                 and r["failure_category"] == cat) for c in conds])
    md += ["## Failure categories", "",
           "Final category = manual label when present, otherwise the heuristic label.", "",
           _md_table(["category"] + conds, body), "", "![](failure_categories.png)", ""]

    labeled = [r for r in rows if not r["correct"] and r["manual_category"] and r["status"] != "api_error"]
    if labeled:
        agree = sum(r["manual_category"] == r["heuristic_category"] for r in labeled)
        conf = Counter((r["heuristic_category"], r["manual_category"]) for r in labeled
                       if r["manual_category"] != r["heuristic_category"])
        md += ["### Heuristic vs manual labels", "",
               f"{agree}/{len(labeled)} manually labeled failures ({_fmt_pct(agree / len(labeled))}) agree with the heuristic.", ""]
        if conf:
            md += [_md_table(["heuristic said", "manual said", "count"], [[h, m, n] for (h, m), n in conf.most_common()]), ""]
    else:
        md += ["_No manual labels yet. Categories are heuristic only (run `label` to review them)._", ""]

    # ---- intervention comparison ----
    if "baseline" in conds and len(conds) > 1:
        def per_task(c):
            acc = defaultdict(list)
            for r in _scored([r for r in rows if r["condition"] == c]):
                acc[r["task_id"]].append(r["correct"])
            return {t: sum(v) / len(v) for t, v in acc.items()}
        base = per_task("baseline")
        body, flips = [], []
        for c in conds:
            if c == "baseline":
                continue
            other = per_task(c)
            common = sorted(set(base) & set(other))
            if not common:
                continue
            b_rate = sum(base[t] for t in common) / len(common)
            o_rate = sum(other[t] for t in common) / len(common)
            fixed = [t for t in common if other[t] > 0.5 >= base[t]]
            broken = [t for t in common if base[t] > 0.5 >= other[t]]
            p = mcnemar_exact(len(fixed), len(broken))
            body.append([c, len(common), _fmt_pct(b_rate), _fmt_pct(o_rate),
                         f"{100 * (o_rate - b_rate):+.1f} pp", len(fixed), len(broken), f"{p:.3f}"])
            flips.append((c, fixed, broken))
        md += ["## Interventions vs baseline", "",
               "Paired by task (majority outcome over repeats). *fixed* = baseline wrong → intervention right; "
               "*broken* = the reverse. p = exact McNemar test on fixed vs broken. With this few tasks, treat "
               "p > 0.05 as \"no detectable effect\", not as evidence of no effect.", "",
               _md_table(["condition", "paired tasks", "baseline", "condition", "Δ", "fixed", "broken", "McNemar p"], body), ""]
        for c, fixed, broken in flips:
            md += [f"- **{c}**: fixed {fixed or '—'}; broken {broken or '—'}"]
        md += [""]

    body = []
    for c in conds:
        rs = _scored([r for r in rows if r["condition"] == c])
        if not rs:
            continue
        mean = lambda k: sum(r[k] for r in rs) / len(rs)  # noqa: E731
        body.append([c, f"{mean('model_calls'):.1f}", f"{mean('tool_calls'):.1f}", f"{mean('tool_errors'):.2f}",
                     f"{sum(r['prompt_tokens'] + r['output_tokens'] for r in rs) / len(rs):,.0f}",
                     f"{mean('duration_s'):.1f}", sum(r["retries"] for r in rs),
                     sum(r.get("empty_responses", 0) for r in rs),
                     f"{sum(r.get('self_checks_answered', 0) for r in rs)}/{sum(r['self_checks'] for r in rs)}"])
    md += ["## Cost and intervention delivery", "",
           "*self-checks answered* = self-check prompts the model responded to, out of prompts sent. If it's "
           "below the total, the model silently skipped verification (empty reply), and that condition does not "
           "really test self-check. *seconds* includes rate-limit and retry waits.", "",
           _md_table(["condition", "model calls", "tool calls", "tool errors", "tokens", "seconds",
                      "API retries (total)", "empty responses", "self-checks answered"], body),
           "", "![](cost_by_condition.png)", "", "## Per-task outcomes", "", "![](per_task_outcomes.png)", ""]

    body = []
    for t in load_tasks():
        line = [t.id, t.steps]
        present = False
        for c in conds:
            rs = _scored([r for r in rows if r["condition"] == c and r["task_id"] == t.id])
            if rs:
                present = True
                k = sum(r["correct"] for r in rs)
                cats = ",".join(sorted({r["failure_category"] for r in rs if not r["correct"]}))
                line.append(f"{k}/{len(rs)}" + (f" ({cats})" if cats else ""))
            else:
                line.append("–")
        if present:
            body.append(line)
    md += [_md_table(["task", "steps"] + conds, body), ""]

    path = out_dir / "summary.md"
    path.write_text("\n".join(md), encoding="utf-8")
    return path
