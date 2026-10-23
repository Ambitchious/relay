"""BM25 ranking behaviour."""

from __future__ import annotations

from app.retrieval import BM25Index, Document, load_runbooks, tokenize
from app.config import RUNBOOK_DIR


def _doc(doc_id: str, title: str, body: str) -> Document:
    return Document(doc_id, title, body, tokenize(f"{title} {body}"))


def test_tokenize_drops_stopwords_and_punctuation():
    assert tokenize("How do I fix the Spark job?") == ["do", "fix", "spark", "job"]


def test_ranks_the_matching_document_first():
    index = BM25Index(
        [
            _doc("spark", "Spark executor OOM", "executor heap memory overhead shuffle"),
            _doc("access", "Requesting access", "portal approver manager business reason"),
        ]
    )
    hits = index.search("executor out of memory heap")
    assert hits, "expected at least one hit"
    assert hits[0][0].doc_id == "spark"


def test_returns_nothing_when_no_term_matches():
    index = BM25Index([_doc("a", "Alpha", "one two three")])
    assert index.search("kubernetes helm chart") == []


def test_empty_index_is_safe():
    assert BM25Index([]).search("anything") == []


def test_respects_top_k():
    docs = [_doc(str(i), f"Doc {i}", "spark memory error") for i in range(5)]
    assert len(BM25Index(docs).search("spark memory", top_k=2)) == 2


def test_rare_terms_outrank_common_ones():
    """A term in every document carries no signal; a rare one decides the ranking."""
    index = BM25Index(
        [
            _doc("a", "A", "platform platform platform segments"),
            _doc("b", "B", "platform coordinator metastore failover"),
            _doc("c", "C", "platform notebook kernel volume"),
        ]
    )
    hits = index.search("platform metastore")
    assert hits[0][0].doc_id == "b"


def test_loads_the_real_runbook_corpus():
    docs = load_runbooks(RUNBOOK_DIR)
    assert len(docs) >= 4
    # Title comes from the first markdown heading, not the filename.
    titles = {d.title for d in docs}
    assert any("Spark" in t for t in titles)
