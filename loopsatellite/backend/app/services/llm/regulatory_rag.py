"""Feature 2 — ground the case in law, then draft the notice.

The hard rule, enforced structurally rather than by asking nicely:

    Every regulatory claim must be RETRIEVED and QUOTED with a citation.
    Nothing may be generated from the model's memory.
    If retrieval finds nothing relevant, no notice is drafted at all.

How that is enforced:

  1. `retrieve()` runs a deterministic query against the local index of source
     legal texts and applies a score floor. The LLM has no say in what comes back.
  2. If the floor is not cleared, `draft()` returns `grounded=False`, `draft=None`
     and an explanation. There is no code path that reaches the model without
     provisions in hand.
  3. The prompt hands the model the retrieved quotes and forbids it from citing
     anything else. Afterwards `_verify_citations()` re-checks the produced text:
     any citation in the draft that is not in the retrieved set means the draft is
     rejected, not returned with a warning.

A notice is a document that can start an enforcement action against a real
person. It is worth being this strict about.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

from app.rag.store import SearchHit, get_index, is_populated
from app.services.llm import client

logger = logging.getLogger(__name__)

# BM25 floor. Below this, a "hit" is term coincidence rather than a provision on
# point, and we would rather cite nothing than cite something adjacent.
MIN_RELEVANCE_SCORE = 6.0
TOP_K = 6
MAX_PROVISIONS = 4

DISCLAIMER = (
    "Draft only. Generated from satellite measurements and the provisions quoted above. "
    "It has not been checked against the site record, ownership, or any permission that "
    "may have been granted, and it carries no legal effect until an authorised officer "
    "has verified the facts and issued it."
)

SYSTEM = """You draft show-cause notices for a wetlands regulator in West Bengal, India.

You will be given (a) a water-loss event confirmed from satellite data, and
(b) the verbatim text of statutory provisions that were retrieved from the source
instruments for you.

ABSOLUTE RULES:
1. You may cite ONLY the provisions supplied to you, using exactly the citation
   strings given. Do not cite any other rule, section, act, judgment or authority,
   even if you are confident it exists. If a provision you want is not in the list,
   write around its absence.
2. Do not paraphrase a provision as though it were its text. When you state what
   the law requires, quote it.
3. Do not assert any fact that is not in the event data — no ownership, no names,
   no dates of construction, no intent. Where the notice needs a fact you were not
   given, write a bracketed blank like [name of occupier] for the officer to fill.
4. Do not state a conclusion of law. The notice asks the recipient to show cause;
   it does not find them in breach.

Format — plain text, this structure, no markdown:
  reference line, date line
  addressee block
  Subject line
  1. The facts observed (satellite measurement, dates, area)
  2. The provisions engaged (quoted, with citation)
  3. What the recipient is required to do, and by when
  4. Signature block
Keep it under 450 words.
"""


def build_query(anomaly: dict[str, Any]) -> str:
    """Deterministic retrieval query, built from the event, not from a model."""
    terms = [
        "wetland conversion non-wetland uses encroachment prohibited",
        "restrictions of activities in wetlands",
    ]
    signal = anomaly.get("conversion_signal")
    if signal == "built_up":
        terms.append("construction of a permanent nature within fifty metres")
    elif signal == "bare":
        terms.append("solid waste dumping land filling")
    if not anomaly.get("recovered"):
        terms.append("change in ecological character wise use")
    return " ".join(terms)


def retrieve(anomaly: dict[str, Any]) -> list[SearchHit]:
    if not is_populated():
        return []
    hits = get_index().search(build_query(anomaly), k=TOP_K)
    return [h for h in hits if h.score >= MIN_RELEVANCE_SCORE][:MAX_PROVISIONS]


def draft(
    anomaly: dict[str, Any],
    *,
    addressee: str | None = None,
    officer_name: str | None = None,
    officer_designation: str | None = None,
) -> dict[str, Any]:
    hits = retrieve(anomaly)

    if not hits:
        return {
            "anomaly_id": anomaly["id"],
            "grounded": False,
            "provisions": [],
            "draft": None,
            "disclaimer": DISCLAIMER,
            "llm_used": False,
            "note": _no_grounding_note(),
        }

    provisions = [
        {
            "document": h.chunk.document,
            "citation": h.chunk.citation,
            "quote": h.chunk.text,
            "score": h.score,
            "relevance_note": None,
        }
        for h in hits
    ]

    if not client.is_configured():
        return {
            "anomaly_id": anomaly["id"],
            "grounded": True,
            "provisions": provisions,
            "draft": _template_draft(anomaly, provisions, addressee, officer_name, officer_designation),
            "disclaimer": DISCLAIMER,
            "llm_used": False,
            "note": (
                "No language model is configured, so this notice was assembled from a "
                "fixed template. The provisions quoted are the ones retrieved from the "
                "source instruments and are unaffected."
            ),
        }

    prompt = _build_prompt(anomaly, provisions, addressee, officer_name, officer_designation)
    try:
        text = client.complete(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=1400,
        )
    except client.LLMError as exc:
        logger.warning("notice drafting failed: %s", exc)
        return {
            "anomaly_id": anomaly["id"],
            "grounded": True,
            "provisions": provisions,
            "draft": _template_draft(anomaly, provisions, addressee, officer_name, officer_designation),
            "disclaimer": DISCLAIMER,
            "llm_used": False,
            "note": f"The model call failed ({exc}); fell back to the fixed template.",
        }

    stray = _verify_citations(text, provisions)
    if stray:
        logger.warning("rejecting draft citing un-retrieved provisions: %s", stray)
        return {
            "anomaly_id": anomaly["id"],
            "grounded": True,
            "provisions": provisions,
            "draft": _template_draft(anomaly, provisions, addressee, officer_name, officer_designation),
            "disclaimer": DISCLAIMER,
            "llm_used": False,
            "note": (
                "The drafted notice cited provisions that were not retrieved from the "
                f"source texts ({', '.join(sorted(stray))}), so it was discarded and the "
                "fixed template used instead. Nothing in this notice is quoted from model "
                "memory."
            ),
        }

    return {
        "anomaly_id": anomaly["id"],
        "grounded": True,
        "provisions": provisions,
        "draft": text,
        "disclaimer": DISCLAIMER,
        "llm_used": True,
        "note": None,
    }


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------
# Anything that looks like a statutory citation in the produced text.
_CITATION_RE = re.compile(
    r"\b(?:Rule|Section|Sec\.|Clause|Article|Para(?:graph)?)\s*\d+[A-Za-z]?(?:\s*\([^)]{1,6}\))*",
    re.IGNORECASE,
)


def _normalise(citation: str) -> str:
    return re.sub(r"[\s.]", "", citation).lower()


def _verify_citations(text: str, provisions: list[dict[str, Any]]) -> set[str]:
    """Return citations appearing in the draft that were never retrieved.

    A retrieved `Rule 4(2)(i)` licenses a reference to `Rule 4` or `Rule 4(2)` —
    those are its parents and their text was in front of the model. It does not
    license `Rule 17`, which the model would only know from memory.
    """
    allowed: set[str] = set()
    for p in provisions:
        norm = _normalise(p["citation"])
        allowed.add(norm)
        # every prefix that ends at a bracket boundary
        for i, ch in enumerate(norm):
            if ch == "(":
                allowed.add(norm[:i])
        allowed.add(re.sub(r"\(.*", "", norm))

    return {
        found.strip()
        for found in _CITATION_RE.findall(text)
        if _normalise(found) not in allowed
    }


def _no_grounding_note() -> str:
    if not is_populated():
        return (
            "No source legal texts have been ingested, so there is nothing to cite. "
            "Add the instruments to backend/app/rag/documents/ and run "
            "`python -m app.rag.ingest`. No notice has been drafted — this tool will not "
            "write a regulatory claim it cannot quote from a source."
        )
    return (
        "No provision in the ingested source texts was a close enough match to this "
        "event to cite. No notice has been drafted. This is deliberate: a notice is "
        "only ever drafted around a provision that was retrieved and quoted, never one "
        "recalled from the model's training. Review the event manually, or add the "
        "relevant instrument to the document set."
    )


# ---------------------------------------------------------------------------
# Prompt and deterministic template
# ---------------------------------------------------------------------------
def _facts_block(anomaly: dict[str, Any]) -> str:
    return (
        f"Pond reference: {anomaly['pond_id']}"
        f"{' (' + anomaly['pond_name'] + ')' if anomaly.get('pond_name') else ''}\n"
        f"Mouza: {anomaly.get('mouza') or '[mouza]'}\n"
        f"Ward / block: {anomaly.get('ward') or '[ward]'}\n"
        f"Approximate coordinates: {anomaly.get('centroid_lat')}, {anomaly.get('centroid_lon')}\n"
        f"Site: East Kolkata Wetlands, Ramsar site no. 1208\n"
        f"Period observed: {anomaly['window_start']} to {anomaly['window_end']}\n"
        f"Water surface expected for the season: "
        f"{(anomaly.get('baseline_area_m2') or 0) / 10000:.2f} ha\n"
        f"Water surface actually observed: "
        f"{(anomaly.get('observed_area_m2') or 0) / 10000:.2f} ha\n"
        f"Reduction: {anomaly['loss_pct']:.0f} per cent "
        f"({anomaly.get('loss_ha', 0):.2f} ha)\n"
        f"Seasonal variation already accounted for: yes\n"
        f"Recovered since: {'yes' if anomaly['recovered'] else 'no'}\n"
        f"Surface condition now: {anomaly.get('conversion_label') or 'not assessed'}\n"
    )


def _build_prompt(
    anomaly: dict[str, Any],
    provisions: list[dict[str, Any]],
    addressee: str | None,
    officer_name: str | None,
    officer_designation: str | None,
) -> str:
    quoted = "\n\n".join(
        f"[{p['citation']}] — {p['document']}\n\"{p['quote']}\"" for p in provisions
    )
    return (
        f"EVENT (confirmed by satellite measurement, not by you)\n{_facts_block(anomaly)}\n"
        f"ADDRESSEE: {addressee or '[name of occupier / owner — unknown]'}\n"
        f"ISSUING OFFICER: {officer_name or '[officer name]'}, "
        f"{officer_designation or '[designation]'}\n"
        f"DATE: {date.today().isoformat()}\n\n"
        f"PROVISIONS RETRIEVED FOR YOU — cite only these:\n\n{quoted}\n"
    )


def _template_draft(
    anomaly: dict[str, Any],
    provisions: list[dict[str, Any]],
    addressee: str | None,
    officer_name: str | None,
    officer_designation: str | None,
) -> str:
    """Fully deterministic notice. Used when no model is available, or as the
    fallback when a model draft fails verification."""
    quoted = "\n\n".join(
        f'   {p["citation"]} of the {p["document"]} provides:\n   "{p["quote"]}"'
        for p in provisions
    )
    return f"""Ref: LS/{anomaly['id']}
Date: {date.today().isoformat()}

To,
{addressee or '[Name and address of the occupier / owner]'}

Subject: Show-cause notice — apparent reduction of water surface within the East
Kolkata Wetlands (Ramsar site no. 1208)

1. FACTS OBSERVED

{_facts_block(anomaly)}
   These figures are derived from Sentinel-2 satellite observations. The normal
   seasonal rise and fall of this water body has been accounted for before the
   above reduction was recorded.

2. PROVISIONS ENGAGED

{quoted}

3. ACTION REQUIRED

   You are hereby called upon to show cause, within 15 (fifteen) days of receipt
   of this notice, as to why action should not be initiated in respect of the
   reduction described in paragraph 1. You may produce any permission, order or
   record on which you rely, and you may seek a personal hearing.

   Nothing in this notice is a finding that any provision has been contravened.

4.

   {officer_name or '[Officer name]'}
   {officer_designation or '[Designation]'}
   [Office]
"""
