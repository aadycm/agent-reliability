"""Command-line interface.

    python -m agent_reliability list-tools
    python -m agent_reliability list-tasks
    python -m agent_reliability run-task T06 [--reflection] [--self-check]     # watch the loop live
    python -m agent_reliability benchmark --name baseline [--self-check] [--reflection] [--repeats N]
    python -m agent_reliability ablation --prefix study1 [--repeats N]          # all 4 conditions + report
    python -m agent_reliability analyze runs/baseline
    python -m agent_reliability label runs/baseline
    python -m agent_reliability report runs/study1_* --out reports/study1
    python -m agent_reliability show-trace runs/baseline/traces/T06_founder_age__r0.json
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning, module="google")

from . import PROJECT_ROOT, RUNS_DIR  # noqa: E402
from .config import AgentConfig  # noqa: E402

CONDITIONS = {
    "baseline": dict(reflection=False, self_check=False),
    "reflection": dict(reflection=True, self_check=False),
    "selfcheck": dict(reflection=False, self_check=True),
    "reflection+selfcheck": dict(reflection=True, self_check=True),
}


def _config(args, **overrides) -> AgentConfig:
    cfg = AgentConfig()
    if getattr(args, "model", None):
        cfg.model = args.model
    if getattr(args, "max_steps", None):
        cfg.max_steps = args.max_steps
    if getattr(args, "rpm", None):
        cfg.retry.requests_per_minute = args.rpm
    cfg.reflection = overrides.get("reflection", getattr(args, "reflection", False))
    cfg.self_check = overrides.get("self_check", getattr(args, "self_check", False))
    return cfg


def _expand(paths: list[str]) -> list[Path]:
    out = []
    for p in paths:
        matches = sorted(glob.glob(p)) or [p]
        out += [Path(m) for m in matches if (Path(m) / "results.jsonl").exists()]
    if not out:
        sys.exit(f"no run directories with results.jsonl found in {paths}")
    return out


def cmd_list_tools(args):
    from .tools import DEFAULT_REGISTRY
    for t in DEFAULT_REGISTRY._tools.values():
        print(f"{t.name}: {t.description}\n    params: {json.dumps(t.parameters.get('properties', {}))}\n")


def cmd_list_tasks(args):
    from .benchmark import load_tasks
    for t in load_tasks():
        print(f"{t.id:34s} steps={t.steps}  {t.difficulty:20s} tools={t.required_tools}")


def cmd_run_task(args):
    from .agent import Agent
    from .benchmark import grade, load_tasks
    tasks = load_tasks(ids=[args.task])
    if not tasks:
        sys.exit(f"no task matching {args.task!r}")
    task = tasks[0]
    cfg = _config(args)
    trace = Agent(cfg, verbose=True).run(task.question, task_id=task.id)
    ok, why = grade(task, trace.final_answer) if trace.status == "answered" else (False, trace.status)
    print(f"\nexpected={task.answer!r}  correct={ok}  ({why})")
    print(f"stats: {trace.stats}")
    out = RUNS_DIR / "adhoc" / f"{task.id}__{cfg.condition_name}__{cfg.model}.json"
    trace.save(out)
    print(f"trace saved to {out.relative_to(PROJECT_ROOT)}")


def cmd_benchmark(args):
    from .benchmark.runner import run_benchmark
    from .evaluation.labels import analyze
    cfg = _config(args)
    run_dir = run_benchmark(cfg, run_name=args.name, task_ids=args.tasks, repeats=args.repeats, verbose=args.verbose)
    analyze(run_dir)
    print(f"failure labels: {run_dir / 'failures.csv'}")


def cmd_ablation(args):
    from .benchmark.runner import run_benchmark
    from .evaluation.labels import analyze
    from .reporting import build_report
    run_dirs = []
    for cond in args.conditions:
        print(f"\n######## condition: {cond} ########")
        cfg = _config(args, **CONDITIONS[cond])
        rd = run_benchmark(cfg, run_name=f"{args.prefix}_{cond}", task_ids=args.tasks,
                           repeats=args.repeats, verbose=args.verbose)
        analyze(rd)
        run_dirs.append(rd)
    out = build_report(run_dirs, PROJECT_ROOT / "reports" / args.prefix)
    print(f"\nreport: {out}")


def cmd_analyze(args):
    from collections import Counter
    from .evaluation.labels import analyze
    for rd in _expand(args.run_dirs):
        merged = analyze(rd)
        print(f"{rd.name}: {len(merged)} failures → {dict(Counter(m['final_category'] for m in merged))}")
        for m in merged:
            print(f"  {m['task_id']} r{m['repeat']}: {m['final_category']} [{m['label_source']}] — {m['evidence'][:150]}")


def cmd_label(args):
    from .evaluation.labels import interactive_label
    interactive_label(Path(args.run_dir), relabel=args.relabel)


def cmd_report(args):
    from .reporting import build_report
    out = build_report(_expand(args.run_dirs), Path(args.out))
    print(f"report written: {out}")


def cmd_show_trace(args):
    from .evaluation.labels import format_trace
    from .trace import load_trace
    print(format_trace(load_trace(Path(args.path)), max_out=args.max_out))


def main(argv=None):
    p = argparse.ArgumentParser(prog="agent_reliability", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def agent_opts(sp, toggles=True):
        sp.add_argument("--model", help="Gemini model name (default: $GEMINI_MODEL or gemini-3.6-flash)")
        sp.add_argument("--max-steps", type=int)
        sp.add_argument("--rpm", type=float, help="client-side requests-per-minute limit")
        if toggles:
            sp.add_argument("--reflection", action="store_true", help="critique the plan before executing")
            sp.add_argument("--self-check", action="store_true", help="verify the answer before finalizing")

    sub.add_parser("list-tools").set_defaults(fn=cmd_list_tools)
    sub.add_parser("list-tasks").set_defaults(fn=cmd_list_tasks)

    sp = sub.add_parser("run-task", help="run one task with live step-by-step output")
    sp.add_argument("task", help="task id or prefix, e.g. T06")
    agent_opts(sp)
    sp.set_defaults(fn=cmd_run_task)

    sp = sub.add_parser("benchmark", help="run all tasks under one condition")
    sp.add_argument("--name", help="run directory name under runs/ (reuse it to resume)")
    sp.add_argument("--tasks", nargs="*", help="subset of task ids/prefixes")
    sp.add_argument("--repeats", type=int, default=1)
    sp.add_argument("-v", "--verbose", action="store_true")
    agent_opts(sp)
    sp.set_defaults(fn=cmd_benchmark)

    sp = sub.add_parser("ablation", help="run several conditions and build a comparison report")
    sp.add_argument("--prefix", required=True)
    sp.add_argument("--conditions", nargs="*", default=list(CONDITIONS), choices=list(CONDITIONS))
    sp.add_argument("--tasks", nargs="*")
    sp.add_argument("--repeats", type=int, default=1)
    sp.add_argument("-v", "--verbose", action="store_true")
    agent_opts(sp, toggles=False)
    sp.set_defaults(fn=cmd_ablation)

    sp = sub.add_parser("analyze", help="(re)compute heuristic failure labels")
    sp.add_argument("run_dirs", nargs="+")
    sp.set_defaults(fn=cmd_analyze)

    sp = sub.add_parser("label", help="interactively label failed runs")
    sp.add_argument("run_dir")
    sp.add_argument("--relabel", action="store_true", help="include runs that already have a manual label")
    sp.set_defaults(fn=cmd_label)

    sp = sub.add_parser("report", help="build CSV + plots + summary.md from run directories")
    sp.add_argument("run_dirs", nargs="+")
    sp.add_argument("--out", default=str(PROJECT_ROOT / "reports" / "latest"))
    sp.set_defaults(fn=cmd_report)

    sp = sub.add_parser("show-trace", help="pretty-print a trace file")
    sp.add_argument("path")
    sp.add_argument("--max-out", type=int, default=600)
    sp.set_defaults(fn=cmd_show_trace)

    args = p.parse_args(argv)
    try:
        args.fn(args)
    except RuntimeError as e:  # e.g. missing API key
        sys.exit(f"error: {e}")
    except Exception as e:
        from .llm import DailyQuotaExhausted
        if isinstance(e, DailyQuotaExhausted):
            sys.exit(f"error: {e}")
        raise


if __name__ == "__main__":
    main()
