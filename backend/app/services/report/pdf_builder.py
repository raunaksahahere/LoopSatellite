"""ReportLab PDF builder.

Takes `facts` (numbers, straight from precomputed/) and `sections` (prose, from
the template or the report writer) and lays them out. Every figure printed here
comes from `facts` — the prose is never parsed for numbers.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

INK = colors.HexColor("#1d2b2a")
MUTED = colors.HexColor("#5d6b69")
ACCENT = colors.HexColor("#0f6f6c")
BAND_COLORS = {
    "high": colors.HexColor("#b3261e"),
    "medium": colors.HexColor("#a8620a"),
    "low": colors.HexColor("#4a6b45"),
}

SECTION_TITLES = [
    ("what_we_observed", "What we observed"),
    ("why_this_is_not_seasonal", "Why this is not just the season"),
    ("what_replaced_the_water", "What replaced the water"),
    ("corroborating_evidence", "Corroborating evidence"),
    ("recommended_action", "Recommended action"),
]


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "LSTitle", parent=base["Title"], fontSize=19, leading=23, textColor=INK, alignment=TA_LEFT
        ),
        "kicker": ParagraphStyle(
            "LSKicker", parent=base["Normal"], fontSize=8.5, leading=11, textColor=ACCENT,
            spaceAfter=2, fontName="Helvetica-Bold",
        ),
        "headline": ParagraphStyle(
            "LSHeadline", parent=base["Normal"], fontSize=12.5, leading=17, textColor=INK,
            spaceBefore=6, spaceAfter=10,
        ),
        "h2": ParagraphStyle(
            "LSH2", parent=base["Heading2"], fontSize=11.5, leading=14, textColor=ACCENT,
            spaceBefore=14, spaceAfter=5,
        ),
        "body": ParagraphStyle(
            "LSBody", parent=base["BodyText"], fontSize=9.8, leading=14.5, textColor=INK,
            spaceAfter=6,
        ),
        "small": ParagraphStyle(
            "LSSmall", parent=base["Normal"], fontSize=8, leading=11, textColor=MUTED,
        ),
        "mono": ParagraphStyle(
            "LSMono", parent=base["Normal"], fontName="Courier", fontSize=8.2, leading=11.5,
            textColor=INK,
        ),
    }


def build_pdf(
    facts: dict[str, Any],
    sections: dict[str, str],
    *,
    officer_name: str | None = None,
    notice: dict[str, Any] | None = None,
) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=facts["title"],
        author="LoopSatellite — Loop Errors",
    )
    st = _styles()
    story: list[Any] = []

    story.append(Paragraph("LOOPSATELLITE — WETLAND WATER SURFACE MONITORING", st["kicker"]))
    story.append(Paragraph(facts["title"], st["title"]))
    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            f"{facts['study_area']} &nbsp;·&nbsp; generated "
            f"{_pretty_date(facts['generated_at'])}"
            + (f" &nbsp;·&nbsp; prepared by {officer_name}" if officer_name else ""),
            st["small"],
        )
    )
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", color=colors.HexColor("#d8dedd"), thickness=0.8))

    if facts.get("is_synthetic"):
        story.append(Spacer(1, 8))
        story.append(_callout(
            "Demonstration data. The pond boundaries and satellite measurements in this "
            "report are synthetic and must not be used for any enforcement purpose.",
            st,
        ))

    story.append(Paragraph(sections.get("headline", ""), st["headline"]))
    story.append(_summary_table(facts))

    for key, heading in SECTION_TITLES:
        text = sections.get(key)
        if not text:
            continue
        story.append(Paragraph(heading, st["h2"]))
        story.append(Paragraph(_escape(text), st["body"]))

    items = facts.get("items") or []
    if items:
        story.append(Paragraph("Flagged events", st["h2"]))
        story.append(_events_table(items, st))

    story.append(Paragraph("How this was measured", st["h2"]))
    story.append(
        Paragraph(
            "A satellite passes over the wetland every few days and records how each pond's "
            "surface reflects light. Water and land reflect infrared very differently, which "
            "is what lets the water surface be measured. Cloudy passes are discarded. Each "
            "pond's own history is then used to work out how much water it normally holds in "
            "each month of the year, and that seasonal pattern is subtracted before anything "
            "is flagged — so a pond that shrinks every April does not appear here. "
            "<b>No language model takes any part in deciding whether a pond shrank.</b>",
            st["body"],
        )
    )

    if notice and notice.get("provisions"):
        story.append(PageBreak())
        story.append(Paragraph("Draft notice", st["h2"]))
        story.append(Paragraph(_escape(notice.get("disclaimer", "")), st["small"]))
        story.append(Spacer(1, 6))
        if notice.get("draft"):
            story.append(Paragraph(_escape(notice["draft"]).replace("\n", "<br/>"), st["mono"]))
        story.append(Paragraph("Provisions relied on", st["h2"]))
        for p in notice["provisions"]:
            story.append(
                Paragraph(f"<b>{_escape(p['citation'])}</b> — {_escape(p['document'])}", st["body"])
            )
            story.append(Paragraph(f"“{_escape(p['quote'])}”", st["small"]))
            story.append(Spacer(1, 5))

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()


def _summary_table(facts: dict[str, Any]) -> Table:
    rows = [
        ["Ponds affected", str(facts["pond_count"])],
        ["Events flagged", str(facts["anomaly_count"])],
        ["Water surface lost", f"{facts['total_loss_ha']:.2f} ha"],
        ["High confidence", str(facts["high_confidence_count"])],
        ["Not recovered", str(facts["unrecovered_count"])],
        ["Filling visible", str(facts["conversion_count"])],
    ]
    table = Table([[r[0] for r in rows], [r[1] for r in rows]], colWidths=[28 * mm] * 6)
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, 0), 7.2),
                ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 1), (-1, 1), 13),
                ("TEXTCOLOR", (0, 1), (-1, 1), INK),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
                ("TOPPADDING", (0, 1), (-1, 1), 0),
                ("LINEBELOW", (0, 1), (-1, 1), 0.8, colors.HexColor("#d8dedd")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


def _events_table(items: list[dict[str, Any]], st: dict[str, ParagraphStyle]) -> Table:
    header = ["Pond", "Ward", "From", "Loss", "Area", "Recovered", "Surface now", "Conf."]
    data: list[list[Any]] = [[Paragraph(f"<b>{h}</b>", st["small"]) for h in header]]
    for item in items[:60]:
        data.append(
            [
                Paragraph(_escape(item.get("pond_name") or item["pond_id"]), st["small"]),
                Paragraph(_escape(item.get("ward") or "—"), st["small"]),
                Paragraph(item["window_start"][:7], st["small"]),
                Paragraph(f"{item['loss_pct']:.0f}%", st["small"]),
                Paragraph(f"{item.get('loss_ha', 0):.2f} ha", st["small"]),
                Paragraph("no" if not item["recovered"] else "yes", st["small"]),
                Paragraph(_escape(item.get("conversion_label") or "—"), st["small"]),
                Paragraph(
                    f'<font color="{BAND_COLORS.get(item["confidence_band"], MUTED)}">'
                    f'<b>{item["confidence_band"]}</b></font>',
                    st["small"],
                ),
            ]
        )
    table = Table(
        data,
        colWidths=[34 * mm, 18 * mm, 15 * mm, 12 * mm, 16 * mm, 17 * mm, 41 * mm, 15 * mm],
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#c9d2d1")),
                ("LINEBELOW", (0, 1), (-1, -2), 0.3, colors.HexColor("#e8eceb")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return table


def _callout(text: str, st: dict[str, ParagraphStyle]) -> KeepTogether:
    table = Table([[Paragraph(_escape(text), st["small"])]], colWidths=[170 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fdf4e3")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#d9b779")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return KeepTogether([table, Spacer(1, 6)])


def _footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(
        20 * mm, 11 * mm, "LoopSatellite · Loop Errors · detection is statistical, not generative"
    )
    canvas.drawRightString(A4[0] - 20 * mm, 11 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _pretty_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d %B %Y, %H:%M UTC")
    except ValueError:
        return iso


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def filename_for(facts: dict[str, Any]) -> str:
    stamp = facts["generated_at"][:10]
    slug = "".join(c if c.isalnum() else "-" for c in facts["title"].lower()).strip("-")
    slug = "-".join(filter(None, slug.split("-")))[:60]
    return f"loopsatellite-{slug}-{stamp}.pdf"
