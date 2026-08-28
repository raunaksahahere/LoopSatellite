"""PDF report download."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.services.llm import regulatory_rag, report_writer
from app.services.report import pdf_builder

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/pdf", summary="Download a ward, event, or whole-site report as PDF")
def report_pdf(
    scope: Literal["anomaly", "ward", "all"] = "all",
    anomaly_id: str | None = None,
    ward: str | None = None,
    officer_name: str | None = None,
    include_notice: bool = Query(
        False, description="Append the grounded draft notice (scope=anomaly only)"
    ),
) -> Response:
    try:
        facts = report_writer.collect_facts(scope, anomaly_id=anomaly_id, ward=ward)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Unknown event {exc}")
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    sections = report_writer.write(facts)["sections"]

    notice = None
    if include_notice and scope == "anomaly" and facts["items"]:
        drafted = regulatory_rag.draft(facts["items"][0], officer_name=officer_name)
        if drafted["grounded"]:
            notice = drafted

    pdf = pdf_builder.build_pdf(facts, sections, officer_name=officer_name, notice=notice)
    filename = pdf_builder.filename_for(facts)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
