"""Chunk the source legal texts into citable provisions and build the index.

Each chunk keeps a **citation** and the **verbatim text** of one provision,
because the notice drafter is only ever allowed to quote — never to state a
regulatory claim from the model's own memory.

Source files live in app/rag/documents/ as plain text or Markdown, one document
per file, with a small front-matter header:

    # DOCUMENT: Wetlands (Conservation and Management) Rules, 2017
    # SOURCE: https://...

    4. Restrictions of activities in wetlands.
    (1) ...
    (2) The following activities shall be prohibited ...

Chunking splits on numbered provisions — `4.`, `4(1)`, `(2)(i)`, `Rule 4`,
`Section 12`, `Para 5` — and falls back to paragraph splitting for anything
unnumbered. If a document is missing, nothing is faked: the store simply has
fewer chunks, and /api/llm/notice returns `grounded: false`.

Usage:
    python -m app.rag.ingest
    python -m app.rag.ingest --show "filling of wetland"
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from app.rag.store import Chunk, LexicalIndex, get_index

DOCUMENTS_DIR = Path(__file__).resolve().parent / "documents"

_HEADER_DOC = re.compile(r"^#\s*DOCUMENT:\s*(.+)$", re.MULTILINE)
_HEADER_SRC = re.compile(r"^#\s*SOURCE:\s*(.+)$", re.MULTILINE)

# Start of a numbered provision at the beginning of a line.
_PROVISION_RE = re.compile(
    r"^(?P<cite>"
    r"(?:Rule|Section|Clause|Para(?:graph)?|Article)\s+\d+[A-Za-z]?(?:\s*\([^)]{1,6}\))*"
    r"|\d+[A-Za-z]?\.(?:\s*\([^)]{1,6}\))*"
    r"|\(\d+\)(?:\s*\([^)]{1,6}\))*"
    r"|\([ivxlcdm]+\)"
    r")\s+",
    re.MULTILINE,
)

MIN_CHUNK_CHARS = 60
MAX_CHUNK_CHARS = 2000


def parse_document(path: Path) -> list[Chunk]:
    raw = path.read_text(encoding="utf-8")
    doc_match = _HEADER_DOC.search(raw)
    document = doc_match.group(1).strip() if doc_match else path.stem.replace("_", " ")
    body = _HEADER_DOC.sub("", raw)
    body = _HEADER_SRC.sub("", body).strip()

    matches = list(_PROVISION_RE.finditer(body))
    chunks: list[Chunk] = []

    if matches:
        context = _CitationContext()
        for i, m in enumerate(matches):
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
            text = body[start:end].strip()
            citation = context.resolve(m.group("cite"))
            if len(text) < MIN_CHUNK_CHARS:
                # Too short to be worth retrieving on its own, but it still moves
                # the citation context on — e.g. a bare "4." heading line.
                continue
            for j, piece in enumerate(_split_long(text)):
                suffix = f"#{j}" if j else ""
                chunks.append(
                    Chunk(
                        id=f"{path.stem}:{citation}{suffix}",
                        document=document,
                        citation=citation,
                        text=piece,
                        source_path=str(path.relative_to(DOCUMENTS_DIR.parent)),
                    )
                )
    else:
        for i, para in enumerate(p.strip() for p in body.split("\n\n")):
            if len(para) < MIN_CHUNK_CHARS:
                continue
            chunks.append(
                Chunk(
                    id=f"{path.stem}:para{i}",
                    document=document,
                    citation=f"para {i + 1}",
                    text=para,
                    source_path=str(path.relative_to(DOCUMENTS_DIR.parent)),
                )
            )
    return chunks


_TOP_LEVEL = re.compile(r"^(?:Rule|Section|Clause|Para(?:graph)?|Article)?\s*(\d+[A-Za-z]?)\.?$")
_SUBRULE = re.compile(r"^\((\d+)\)$")
_ITEM = re.compile(r"^\(([ivxlcdm]+|[a-z])\)$", re.IGNORECASE)


class _CitationContext:
    """Turns a document's flat sequence of markers into full citations.

    A gazette body reads `4.` … `(2)` … `(i)`, and a chunk labelled `(i)` is
    worthless in a notice. This tracks the enclosing rule and sub-rule so that
    clause becomes `Rule 4(2)(i)`, which is a thing an officer can actually cite.
    """

    def __init__(self, kind: str = "Rule") -> None:
        self.kind = kind
        self.rule: str | None = None
        self.sub: str | None = None

    def resolve(self, marker: str) -> str:
        marker = " ".join(marker.split()).strip()

        # A marker may itself be compound, e.g. "4(2)" or "Rule 4 (2)".
        head, *tail = re.findall(r"[A-Za-z]+\s*\d+[A-Za-z]?|\d+[A-Za-z]?\.?|\([^)]{1,6}\)", marker)

        if top := _TOP_LEVEL.match(head.strip()):
            self.rule, self.sub = top.group(1), None
            kind = head.strip().split()[0] if head.strip()[0].isalpha() else self.kind
            self.kind = kind.capitalize() if kind[0].isalpha() else self.kind
            citation = f"{self.kind} {self.rule}"
            for part in tail:
                citation += part
                if _SUBRULE.match(part):
                    self.sub = part.strip("()")
            return citation

        if _SUBRULE.match(head):
            self.sub = head.strip("()")
            base = f"{self.kind} {self.rule}" if self.rule else ""
            return (base + head + "".join(tail)) or head

        if _ITEM.match(head):
            base = f"{self.kind} {self.rule}" if self.rule else ""
            if self.sub:
                base += f"({self.sub})"
            return (base + head + "".join(tail)) or head

        return marker.rstrip(". ")


def _split_long(text: str) -> list[str]:
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]
    pieces, current = [], ""
    for para in text.split("\n"):
        if len(current) + len(para) + 1 > MAX_CHUNK_CHARS and current:
            pieces.append(current.strip())
            current = ""
        current += para + "\n"
    if current.strip():
        pieces.append(current.strip())
    return pieces


def ingest() -> LexicalIndex:
    DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
    paths = sorted(
        p for p in DOCUMENTS_DIR.iterdir() if p.suffix.lower() in (".txt", ".md") and p.name != "README.md"
    )
    chunks: list[Chunk] = []
    for path in paths:
        found = parse_document(path)
        print(f"  {path.name}: {len(found)} provisions")
        chunks.extend(found)

    index = LexicalIndex()
    index.build(chunks)
    index.save()
    return index


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--show", help="run a test query against the freshly built index")
    args = ap.parse_args()

    print(f"Ingesting from {DOCUMENTS_DIR}")
    index = ingest()
    if not index.chunks:
        print(
            "\nNo provisions ingested. The notice endpoint will honestly report that no\n"
            "relevant provision was found rather than drafting from model memory.\n"
            f"Add the source texts to {DOCUMENTS_DIR} — see its README.md."
        )
        return
    print(f"\nIndexed {len(index.chunks)} provisions across {len({c.document for c in index.chunks})} document(s).")

    if args.show:
        print(f"\nQuery: {args.show!r}")
        for hit in get_index(refresh=True).search(args.show, k=5):
            print(f"  [{hit.score:6.2f}] {hit.chunk.document} — {hit.chunk.citation}")
            print(f"          {hit.chunk.text[:140].replace(chr(10), ' ')}…")


if __name__ == "__main__":
    main()
