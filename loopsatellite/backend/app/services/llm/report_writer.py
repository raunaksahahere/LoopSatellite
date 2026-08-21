"""Feature 4 — numbers into English, by filling slots in a fixed template.

The model does not choose the report's structure, its order, or which facts
appear. `ReportSections` is the structure; the model writes the prose for six
named slots and nothing else. Every number in `facts` is computed here from
precomputed/ and passed to the PDF builder directly — the model's output is never
parsed for figures.

English only for the MVP. `services/report/bhashini.py` is the hook point for
Bengali and text-to-speech; it is a stub and is not called.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.services.detection import repository, stl_esd
from app.services.llm import client

logger = logging.getLogger(__name__)

SLOTS = (
    "headline",
    "what_we_observed",
    "why_this_is_not_seasonal",
    "what_replaced_the_water",
    "corroborating_evidence",
    "recommended_action",
)

SYSTEM = """You write the prose for a wetlands monitoring report for officers in West Bengal.

You are filling six named slots in a fixed template. You do not choose the
structure, the order, or which facts appear — that is already decided.

Return ONLY JSON with exactly these keys, all strings:
  headline                  one sentence, under 20 words
  what_we_observed          2-4 sentences
  why_this_is_not_seasonal  2-3 sentences
  what_replaced_the_water   1-3 sentences
  corroborating_evidence    1-3 sentences
  recommended_action        2-3 sentences

RULES:
- Use only the figures given to you. Do not compute, re-round, or introduce a
  number that is not in the data. Do not state a total you were not given.
- Plain language for a reader who is not a remote-sensing specialist. Never write
  "MNDWI", "STL", "ESD", "residual", "z-score" or "NDBI".
- Do not assert who is responsible, or that any law has been broken.
- If a slot has nothing to report (no evidence was gathered, filling was not
  assessed), say so plainly in one sentence. Do not pad it.
- If the data is marked as synthetic or demonstration data, say so in `headline`.
"""


def collect_facts(
    scope: str, *, anomaly_id: str | None = None, ward: str | None = None
) -> dict[str, Any]:
    manifest = repository.manifest()

    if scope == "anomaly":
        if not anomaly_id:
            raise ValueError("anomaly_id is required for scope='anomaly'")
        anomaly = stl_esd.get(anomaly_id)
        if not anomaly:
            raise KeyError(anomaly_id)
        items = [anomaly]
        title = f"Water-loss report — {anomaly.get('pond_name') or anomaly['pond_id']}"
    elif scope == "ward":
        if not ward:
            raise ValueError("ward is required for scope='ward'")
        items = stl_esd.filter_anomalies(ward=ward)
        title = f"Water-loss report — {ward}"
    else:
        items = stl_esd.all_anomalies()
        title = "Water-loss report — East Kolkata Wetlands"

    return {
        "scope": scope,
        "title": title,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "study_area": manifest["study_area"],
        "pond_count": len({i["pond_id"] for i in items}),
        "anomaly_count": len(items),
        "total_loss_ha": round(sum(i.get("loss_ha") or 0 for i in items), 2),
        "high_confidence_count": sum(1 for i in items if i["confidence_band"] == "high"),
        "unrecovered_count": sum(1 for i in items if not i["recovered"]),
        "conversion_count": sum(
            1 for i in items if i.get("conversion_signal") in ("built_up", "bare")
        ),
        "is_synthetic": bool(manifest.get("is_synthetic")),
        "items": items,
    }


def write(facts: dict[str, Any], evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return {'sections': {...}, 'llm_used': bool}."""
    if not client.is_configured():
        return {"sections": template_sections(facts, evidence), "llm_used": False}

    try:
        payload = client.complete_json(
            [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": _prompt(facts, evidence)},
            ],
            temperature=0.3,
            max_tokens=1400,
        )
    except client.LLMError as exc:
        logger.warning("report writing failed: %s", exc)
        return {"sections": template_sections(facts, evidence), "llm_used": False}

    if not isinstance(payload, dict):
        return {"sections": template_sections(facts, evidence), "llm_used": False}

    fallback = template_sections(facts, evidence)
    sections = {
        slot: str(payload.get(slot) or fallback[slot]).strip()[:2000] for slot in SLOTS
    }
    return {"sections": sections, "llm_used": True}


def _prompt(facts: dict[str, Any], evidence: dict[str, Any] | None) -> str:
    lines = [
        f"SCOPE: {facts['scope']}",
        f"AREA: {facts['study_area']}",
        f"PONDS AFFECTED: {facts['pond_count']}",
        f"EVENTS: {facts['anomaly_count']}",
        f"TOTAL WATER SURFACE LOST: {facts['total_loss_ha']} hectares",
        f"HIGH-CONFIDENCE EVENTS: {facts['high_confidence_count']}",
        f"EVENTS WITH NO RECOVERY: {facts['unrecovered_count']}",
        f"EVENTS WHERE FILLING IS VISIBLE: {facts['conversion_count']}",
        f"DATA IS DEMONSTRATION/SYNTHETIC: {facts['is_synthetic']}",
        "",
        "EVENTS:",
    ]
    for item in facts["items"][:25]:
        lines.append(
            f"- {item.get('pond_name') or item['pond_id']} "
            f"({item.get('ward') or 'ward unknown'}, {item.get('mouza') or 'mouza unknown'}): "
            f"lost {item['loss_pct']:.0f}% ({item.get('loss_ha', 0):.2f} ha) "
            f"from {item['window_start'][:7]}; "
            f"{'not recovered' if not item['recovered'] else 'later recovered'}; "
            f"{item.get('conversion_label') or 'filling not assessed'}; "
            f"confidence {item['confidence_band']}"
        )
    if len(facts["items"]) > 25:
        lines.append(f"- … and {len(facts['items']) - 25} more, not listed here")

    lines += ["", "HOW THIS WAS MEASURED (for your own understanding, do not quote jargon):"]
    lines.append(
        "Satellite passes every few days; cloudy passes discarded; the pond's normal "
        "yearly rise and fall subtracted before anything was flagged."
    )

    lines += ["", "CORROBORATING EVIDENCE:"]
    findings = (evidence or {}).get("findings") or []
    if findings:
        for f in findings[:6]:
            lines.append(f"- [{f['relevance']}] {f['title']} ({f.get('source') or f.get('url')})")
    else:
        lines.append("- None gathered.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Deterministic template — used when no model is available
# ---------------------------------------------------------------------------
def template_sections(facts: dict[str, Any], evidence: dict[str, Any] | None = None) -> dict[str, str]:
    items = facts["items"]
    synthetic = " (demonstration data)" if facts["is_synthetic"] else ""

    if facts["scope"] == "anomaly" and items:
        item = items[0]
        headline = (
            f"{item.get('pond_name') or item['pond_id']} lost "
            f"{item['loss_pct']:.0f}% of its expected water surface{synthetic}."
        )
        observed = stl_esd.summarise(item)
        conversion = item.get("conversion_label") or "Filling was not assessed for this pond."
    else:
        headline = (
            f"{facts['anomaly_count']} water-loss events across {facts['pond_count']} "
            f"ponds, totalling {facts['total_loss_ha']} hectares{synthetic}."
        )
        observed = (
            f"Across {facts['study_area']}, {facts['anomaly_count']} events were flagged on "
            f"{facts['pond_count']} ponds, together accounting for about "
            f"{facts['total_loss_ha']} hectares of lost water surface. "
            f"{facts['high_confidence_count']} of these are high-confidence findings."
        )
        conversion = (
            f"{facts['conversion_count']} of the {facts['anomaly_count']} events show bare "
            "earth or structures where water used to be."
        )

    findings = (evidence or {}).get("findings") or []
    direct = [f for f in findings if f["relevance"] == "direct"]
    if direct:
        corroboration = (
            f"{len(direct)} item(s) in the public record refer directly to this site in "
            f"the same period, beginning with \"{direct[0]['title']}\"."
        )
    elif findings:
        corroboration = (
            f"{len(findings)} related item(s) were found in the public record, none of them "
            "specific to this site."
        )
    else:
        corroboration = (
            "No corroborating documents were found in the public record. The satellite "
            "measurement stands on its own."
        )

    return {
        "headline": headline,
        "what_we_observed": observed,
        "why_this_is_not_seasonal": (
            "Each pond's normal yearly cycle — filling after the monsoon, drawing down "
            "through the dry season — was measured from its own history and subtracted "
            "before anything was flagged. What remains is the part of the change that the "
            "season does not explain. "
            f"{facts['unrecovered_count']} of these events had still not recovered when "
            "last observed."
        ),
        "what_replaced_the_water": conversion,
        "corroborating_evidence": corroboration,
        "recommended_action": (
            "Verify the highest-confidence findings on the ground before any enforcement "
            "step. Each entry links back to the measurement it came from, including the "
            "month-by-month record, so the finding can be checked independently."
        ),
    }
