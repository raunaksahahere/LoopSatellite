"""Feature 1 — corroborate a flagged anomaly against the documentary record.

The statistics have already decided this pond shrank. This module does not
revisit that. It goes looking for whatever else was written down about that
place in that window — a news report, a construction notice, a tender, a
municipal minute — and returns a **structured list of findings with links**, not
prose the officer has to take on trust.

Every finding carries a `relevance` the model had to commit to, including
"unrelated". A search that turns up nothing returns an empty list and says so;
it never pads the answer.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.services.llm import client
from app.services.llm.search import SearchUnavailable, web_search

logger = logging.getLogger(__name__)

SYSTEM = """You are an evidence researcher for a wetlands regulator in West Bengal, India.

You are given a water-loss event that a statistical pipeline has ALREADY confirmed
from satellite data. Your job is NOT to judge whether the water loss happened —
that is settled and not yours to question. Your job is to find the documentary
trail around it.

Return ONLY JSON of this shape:
{"findings": [{"title": str, "url": str|null, "source": str|null,
               "published": "YYYY-MM-DD"|null, "snippet": str,
               "relevance": "direct"|"contextual"|"unrelated",
               "why_relevant": str}]}

Rules you must follow:
- Every finding must come from the search results provided. Never invent a
  source, a URL, a date or a quotation. If you are unsure of a URL, use null.
- "direct" means the item is about this specific site or an adjacent parcel in
  this window. "contextual" means it is about the area or the wider pattern but
  not this pond. "unrelated" means it surfaced in the search but does not bear
  on the case — say so plainly rather than dropping it.
- `snippet` must be text from the result, not your summary of it.
- If nothing in the results bears on the case, return {"findings": []}.
"""


def build_query(anomaly: dict[str, Any], extra_terms: list[str] | None = None) -> str:
    """Deterministic search query — the LLM does not get to choose where we look."""
    parts = ["East Kolkata Wetlands"]
    if anomaly.get("mouza"):
        parts.append(anomaly["mouza"])
    if anomaly.get("ward"):
        parts.append(anomaly["ward"])
    window = f"{anomaly['window_start'][:7]} to {anomaly['window_end'][:7]}"
    parts += ["pond filling OR encroachment OR construction OR land filling", window]
    if extra_terms:
        parts += list(extra_terms)[:8]
    return " ".join(parts)


def corroborate(anomaly: dict[str, Any], extra_terms: list[str] | None = None) -> dict[str, Any]:
    query = build_query(anomaly, extra_terms)

    if not client.is_configured():
        return {
            "anomaly_id": anomaly["id"],
            "query_used": query,
            "findings": [],
            "searched": False,
            "note": (
                "Evidence search is switched off because no language model is configured. "
                "Set OPENROUTER_API_KEY and OPENROUTER_MODEL to enable it. "
                "The water-loss finding itself does not depend on this step."
            ),
        }

    try:
        results, used_online = web_search(query)
    except SearchUnavailable as exc:
        return {
            "anomaly_id": anomaly["id"],
            "query_used": query,
            "findings": [],
            "searched": False,
            "note": f"No web search provider is available ({exc}).",
        }

    context = _format_context(anomaly, results)
    try:
        payload = client.complete_json(
            [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": context},
            ],
            temperature=0.0,
            max_tokens=1600,
            online=used_online,
        )
    except client.LLMError as exc:
        logger.warning("evidence corroboration failed: %s", exc)
        return {
            "anomaly_id": anomaly["id"],
            "query_used": query,
            "findings": [],
            "searched": True,
            "note": f"The evidence search could not be completed ({exc}). Try again.",
        }

    findings = _clean(payload.get("findings", []) if isinstance(payload, dict) else [])
    return {
        "anomaly_id": anomaly["id"],
        "query_used": query,
        "findings": findings,
        "searched": True,
        "note": None
        if findings
        else (
            "Nothing in the public record was found for this pond and window. "
            "That is common for small parcels and is not evidence that the loss did "
            "not happen — the satellite measurement stands on its own."
        ),
    }


def _format_context(anomaly: dict[str, Any], results: list[dict[str, Any]]) -> str:
    facts = (
        f"Pond: {anomaly.get('pond_name') or anomaly['pond_id']}\n"
        f"Mouza: {anomaly.get('mouza') or 'unknown'}\n"
        f"Ward / block: {anomaly.get('ward') or 'unknown'}\n"
        f"Coordinates: {anomaly.get('centroid_lat')}, {anomaly.get('centroid_lon')}\n"
        f"Window: {anomaly['window_start']} to {anomaly['window_end']}\n"
        f"Measured loss: {anomaly['loss_pct']}% of seasonally expected water surface "
        f"({anomaly.get('loss_ha')} ha)\n"
        f"Recovered since: {'yes' if anomaly['recovered'] else 'no'}\n"
        f"Surface now reads as: {anomaly.get('conversion_label') or 'not assessed'}\n"
    )
    if results:
        blocks = "\n\n".join(
            f"[{i + 1}] {r.get('title')}\nURL: {r.get('url')}\nDate: {r.get('published')}\n{r.get('snippet')}"
            for i, r in enumerate(results)
        )
    else:
        blocks = (
            "(No pre-fetched results — use your own web search tool if you have one, "
            "and report only what you actually retrieve.)"
        )
    return f"CONFIRMED WATER-LOSS EVENT\n{facts}\nSEARCH RESULTS\n{blocks}"


def _clean(raw: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        relevance = item.get("relevance")
        if relevance not in ("direct", "contextual", "unrelated"):
            relevance = "contextual"
        out.append(
            {
                "title": str(item["title"])[:300],
                "url": item.get("url") or None,
                "source": item.get("source") or None,
                "published": item.get("published") or None,
                "snippet": str(item.get("snippet") or "")[:1200],
                "relevance": relevance,
                "why_relevant": str(item.get("why_relevant") or "")[:600],
            }
        )
    order = {"direct": 0, "contextual": 1, "unrelated": 2}
    out.sort(key=lambda f: order[f["relevance"]])
    return out


def provider_note() -> str:
    return f"search_provider={settings.search_provider}"
