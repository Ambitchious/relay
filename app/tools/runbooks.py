"""Runbook retrieval tool — points the user at the right document."""

from __future__ import annotations

from functools import lru_cache

from app.config import RUNBOOK_DIR
from app.retrieval import BM25Index, load_runbooks
from app.tools.registry import registry


@lru_cache(maxsize=1)
def _index() -> BM25Index:
    return BM25Index(load_runbooks(RUNBOOK_DIR))


def reset_index() -> None:
    """Drop the cached index. Used by tests that write runbooks on the fly."""
    _index.cache_clear()


@registry.register(
    name="search_runbooks",
    description=(
        "Search the platform runbook library for operational procedures, "
        "troubleshooting steps and known fixes. Use this whenever the user asks "
        "how to do something, or how to fix something that is broken."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural-language description of the problem or task.",
            },
            "top_k": {
                "type": "integer",
                "description": "How many runbooks to return (1-5). Default 2.",
            },
        },
        "required": ["query"],
    },
)
def search_runbooks(query: str, top_k: int = 2) -> str:
    hits = _index().search(query, top_k=max(1, min(int(top_k), 5)))
    if not hits:
        return "No runbook matched that query."

    blocks = []
    for doc, score in hits:
        # Excerpt rather than whole document: the model needs enough to decide
        # whether this is the right runbook and to quote the key step, and a
        # full document crowds out the rest of the context.
        excerpt = "\n".join(doc.body.strip().splitlines()[:18])
        blocks.append(f"[{doc.doc_id}] {doc.title} (score {score:.2f})\n{excerpt}")
    return "\n\n---\n\n".join(blocks)
