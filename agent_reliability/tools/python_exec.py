"""Sandboxed-ish Python executor.

Defense in layers, but NOT a security boundary. Don't point it at untrusted models or code
you wouldn't run yourself:
  1. Static check: reject imports of os/subprocess/socket/etc. and calls to open/exec/eval.
  2. Separate process: `python -I` (isolated mode: no user site-packages, no env vars),
     in a fresh temporary working directory, with an almost-empty environment.
  3. Hard wall-clock timeout (kills the process).
  4. On POSIX, CPU-time and memory rlimits. On macOS, RLIMIT_AS is generally not
     enforced, so the memory limit is best-effort there; the CPU limit and timeout
     still apply. On Windows there are no rlimits, only the timeout.
  5. Output truncation so a runaway print can't blow up the context window.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import tempfile

from .base import ToolError, tool

TIMEOUT_S = 10
MAX_OUTPUT_CHARS = 4000
ALLOWED_IMPORTS = {
    "math", "statistics", "itertools", "functools", "collections", "datetime", "decimal",
    "fractions", "re", "json", "string", "random", "heapq", "bisect", "operator",
}
BLOCKED_CALLS = {"open", "exec", "eval", "compile", "__import__", "input", "breakpoint"}


def _static_check(code: str) -> None:
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise ToolError(f"SyntaxError: {e.msg} (line {e.lineno})") from None
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for m in mods:
                if m.split(".")[0] not in ALLOWED_IMPORTS:
                    raise ToolError(f"import of '{m}' is not allowed. Allowed: {sorted(ALLOWED_IMPORTS)}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALLS:
            raise ToolError(f"call to '{node.func.id}' is not allowed in the sandbox")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__") and node.attr != "__init__":
            raise ToolError("dunder attribute access is not allowed in the sandbox")


def _limit_resources() -> None:  # runs in the child process (POSIX only)
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (TIMEOUT_S, TIMEOUT_S))
    try:
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    except (ValueError, OSError):
        pass  # not supported (e.g. macOS)


def run_python(code: str) -> str:
    _static_check(code)
    with tempfile.TemporaryDirectory() as workdir:
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-c", code],
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_S,
                env={"PYTHONIOENCODING": "utf-8", "SYSTEMROOT": _systemroot()},
                preexec_fn=_limit_resources if sys.platform != "win32" else None,
            )
        except subprocess.TimeoutExpired:
            raise ToolError(f"execution timed out after {TIMEOUT_S}s") from None
    out = proc.stdout
    if proc.returncode != 0:
        err = proc.stderr.strip().splitlines()
        # The last traceback line is what matters; keep a little context.
        raise ToolError("\n".join(err[-3:])[:MAX_OUTPUT_CHARS] or f"exited with code {proc.returncode}")
    if not out.strip():
        return "(no output; use print() to see results)"
    if len(out) > MAX_OUTPUT_CHARS:
        out = out[:MAX_OUTPUT_CHARS] + f"\n...[truncated {len(out) - MAX_OUTPUT_CHARS} chars]"
    return out


def _systemroot() -> str:
    import os
    return os.environ.get("SYSTEMROOT", "")  # needed for Python to start on Windows


tool(
    name="python_exec",
    description=(
        "Run a short Python 3 program in a sandbox and return what it printed to stdout. "
        "You MUST print() the values you want to see. No file, network, or OS access. Allowed "
        f"imports: {', '.join(sorted(ALLOWED_IMPORTS))}. Timeout {TIMEOUT_S}s. Each call is a fresh "
        "process: variables do not persist between calls."
    ),
    parameters={
        "type": "object",
        "properties": {"code": {"type": "string", "description": "Python source code to execute."}},
        "required": ["code"],
    },
)(run_python)
