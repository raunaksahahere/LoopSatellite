"""Session verification for Clerk.

The frontend signs in or signs up through Clerk and sends the resulting session
JWT as `Authorization: Bearer <jwt>`. This module checks that token's signature
against Clerk's published keys and hands routes a `Principal` or a 401.

**The frontend gate is not the gate.** `RequireSession` in the React app decides
what to *render*; it is JavaScript, it runs on the visitor's machine, and a
debugger steps over it in a second. The router dependency here is what actually
refuses to serve data. Every protected router carries `Session`, and
`tests/test_auth.py` walks the live app to prove none was missed.

Two states, not three
---------------------
1. **A valid Clerk JWT** — a real user. Full access, including writes.
2. **Anything else, with auth configured** — 401.

There used to be a third: a read-only "continue as demo" principal that skipped
sign-in entirely. It is gone, and its header with it. Clerk offers sign-*up* as
well as sign-in, so the reason the demo door existed — a visitor with no way in
at all — no longer holds. Removing it also removes the thing it cost: a header
anyone could send to read the whole API without ever having an account.

Writes and Earth Engine
-----------------------
Any signed-in user may submit an area, which is deliberate. But that route spends
a personal Earth Engine OAuth quota, so it is capped per user and per deployment
in `services/quota.py` — a signup is not a licence to drain it.

When auth is not configured
---------------------------
`CLERK_ISSUER` unset means Clerk has not been wired up yet. The API then runs
**open**, says so loudly at startup and in `/api/health`, because a deployment
with no auth server and no way to sign in would be a locked building with the
keys inside.

That is a local-development state, not a deployment one. Set `AUTH_REQUIRED=true`
and the app refuses to boot unconfigured, which is what Render should run with.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from fastapi import Depends, HTTPException, Request, status

from app.core.config import settings

logger = logging.getLogger(__name__)

#: Clock skew tolerated between Clerk and this server.
LEEWAY_SECONDS = 30


class AuthNotConfigured(RuntimeError):
    """CLERK_ISSUER is unset while AUTH_REQUIRED is true."""


@dataclass(frozen=True)
class Principal:
    """Who is making this request. Read from the token, never from the body."""

    user_id: str
    email: str | None = None
    name: str | None = None
    claims: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        """What to record against an action they took.

        Verified, unlike the officer name a client used to be able to type into
        the request body. Falls back through name -> email -> id so this is never
        empty and never a lie.
        """
        return self.name or self.email or self.user_id


def is_configured() -> bool:
    return settings.auth_configured


def jwks_url() -> str:
    return settings.clerk_jwks


def issuer() -> str:
    return (settings.clerk_issuer or "").rstrip("/")


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


def _unauthorized() -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        detail="A valid session is required.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def verify(token: str) -> Principal:
    """Verify a Clerk JWT and return who it belongs to. Raises HTTPException(401).

    Clerk's session tokens carry no `aud`, so audience is not checked; `azp` is,
    when authorized parties are configured. That is the claim that stops a token
    minted for your instance being replayed from somebody else's page.
    """
    import jwt

    try:
        signing_key = _jwk_client(jwks_url()).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=issuer(),
            leeway=LEEWAY_SECONDS,
            options={"require": ["exp", "sub"], "verify_aud": False},
        )
        parties = settings.authorized_party_list
        if parties and claims.get("azp") not in parties:
            raise ValueError(f"azp {claims.get('azp')!r} is not an authorized party")
    except Exception as exc:
        # The reason goes to the log, never to the caller: "signature invalid"
        # versus "expired" tells an attacker which half to work on.
        logger.info("session rejected: %s: %s", type(exc).__name__, exc)
        raise _unauthorized() from exc

    return Principal(
        user_id=str(claims.get("sub")),
        email=claims.get("email") or claims.get("primary_email_address"),
        name=_display_name(claims),
        claims=claims,
    )


def _display_name(claims: dict[str, Any]) -> str | None:
    """A human name from whichever claims this Clerk template happens to send.

    Clerk's default session token is deliberately small and may carry none of
    these; a JWT template can add any of them. Every branch is optional on
    purpose — the caller falls back to the email or the id.
    """
    if name := claims.get("name"):
        return str(name)
    parts = [claims.get("first_name"), claims.get("last_name")]
    joined = " ".join(str(p) for p in parts if p).strip()
    return joined or claims.get("username") or None


def require_session(request: Request) -> Principal | None:
    """FastAPI dependency. 401 unless the request carries a valid Clerk session.

    Returns None — and allows the request — only when auth has not been configured
    at all. See the module docstring: a documented local state that `/api/health`
    reports and `AUTH_REQUIRED=true` forbids.
    """
    if not is_configured():
        return None

    token = bearer_token(request)
    if not token:
        raise _unauthorized()
    return verify(token)


#: The dependency to hang on a router. `Depends` in a default is the FastAPI idiom.
Session = Depends(require_session)

#: Kept as a distinct name so routes that persist something, or spend real quota,
#: read differently from routes that only serve data — and so the two write routes
#: did not have to change when the demo principal was removed. Any signed-in user
#: is writable now; the Earth Engine cap lives in services/quota.py, where it can
#: see the database.
require_writable_session = require_session
WritableSession = Depends(require_writable_session)


def check_startup() -> None:
    """Refuse to boot unconfigured when the operator asked for auth."""
    if settings.auth_required and not is_configured():
        raise AuthNotConfigured(
            "AUTH_REQUIRED=true but CLERK_ISSUER is unset. Create a Clerk "
            "application (dashboard.clerk.com), then set CLERK_ISSUER to its "
            "Frontend API URL, e.g. https://sound-pelican-42.clerk.accounts.dev"
        )


def status_for_health() -> dict[str, Any]:
    return {
        "configured": is_configured(),
        "required": settings.auth_required,
        "provider": "clerk",
        "issuer": settings.clerk_issuer,
        "note": (
            None
            if is_configured()
            else "CLERK_ISSUER is unset: every API route is open. Local-only state."
        ),
    }
