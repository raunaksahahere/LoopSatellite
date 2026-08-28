"""Earth Engine authentication from a personal OAuth refresh token.

Why not a service account
-------------------------
A GCP service account is the correct long-term answer for a deployed product:
it is an identity that belongs to the project rather than to a person, it can be
scoped and rotated without touching anyone's Google account, and it survives that
person leaving. We are deliberately not using one here.

What we use instead is the refresh token that `earthengine authenticate` already
wrote to `~/.config/earthengine/credentials` on a developer machine. Its whole
contents go into one environment variable, `EARTHENGINE_CREDENTIALS_JSON`.

The trade-off, stated plainly so nobody discovers it later:

  - The token carries **a person's** identity and **that person's** Earth Engine
    quota. Every tile this service pulls is billed to them.
  - Revoking that person's Google access, or their leaving, breaks production.
  - It cannot be scoped down. It is as powerful as the account it came from.

That is acceptable for a hackathon and not acceptable beyond one. See README.md.

Where this is used
------------------
Only the **slow path** — processing a brand-new area nobody has monitored before
(`services/area_processing.py`) — and the offline `data_pipeline/`. The fast path
that answers "what's going on around Haldia" never touches Earth Engine; it reads
anomalies that were computed earlier. Keeping that boundary is the whole reason
the demo can answer in under a second.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

TOKEN_URI = "https://oauth2.googleapis.com/token"

_initialised = False
_last_error: str | None = None


class EarthEngineUnavailable(RuntimeError):
    """Earth Engine is not configured, not installed, or refused the credentials."""


def _build_credentials(raw: str) -> Any:
    from google.oauth2.credentials import Credentials

    try:
        creds = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise EarthEngineUnavailable(
            "EARTHENGINE_CREDENTIALS_JSON is not valid JSON. It must be the entire "
            "contents of ~/.config/earthengine/credentials, on one line."
        ) from exc

    if not creds.get("refresh_token"):
        raise EarthEngineUnavailable(
            "EARTHENGINE_CREDENTIALS_JSON has no refresh_token. It must be the entire "
            "contents of ~/.config/earthengine/credentials, on one line. Re-run "
            "`earthengine authenticate` if that file is missing or empty."
        )

    # Current versions of `earthengine authenticate` write only refresh_token,
    # scopes and redirect_uri — the OAuth client is the Earth Engine library's
    # own, so the file has no client_id or client_secret to write. Requiring
    # them rejected every credentials file produced in the last several releases
    # with "re-run earthengine authenticate", which regenerates the same file.
    #
    # Fall back to the library's client, which is what the `ee` CLI itself uses
    # against exactly these tokens. A file that does carry its own pair — an
    # older one, or a custom OAuth app — still wins.
    client_id = creds.get("client_id")
    client_secret = creds.get("client_secret")
    if not (client_id and client_secret):
        try:
            from ee import oauth

            client_id = client_id or oauth.CLIENT_ID
            client_secret = client_secret or oauth.CLIENT_SECRET
        except (ImportError, AttributeError) as exc:
            raise EarthEngineUnavailable(
                "EARTHENGINE_CREDENTIALS_JSON has no client_id/client_secret and the "
                "earthengine-api default OAuth client could not be read. Install the "
                'pipeline extra: pip install -e ".[pipeline]"'
            ) from exc

    return Credentials(
        token=None,
        refresh_token=creds["refresh_token"],
        client_id=client_id,
        client_secret=client_secret,
        token_uri=TOKEN_URI,
        scopes=creds.get("scopes"),
    )


def initialize_earth_engine(*, force: bool = False) -> None:
    """Authenticate once per process. Idempotent; safe to call again.

    Raises EarthEngineUnavailable rather than letting an import error or an auth
    failure escape as something unrecognisable.
    """
    global _initialised, _last_error

    if _initialised and not force:
        return

    if not settings.earthengine_credentials_json:
        raise EarthEngineUnavailable(
            "EARTHENGINE_CREDENTIALS_JSON is not set. Run `earthengine authenticate` "
            "locally, then put the whole of ~/.config/earthengine/credentials into "
            "that variable."
        )
    if not settings.gee_project_id:
        raise EarthEngineUnavailable("GEE_PROJECT_ID is not set.")

    try:
        import ee
    except ImportError as exc:
        raise EarthEngineUnavailable(
            "earthengine-api is not installed. It ships in the optional 'pipeline' "
            'extra: pip install -e ".[pipeline]"'
        ) from exc

    credentials = _build_credentials(settings.earthengine_credentials_json)

    try:
        ee.Initialize(credentials, project=settings.gee_project_id)
    except Exception as exc:
        _last_error = f"{type(exc).__name__}: {exc}"
        raise EarthEngineUnavailable(f"ee.Initialize failed — {_last_error}") from exc

    _initialised = True
    _last_error = None
    logger.info("Earth Engine ready (project=%s, personal OAuth token)", settings.gee_project_id)


def try_initialize() -> bool:
    """Best-effort init for application startup.

    Never raises. Earth Engine being unavailable must not stop the API from
    booting — the entire read path, the queue, the reports and all four LLM
    features work without it.
    """
    global _last_error
    try:
        initialize_earth_engine()
        return True
    except EarthEngineUnavailable as exc:
        _last_error = str(exc)
        logger.info("Earth Engine not available: %s", exc)
        return False


def is_ready() -> bool:
    return _initialised


def status() -> dict[str, Any]:
    """Surfaced at /api/health so the UI can be honest about the slow path."""
    return {
        "configured": settings.gee_configured,
        "initialised": _initialised,
        "project": settings.gee_project_id,
        "auth_method": "personal-oauth-refresh-token",
        "error": _last_error,
    }
