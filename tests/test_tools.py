from agent_reliability.tools import DEFAULT_REGISTRY as REG


def test_registry_has_required_tools():
    assert {"calculator", "python_exec", "read_file", "list_files", "search"} <= set(REG.names())


def test_calculator():
    assert REG.execute("calculator", {"expression": "412000000 / 2150"}).output == 191627.9069767442
    assert REG.execute("calculator", {"expression": "2^10"}).output == 1024
    assert REG.execute("calculator", {"expression": "sqrt(16) + 1,000"}).output == 1004
    assert "division by zero" in REG.execute("calculator", {"expression": "1/0"}).error
    assert REG.execute("calculator", {"expression": "__import__('os')"}).error


def test_python_exec_ok_and_blocked():
    assert REG.execute("python_exec", {"code": "print(sum(range(10)))"}).output.strip() == "45"
    assert "not allowed" in REG.execute("python_exec", {"code": "import os\nprint(os.listdir())"}).error
    assert "not allowed" in REG.execute("python_exec", {"code": "open('x','w')"}).error
    err = REG.execute("python_exec", {"code": "print(1/0)"}).error
    assert "ZeroDivisionError" in err


def test_python_exec_timeout():
    res = REG.execute("python_exec", {"code": "while True: pass"})
    assert res.error and ("timed out" in res.error or "exited" in res.error)


def test_file_reader():
    assert "sales_q3.csv" in REG.execute("list_files", {}).output
    text = REG.execute("read_file", {"path": "recipe.txt", "start_line": 1, "end_line": 2}).output
    assert text.splitlines() == ["Harvest Loaf", "Serves 3."]
    assert "outside" in REG.execute("read_file", {"path": "../knowledge_base.json"}).error
    assert "not found" in REG.execute("read_file", {"path": "nope.txt"}).error


def test_integer_args_coerced_from_float():
    # Gemini sends numbers as floats; list slicing would crash without coercion.
    out = REG.execute("read_file", {"path": "recipe.txt", "start_line": 1.0, "end_line": 1.0}).output
    assert out == "Harvest Loaf"


def test_search():
    res = REG.execute("search", {"query": "Veltrix Dynamics"}).output
    assert res[0]["title"] == "Veltrix Dynamics"
    assert REG.execute("search", {"query": "zzzz qqqq"}).output[0]["title"] == "No results"


def test_unknown_tool_and_missing_args():
    assert "unknown tool" in REG.execute("teleport", {}).error
    assert "missing required" in REG.execute("calculator", {}).error
