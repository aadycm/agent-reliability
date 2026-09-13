"""Heuristic categorization on hand-built traces, plus an offline end-to-end pipeline test
(scripted LLM → runner → analyze → report) in a temp directory. These are fixtures to test
the code, not benchmark results."""

from agent_reliability.agent import Agent
from agent_reliability.benchmark import grade, load_tasks
from agent_reliability.benchmark.runner import result_row, run_benchmark
from agent_reliability.config import AgentConfig
from agent_reliability.evaluation.failure_analysis import categorize
from agent_reliability.evaluation.labels import analyze, load_manual, merge_labels, save_manual
from agent_reliability.llm import FunctionCall, LLMResponse, ScriptedBackend
from agent_reliability.reporting import build_report

TASKS = {t.id: t for t in load_tasks()}


def run_script(task_id, script, **cfg):
    task = TASKS[task_id]
    agent = Agent(AgentConfig(model="scripted", **cfg), backend=ScriptedBackend(script))
    trace = agent.run(task.question, task.id).to_dict()
    return task, trace, result_row(task, trace, 0)


def S(name, **args):
    return FunctionCall(name, args)


def FA(a):
    return LLMResponse(function_calls=[S("final_answer", answer=a)])


def label_of(task_id, script, **cfg):
    task, trace, row = run_script(task_id, script, **cfg)
    lab = categorize(task, trace, row)
    return lab.category if lab else None, lab


def test_correct_run_has_no_label():
    cat, _ = label_of("T01_rev_per_employee", [
        LLMResponse(function_calls=[S("search", query="Veltrix Dynamics")]),
        LLMResponse(function_calls=[S("calculator", expression="412000000/2150")]),
        FA("191628"),
    ])
    assert cat is None


def test_hallucinated_no_tools():
    cat, lab = label_of("T01_rev_per_employee", [FA("150000")])
    assert cat == "hallucinated_tool_result"


def test_hallucinated_fabricated_number_in_calculation():
    cat, lab = label_of("T01_rev_per_employee", [
        LLMResponse(function_calls=[S("search", query="Veltrix Dynamics")]),
        LLMResponse(function_calls=[S("calculator", expression="412000000/2300")]),  # 2300 never returned
        FA("179130"),
    ])
    assert cat == "hallucinated_tool_result" and 2300.0 in lab.signals["fabricated_numbers"]


def test_wrong_tool_choice():
    cat, _ = label_of("T04_north_units", [
        LLMResponse(function_calls=[S("search", query="sales q3 North units")]),
        LLMResponse(function_calls=[S("calculator", expression="40+120")]),
        FA("160"),
    ])
    assert cat == "wrong_tool_choice"


def test_infinite_loop():
    loop = [LLMResponse(function_calls=[S("search", query="Orin Cup")])] * 5
    cat, _ = label_of("T13_orin_cup_estmark", loop, max_steps=5)
    assert cat == "infinite_loop"


def test_gave_up_early():
    cat, _ = label_of("T11_memo_leader_birthplace", [
        LLMResponse(function_calls=[S("read_file", path="memo_2024.txt")]),
        FA("I cannot determine the birthplace from the available information."),
    ])
    assert cat == "gave_up_early"


def test_bad_plan_missing_intermediate():
    # Read the memo, searched Quorra, but never looked up the CEO's birthplace. Guessed Lindell Bay (the HQ).
    cat, lab = label_of("T11_memo_leader_birthplace", [
        LLMResponse(function_calls=[S("read_file", path="memo_2024.txt")]),
        LLMResponse(function_calls=[S("search", query="Quorra Biotech", top_k=1)]),
        FA("Lindell Bay"),
    ])
    assert cat == "bad_plan" and "born 1974 in Harlow Pike" in lab.signals["missing_intermediates"]


def test_execution_error_near_miss():
    cat, _ = label_of("T01_rev_per_employee", [
        LLMResponse(function_calls=[S("search", query="Veltrix Dynamics")]),
        LLMResponse(function_calls=[S("calculator", expression="412000000/2150")]),
        FA("191000"),
    ])
    assert cat == "execution_error"


def test_bad_plan_right_info_wrong_logic():
    cat, _ = label_of("T08_top_product", [
        LLMResponse(function_calls=[S("read_file", path="sales_q3.csv")]),
        LLMResponse(function_calls=[S("python_exec", code="print('Kestrel-9')")]),
        FA("Kestrel-9"),
    ])
    assert cat == "bad_plan"


def test_manual_labels_override(tmp_path):
    run_dir = _fake_run(tmp_path, "baseline", {})
    merged = analyze(run_dir)
    first = merged[0]
    save_manual(run_dir, {(first["task_id"], first["repeat"]): {"category": "bad_plan", "notes": "checked"}})
    merged = merge_labels(run_dir)
    assert merged[0]["final_category"] == "bad_plan" and merged[0]["label_source"] == "manual"
    assert load_manual(run_dir)[(first["task_id"], 0)]["notes"] == "checked"


class _FakeAgent:
    """Stands in for the real agent in the runner: answers correctly on some tasks, not on others."""

    def __init__(self, cfg, right: set[str]):
        self.cfg, self.right = cfg, right

    def run(self, question, task_id):
        task = TASKS[task_id]
        script = ([FA(str(task.answer))] if task_id in self.right else [FA("I don't know")])
        return Agent(self.cfg, backend=ScriptedBackend(script)).run(question, task_id)


def _fake_run(tmp_path, cond, right):
    flags = {"baseline": {}, "selfcheck": {"self_check": False}}[cond]
    cfg = AgentConfig(model="scripted", **flags)
    ids = ["T01", "T02", "T08", "T13", "T21"]
    rd = run_benchmark(cfg, run_name=f"x_{cond}", task_ids=ids, agent=_FakeAgent(cfg, right), runs_dir=tmp_path)
    return rd


def test_end_to_end_report(tmp_path):
    rd1 = _fake_run(tmp_path, "baseline", {"T01_rev_per_employee"})
    rd2 = _fake_run(tmp_path, "selfcheck", {"T01_rev_per_employee", "T02_founding_gap"})
    out = build_report([rd1, rd2], tmp_path / "report")
    text = out.read_text(encoding="utf-8")
    assert "Overall success" in text and "gave_up_early" in text
    for png in ["success_by_condition", "success_by_difficulty", "failure_categories", "per_task_outcomes", "cost_by_condition"]:
        assert (tmp_path / "report" / f"{png}.png").stat().st_size > 5000
    assert (tmp_path / "report" / "results.csv").read_text(encoding="utf-8").count("\n") == 11
    # resume: rerunning uses cached traces
    rd1b = _fake_run(tmp_path, "baseline", set())  # would answer wrong if it actually re-ran
    assert grade(TASKS["T01_rev_per_employee"], "191628")[0]
    assert "(cached)" not in str(rd1b)  # path only; behaviour checked below
    from agent_reliability.benchmark.runner import load_results
    assert any(r["correct"] for r in load_results(rd1b))
