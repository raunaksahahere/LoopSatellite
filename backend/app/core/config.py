"""Application settings, read from the environment / repo-root .env."""

from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> backend/app/core -> backend/app -> backend -> repo root
BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
PRECOMPUTED_DIR = BACKEND_DIR / "precomputed"

# libpq query parameters that asyncpg does not understand. Neon (and most hosted
# Postgres consoles) hand you a URL containing these; asyncpg raises
# `connect() got an unexpected keyword argument 'sslmode'` on them.
_LIBPQ_ONLY_PARAMS = {
    "sslmode",
    "channel_binding",
    "target_session_attrs",
    "gssencmode",
    "options",
}


def normalise_database_url(url: str | None) -> str | None:
    """Make a pasted-from-the-console Postgres URL usable by the async engine.

    Neon gives you:
        postgresql://user:pw@host/db?sslmode=require&channel_binding=require

    Two things are wrong with that here, and both fail at connect time rather
    than at startup, so they are worth fixing once in one place:

      1. No driver, so SQLAlchemy reaches for psycopg2 — which isn't installed,
         and wouldn't be async if it were. We need `postgresql+asyncpg`.
      2. `sslmode` / `channel_binding` are libpq spellings. asyncpg takes `ssl`.

    Anyone can now paste the URL exactly as their provider printed it.
    """
    if not url:
        return url

    url = url.strip().strip("'\"")

    # 1. Driver.
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            url = "postgresql+asyncpg://" + url[len(prefix) :]
            break

    if "+asyncpg" not in url:
        return url  # some other driver was named explicitly; leave it alone

    # 2. Query parameters.
    parts = urlsplit(url)
    params = parse_qsl(parts.query, keep_blank_values=True)
    kept = [(k, v) for k, v in params if k.lower() not in _LIBPQ_ONLY_PARAMS]
    dropped = {k.lower(): v for k, v in params if k.lower() in _LIBPQ_ONLY_PARAMS}

    # sslmode=require/verify-* all mean "encrypt this"; asyncpg spells it `ssl`.
    if "ssl" not in {k.lower() for k, _ in kept}:
        sslmode = dropped.get("sslmode")
        if sslmode and sslmode != "disable":
            kept.append(("ssl", "require"))

    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Database -------------------------------------------------------
    # Optional: the demo read path serves precomputed/ and does not need a DB.
    # Areas submitted at runtime do need one — see services/areas.py.
    database_url: str | None = None

    # --- LLM (Google AI Studio, via its OpenAI-compatible endpoint) -----
    gemini_api_key: str | None = None
    # gemini-2.0-flash-lite is retired; the API refuses it with a 404 naming this
    # as the replacement. `gemini-flash-lite-latest` also exists but floats, and a
    # model that changes under you changes the prose in a warmed cache too.
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    # Google AI Studio's free tier is a single provider, so there is no chain to
    # fall down. A 429 is a rate limit rather than a dead model, and waiting is
    # the correct response. On exhaustion the caller gets LLMError and degrades.
    llm_max_retries: int = 3
    llm_retry_base_delay: float = 1.0
    # Bounds on how long one `complete()` may take. Both matter because the free
    # tier can hang rather than refuse: without an explicit per-request timeout
    # the SDK's default lets a single stalled socket hold a web request open, and
    # without a total budget three retries plus three `Retry-After: 60` sleeps
    # add up to minutes. `complete()` gives up inside LLM_TOTAL_BUDGET seconds and
    # the caller degrades to its deterministic path.
    llm_request_timeout: float = 30.0
    llm_total_budget: float = 75.0
    # Write-through response cache under precomputed/llm/. Switch off to force
    # every call to hit the provider (useful when checking a prompt change).
    llm_cache_enabled: bool = True

    # --- Web search (evidence corroboration) ----------------------------
    # tavily | serper | none. There is no provider-side web search here: Gemini
    # has no equivalent of OpenRouter's `:online` model variant, so results are
    # fetched server-side and handed to the model as context.
    search_provider: str = "tavily"
    search_api_key: str | None = None

    # --- Sessions (Clerk) -----------------------------------------------
    # The Frontend API origin Clerk prints for the instance, e.g.
    #   https://sound-pelican-42.clerk.accounts.dev
    # It is the `iss` of every token Clerk issues and the root of its JWKS. Blank
    # means auth is not configured: the API runs open and says so at startup and
    # in /api/health. That is a local state, not a deployed one.
    clerk_issuer: str | None = None
    # Override only if Clerk ever moves the path. Derived from the issuer.
    clerk_jwks_url: str | None = None
    # Optional but recommended on a deployment: Clerk puts the origin the token
    # was minted for in `azp`. Setting this refuses a token lifted from your
    # instance and replayed from someone else's page. Comma-separated.
    clerk_authorized_parties: str = ""
    # Set true on a deployment. The app then refuses to boot unconfigured,
    # rather than quietly serving everything to everyone.
    auth_required: bool = False

    # --- Earth Engine quota, per signed-in user -------------------------
    # POST /api/areas spends a personal Earth Engine OAuth quota, and any signed-in
    # user may call it. These caps are what stops one account draining it. Counted
    # over a rolling 24 hours against the Clerk user id. 0 disables a cap.
    area_quota_per_user_per_day: int = 3
    area_quota_per_day: int = 20

    # --- Google Earth Engine (offline pipeline + the slow area path) -----
    # Personal OAuth refresh token, not a service account. The whole contents of
    # ~/.config/earthengine/credentials, as one line. See core/gee_auth.py.
    earthengine_credentials_json: str | None = None
    gee_project_id: str | None = None

    # --- Paths ----------------------------------------------------------
    precomputed_dir: Path = PRECOMPUTED_DIR

    # --- CORS -----------------------------------------------------------
    # Comma-separated. The deployed frontend origin goes here. Never "*".
    # Kept as a plain string, not list[str]: pydantic-settings JSON-decodes list
    # fields inside the dotenv source, before any validator can normalise them,
    # so `CORS_ORIGINS=a,b` in a .env raises SettingsError. Parsed by
    # `cors_origin_list` below instead.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @field_validator("database_url", mode="after")
    @classmethod
    def _fix_database_url(cls, value: str | None) -> str | None:
        return normalise_database_url(value)

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def llm_cache_dir(self) -> Path:
        return self.precomputed_dir / "llm"

    @property
    def llm_configured(self) -> bool:
        return bool(self.gemini_api_key and self.gemini_model)

    @property
    def db_configured(self) -> bool:
        return bool(self.database_url)

    @property
    def auth_configured(self) -> bool:
        return bool(self.clerk_issuer)

    @property
    def clerk_jwks(self) -> str:
        if self.clerk_jwks_url:
            return self.clerk_jwks_url
        return f"{(self.clerk_issuer or '').rstrip('/')}/.well-known/jwks.json"

    @property
    def authorized_party_list(self) -> list[str]:
        return [p.strip() for p in self.clerk_authorized_parties.split(",") if p.strip()]

    @property
    def gee_configured(self) -> bool:
        return bool(self.earthengine_credentials_json and self.gee_project_id)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
