"""Stress conditions: degraded tools, injected failures, and their bookkeeping."""

from agent_reliability.agent import Agent
from agent_reliability.config import AgentConfig
from agent_reliability.llm import FunctionCall, LLMResponse, ScriptedBackend
from agent_reliability.stress import TRANSIENT_ERROR, StressRegistry
from agent_reliability.tools import DEFAULT_REGISTRY as REG


def test_degraded_search_returns_one_truncated_result():
    full = REG.execute("search", {"query": "Veltrix Dynamics", "top_k": 3}).output
    assert len(full) >= 2
    s = StressRegistry(REG, degrade_search=True)
    out = s.execute("search", {"query": "Veltrix Dynamics", "top_k": 3}).output
    assert len(out) == 1
    assert out[0]["title"] == "Veltrix Dynamics"
    assert out[0]["snippet"].endswith("Mira Osterfeld.")     # first sentence only
    assert "2,150" not in out[0]["snippet"]                   # later facts withheld
    assert "truncated" in out[0]["note"]


def test_other_tools_untouched_by_search_degradation():
    s = StressRegistry(REG, degrade_search=True)
    assert s.execute("calculator", {"expression": "2+2"}).output == 4


def test_injected_failures_are_reproducible_per_task():
    a = StressRegistry(REG, tool_failure_rate=0.5, seed=7)
    b = StressRegistry(REG, tool_failure_rate=0.5, seed=7)
    a.begin_run("T01"); b.begin_run("T01")
    pattern_a = [a.execute("calculator", {"expression": "1+1"}).error for _ in range(20)]
    pattern_b = [b.execute("calculator", {"expression": "1+1"}).error for _ in range(20)]
    assert pattern_a == pattern_b                      # same seed + task -> same failures
    assert any(e == TRANSIENT_ERROR for e in pattern_a) and any(e is None for e in pattern_a)
    b.begin_run("T02")
    assert [b.execute("calculator", {"expression": "1+1"}).error for _ in range(20)] != pattern_a


def test_failure_rate_zero_and_one():
    never = StressRegistry(REG, tool_failure_rate=0.0); never.begin_run("t")
    assert all(never.execute("calculator", {"expression": "1+1"}).error is None for _ in range(10))
    always = StressRegistry(REG, tool_failure_rate=1.0); always.begin_run("t")
    assert all(always.execute("calculator", {"expression": "1+1"}).error == TRANSIENT_ERROR for _ in range(10))


def test_declarations_unchanged_so_model_is_not_told():
    s = StressRegistry(REG, tool_failure_rate=0.9, degrade_search=True)
    assert s.declarations() == REG.declarations() and s.names() == REG.names()


def test_condition_names_separate_stressed_from_normal():
    assert AgentConfig().condition_name == "baseline"
    assert AgentConfig(max_steps=4).condition_name == "baseline[steps4]"
    assert AgentConfig(tool_failure_rate=0.3).condition_name == "baseline[flaky0.3]"
    assert AgentConfig(degrade_search=True, self_check=True).condition_name == "selfcheck[search1]"
    assert AgentConfig(reflection=True, max_steps=4, degrade_search=True).condition_name == \
        "reflection[steps4,search1]"


def test_agent_wraps_registry_and_records_injected_errors():
    cfg = AgentConfig(model="scripted", tool_failure_rate=1.0)
    agent = Agent(cfg, backend=ScriptedBackend([
        LLMResponse(function_calls=[FunctionCall("calculator", {"expression": "6*7"})]),
        LLMResponse(function_calls=[FunctionCall("final_answer", {"answer": "42"})]),
    ]))
    t = agent.run("6*7?", "T_x")
    assert t.steps[0].tool_calls[0].error == TRANSIENT_ERROR
    assert t.config["tool_failure_rate"] == 1.0 and t.condition == "baseline[flaky1]"


# --- search degradation dose ladder ------------------------------------------

def _search(level, top_k=3):
    s = StressRegistry(REG, degrade_search=True, search_level=level)
    return s.execute("search", {"query": "Veltrix Dynamics", "top_k": top_k}).output


def test_severe_is_unchanged_from_the_original_setting():
    """Earlier runs used this behaviour; it must stay identical or they stop being comparable."""
    out = _search("severe")
    assert len(out) == 1
    assert out[0]["title"] == "Veltrix Dynamics"
    assert out[0]["snippet"].endswith("Mira Osterfeld.")   # first sentence only
    assert "2,150" not in out[0]["snippet"]                # later facts withheld


def test_moderate_keeps_one_full_snippet():
    out = _search("moderate")
    assert len(out) == 1
    assert "2,150" in out[0]["snippet"]                    # the whole snippet survives
    assert "top match only" in out[0]["note"]


def test_mild_keeps_two_full_snippets():
    out = _search("mild")
    assert len(out) == 2
    assert all("..." not in d["snippet"] for d in out)
    assert "2,150" in out[0]["snippet"]


def test_ladder_is_monotonic_in_information():
    """Each step up the ladder withholds at least as much as the one below it."""
    sizes = [sum(len(d["snippet"]) for d in _search(lvl)) for lvl in ("mild", "moderate", "severe")]
    assert sizes[0] > sizes[1] > sizes[2]


def test_level_ignored_when_degradation_is_off():
    s = StressRegistry(REG, degrade_search=False, search_level="severe")
    assert s.search_level == "off"
    assert s.execute("search", {"query": "Veltrix Dynamics", "top_k": 3}).output == \
        REG.execute("search", {"query": "Veltrix Dynamics", "top_k": 3}).output


def test_unknown_level_is_rejected():
    import pytest
    from agent_reliability.stress import _truncate_search
    with pytest.raises(ValueError):
        _truncate_search([{"title": "x", "snippet": "y."}], "catastrophic")


def test_condition_names_distinguish_the_levels():
    assert AgentConfig(degrade_search=True, search_level="severe").condition_name == "baseline[search1]"
    assert AgentConfig(degrade_search=True, search_level="mild").condition_name == "baseline[search-mild]"
    assert AgentConfig(degrade_search=True, search_level="moderate", reflection=True).condition_name == \
        "reflection[search-moderate]"
