"""The four LLM endpoints.

Each one starts from a record the statistics already produced. None of them can
create, alter, or suppress a water-loss finding.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.api.deps import get_anomaly_or_404
from app.schemas.llm import (
    EvidenceRequest,
    EvidenceResponse,
    NLQueryRequest,
    NLQueryResponse,
    NoticeRequest,
    NoticeResponse,
    ReportRequest,
    ReportResponse,
)
from app.services.llm import (
    client,
    evidence_corroboration,
    nl_query,
    regulatory_rag,
    report_writer,
)

router = APIRouter(prefix="/api/llm", tags=["llm"])


@router.get("/status", summary="Is the LLM configured, and what is it?")
def llm_status() -> dict[str, Any]:
    from app.rag import store

    return {
        **client.status(),
        "rag_documents": store.documents(),
        "rag_chunks": len(store.get_index().chunks),
    }


@router.post("/evidence", response_model=EvidenceResponse, summary="Corroborate a flagged event")
def evidence(payload: EvidenceRequest) -> EvidenceResponse:
    anomaly = get_anomaly_or_404(payload.anomaly_id)
    return EvidenceResponse(**evidence_corroboration.corroborate(anomaly, payload.extra_terms))


@router.post("/notice", response_model=NoticeResponse, summary="Draft a grounded show-cause notice")
def notice(payload: NoticeRequest) -> NoticeResponse:
    anomaly = get_anomaly_or_404(payload.anomaly_id)
    return NoticeResponse(
        **regulatory_rag.draft(
            anomaly,
            addressee=payload.addressee,
            officer_name=payload.officer_name,
            officer_designation=payload.officer_designation,
        )
    )


@router.post("/query", response_model=NLQueryResponse, summary="Ask a question in plain English")
def query(payload: NLQueryRequest) -> NLQueryResponse:
    return NLQueryResponse(**nl_query.query(payload.question))


@router.post("/report", response_model=ReportResponse, summary="Write the report prose")
def report(payload: ReportRequest) -> ReportResponse:
    try:
        facts = report_writer.collect_facts(
            payload.scope, anomaly_id=payload.anomaly_id, ward=payload.ward
        )
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Unknown event {exc}")
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    written = report_writer.write(facts)
    return ReportResponse(
        scope=facts["scope"],
        title=facts["title"],
        generated_at=facts["generated_at"],
        facts={k: v for k, v in facts.items() if k != "items"},
        sections=written["sections"],
        llm_used=written["llm_used"],
        pdf_url=_pdf_url(payload),
    )


def _pdf_url(payload: ReportRequest) -> str:
    params = [f"scope={payload.scope}"]
    if payload.anomaly_id:
        params.append(f"anomaly_id={payload.anomaly_id}")
    if payload.ward:
        params.append(f"ward={payload.ward}")
    return "/api/reports/pdf?" + "&".join(params)
