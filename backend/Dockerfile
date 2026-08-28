# LoopSatellite API — deployed to Render.
#
# Includes the [server] extra so the slow "process a new area" path can run:
# numpy/scipy/statsmodels for detection, earthengine-api for the satellite pull.
# The fast path needs none of it, so the service still boots and answers
# questions if Earth Engine is unconfigured.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Build tooling for scipy/statsmodels wheels that lack an aarch64 build.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first, so a code change doesn't reinstall scipy.
COPY pyproject.toml ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && mkdir -p app && touch app/__init__.py \
    && /opt/venv/bin/pip install ".[server]"

ENV PATH="/opt/venv/bin:$PATH"

# Application code, then the data the read path serves.
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY precomputed ./precomputed

# The retrieval index is derived from the tracked source texts; build it here so
# the notice endpoint is grounded from the first request, with no cold start and
# no download at runtime.
RUN python -m app.rag.ingest

# Officer verifications when no DATABASE_URL is set.
RUN mkdir -p var

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

# Render supplies $PORT. Single worker on purpose: BackgroundTasks run in the
# web process, and a second worker would not see the first one's job.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
