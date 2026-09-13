"""Mock search/lookup over a small local knowledge base (data/knowledge_base.json).

The knowledge base is deliberately FICTIONAL (invented companies, towns, people). The
model can't know these facts from pretraining, so a correct answer requires actually
calling the tool, and a confident answer given without searching is detectably made up.

Scoring is a simple keyword overlap (title matches weighted higher), which is
deterministic and good enough for a benchmark.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache

from .. import DATA_DIR
from .base import ToolError, tool

KB_PATH = DATA_DIR / "knowledge_base.json"
_STOP = {"the", "a", "an", "of", "in", "is", "what", "who", "for", "and", "to", "how", "many", "was", "does", "did"}


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOP}


@lru_cache(maxsize=1)
def _load() -> list[dict]:
    return json.loads(KB_PATH.read_text(encoding="utf-8"))


def search(query: str, top_k: int = 3) -> list[dict]:
    q = _tokens(query)
    if not q:
        raise ToolError("query has no searchable keywords")
    scored = []
    for doc in _load():
        title_t, body_t = _tokens(doc["title"]), _tokens(doc["text"])
        score = 3 * len(q & title_t) + len(q & body_t)
        if score > 0:
            scored.append((score, doc))
    scored.sort(key=lambda s: -s[0])
    results = [{"title": d["title"], "snippet": d["text"]} for _, d in scored[: max(1, min(top_k, 5))]]
    if not results:
        return [{"title": "No results", "snippet": f"No documents matched '{query}'. Try different keywords."}]
    return results


tool(
    name="search",
    description=(
        "Search the internal knowledge base (company, place, and people records) by keywords. "
        "Returns up to top_k results with title and snippet. Use specific names as keywords."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Keywords, e.g. 'Veltrix Dynamics founded'."},
            "top_k": {"type": "integer", "description": "Number of results (1-5, default 3)."},
        },
        "required": ["query"],
    },
)(search)
