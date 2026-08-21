"""LoopSatellite API.

Reads backend/precomputed/ and serves it. During a demo this process makes no
Earth Engine call, downloads nothing, and recomputes nothing — see the golden
rule in README.md. The only outbound calls it ever makes are to OpenRouter, and
only from the four /api/llm endpoints, and only after statistics have already
flagged something.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import anomalies, llm, ponds, reports, verification_queue
from app.core.config import settings
from app.services import verifications
from app.services.detection import repository
from app.services.llm import client

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("loopsatellite")

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    _log_startup()
    yield


app = FastAPI(
    lifespan=lifespan,
    title="LoopSatellite",
    description=(
        "Satellite monitoring for the East Kolkata Wetlands. "
        "Statistics detect; the LLM builds the case."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ponds.router)
app.include_router(anomalies.router)
app.include_router(verification_queue.router)
app.include_router(reports.router)
app.include_router(llm.router)

# Chips for the before/after slider are static files under precomputed/.
if settings.precomputed_dir.exists():
    app.mount(
        "/precomputed",
        StaticFiles(directory=settings.precomputed_dir),
        name="precomputed",
    )


@app.exception_handler(repository.PrecomputedMissingError)
async def precomputed_missing_handler(
    request: Request, exc: repository.PrecomputedMissingError
) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "detail": str(exc),
            "hint": "The API serves precomputed data only; it will not compute it on demand.",
        },
    )


@app.get("/api/health", tags=["meta"], summary="Service and data status")
def health() -> dict[str, Any]:
    try:
        manifest = repository.manifest()
        data: dict[str, Any] = {
            "precomputed": True,
            "generated_at": manifest["generated_at"],
            "pond_count": manifest["pond_count"],
            "anomaly_count": manifest["anomaly_count"],
            "is_synthetic": manifest.get("is_synthetic", False),
            "pond_provenance": manifest.get("pond_provenance", []),
        }
    except repository.PrecomputedMissingError as exc:
        data = {"precomputed": False, "detail": str(exc)}

    return {
        "status": "ok" if data.get("precomputed") else "degraded",
        "data": data,
        "llm": client.status(),
        "verification_storage": verifications.backend(),
    }


@app.get("/api/manifest", tags=["meta"], summary="How the current data was produced")
def manifest() -> dict[str, Any]:
    return repository.manifest()


def _log_startup() -> None:
    try:
        m = repository.manifest()
        logger.info(
            "precomputed bundle: %s ponds, %s events, generated %s%s",
            m["pond_count"],
            m["anomaly_count"],
            m["generated_at"],
            " (SYNTHETIC DEMO DATA)" if m.get("is_synthetic") else "",
        )
    except repository.PrecomputedMissingError as exc:
        logger.warning("no precomputed bundle: %s", exc)
    logger.info(
        "llm configured=%s model=%s | verifications=%s",
        client.is_configured(),
        settings.openrouter_model,
        verifications.backend(),
    )
