"""BM25 retrieval over the runbook corpus.

Implemented directly rather than pulled from a library for two reasons: the
corpus is small enough that an inverted index in memory is the right call, and
keeping the scoring visible makes the ranking debuggable when a runbook that
should match does not.

BM25 (Robertson/Sparck Jones) scores a document d for query q as:

    sum over terms t in q of
        IDF(t) * f(t,d) * (k1 + 1) / (f(t,d) + k1 * (1 - b + b * |d| / avgdl))

k1 damps the effect of repeated terms; b controls how much a long document is
penalised for its length.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

K1 = 1.5
B = 0.75

_TOKEN = re.compile(r"[a-z0-9_]+")
# Short function words carry no discriminating signal in a corpus this small.
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "has", "have", "how", "i", "if", "in", "is", "it", "its", "of", "on",
    "or", "that", "the", "then", "there", "these", "this", "to", "was",
    "what", "when", "where", "which", "why", "with", "you", "your",
}


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS]


@dataclass
class Document:
    doc_id: str
    title: str
    body: str
    tokens: list[str]


class BM25Index:
    def __init__(self, documents: list[Document]) -> None:
        self.documents = documents
        self.doc_freq: Counter[str] = Counter()
        self.term_freq: list[Counter[str]] = []
        self.lengths: list[int] = []

        for doc in documents:
            counts = Counter(doc.tokens)
            self.term_freq.append(counts)
            self.lengths.append(len(doc.tokens))
            self.doc_freq.update(counts.keys())

        self.n = len(documents)
        self.avgdl = (sum(self.lengths) / self.n) if self.n else 0.0

    def _idf(self, term: str) -> float:
        df = self.doc_freq.get(term, 0)
        if df == 0:
            return 0.0
        # Smoothed IDF; the +0.5 terms keep this positive for terms that appear
        # in more than half the corpus, which the raw formula does not.
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def search(self, query: str, top_k: int = 3) -> list[tuple[Document, float]]:
        terms = tokenize(query)
        if not terms or self.n == 0:
            return []

        scored: list[tuple[Document, float]] = []
        for idx, doc in enumerate(self.documents):
            counts = self.term_freq[idx]
            length = self.lengths[idx] or 1
            score = 0.0
            for term in terms:
                f = counts.get(term, 0)
                if not f:
                    continue
                denom = f + K1 * (1 - B + B * length / (self.avgdl or 1))
                score += self._idf(term) * f * (K1 + 1) / denom
            if score > 0:
                scored.append((doc, score))

        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:top_k]


def load_runbooks(directory: Path) -> list[Document]:
    """Read every markdown file in `directory` as one document.

    The first `# ` heading becomes the title; if there isn't one the filename
    stands in, so a runbook without a heading is still retrievable.
    """
    docs: list[Document] = []
    if not directory.exists():
        return docs

    for path in sorted(directory.glob("*.md")):
        body = path.read_text(encoding="utf-8")
        title = path.stem.replace("-", " ").title()
        for line in body.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
        docs.append(
            Document(
                doc_id=path.stem,
                title=title,
                body=body,
                tokens=tokenize(f"{title} {body}"),
            )
        )
    return docs
