"""Request/response shapes for the four LLM endpoints.

Architectural note that these shapes are built to enforce:
the LLM never decides *whether* a pond shrank. Every request below starts from an
anomaly the statistics already flagged, and every response is structured — lists
of findings with links, quoted provisions with citations, filter objects, slot
fills — rather than free prose the caller has to trust.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.anomaly import AnomalyOut


# ---------------------------------------------------------------------------
# 1. Evidence corroboration
# ---------------------------------------------------------------------------
class EvidenceRequest(BaseModel):
    anomaly_id: str
    extra_terms: list[str] = Field(
        default_factory=list, max_length=8, description="Optional extra search terms"
    )


class EvidenceFinding(BaseModel):
    title: str
    url: str | None = None
    source: str | None = None
    published: str | None = Field(None, description="YYYY-MM-DD if the source gives one")
    snippet: str
    relevance: Literal["direct", "contextual", "unrelated"]
    why_relevant: str


class EvidenceResponse(BaseModel):
    anomaly_id: str
    query_used: str
    findings: list[EvidenceFinding]
    searched: bool = Field(description="False when no search provider is configured")
    note: str | None = Field(
        None, description="Set when nothing was found, or the search was not run"
    )


# ---------------------------------------------------------------------------
# 2. Regulatory grounding + notice drafting
# ---------------------------------------------------------------------------
class NoticeRequest(BaseModel):
    anomaly_id: str
    addressee: str | None = Field(None, description="Occupier / owner, if known")
    officer_name: str | None = None
    officer_designation: str | None = None


class RetrievedProvision(BaseModel):
    """A provision that was *retrieved*, never recalled.

    `quote` is verbatim text from the ingested source document. If this list is
    empty the notice is not drafted at all — see `grounded`.
    """

    document: str
    citation: str
    quote: str
    score: float
    relevance_note: str | None = None


class NoticeResponse(BaseModel):
    anomaly_id: str
    grounded: bool = Field(
        description="False when retrieval found no relevant provision. "
        "When False, `draft` is null and no notice is produced."
    )
    provisions: list[RetrievedProvision]
    draft: str | None = None
    disclaimer: str
    llm_used: bool = Field(
        description="False when the draft came from the fixed template — because no "
        "model is configured, the call failed, or the model's draft was rejected for "
        "citing a provision that was not retrieved."
    )
    note: str | None = None


# ---------------------------------------------------------------------------
# 3. Natural-language query
# ---------------------------------------------------------------------------
class NLQueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class ParsedFilter(BaseModel):
    """The structured filter the LLM produced. Shown to the officer verbatim,
    so they can see exactly how their sentence was interpreted."""

    place: str | None = Field(None, description="Place name as the officer wrote it")
    radius_km: float | None = None
    ward: str | None = None
    mouza: str | None = None
    min_loss_pct: float | None = None
    max_loss_pct: float | None = None
    recovered: bool | None = None
    conversion_signal: Literal["built_up", "bare", "none"] | None = None
    confidence_band: Literal["high", "medium", "low"] | None = None
    min_confidence: float | None = None
    since: str | None = None
    until: str | None = None


class ResolvedPlace(BaseModel):
    """A place from the cached gazetteer. Resolved offline, never at request time."""

    name: str
    lat: float
    lon: float
    display_name: str
    source: str = "nominatim"


class NLQueryResponse(BaseModel):
    question: str
    filter: ParsedFilter
    interpretation: str = Field(description="Plain-language restatement of the filter")
    results: list[AnomalyOut]
    count: int
    unparsed: list[str] = Field(
        default_factory=list,
        description="Parts of the question the filter could not represent",
    )

    # --- present only when the question named a place -----------------------
    place: ResolvedPlace | None = Field(
        None, description="Null when the place could not be resolved"
    )
    place_query: str | None = Field(None, description="What the officer actually typed")
    resolved: bool | None = Field(
        None, description="False when a place was named but is not in the gazetteer"
    )
    radius_km: float | None = None
    assumed_radius: bool | None = Field(
        None, description="True when no distance was given and a default was used"
    )
    monitored_pond_count: int | None = Field(
        None, description="Water bodies in range that are monitored at all — the denominator"
    )
    summary: str | None = Field(
        None,
        description="Deterministic plain-language answer. Composed from the numbers, "
        "never written by a model.",
    )


# ---------------------------------------------------------------------------
# 4. Report writer
# ---------------------------------------------------------------------------
class ReportRequest(BaseModel):
    scope: Literal["anomaly", "ward", "all"] = "anomaly"
    anomaly_id: str | None = None
    ward: str | None = None
    officer_name: str | None = None


class ReportSections(BaseModel):
    """Template slots. The model fills these; it does not choose the structure."""

    headline: str
    what_we_observed: str
    why_this_is_not_seasonal: str
    what_replaced_the_water: str
    corroborating_evidence: str
    recommended_action: str


class ReportResponse(BaseModel):
    scope: str
    title: str
    generated_at: str
    facts: dict[str, Any] = Field(description="The numbers, straight from precomputed/")
    sections: ReportSections
    llm_used: bool
    pdf_url: str | None = None
