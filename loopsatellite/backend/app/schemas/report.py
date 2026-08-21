from typing import Any

from pydantic import BaseModel


class ReportFacts(BaseModel):
    """Everything numeric in a report, lifted straight from precomputed/.

    The report writer is allowed to phrase these; it is not allowed to alter,
    round differently, or invent any of them.
    """

    scope: str
    title: str
    generated_at: str
    study_area: str
    pond_count: int
    anomaly_count: int
    total_loss_ha: float
    high_confidence_count: int
    unrecovered_count: int
    conversion_count: int
    is_synthetic: bool
    items: list[dict[str, Any]]


class ReportMeta(BaseModel):
    filename: str
    scope: str
    generated_at: str
