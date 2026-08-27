"""Officer-facing copy carries no jargon — the test the README already claims.

The README says *"No 'MNDWI' or 'STL residual' in the copy — a test enforces
that."* Until now the only thing that existed was a single assertion buried in
`test_detection.py`, covering `stl_esd.explain()` and nothing else. Every other
sentence an officer reads — the area summaries, the radius answers, the report
prose, the job status lines, the whole frontend — was unguarded.

Two rules
---------
1. **No remote-sensing or statistics jargon in PRIMARY copy.** It belongs behind
   the "How this was detected" disclosure, in a `technical` field.
2. **It must actually be there.** Hiding the jargon is only honest if the detail
   remains available to anyone who wants it, so the technical fields are checked
   for the terms the plain copy is forbidden.

Scope, deliberately
-------------------
Comments, docstrings, identifiers and API field names are **exempt**. `residual_z`
is a column, `geojson` is a media type; neither reaches a screen. What is checked
is generated prose and frontend strings that a person reads.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services import areas as areas_service
from app.services.detection import conversion_classifier, mndwi, stl_esd
from app.services.llm import nl_query, report_writer

BACKEND = Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend" / "src"

#: Never in primary copy. An officer should not have to know any of these words.
JARGON = (
    "mndwi",
    "ndbi",
    "bsi",
    "stl",
    "esd",
    "seasonal-hybrid",
    "z-score",
    "residual",
    "decomposition",
    "sentinel-2",
    "geojson",
    "haversine",
    "geodesic",
    "asyncpg",
)

#: Words that contain a banned term but are ordinary English. Checked first.
ALLOWED_SUBSTRINGS = (
    "best",       # contains "esd"? no — kept as a guard for future additions
    "requested",
    "requests",
)


def offending(text: str) -> list[str]:
    lowered = text.lower()
    hits = []
    for term in JARGON:
        # Word-ish boundary so "bsi" doesn't fire inside "obsidian".
        if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", lowered):
            hits.append(term)
    return hits


# ---------------------------------------------------------------------------
# Generated prose
# ---------------------------------------------------------------------------
def _all_anomalies():
    return stl_esd.all_anomalies()


@pytest.mark.parametrize("anomaly", _all_anomalies(), ids=lambda a: a["id"])
def test_detection_explanation_is_plain(anomaly):
    explanation = stl_esd.explain(anomaly)
    plain = " ".join(
        [explanation["summary"], *explanation["reasons"], explanation["seasonality_note"]]
    )
    assert not offending(plain), f"{offending(plain)} in plain copy for {anomaly['id']}"


@pytest.mark.parametrize("anomaly", _all_anomalies(), ids=lambda a: a["id"])
def test_one_line_summary_is_plain(anomaly):
    assert not offending(stl_esd.summarise(anomaly))


@pytest.mark.parametrize("anomaly", _all_anomalies(), ids=lambda a: a["id"])
def test_conversion_explanation_is_plain(anomaly):
    conversion = conversion_classifier.explain(anomaly)
    assert not offending(conversion["label"] + " " + conversion["summary"])


def test_measurement_explanation_is_plain():
    assert not offending(mndwi.explain()["summary"])


@pytest.mark.parametrize(
    "question",
    [
        "problems around the East Kolkata Wetlands within 5 km",
        "what is going on around Haldia for 5km",
        "ponds in Ward 108 that lost more than 20% and never recovered",
        "anything wrong around Barrackpore for 10km",
    ],
)
def test_radius_answers_are_plain(question):
    """The sentence an officer reads back from a question is the most-read copy
    in the app, and until now nothing checked it."""
    result = nl_query.query(question)
    text = " ".join(filter(None, [result.get("summary"), result["interpretation"]]))
    assert not offending(text), f"{offending(text)} in the answer to {question!r}"


@pytest.mark.parametrize("scope", ["all", "anomaly"])
def test_report_prose_is_plain(scope):
    kwargs = {"anomaly_id": _all_anomalies()[0]["id"]} if scope == "anomaly" else {}
    facts = report_writer.collect_facts(scope, **kwargs)
    sections = report_writer.template_sections(facts)
    joined = " ".join(sections.values())
    assert not offending(joined), f"{offending(joined)} in the {scope} report"


def test_area_job_status_copy_is_plain():
    """The slow path's status lines are read while someone waits, so they matter."""

    class _Area:
        name, radius_km, status, progress, error = "Haldia", 5.0, "processing", "Working", None
        pond_count = anomaly_count = 0

    for status in ("pending", "processing", "ready", "failed"):
        _Area.status = status
        text = areas_service.headline(_Area) + " " + (areas_service.eta_note(_Area) or "")
        assert not offending(text), f"{offending(text)} in area status copy ({status})"


# ---------------------------------------------------------------------------
# …and the jargon must still be available behind the disclosure
# ---------------------------------------------------------------------------
def test_the_technical_detail_actually_exists():
    """Hiding jargon is only honest if the detail is one click away."""
    explanation = stl_esd.explain(_all_anomalies()[0])
    technical = explanation["technical"].lower()
    assert "stl" in technical and "esd" in technical

    measurement = mndwi.explain()["technical"]
    assert "MNDWI" in measurement


# ---------------------------------------------------------------------------
# Frontend strings
# ---------------------------------------------------------------------------
_COMMENT = re.compile(r"/\*.*?\*/|(?<!:)//[^\n]*", re.DOTALL)
_IMPORT = re.compile(r"^\s*import .*$", re.MULTILINE)
_STRING = re.compile(r"'([^'\\\n]*(?:\\.[^'\\\n]*)*)'|\"([^\"\\\n]*(?:\\.[^\"\\\n]*)*)\"")
_JSX_TEXT = re.compile(r">([^<>{}]{4,})<")


def user_visible_strings(source: str) -> list[str]:
    """Prose a person could read. Identifiers and paths are deliberately excluded.

    A string only counts as copy if it contains a space — `'pond-fill'` is a layer
    id, `'Structures now visible'` is a sentence. That heuristic is what keeps this
    test from crying wolf over every CSS class, and a guard that cries wolf gets
    switched off.
    """
    body = _IMPORT.sub("", _COMMENT.sub("", source))
    found = [m.group(1) or m.group(2) or "" for m in _STRING.finditer(body)]
    found += [m.group(1) for m in _JSX_TEXT.finditer(body)]
    return [s.strip() for s in found if " " in s.strip()]


def frontend_files() -> list[Path]:
    return sorted(
        p
        for p in FRONTEND.rglob("*.tsx")
        # types.ts / api.ts carry field names, not copy.
        if p.suffix == ".tsx"
    )


@pytest.mark.parametrize("path", frontend_files(), ids=lambda p: p.name)
def test_frontend_copy_is_plain(path: Path):
    for text in user_visible_strings(path.read_text(encoding="utf-8")):
        hits = offending(text)
        assert not hits, f"{hits} in {path.name}: {text[:90]!r}"


def test_the_extractor_finds_prose_and_ignores_identifiers():
    """Guards the guard. A silently-empty extractor would pass everything."""
    sample = """
      // MNDWI in a comment is fine
      const id = 'pond-fill'
      const copy = 'Water surface fell sharply'
      return <p>The dry season has been accounted for</p>
    """
    found = user_visible_strings(sample)
    assert "Water surface fell sharply" in found
    assert "The dry season has been accounted for" in found
    assert "pond-fill" not in found
    assert not any("comment" in f for f in found)
