"""Earth Engine credential handling.

No network and no Earth Engine call. What is tested is the shape of the
credentials object we hand to `ee.Initialize`, because that is where a
perfectly good token was being rejected before it ever reached Google.
"""

from __future__ import annotations

import json

import pytest

from app.core import gee_auth

#: What `earthengine authenticate` writes today. Note what is NOT here: the
#: OAuth client is the Earth Engine library's own, so the file has no client_id
#: and no client_secret to write.
MODERN = {
    "refresh_token": "1//0gFAKEfakefake",
    "scopes": ["https://www.googleapis.com/auth/earthengine"],
    "redirect_uri": "http://localhost:8085",
}

#: What older versions wrote, and what a custom OAuth app still writes.
LEGACY = {
    **MODERN,
    "client_id": "custom-client.apps.googleusercontent.com",
    "client_secret": "custom-secret",
}


def test_a_modern_credentials_file_is_accepted(monkeypatch):
    """Regression. Requiring client_id/client_secret rejected every credentials
    file produced in the last several releases — and told the user to re-run
    `earthengine authenticate`, which regenerates exactly the same file."""
    creds = gee_auth._build_credentials(json.dumps(MODERN))
    assert creds.refresh_token == MODERN["refresh_token"]
    # Filled in from the library's own OAuth client, which is what the `ee` CLI
    # uses against these same tokens.
    assert creds.client_id
    assert creds.client_secret


def test_a_files_own_client_wins_over_the_library_default():
    creds = gee_auth._build_credentials(json.dumps(LEGACY))
    assert creds.client_id == LEGACY["client_id"]
    assert creds.client_secret == LEGACY["client_secret"]


def test_the_library_default_is_the_earth_engine_client():
    from ee import oauth

    creds = gee_auth._build_credentials(json.dumps(MODERN))
    assert creds.client_id == oauth.CLIENT_ID
    assert creds.client_secret == oauth.CLIENT_SECRET


@pytest.mark.parametrize(
    "wrapper",
    [
        "{raw}",          # a hosting dashboard: literal, no quotes
        "'{raw}'",        # a .env file: single-quoted, or dotenv stops at the first "
        '"{raw}"',
        "  {raw}  ",
        "{raw}\n",
    ],
)
def test_quoting_from_either_place_is_accepted(wrapper):
    """Regression, from a real failed deploy.

    A .env file needs the value single-quoted because it is full of double
    quotes. Render's dashboard takes it literally, so the same quoted string
    arrives with a leading `'` and json.loads reports "Expecting value" — which
    reads as corrupt credentials when they are perfect. The difference is an
    artefact of where it was typed.
    """
    creds = gee_auth._build_credentials(wrapper.format(raw=json.dumps(MODERN)))
    assert creds.refresh_token == MODERN["refresh_token"]


@pytest.mark.parametrize("payload", ['["1//0gFAKE"]', "42"])
def test_json_that_is_not_a_credentials_file_is_named_as_such(payload):
    """Valid JSON of the wrong shape. Left unchecked it reaches .get() on a list
    or an int and raises an AttributeError nobody can act on."""
    with pytest.raises(gee_auth.EarthEngineUnavailable) as exc:
        gee_auth._build_credentials(payload)
    assert "not a JSON object" in str(exc.value)


def test_a_missing_refresh_token_is_still_refused():
    """The one field we genuinely cannot substitute."""
    with pytest.raises(gee_auth.EarthEngineUnavailable) as exc:
        gee_auth._build_credentials(json.dumps({"scopes": []}))
    assert "refresh_token" in str(exc.value)


def test_the_scopes_are_carried_through():
    creds = gee_auth._build_credentials(json.dumps(MODERN))
    assert creds.scopes == MODERN["scopes"]


def test_junk_is_reported_as_junk_not_as_a_missing_field():
    with pytest.raises(gee_auth.EarthEngineUnavailable) as exc:
        gee_auth._build_credentials("not json at all")
    assert "valid JSON" in str(exc.value)


def test_status_reports_configured_without_initialising(monkeypatch):
    """/api/health must be able to say "configured but not connected" — those are
    different states and the UI shows different things for them."""
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "earthengine_credentials_json", json.dumps(MODERN))
    monkeypatch.setattr(settings, "gee_project_id", "some-project")
    state = gee_auth.status()
    assert state["configured"] is True
    assert state["auth_method"] == "personal-oauth-refresh-token"
