"""Offline tests of the loop logic using a scripted LLM (no API calls)."""

from google.api_core import exceptions as gexc

from agent_reliability.agent import Agent
from agent_reliability.config import AgentConfig, RetryConfig
from agent_reliability.llm import FunctionCall, LLMAPIError, LLMResponse, ScriptedBackend, call_with_retries

FA = lambda a: FunctionCall("final_answer", {"answer": a})  # noqa: E731


def make_agent(script, **cfg):
    backend = ScriptedBackend(script)
    return Agent(AgentConfig(model="scripted", **cfg), backend=backend), backend


def test_tool_then_final_answer():
    agent, _ = make_agent([
        LLMResponse(text="Compute it.", function_calls=[FunctionCall("calculator", {"expression": "6*7"})]),
        LLMResponse(function_calls=[FA("42")]),
    ])
    t = agent.run("What is 6*7?", "t")
    assert t.status == "answered" and t.final_answer == "42" and t.finish_mode == "final_answer_tool"
    assert t.steps[0].reasoning == "Compute it."
    assert t.steps[0].tool_calls[0].output == 42
    assert t.stats["tool_calls"] == 1 and t.stats["model_calls"] == 2


def test_tool_error_is_returned_not_raised():
    agent, backend = make_agent([
        LLMResponse(function_calls=[FunctionCall("calculator", {"expression": "1/0"})]),
        LLMResponse(function_calls=[FA("undefined")]),
    ])
    t = agent.run("1/0?")
    assert t.steps[0].tool_calls[0].error == "division by zero"
    tool_msgs = [h for h in backend.conversation.history if h[0] == "tool"]
    assert tool_msgs[0][1][0] == ("calculator", {"error": "division by zero"})


def test_step_limit():
    loop = [LLMResponse(function_calls=[FunctionCall("calculator", {"expression": "1+1"})])] * 5
    agent, _ = make_agent(loop, max_steps=3)
    t = agent.run("loop forever")
    assert t.status == "step_limit" and len(t.steps) == 3


def test_text_response_is_final():
    agent, _ = make_agent([LLMResponse(text="The answer is 5.")])
    t = agent.run("?")
    assert t.status == "answered" and t.finish_mode == "text_response"


def test_empty_response_nudged_then_no_answer():
    agent, _ = make_agent([LLMResponse(finish_reason="MALFORMED_FUNCTION_CALL")] * 3, max_empty_response_nudges=2)
    t = agent.run("?")
    assert t.status == "no_answer" and [s.nudged for s in t.steps] == [True, True, False]
    assert t.stats["empty_responses"] == 3


def test_self_check_intercepts_once_and_can_revise():
    agent, backend = make_agent([
        LLMResponse(function_calls=[FA("40")]),
        LLMResponse(text="Let me recheck.", function_calls=[FunctionCall("calculator", {"expression": "6*7"})]),
        LLMResponse(function_calls=[FA("42")]),
    ], self_check=True)
    t = agent.run("6*7?")
    assert t.final_answer == "42"
    assert [s.kind for s in t.steps] == ["model", "self_check", "model"]
    assert t.steps[0].proposed_answer == "40"
    assert t.stats["self_checks"] == 1 and t.stats["self_checks_answered"] == 1
    # The verification request is delivered as the final_answer tool result, not as a separate text turn.
    tool_turn = [h for h in backend.conversation.history if h[0] == "tool"][0][1]
    name, payload = tool_turn[-1]
    assert name == "final_answer" and "NOT ACCEPTED" in payload["status"] and "verify" in payload["instructions"]
    assert not any(h[0] == "user" and "verify" in h[1] for h in backend.conversation.history)


def test_ignored_self_check_stays_visible_in_trace():
    # Regression: the model answering the self-check prompt with nothing used to be relabeled 'nudge'.
    agent, _ = make_agent([
        LLMResponse(function_calls=[FA("37")]),
        LLMResponse(),                                # empty reply to the self-check
        LLMResponse(function_calls=[FA("37")]),
    ], self_check=True)
    t = agent.run("?")
    assert [s.kind for s in t.steps] == ["model", "self_check", "model"]
    assert t.steps[1].nudged
    assert t.stats["self_checks"] == 1 and t.stats["self_checks_answered"] == 0


def test_self_check_does_not_eat_step_budget():
    agent, _ = make_agent([LLMResponse(function_calls=[FA("1")]), LLMResponse(function_calls=[FA("1")])],
                          self_check=True, max_steps=1)
    assert agent.run("?").status == "answered"


def test_reflection_step_recorded():
    agent, _ = make_agent([LLMResponse(text="PLAN: ...\nREVISED PLAN: 1. answer"), LLMResponse(function_calls=[FA("x")])],
                          reflection=True)
    t = agent.run("?")
    assert t.steps[0].kind == "reflection" and t.reflection_plan.startswith("PLAN")
    assert t.config["condition"] == "reflection"


def test_api_error_ends_run_gracefully():
    agent, _ = make_agent([LLMAPIError("quota exhausted")])
    t = agent.run("?")
    assert t.status == "api_error" and "quota" in t.error


def test_retry_backoff_on_rate_limit():
    calls = {"n": 0}
    sleeps = []

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise gexc.TooManyRequests("429 retry_delay { seconds: 5 }")
        return "ok"

    result, retries = call_with_retries(flaky, RetryConfig(max_retries=4, base_delay=0.01), sleep=sleeps.append)
    assert result == "ok" and retries == 2
    assert all(s >= 6 for s in sleeps)  # honoured the server-suggested delay


DAILY_429 = ('429 You exceeded your current quota. Please retry in 31.8s. violations { quota_metric: '
             '"generate_content_free_tier_requests" quota_id: "GenerateRequestsPerDayPerProjectPerModel-FreeTier" '
             'quota_value: 20 } retry_delay { seconds: 31 }')


def test_daily_quota_is_not_retried():
    from agent_reliability.llm import DailyQuotaExhausted
    sleeps = []

    def exhausted():
        raise gexc.ResourceExhausted(DAILY_429)
    try:
        call_with_retries(exhausted, RetryConfig(max_retries=6), sleep=sleeps.append)
    except DailyQuotaExhausted as e:
        assert "limit 20" in str(e) and sleeps == []
    else:
        raise AssertionError("expected DailyQuotaExhausted")


def test_runner_stops_on_daily_quota_and_resumes(tmp_path):
    from agent_reliability.benchmark.runner import load_results, run_benchmark
    from agent_reliability.benchmark import load_tasks
    from agent_reliability.llm import DailyQuotaExhausted
    tasks = {t.id: t for t in load_tasks(ids=["T01", "T02", "T03"])}

    class QuotaAgent:
        def __init__(self, budget):
            self.budget = budget

        def run(self, question, task_id):
            if self.budget == 0:
                raise DailyQuotaExhausted("daily quota exhausted")
            self.budget -= 1
            return Agent(AgentConfig(model="scripted"),
                         backend=ScriptedBackend([LLMResponse(function_calls=[FA(str(tasks[task_id].answer))])])
                         ).run(question, task_id)

    cfg = AgentConfig(model="scripted")
    rd = run_benchmark(cfg, run_name="q", task_ids=list(tasks), agent=QuotaAgent(1), runs_dir=tmp_path)
    assert len(load_results(rd)) == 1 and len(list((rd / "traces").iterdir())) == 1
    rd = run_benchmark(cfg, run_name="q", task_ids=list(tasks), agent=QuotaAgent(5), runs_dir=tmp_path)
    assert [r["correct"] for r in load_results(rd)] == [True, True, True]


def test_non_retryable_error_raises_immediately():
    def bad():
        raise gexc.InvalidArgument("bad schema")
    try:
        call_with_retries(bad, RetryConfig(max_retries=5), sleep=lambda s: None)
    except LLMAPIError as e:
        assert "InvalidArgument" in str(e)
    else:
        raise AssertionError("expected LLMAPIError")
