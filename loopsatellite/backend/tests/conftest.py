"""Test configuration.

**Tests never touch a real database.** Without this, adding DATABASE_URL to .env
silently repoints the verification tests at production Neon: they write rows into
the live `verification` table, and they fail on a foreign key because anomalies
live in precomputed/ files rather than in Postgres.

Verification storage has a file backend precisely so the read path works without
a database, and that is what the suite exercises. To test against a real
database, set TEST_DATABASE_URL — never DATABASE_URL.

**Tests never call a real language model either.** Once OPENROUTER_API_KEY is
filled in, every notice, report and query test starts making live billable calls:
slow, flaky (a provider 429 is not a code defect), and non-deterministic. The
suite runs against the deterministic fallbacks, which is what should be asserted
anyway. Individual tests that want a model monkeypatch `client.complete`.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from app.core import config


@pytest.fixture(scope="session", autouse=True)
def isolate_from_production_database() -> None:
    settings = config.get_settings()
    settings.database_url = os.environ.get("TEST_DATABASE_URL") or None


@pytest.fixture(scope="session", autouse=True)
def isolate_from_live_llm() -> None:
    settings = config.get_settings()
    if os.environ.get("TEST_ALLOW_LIVE_LLM"):
        return
    settings.openrouter_api_key = None
    settings.openrouter_model = None


@pytest.fixture(scope="session", autouse=True)
def isolate_verification_store() -> None:
    """Point the file-backed verification store at a temp file, not backend/var/."""
    from app.services import verifications

    with tempfile.TemporaryDirectory() as tmp:
        original = verifications.FALLBACK_PATH
        verifications.FALLBACK_PATH = Path(tmp) / "verifications.json"
        yield
        verifications.FALLBACK_PATH = original
