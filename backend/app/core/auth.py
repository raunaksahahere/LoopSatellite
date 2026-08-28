"""Session verification for Neon Managed Better Auth.

The frontend signs in against Neon's auth server and sends the resulting JWT as
`Authorization: Bearer <jwt>`. This module checks that token's signature against
Neon's published keys, and hands routes a `Principal` or a 401.

**The frontend gate is not the gate.** `RequireSession` in the React app decides
what to *render*; it is JavaScript, it runs on the visitor's machine, and a
debugger steps over it in a second. The router dependency here is what actually
refuses to serve data. Every protected router carries `Session`, and
`tests/test_auth.py` walks the live app to prove none was missed.

Three states, not two
---------------------
1. **A valid JWT** — a real operator. Full access, including writes.
2. **The demo header** — a deliberately limited, read-only principal. It can see
   every finding the app has and cannot record a verification or submit an area.
   That second half is the point: submitting an area spends Earth Engine quota
   against a personal token, so it is a write in every sense that matters.
3. **Neither, with auth configured** — 401.

The demo principal is checked *before* `is_configured()`, so it works on a
configured deployment too. That is deliberate: a judge should be able to open the
URL and use the whole read path without an account. It also means reads are, in
practice, public to anyone who sends the header. Nothing behind a read is secret
— the bundle ships in the repository — and the things that cost money are writes.

When auth is not configured
---------------------------
`NEON_AUTH_URL` unset means Managed Better Auth has not been enabled on the Neon
branch yet. The API then runs **open**, says so loudly at startup and in
`/api/health`, because a deployment with no auth server and no way to sign in
would otherwise be a locked building with the keys inside.

That is a local-development state, not a deployment one. Set `AUTH_REQUIRED=true`
and the app refuses to boot without an auth URL, which is what Render should run
with.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request, status

from app.core.config import settings

logger = logging.getLogger(__name__)

#: Clock skew tolerated between Neon's auth server and this one.
LEEWAY_SECONDS = 30

#: The header a browser sends after choosing "Continue as demo".
DEMO_HEADER = "x-loopsatellite-demo"
DEMO_HEADER_VALUE = "session"


class AuthNotConfigured(RuntimeError):
    """NEON_AUTH_URL is unset while AUTH_REQUIRED is true."""


@dataclass(frozen=True)
class Principal:
    """Who is making this request. Read from the token, never from the body."""

    user_id: str
    email: str | None = None
    claims: dict[str, Any] = field(default_factory=dict)
    is_demo: bool = False


def is_configured() -> bool:
    return bool(settings.neon_auth_url)


def jwks_url() -> str:
    """Neon publishes its signing keys under the auth URL."""
    return f"{(settings.neon_auth_url or '').rstrip('/')}/.well-known/jwks.json"


def issuer() -> str:
    """The origin of the auth URL, which is what Better Auth puts in `iss`."""
    parts = urlsplit(settings.neon_auth_url or "")
    return f"{parts.scheme}://{parts.netloc}"


@lru_cache(maxsize=4)
def _jwk_client(url: str):
    from jwt import PyJWKClient

    # PyJWKClient caches keys in-process and re-fetches on an unseen `kid`, so a
    # key rotation costs one request rather than every request.
    return PyJWKClient(url, cache_keys=True, lifespan=3600)


def bearer_token(request: Request) -> str | None:
    """The token from the Authorization header, or None.

    Deliberately strict about the scheme: a header that is present but malformed
    is a client bug worth surfacing as 401, not something to guess at.
    """
    header = request.headers.get("authorization") or ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def is_demo_request(request: Request) -> bool:
    """Whether this is the deliberately limited browser demo session.

    Not a substitute JWT and not a database user. A distinct, read-only principal
    sent by a browser that chose the demo door for this tab. Writes reject it.
    """
    return request.headers.get(DEMO_HEADER) == DEMO_HEADER_VALUE


def verify(token: str) -> Principal:
    """Verify a JWT and return who it belongs to. Raises HTTPException(401)."""
    import jwt

    try:
        signing_key = _jwk_client(jwks_url()).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256", "EdDSA"],
            issuer=issuer(),
            leeway=LEEWAY_SECONDS,
            options={"require": ["exp", "sub"]},
        )
    except Exception as exc:
        # The reason goes to the log, never to the caller: "signature invalid"
        # versus "expired" tells an attacker which half to work on.
        logger.info("session rejected: %s: %s", type(exc).__name__, exc)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="A valid session is required.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return Principal(
        user_id=str(claims.get("sub")),
        email=claims.get("email"),
        claims=claims,
    )


def require_session(request: Request) -> Principal | None:
    """FastAPI dependency. 401 unless the request carries a session.

    Returns None — and allows the request — only when auth has not been configured
    at all. See the module docstring: a documented local state that `/api/health`
    reports and `AUTH_REQUIRED=true` forbids.
    """
    if is_demo_request(request):
        return Principal(user_id="demo-session", is_demo=True)

    if not is_configured():
        return None

    token = bearer_token(request)
    if not token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="A valid session is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return verify(token)


#: The dependency to hang on a router. `Depends` in a default is the FastAPI idiom.
Session = Depends(require_session)


def require_writable_session(request: Request) -> Principal | None:
    """Require a session allowed to persist an action, or spend real quota.

    Two routes need this. Recording a verification writes an officer's verdict
    against their name. Submitting an area starts a Sentinel-2 pull billed to a
    personal Earth Engine token — the single most expensive thing an anonymous
    visitor could do to this deployment.
    """
    principal = require_session(request)
    if principal is not None and principal.is_demo:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail=(
                "Demo sessions can see every finding but cannot record a review or "
                "start monitoring a new area. Sign in to do that."
            ),
        )
    return principal


WritableSession = Depends(require_writable_session)


def check_startup() -> None:
    """Refuse to boot unconfigured when the operator asked for auth."""
    if settings.auth_required and not is_configured():
        raise AuthNotConfigured(
            "AUTH_REQUIRED=true but NEON_AUTH_URL is unset. Enable Managed Better "
            "Auth on the Neon branch (Console -> Project -> Branch -> Auth) and set "
            "NEON_AUTH_URL to the auth URL it prints."
        )


def status_for_health() -> dict[str, Any]:
    return {
        "configured": is_configured(),
        "required": settings.auth_required,
        "provider": "neon-managed-better-auth",
        "auth_url": settings.neon_auth_url,
        "demo_header": DEMO_HEADER,
        "note": (
            None
            if is_configured()
            else "NEON_AUTH_URL is unset: every API route is open. Local-only state."
        ),
    }
