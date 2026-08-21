"""Feature 3 — natural-language query over already-computed results.

"which ponds in Ward 108 lost more than 20% and never recovered"

The LLM's entire job is to turn that sentence into a filter object. It then steps
aside: the filter runs against precomputed/ in Python, and the numbers that come
back were never in the model's context. The model cannot change a loss figure, a
confidence, or which ponds match — only which question was asked.

The parsed filter is returned to the UI and shown to the officer, so a
misreading is visible rather than silent.

There is a deterministic parser underneath too, which handles the common shapes
without any model at all. It runs first; the model is only consulted for what the
patterns miss, and is skipped entirely when it isn't configured.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.services.detection import repository, stl_esd
from app.services.llm import client

logger = logging.getLogger(__name__)

FILTER_KEYS = (
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

SYSTEM = """You convert an officer's question about wetland water-loss records into a filter.

You are NOT answering the question. You never see the records and you must never
guess how many there are or what they say. You only decide what was asked.

Return ONLY JSON:
{"filter": {...}, "interpretation": str, "unparsed": [str]}

Allowed keys in "filter" (omit any that the question does not constrain):
  ward              string, e.g. "Ward 108"  — must match one of the known wards
  mouza             string                    — must match one of the known mouzas
  min_loss_pct      number 0-100
  max_loss_pct      number 0-100
  recovered         true | false   (false = "never recovered", "still dry")
  conversion_signal "built_up" | "bare" | "none"
  confidence_band   "high" | "medium" | "low"
  min_confidence    number 0-1
  since             "YYYY-MM-DD"   (event started on or after)
  until             "YYYY-MM-DD"   (event started on or before)

"interpretation" is one plain sentence restating the filter for the officer to
check — no jargon, no numbers you were not given.
"unparsed" lists any part of the question the filter cannot express (for example a
request to sort, or a question about something not in the list above). Be honest
here; an empty list when the question asked for more is worse than admitting it.
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


def rule_parse(question: str) -> dict[str, Any]:
    f: dict[str, Any] = {}

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

    for mouza in repository.mouzas():
        if re.search(rf"\b{re.escape(mouza)}\b", question, re.IGNORECASE):
            f["mouza"] = mouza
            break

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
            "built-in patterns (ward, loss threshold, recovery, filling, confidence, year)."
        )

    results = stl_esd.filter_anomalies(**parsed)
    return {
        "question": question,
        "filter": parsed,
        "interpretation": interpretation or describe(parsed),
        "results": results,
        "count": len(results),
        "unparsed": unparsed,
    }


def _context(question: str) -> str:
    return (
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


def describe(f: dict[str, Any]) -> str:
    """Deterministic plain-language restatement — the fallback interpretation."""
    if not f:
        return "Showing every flagged water-loss event."
    bits = ["Showing water-loss events"]
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
