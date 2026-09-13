"""Tool package. Importing a module registers its tools in DEFAULT_REGISTRY."""

from . import calculator, file_reader, python_exec, search  # noqa: F401  (registration side effects)
from .base import DEFAULT_REGISTRY, Tool, ToolError, ToolRegistry, ToolResult, tool

__all__ = ["DEFAULT_REGISTRY", "Tool", "ToolError", "ToolRegistry", "ToolResult", "tool", "get_default_registry"]


def get_default_registry() -> ToolRegistry:
    return DEFAULT_REGISTRY
