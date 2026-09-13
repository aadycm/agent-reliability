"""File/text reader, confined to data/files/ (path traversal is rejected)."""

from __future__ import annotations

from pathlib import Path

from .. import DATA_DIR
from .base import ToolError, tool

FILES_DIR = DATA_DIR / "files"
MAX_CHARS = 6000


def _resolve(path: str) -> Path:
    candidate = (FILES_DIR / path).resolve()
    if FILES_DIR.resolve() not in candidate.parents and candidate != FILES_DIR.resolve():
        raise ToolError("access denied: path is outside the readable files directory")
    return candidate


def list_files() -> list[str]:
    return sorted(str(p.relative_to(FILES_DIR)).replace("\\", "/") for p in FILES_DIR.rglob("*") if p.is_file())


def read_file(path: str, start_line: int = 1, end_line: int | None = None) -> str:
    p = _resolve(path)
    if not p.is_file():
        raise ToolError(f"file not found: '{path}'. Use list_files to see available files.")
    lines = p.read_text(encoding="utf-8").splitlines()
    start = max(start_line, 1)
    end = len(lines) if end_line is None else min(end_line, len(lines))
    text = "\n".join(lines[start - 1:end])
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + f"\n...[truncated; file has {len(lines)} lines, use start_line/end_line]"
    return text


tool(
    name="list_files",
    description="List the text files that read_file can open.",
    parameters={"type": "object", "properties": {}},
)(list_files)

tool(
    name="read_file",
    description=(
        "Read a text file (by the relative path shown in list_files). Optionally read only "
        "lines start_line..end_line (1-indexed, inclusive)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path, e.g. 'sales_q3.csv'."},
            "start_line": {"type": "integer", "description": "First line to read (default 1)."},
            "end_line": {"type": "integer", "description": "Last line to read (default end of file)."},
        },
        "required": ["path"],
    },
)(read_file)
