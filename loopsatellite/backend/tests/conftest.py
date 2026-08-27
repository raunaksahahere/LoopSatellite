"""Test configuration.

**Tests never touch a real database.** Without this, adding DATABASE_URL to .env
silently repoints the verification tests at production Neon: they write rows into
the live `verification` table, and they fail on a foreign key because anomalies
live in precomputed/ files rather than in Postgres.

Verification storage has a file backend precisely so the read path works without
a database, and that is what the suite exercises. To test against a real
database, set TEST_DATABASE_URL — never DATABASE_URL.

**Tests never call a real language model either** — and, since the response cache
landed, never read one's cached answer. Stripping only the API key was not enough:
`precomputed/llm/` ships 27 warmed entries, so `client.is_available()` stayed true
and every notice, report and query test quietly started asserting against model
prose instead of the deterministic fallback. Whether those tests passed then
depended on what someone last warmed, which is not a test.

So the cache is switched off here as well. The suite asserts the deterministic
path, which is the one that has to be right when nothing else is available.
`tests/test_llm_cache.py` exercises the cache itself against its own tmp_path.
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
    settings.openrouter_model_fallbacks = ""
    # Not just the key: a warm cache would make is_available() true and serve
    # model prose to tests that exist to check the fallback.
    settings.llm_cache_enabled = False


@pytest.fixture(scope="session", autouse=True)
def isolate_verification_store() -> None:
    """Point the file-backed verification store at a temp file, not backend/var/."""
    from app.services import verifications

    with tempfile.TemporaryDirectory() as tmp:
        original = verifications.FALLBACK_PATH
        verifications.FALLBACK_PATH = Path(tmp) / "verifications.json"
        yield
        verifications.FALLBACK_PATH = original
