"""Sessions: what is refused, what gets through, and what stays public.

No network. A throwaway RSA key is generated per session and `_jwk_client` is
stubbed to hand back its public half, so tokens are signed and verified for real
without Clerk being involved.

The test that matters most is the last one: it walks the live application and
fails if any data route is reachable without a session. Protecting a route is a
one-line router registration in `main.py`, which means forgetting one is a
one-line mistake — so it is checked mechanically rather than by review.
"""

from __future__ import annotations

import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.core import auth
from app.core.config import get_settings
from app.main import app

ISSUER = "https://sound-pelican-42.clerk.accounts.dev"

#: Reachable with no session at all. Everything else needs one.
PUBLIC_PATHS = ("/api/health", "/api/manifest", "/api/provenance")


@pytest.fixture(scope="module")
def keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return key, pem


@pytest.fixture
def configured(monkeypatch, keypair):
    """Auth switched on, with our own key standing in for Clerk's JWKS."""
    key, _ = keypair
    settings = get_settings()
    monkeypatch.setattr(settings, "clerk_issuer", ISSUER)
    monkeypatch.setattr(settings, "clerk_jwks_url", None)
    monkeypatch.setattr(settings, "clerk_authorized_parties", "")

    class _SigningKey:
        def __init__(self, public_key):
            self.key = public_key

    class _Client:
        def get_signing_key_from_jwt(self, _token):
            return _SigningKey(key.public_key())

    monkeypatch.setattr(auth, "_jwk_client", lambda _url: _Client())
    return settings


@pytest.fixture
def signed(keypair):
    """Mint a token. Claims can be overridden to make a bad one."""
    _, pem = keypair

    def make(**overrides) -> str:
        import jwt

        claims = {
            "sub": "user_2abcDEF",
            "email": "officer@example.gov.in",
            "iss": auth.issuer(),
            "exp": int(time.time()) + 600,
            **overrides,
        }
        return jwt.encode(claims, pem, algorithm="RS256")

    return make


@pytest.fixture
def api():
    with TestClient(app) as client:
        yield client


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------
def test_no_session_is_401_not_data(api, configured):
    response = api.get("/api/ponds")
    assert response.status_code == 401
    assert "features" not in response.text


def test_a_valid_session_gets_through(api, configured, signed):
    response = api.get("/api/ponds", headers={"Authorization": f"Bearer {signed()}"})
    assert response.status_code == 200


@pytest.mark.parametrize(
    "header",
    ["", "Bearer", "Bearer ", "Basic dXNlcjpwdw==", "Token abc.def.ghi", "bearer"],
)
def test_a_malformed_authorization_header_is_401(api, configured, header):
    assert api.get("/api/ponds", headers={"Authorization": header}).status_code == 401


def test_an_expired_token_is_401(api, configured, signed):
    stale = signed(exp=int(time.time()) - 3600)
    assert api.get("/api/ponds", headers={"Authorization": f"Bearer {stale}"}).status_code == 401


def test_a_token_from_another_issuer_is_401(api, configured, signed):
    forged = signed(iss="https://evil.example.com")
    assert api.get("/api/ponds", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_a_token_without_a_subject_is_401(api, configured, keypair):
    import jwt

    _, pem = keypair
    token = jwt.encode(
        {"iss": auth.issuer(), "exp": int(time.time()) + 600}, pem, algorithm="RS256"
    )
    assert api.get("/api/ponds", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_a_tampered_token_is_401(api, configured, signed):
    head, payload, signature = signed().split(".")
    tampered = f"{head}.{payload}.{signature[:-4]}AAAA"
    assert api.get("/api/ponds", headers={"Authorization": f"Bearer {tampered}"}).status_code == 401


def test_the_rejection_does_not_say_why(api, configured, signed):
    """"Expired" versus "bad signature" tells an attacker which half to work on."""
    for token in (signed(exp=1), signed(iss="https://evil.example.com")):
        detail = api.get("/api/ponds", headers={"Authorization": f"Bearer {token}"}).json()
        assert detail["detail"] == "A valid session is required."


# ---------------------------------------------------------------------------
# There is no demo door any more
# ---------------------------------------------------------------------------
def test_the_demo_header_no_longer_opens_anything(api, configured):
    """Regression. Reads used to be reachable by anyone who sent one header and
    never signed in. Clerk offers sign-up, so the reason for that door is gone —
    and a header that still worked would be the whole auth system's back wall
    missing."""
    for header in ("x-loopsatellite-demo", "X-LoopSatellite-Demo"):
        response = api.get("/api/ponds", headers={header: "session"})
        assert response.status_code == 401, f"{header} still let a request through"
        assert "features" not in response.text


def test_no_demo_symbols_survive_in_the_auth_module():
    """The header, its value, and the read-only principal are gone — not merely
    unused. A dormant demo path is one import away from being live again."""
    for name in ("DEMO_HEADER", "DEMO_HEADER_VALUE", "is_demo_request"):
        assert not hasattr(auth, name), f"auth.{name} is still defined"


def test_a_real_session_may_write(api, configured, signed):
    response = api.post(
        "/api/areas",
        headers={"Authorization": f"Bearer {signed()}"},
        json={"name": "Haldia", "lat": 22.028, "lon": 88.063, "radius_km": 5},
    )
    # 503 because no DATABASE_URL in tests — the point is it got past the guard.
    assert response.status_code != 403
    assert response.status_code != 401


def test_an_anonymous_write_is_refused(api, configured):
    """The expensive one: submitting an area spends Earth Engine quota against a
    personal token."""
    response = api.post(
        "/api/areas",
        json={"name": "Haldia", "lat": 22.028, "lon": 88.063, "radius_km": 5},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Authorized party (azp)
# ---------------------------------------------------------------------------
def test_a_token_for_another_origin_is_refused_when_azp_is_configured(
    api, configured, signed, monkeypatch
):
    """Clerk stamps the origin a token was minted for into `azp`. Without this
    check, a token lifted from our instance works from anyone's page."""
    monkeypatch.setattr(configured, "clerk_authorized_parties", "https://loopsatellite.vercel.app")
    good = signed(azp="https://loopsatellite.vercel.app")
    bad = signed(azp="https://evil.example.com")
    assert api.get("/api/ponds", headers={"Authorization": f"Bearer {good}"}).status_code == 200
    assert api.get("/api/ponds", headers={"Authorization": f"Bearer {bad}"}).status_code == 401


def test_azp_is_not_checked_when_it_is_not_configured(api, configured, signed):
    """Default deployment state. Checking a claim we were never told to expect
    would lock out every correctly-issued token."""
    token = signed(azp="https://anything.example.com")
    assert api.get("/api/ponds", headers={"Authorization": f"Bearer {token}"}).status_code == 200


# ---------------------------------------------------------------------------
# Public surfaces
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", PUBLIC_PATHS)
def test_public_paths_stay_public(api, configured, path):
    assert api.get(path).status_code == 200


def test_provenance_is_public_on_purpose(api, configured):
    """It answers "how do we know this works on real data?" with a link somebody
    can open. Behind a session it answers nothing."""
    body = api.get("/api/provenance").json()
    assert body["layers"]


def test_health_reports_the_auth_state(api, configured):
    state = api.get("/api/health").json()["auth"]
    assert state["configured"] is True
    assert state["provider"] == "clerk"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def test_with_no_issuer_the_api_is_open_and_says_so(api):
    assert not auth.is_configured()
    assert api.get("/api/ponds").status_code == 200
    note = api.get("/api/health").json()["auth"]["note"]
    assert "every api route is open" in note.lower()


def test_auth_required_without_an_issuer_refuses_to_boot(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_required", True)
    monkeypatch.setattr(settings, "clerk_issuer", None)
    with pytest.raises(auth.AuthNotConfigured):
        auth.check_startup()


def test_the_jwks_url_and_issuer_come_from_one_setting(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "clerk_issuer", "https://sound-pelican-42.clerk.accounts.dev/")
    monkeypatch.setattr(settings, "clerk_jwks_url", None)
    assert auth.jwks_url() == (
        "https://sound-pelican-42.clerk.accounts.dev/.well-known/jwks.json"
    )
    assert auth.issuer() == "https://sound-pelican-42.clerk.accounts.dev"


# ---------------------------------------------------------------------------
# The one that catches a forgotten route
# ---------------------------------------------------------------------------
def _data_routes() -> list[str]:
    """Every GET under /api that is not deliberately public.

    Read from the OpenAPI schema rather than `app.routes`. FastAPI includes
    routers lazily, so before the app is built `app.routes` holds opaque
    `_IncludedRouter` entries with no path — walking it finds nothing and the
    test passes while checking nothing. `test_there_are_protected_paths_to_test`
    caught exactly that.
    """
    schema = app.openapi()
    return sorted(
        path
        for path, operations in schema.get("paths", {}).items()
        if path.startswith("/api/")
        and "get" in operations
        and path not in PUBLIC_PATHS
        and "{" not in path
    )


def test_there_are_protected_paths_to_test():
    """Without this, a router-walk that found nothing would pass silently."""
    assert len(_data_routes()) >= 4, _data_routes()


@pytest.mark.parametrize("path", _data_routes())
def test_every_data_route_refuses_an_anonymous_request(api, configured, path):
    """Protecting a route is one line in main.py, so forgetting one is one line.
    Checked mechanically rather than by review."""
    if path in PUBLIC_PATHS:
        pytest.skip("deliberately public")
    assert api.get(path).status_code == 401, f"{path} served data with no session"
