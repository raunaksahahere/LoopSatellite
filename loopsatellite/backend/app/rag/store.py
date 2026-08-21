"""Local retrieval index over the source legal texts.

Deliberately a **lexical** (BM25) index rather than an embedding store. Three
reasons, in order of how much they matter here:

  1. Legal retrieval is citation retrieval. An officer asks about "filling of a
     wetland"; the statute says "filling". Exact-term matching is a strength,
     not a limitation, and BM25 will not quietly return a semantically-adjacent
     provision that says something different.
  2. Zero downloads at demo time. An embedding store means either an API call per
     query or an ONNX model fetched on first use. Both violate the golden rule.
  3. The retrieved unit is a verbatim quote with a citation, and quoting is
     exactly what we need — the notice drafter is forbidden from generating any
     regulatory claim from model memory.

The interface is the interface a vector store would have, so swapping in FAISS or
ChromaDB later means replacing this file and nothing else:
    build(chunks) -> None
    search(query, k) -> list[SearchHit]
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

INDEX_DIR = Path(__file__).resolve().parent / "index"
INDEX_PATH = INDEX_DIR / "index.json"

K1 = 1.5
B = 0.75

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "the", "a", "an", "of", "or", "and", "to", "in", "for", "on", "any", "by",
    "be", "is", "are", "as", "with", "that", "which", "shall", "may", "such",
    "this", "these", "under", "from", "at", "it", "its", "than", "not", "no",
}


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1]


@dataclass
class Chunk:
    id: str
    document: str      # e.g. "Wetlands (Conservation and Management) Rules, 2017"
    citation: str      # e.g. "Rule 4(2)(i)"
    text: str          # verbatim source text — this is what gets quoted
    source_path: str | None = None


@dataclass
class SearchHit:
    chunk: Chunk
    score: float


class LexicalIndex:
    def __init__(self) -> None:
        self.chunks: list[Chunk] = []
        self._tf: list[Counter[str]] = []
        self._lengths: list[int] = []
        self._df: Counter[str] = Counter()
        self._avg_len: float = 0.0

    # -- build ------------------------------------------------------------
    def build(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        self._tf = [Counter(tokenize(c.text + " " + c.citation)) for c in chunks]
        self._lengths = [sum(tf.values()) for tf in self._tf]
        self._df = Counter()
        for tf in self._tf:
            self._df.update(tf.keys())
        self._avg_len = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0

    # -- query ------------------------------------------------------------
    def search(self, query: str, k: int = 5, min_score: float = 0.0) -> list[SearchHit]:
        if not self.chunks:
            return []
        terms = tokenize(query)
        if not terms:
            return []
        n = len(self.chunks)
        scored: list[SearchHit] = []
        for i, chunk in enumerate(self.chunks):
            tf, length = self._tf[i], self._lengths[i]
            score = 0.0
            for term in terms:
                f = tf.get(term, 0)
                if not f:
                    continue
                df = self._df[term]
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                denom = f + K1 * (1 - B + B * length / (self._avg_len or 1))
                score += idf * (f * (K1 + 1)) / denom
            if score > min_score:
                scored.append(SearchHit(chunk=chunk, score=round(score, 4)))
        scored.sort(key=lambda h: -h.score)
        return scored[:k]

    # -- persistence ------------------------------------------------------
    def save(self, path: Path = INDEX_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump({"chunks": [asdict(c) for c in self.chunks]}, fh, ensure_ascii=False)

    @classmethod
    def load(cls, path: Path = INDEX_PATH) -> LexicalIndex:
        index = cls()
        if path.exists():
            with path.open(encoding="utf-8") as fh:
                payload = json.load(fh)
            index.build([Chunk(**c) for c in payload.get("chunks", [])])
        return index


_index: LexicalIndex | None = None


def get_index(*, refresh: bool = False) -> LexicalIndex:
    global _index
    if _index is None or refresh:
        _index = LexicalIndex.load()
    return _index


def is_populated() -> bool:
    return bool(get_index().chunks)


def documents() -> list[str]:
    return sorted({c.document for c in get_index().chunks})
