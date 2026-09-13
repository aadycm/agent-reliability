"""Tool abstraction and registry.

A tool is: a name, a description the model reads, a JSON-schema for its arguments,
and a plain Python function. To add a tool:

    from agent_reliability.tools.base import tool

    @tool(
        name="reverse",
        description="Reverse a string.",
        parameters={"type": "object",
                    "properties": {"text": {"type": "string", "description": "Text to reverse"}},
                    "required": ["text"]},
    )
    def reverse(text: str) -> str:
        return text[::-1]

then import the module in `tools/__init__.py`. The registry converts the schema to a
Gemini FunctionDeclaration automatically.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable


class ToolError(Exception):
    """Raised by a tool for an expected, user-facing failure (bad input, file not found)."""


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON schema (type: object)
    fn: Callable[..., Any]

    def declaration(self) -> dict:
        """Function declaration in the dict form accepted by google-generativeai."""
        return {"name": self.name, "description": self.description, "parameters": self.parameters}

    def coerce_args(self, args: dict) -> dict:
        """Gemini returns args as a protobuf Struct, where every number is a float.
        Cast back to int where the schema says integer, and drop unknown keys."""
        props = self.parameters.get("properties", {})
        out = {}
        for key, value in args.items():
            if key not in props:
                continue
            if props[key].get("type") == "integer" and isinstance(value, float) and value.is_integer():
                value = int(value)
            out[key] = value
        return out


@dataclass
class ToolResult:
    output: Any = None
    error: str | None = None
    duration_s: float = 0.0

    def to_model_payload(self) -> dict:
        """What the model sees as the function_response."""
        if self.error is not None:
            return {"error": self.error}
        return {"result": self.output}


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, t: Tool) -> Tool:
        if t.name in self._tools:
            raise ValueError(f"duplicate tool name: {t.name}")
        self._tools[t.name] = t
        return t

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def subset(self, names: list[str]) -> "ToolRegistry":
        reg = ToolRegistry()
        for n in names:
            reg.register(self._tools[n])
        return reg

    def declarations(self) -> list[dict]:
        return [t.declaration() for t in self._tools.values()]

    def execute(self, name: str, args: dict) -> ToolResult:
        """Run a tool. Never raises: every failure becomes an error string the model
        can read and react to (and that the failure analysis can find in the trace)."""
        start = time.perf_counter()
        t = self._tools.get(name)
        if t is None:
            return ToolResult(error=f"unknown tool '{name}'. Available: {', '.join(self._tools)}")
        missing = [r for r in t.parameters.get("required", []) if r not in args]
        if missing:
            return ToolResult(error=f"missing required argument(s): {', '.join(missing)}",
                              duration_s=time.perf_counter() - start)
        try:
            output = t.fn(**t.coerce_args(args))
            return ToolResult(output=output, duration_s=time.perf_counter() - start)
        except ToolError as e:
            return ToolResult(error=str(e), duration_s=time.perf_counter() - start)
        except Exception as e:  # unexpected bug in a tool: still don't crash the agent
            return ToolResult(error=f"{type(e).__name__}: {e}", duration_s=time.perf_counter() - start)


# Global default registry that the @tool decorator populates.
DEFAULT_REGISTRY = ToolRegistry()


def tool(name: str, description: str, parameters: dict, registry: ToolRegistry = DEFAULT_REGISTRY):
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        registry.register(Tool(name=name, description=description, parameters=parameters, fn=fn))
        return fn
    return decorator
