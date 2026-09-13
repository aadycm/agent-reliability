"""Calculator: evaluates arithmetic safely by walking the AST (no eval())."""

from __future__ import annotations

import ast
import math
import operator

from .base import ToolError, tool

_BINOPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {
    "sqrt": math.sqrt, "log": math.log, "log10": math.log10, "exp": math.exp,
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "abs": abs, "round": round,
    "floor": math.floor, "ceil": math.ceil, "min": min, "max": max,
}
_CONSTS = {"pi": math.pi, "e": math.e}


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 1000:
            raise ToolError("exponent too large")
        return _BINOPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
        return _FUNCS[node.func.id](*[_eval(a) for a in node.args])
    if isinstance(node, ast.Name) and node.id in _CONSTS:
        return _CONSTS[node.id]
    raise ToolError(f"unsupported expression element: {ast.dump(node)[:60]}")


def calculate(expression: str) -> float | int:
    expr = expression.replace("^", "**").replace(",", "")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ToolError(f"could not parse expression: {e.msg}") from None
    try:
        result = _eval(tree)
    except ZeroDivisionError:
        raise ToolError("division by zero") from None
    if isinstance(result, float) and result.is_integer() and abs(result) < 1e15:
        return int(result)
    return round(result, 10) if isinstance(result, float) else result


tool(
    name="calculator",
    description=(
        "Evaluate an arithmetic expression and return the number. Supports + - * / // % ** "
        "and parentheses, plus sqrt, log, log10, exp, sin, cos, tan, abs, round, floor, ceil, "
        "min, max, pi, e. Example: '(1250 * 1.08) - 300'."
    ),
    parameters={
        "type": "object",
        "properties": {"expression": {"type": "string", "description": "The arithmetic expression."}},
        "required": ["expression"],
    },
)(calculate)
