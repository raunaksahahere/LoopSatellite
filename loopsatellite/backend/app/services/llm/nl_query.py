"""Feature 3 — natural-language query over already-computed results.

    "which ponds in Ward 108 lost more than 20% and never recovered"
    "find me the places with problems around Haldia for 5km"

The LLM's entire job is to turn that sentence into a structured filter. It then
steps aside: the filter runs against precomputed data in Python, and the numbers
that come back were never in the model's context. The model cannot change a loss
figure, a confidence, a distance, or which ponds match — only which question was
asked. The parsed filter is returned to the UI and shown to the officer, so a
misreading is visible rather than silent.

This is the **fast path**. It answers from results computed earlier and never
calls Earth Engine. Asking about a place nobody has monitored yet returns an
honest "nothing has been processed here", not a multi-minute wait — starting that
work is a separate, explicit action (see services/areas.py).

A deterministic parser runs first and handles the common shapes with no model at
all. The LLM is consulted only for what the patterns miss, and skipped entirely
when it isn't configured.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.core.geo import MAX_RADIUS_KM, MIN_RADIUS_KM
from app.rag import gazetteer
from app.services.detection import repository, stl_esd
from app.services.llm import client

logger = logging.getLogger(__name__)

FILTER_KEYS = (
    "place",
    "radius_km",
    "ward",
    "mouza",
    "min_loss_pct",
    "max_loss_pct",
    "recovered",
    "conversion_signal",
    "confidence_band",
    "min_confidence",
    "since",
    "until",
)

# Used when a place is named but no distance is. Reported back as an assumption.
DEFAULT_RADIUS_KM = 10.0

SYSTEM = """You convert an officer's question about wetland water-loss records into a filter.

You are NOT answering the question. You never see the records and you must never
guess how many there are, where they are, or what they say. You only decide what
was asked.

Return ONLY JSON:
{"filter": {...}, "interpretation": str, "unparsed": [str]}

Allowed keys in "filter" (omit any the question does not constrain):
  place             string — a settlement or landmark name, e.g. "Haldia"
  radius_km         number 0.1-50, the distance around that place
  ward              string, e.g. "Ward 108" — must match one of the known wards
  mouza             string                  — must match one of the known mouzas
  min_loss_pct      number 0-100
  max_loss_pct      number 0-100
  recovered         true | false   (false = "never recovered", "still dry")
  conversion_signal "built_up" | "bare" | "none"
  confidence_band   "high" | "medium" | "low"
  min_confidence    number 0-1
  since             "YYYY-MM-DD"   (event started on or after)
  until             "YYYY-MM-DD"   (event started on or before)

Put a place name in "place" even if you do not recognise it — resolving it is not
your job, and inventing coordinates is forbidden.

"interpretation" is one plain sentence restating the filter for the officer to
check — no jargon, and no numbers you were not given.
"unparsed" lists anything the filter cannot express (a request to sort, a
question about something not listed above). Be honest; an empty list when the
question asked for more is worse than admitting it.
"""


# ---------------------------------------------------------------------------
# Deterministic first pass
# ---------------------------------------------------------------------------
_WARD_RE = re.compile(r"\bward\s*(?:no\.?\s*)?(\d{1,3})\b", re.IGNORECASE)
_MORE_THAN_RE = re.compile(
    r"(?:more than|over|above|greater than|at least|>=?)\s*(\d{1,3})\s*(?:%|per\s*cent|percent)",
    re.IGNORECASE,
)
_LESS_THAN_RE = re.compile(
    r"(?:less than|under|below|<=?)\s*(\d{1,3})\s*(?:%|per\s*cent|percent)", re.IGNORECASE
)
_SINCE_RE = re.compile(r"\b(?:since|after|from)\s+(\d{4})\b", re.IGNORECASE)
_NEVER_RECOVERED = re.compile(
    r"never (?:recovered|came back|refilled)|still (?:dry|empty|gone)|has not recovered|"
    r"did ?n(?:o|')t recover|permanent",
    re.IGNORECASE,
)
_RECOVERED = re.compile(r"\brecovered\b|came back|refilled|seasonal", re.IGNORECASE)
_BUILT_UP = re.compile(r"built|construct|structure|building|concrete", re.IGNORECASE)
_BARE = re.compile(r"\bfill(?:ed|ing)?\b|bare|earth|soil|rubble", re.IGNORECASE)
_HIGH_CONF = re.compile(r"high[- ]confidence|most confident|strongest|certain", re.IGNORECASE)

# "within 5km", "for 5 km", "5km radius", "a 10 kilometre radius", "3000 m"
_RADIUS_RE = re.compile(
    r"(?:within|inside|for|in|of|radius of|a)?\s*"
    r"(\d{1,4}(?:\.\d+)?)\s*"
    r"(km|kms|kilometer|kilometre|kilometers|kilometres|m|meters|metres)\b"
    r"(?:\s*radius)?",
    re.IGNORECASE,
)
# Words that follow a locative preposition but are never place names.
_NOT_PLACES = {
    "ward", "wards", "mouza", "mouzas", "block", "blocks", "district", "districts",
    "area", "areas", "pond", "ponds", "water", "wetland", "wetlands", "bheri", "bheris",
    "the", "this", "that", "these", "those", "all", "any", "which", "total",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
}

# A place named after a locative preposition, when the gazetteer doesn't know it.
_LOCATIVE_RE = re.compile(
    r"\b(?:around|near|nearby|close to|surrounding|about|at|in|by)\s+"
    r"([A-Z][\w'-]*(?:\s+[A-Z][\w'-]*){0,3})",
)


def _parse_radius(question: str) -> float | None:
    for match in _RADIUS_RE.finditer(question):
        value = float(match.group(1))
        unit = match.group(2).lower()
        km = value / 1000.0 if unit in ("m", "meters", "metres") else value
        if MIN_RADIUS_KM <= km <= MAX_RADIUS_KM:
            return km
    return None


def _parse_place(question: str, *, claimed: str = "") -> str | None:
    """The place this question is about, or None.

    Matching against the gazetteer directly is more robust than parsing
    prepositions: the set of names we can actually answer for is small and known,
    so we look for those first and only fall back to grammar for a name we do not
    have. That fallback exists so we can say "we don't monitor Foo" rather than
    silently ignoring the word.

    `claimed` is the question with any ward and mouza spans blanked out. Without
    that, "ponds in Ward 108" reads "Ward" as a place name and the whole query
    collapses into "we have no coordinates for Ward".
    """
    for name in sorted(gazetteer.names(), key=len, reverse=True):
        if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", question, re.IGNORECASE):
            return name

    match = _LOCATIVE_RE.search(claimed or question)
    if not match:
        return None

    candidate = match.group(1).strip()
    if gazetteer.resolve(candidate):
        return candidate
    # Administrative nouns are not place names, however capitalised.
    if candidate.lower() in _NOT_PLACES or candidate.split()[0].lower() in _NOT_PLACES:
        return None
    if candidate.lower() in {m.lower() for m in repository.mouzas()}:
        return None
    return candidate


def rule_parse(question: str) -> dict[str, Any]:
    f: dict[str, Any] = {}
    # Ward and mouza get first claim on the text; whatever they match is blanked
    # out before place parsing, so an administrative label can't be read as a
    # settlement name.
    claimed = question

    if m := _WARD_RE.search(question):
        candidate = f"Ward {m.group(1)}"
        known = {w.lower(): w for w in repository.wards()}
        f["ward"] = known.get(candidate.lower(), candidate)
    else:
        # Not every ward here is "Ward N" — EKW also spans blocks like Bhangar-I
        # and Sonarpur, which officers name directly. Longest match first so
        # "Bhangar-II" isn't swallowed by "Bhangar-I".
        for label in sorted(repository.wards(), key=len, reverse=True):
            if re.search(rf"(?<![\w-]){re.escape(label)}(?![\w-])", question, re.IGNORECASE):
                f["ward"] = label
                break

    if f.get("ward"):
        claimed = re.sub(
            rf"(?:\bward\s*(?:no\.?\s*)?\d{{1,3}}\b|{re.escape(f['ward'])})",
            " ",
            claimed,
            flags=re.IGNORECASE,
        )

    for mouza in repository.mouzas():
        if re.search(rf"\b{re.escape(mouza)}\b", question, re.IGNORECASE):
            f["mouza"] = mouza
            claimed = re.sub(rf"\b{re.escape(mouza)}\b", " ", claimed, flags=re.IGNORECASE)
            break

    if place := _parse_place(question, claimed=claimed):
        f["place"] = place

    if (radius := _parse_radius(question)) is not None:
        f["radius_km"] = radius

    if m := _MORE_THAN_RE.search(question):
        f["min_loss_pct"] = float(m.group(1))
    if m := _LESS_THAN_RE.search(question):
        f["max_loss_pct"] = float(m.group(1))
    if m := _SINCE_RE.search(question):
        f["since"] = f"{m.group(1)}-01-01"

    if _NEVER_RECOVERED.search(question):
        f["recovered"] = False
    elif _RECOVERED.search(question):
        f["recovered"] = True

    if _BUILT_UP.search(question):
        f["conversion_signal"] = "built_up"
    elif _BARE.search(question):
        f["conversion_signal"] = "bare"

    if _HIGH_CONF.search(question):
        f["confidence_band"] = "high"

    return f


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def query(question: str) -> dict[str, Any]:
    parsed = rule_parse(question)
    unparsed: list[str] = []
    interpretation: str | None = None

    if client.is_configured():
        try:
            payload = client.complete_json(
                [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": _context(question)},
                ],
                temperature=0.0,
                max_tokens=600,
            )
            if isinstance(payload, dict):
                model_filter = _sanitise(payload.get("filter") or {})
                # The pattern parser is trusted over the model where both fired:
                # a regex that matched "more than 20%" cannot have hallucinated it.
                parsed = {**model_filter, **parsed}
                interpretation = payload.get("interpretation") or None
                raw_unparsed = payload.get("unparsed")
                if isinstance(raw_unparsed, list):
                    unparsed = [str(u)[:200] for u in raw_unparsed[:5]]
        except client.LLMError as exc:
            logger.warning("nl query parse failed, using pattern parser only: %s", exc)
            unparsed.append("The query parser was unavailable; only simple patterns were read.")
    elif not parsed:
        unparsed.append(
            "No language model is configured, and this question did not match any of the "
            "built-in patterns (place, radius, ward, loss threshold, recovery, filling, "
            "confidence, year)."
        )

    place_name = parsed.pop("place", None)
    radius_km = parsed.pop("radius_km", None)
    attribute_filters = parsed

    # --- No place named: plain attribute query, as before -------------------
    if not place_name:
        results = stl_esd.filter_anomalies(**attribute_filters)
        return _response(
            question, attribute_filters, results, unparsed,
            interpretation or describe(attribute_filters, None, None),
        )

    # --- Place named but unknown: say so, do not guess ----------------------
    place = gazetteer.resolve(place_name)
    if place is None:
        return _response(
            question,
            {
                **attribute_filters,
                "place": place_name,
                # Report the radius too: the officer should see that the distance
                # was understood, even though the place wasn't.
                **({"radius_km": radius_km} if radius_km is not None else {}),
            },
            [],
            unparsed,
            f"We do not have coordinates for “{place_name}”, so this question could not "
            f"be answered. Known places: {', '.join(gazetteer.suggestions(place_name))}.",
            place=None,
            place_query=place_name,
            resolved=False,
        )

    assumed_radius = radius_km is None
    radius_km = float(radius_km or DEFAULT_RADIUS_KM)

    results = stl_esd.find_near(place.lat, place.lon, radius_km, **attribute_filters)
    ponds_in_range = stl_esd.ponds_near(place.lat, place.lon, radius_km)

    used = {**attribute_filters, "place": place.name, "radius_km": radius_km}
    return _response(
        question, used, results, unparsed,
        interpretation or describe(attribute_filters, place.name, radius_km),
        place={
            "name": place.name,
            "lat": place.lat,
            "lon": place.lon,
            "display_name": place.display_name,
            "source": place.source,
        },
        place_query=place_name,
        resolved=True,
        radius_km=radius_km,
        assumed_radius=assumed_radius,
        monitored_pond_count=len(ponds_in_range),
        summary=_summarise_area(place, radius_km, results, ponds_in_range, attribute_filters),
    )


def _response(
    question: str,
    used_filter: dict[str, Any],
    results: list[dict[str, Any]],
    unparsed: list[str],
    interpretation: str,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "question": question,
        "filter": used_filter,
        "interpretation": interpretation,
        "results": results,
        "count": len(results),
        "unparsed": unparsed,
        **extra,
    }


def _summarise_area(
    place: gazetteer.Place,
    radius_km: float,
    results: list[dict[str, Any]],
    ponds_in_range: list[dict[str, Any]],
    filters: dict[str, Any],
) -> str:
    """A deterministic sentence an officer can read out. Never model-written."""
    where = f"within {radius_km:g} km of {place.name}"

    if not ponds_in_range:
        return (
            f"No water body {where} has been monitored yet, so there is nothing to "
            f"report. Submit this area to start monitoring it — the first results take "
            f"a few minutes, because telling encroachment apart from the dry season "
            f"needs a couple of years of history."
        )

    if not results:
        qualifier = " matching those conditions" if filters else ""
        return (
            f"{len(ponds_in_range)} water bodies are monitored {where}, and none of them "
            f"has an unexplained water loss{qualifier}. Seasonal rise and fall has "
            f"already been accounted for."
        )

    ponds = {r["pond_id"] for r in results}
    total_ha = sum(r.get("loss_ha") or 0 for r in results)
    high = sum(1 for r in results if r["confidence_band"] == "high")
    unrecovered = sum(1 for r in results if not r["recovered"])
    nearest = results[0]

    parts = [
        (
            f"{len(results)} unexplained water {'loss' if len(results) == 1 else 'losses'} "
            f"across {len(ponds)} of the {len(ponds_in_range)} water bodies monitored "
            f"{where}, totalling about {total_ha:.1f} hectares."
        )
    ]
    if high:
        parts.append(f"{high} {'is' if high == 1 else 'are'} high confidence.")
    if unrecovered:
        parts.append(f"{unrecovered} had still not recovered when last seen.")
    parts.append(
        f"The nearest is {nearest.get('pond_name') or nearest['pond_id']}, "
        f"{nearest['distance_km']:g} km away, down {nearest['loss_pct']:.0f}%."
    )
    return " ".join(parts)


def _context(question: str) -> str:
    return (
        f"Known places: {', '.join(gazetteer.names())}\n"
        f"Known wards: {', '.join(repository.wards())}\n"
        f"Known mouzas: {', '.join(repository.mouzas())}\n\n"
        f"Question: {question}"
    )


def _sanitise(raw: Any) -> dict[str, Any]:
    """Keep only recognised keys with values of the right shape."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for key in FILTER_KEYS:
        if key not in raw or raw[key] is None:
            continue
        value = raw[key]
        if key in ("min_loss_pct", "max_loss_pct", "min_confidence"):
            try:
                out[key] = float(value)
            except (TypeError, ValueError):
                continue
        elif key == "radius_km":
            try:
                km = float(value)
            except (TypeError, ValueError):
                continue
            if MIN_RADIUS_KM <= km <= MAX_RADIUS_KM:
                out[key] = km
        elif key == "recovered":
            if isinstance(value, bool):
                out[key] = value
        elif key == "conversion_signal":
            if value in ("built_up", "bare", "none"):
                out[key] = value
        elif key == "confidence_band":
            if value in ("high", "medium", "low"):
                out[key] = value
        elif key in ("since", "until"):
            if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                out[key] = value
        else:
            out[key] = str(value)
    return out


def describe(f: dict[str, Any], place: str | None, radius_km: float | None) -> str:
    """Deterministic plain-language restatement — the fallback interpretation."""
    if not f and not place:
        return "Showing every flagged water-loss event."
    bits = ["Showing water-loss events"]
    if place:
        bits.append(f"within {radius_km:g} km of {place}" if radius_km else f"near {place}")
    if f.get("ward"):
        bits.append(f"in {f['ward']}")
    if f.get("mouza"):
        bits.append(f"in {f['mouza']} mouza")
    if f.get("min_loss_pct") is not None:
        bits.append(f"where the pond lost more than {f['min_loss_pct']:.0f}% of its expected water")
    if f.get("max_loss_pct") is not None:
        bits.append(f"and lost less than {f['max_loss_pct']:.0f}%")
    if f.get("recovered") is False:
        bits.append("that have not recovered since")
    elif f.get("recovered") is True:
        bits.append("that have since recovered")
    if f.get("conversion_signal") == "built_up":
        bits.append("where structures are now visible")
    elif f.get("conversion_signal") == "bare":
        bits.append("where bare earth or fill is now visible")
    if f.get("confidence_band"):
        bits.append(f"with {f['confidence_band']} confidence")
    if f.get("since"):
        bits.append(f"starting on or after {f['since']}")
    if f.get("until"):
        bits.append(f"starting on or before {f['until']}")
    return " ".join(bits) + "."
