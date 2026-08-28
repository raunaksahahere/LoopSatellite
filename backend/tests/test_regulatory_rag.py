"""The notice drafter's guardrails.

The behaviour under test is the one that matters most in this codebase: a
regulatory claim must be retrieved and quoted, or not made at all.
"""

from __future__ import annotations

import pytest

from app.rag import store
from app.rag.ingest import _CitationContext
from app.services.detection import stl_esd
from app.services.llm import regulatory_rag


@pytest.fixture
def anomaly():
    return stl_esd.all_anomalies()[0]


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------
def test_index_contains_the_source_rules():
    assert "Wetlands (Conservation and Management) Rules, 2017" in store.documents()


def test_retrieval_finds_the_encroachment_prohibition(anomaly):
    citations = [h.chunk.citation for h in regulatory_rag.retrieve(anomaly)]
    assert "Rule 4(2)(i)" in citations, citations


def test_retrieved_quotes_are_verbatim_from_the_source(anomaly):
    source = (
        store.INDEX_PATH.parent.parent / "documents" / "wetlands_rules_2017.txt"
    ).read_text(encoding="utf-8")
    for hit in regulatory_rag.retrieve(anomaly):
        first_line = hit.chunk.text.splitlines()[0].strip()
        assert first_line in source, f"{hit.chunk.citation} is not verbatim source text"


def test_citations_carry_their_parent_rule():
    """A chunk labelled '(i)' is useless in a notice; it must read 'Rule 4(2)(i)'."""
    ctx = _CitationContext()
    assert ctx.resolve("4.") == "Rule 4"
    assert ctx.resolve("(2)") == "Rule 4(2)"
    assert ctx.resolve("(i)") == "Rule 4(2)(i)"
    assert ctx.resolve("5.") == "Rule 5"
    assert ctx.resolve("(1)") == "Rule 5(1)"


# ---------------------------------------------------------------------------
# The "nothing relevant found" path — required behaviour, not an edge case
# ---------------------------------------------------------------------------
def test_no_notice_is_drafted_when_the_index_is_empty(anomaly, monkeypatch):
    monkeypatch.setattr(store, "_index", store.LexicalIndex())
    monkeypatch.setattr(regulatory_rag, "is_populated", lambda: False)
    monkeypatch.setattr(regulatory_rag, "retrieve", lambda a: [])

    result = regulatory_rag.draft(anomaly)
    assert result["grounded"] is False
    assert result["draft"] is None
    assert "no source legal texts" in result["note"].lower()


def test_no_notice_is_drafted_when_nothing_clears_the_relevance_floor(anomaly, monkeypatch):
    monkeypatch.setattr(regulatory_rag, "retrieve", lambda a: [])
    result = regulatory_rag.draft(anomaly)
    assert result["grounded"] is False
    assert result["draft"] is None
    assert "no notice has been drafted" in result["note"].lower()


def test_relevance_floor_actually_filters(anomaly):
    """Every hit that survives must clear the floor — no near-misses slip through."""
    for hit in regulatory_rag.retrieve(anomaly):
        assert hit.score >= regulatory_rag.MIN_RELEVANCE_SCORE


# ---------------------------------------------------------------------------
# Citation verification
# ---------------------------------------------------------------------------
PROVISIONS = [{"citation": "Rule 4(2)(i)", "document": "X", "quote": "q", "score": 9.0}]


def test_verifier_allows_the_retrieved_citation_and_its_parents():
    text = "As provided in Rule 4(2)(i), and more generally Rule 4(2) and Rule 4 …"
    assert regulatory_rag._verify_citations(text, PROVISIONS) == set()


def test_verifier_catches_a_citation_that_was_never_retrieved():
    text = "Contrary to Rule 4(2)(i) and Section 15 of the Environment (Protection) Act, 1986."
    stray = regulatory_rag._verify_citations(text, PROVISIONS)
    assert any("15" in s for s in stray)


def test_a_draft_citing_un_retrieved_provisions_is_discarded(anomaly, monkeypatch):
    monkeypatch.setattr(regulatory_rag.client, "is_configured", lambda: True)
    monkeypatch.setattr(
        regulatory_rag.client,
        "complete",
        lambda *a, **k: "You have violated Rule 4(2)(i) and Section 33 of the Water Act, 1974.",
    )
    result = regulatory_rag.draft(anomaly)
    assert result["grounded"] is True
    assert result["llm_used"] is False, "a draft citing invented law must not be returned"
    assert "not retrieved" in result["note"]
    assert "Water Act" not in result["draft"]


def test_a_clean_draft_is_returned(anomaly, monkeypatch):
    monkeypatch.setattr(regulatory_rag.client, "is_configured", lambda: True)
    monkeypatch.setattr(
        regulatory_rag.client,
        "complete",
        lambda *a, **k: "Show-cause notice under Rule 4(2)(i). Please respond in 15 days.",
    )
    result = regulatory_rag.draft(anomaly)
    assert result["llm_used"] is True
    assert "Rule 4(2)(i)" in result["draft"]


# ---------------------------------------------------------------------------
# The template fallback
# ---------------------------------------------------------------------------
def test_template_notice_quotes_every_provision_it_relies_on(anomaly):
    result = regulatory_rag.draft(anomaly, addressee="Shri X", officer_name="A. Officer")
    assert result["grounded"] is True
    for provision in result["provisions"]:
        assert provision["citation"] in result["draft"]
        assert provision["quote"].splitlines()[0].strip()[:40] in result["draft"]


def test_template_notice_states_no_finding_of_breach(anomaly):
    draft = regulatory_rag.draft(anomaly)["draft"]
    assert "show cause" in draft.lower()
    assert "nothing in this notice is a finding" in draft.lower()
