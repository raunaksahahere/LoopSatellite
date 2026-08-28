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

from app.api.routes import (
    anomalies,
    areas,
    llm,
    ponds,
    provenance,
    reports,
    verification_queue,
)
from app.core import auth
from app.core.config import settings
from app.core.gee_auth import status as gee_status
from app.core.gee_auth import try_initialize
from app.rag import gazetteer
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
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Every data router is registered WITH the session dependency, in one place, so
# that protecting a route is not something anyone has to remember per-route.
# `tests/test_auth.py` walks the live app and fails if any other path is
# reachable without a session.
PROTECTED_ROUTERS = (
    ponds.router,
    areas.router,
    anomalies.router,
    verification_queue.router,
    reports.router,
    llm.router,
)

for _router in PROTECTED_ROUTERS:
    app.include_router(_router, dependencies=[auth.Session])

# Deliberately public, and a divergence from LoopSpill, which protects its
# equivalent. This page exists to answer "how do we know this works on real
# data?" with a link somebody can open — putting it behind a session defeats the
# only thing it is for. It names no pond and reveals no finding: it describes how
# the bundle was made.
app.include_router(provenance.router)

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
        "auth": auth.status_for_health(),
        "earth_engine": gee_status(),
        "gazetteer": {"places": len(gazetteer.names()), "names": gazetteer.names()},
        "verification_storage": verifications.backend(),
    }


@app.get("/api/manifest", tags=["meta"], summary="How the current data was produced")
def manifest() -> dict[str, Any]:
    return repository.manifest()


def _log_startup() -> None:
    # Raises if AUTH_REQUIRED is set with no auth URL: refusing to boot is the
    # right failure. Booting open on a deployment that asked for auth is not.
    auth.check_startup()
    state = auth.status_for_health()
    logger.info(
        "auth: configured=%s required=%s%s",
        state["configured"],
        state["required"],
        "" if state["configured"] else "  <- EVERY ROUTE IS OPEN",
    )
    # Earth Engine is only needed by the slow path. Failing to reach it must not
    # stop the API booting — everything else works without it.
    try_initialize()
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
        settings.gemini_model,
        verifications.backend(),
    )
