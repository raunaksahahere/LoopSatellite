"""The one and only LLM client.

Every LLM feature imports from here. No feature constructs its own API call, so
there is exactly one place where the model, the key, the headers and the
timeouts are decided.

Thin wrapper around the OpenAI SDK pointed at OpenRouter. The model name is never
hardcoded — it comes from OPENROUTER_MODEL.

Three things make this survive a demo
-------------------------------------
**A model chain.** `settings.model_chain` is the primary followed by
OPENROUTER_MODEL_FALLBACKS. A 429, an overloaded provider or a delisted slug moves
to the next model before anything fails. Free slugs are rate limited and get
delisted without notice; a paid one can still be busy.

**A write-through cache**, keyed on a hash of (model, messages), stored as JSON
under `precomputed/llm/`. This is the golden rule applied to the language model:
**a demo should make zero API calls.** Every path that reaches the provider writes
what it got back, so a question is slow at most once, and
`python -m app.seed --warm-llm` pays that cost ahead of time for everything a demo
touches.

Writing at request time is safe because the key is a hash of the exact messages: a
new question adds an entry, it never rewrites an existing one, so nothing warmed
and checked can be altered by whatever gets asked on stage. The consequence worth
knowing is that `precomputed/llm/` goes git-dirty after any session that made a
live call.

**Graceful degradation.** When the cache misses and every model is exhausted,
callers get `LLMUnavailable` — which subclasses `LLMError`, so every existing
`except LLMError` path already degrades correctly. Nothing here may produce a 500:
the ponds, the detector, the queue, the reports and the notices are all statistics
or retrieval, and every one must still render with no API key at all.

Reminder of the architectural rule this file sits underneath: nothing that calls
into this module is allowed to decide whether a pond shrank. Detection already
happened, deterministically, before any of these functions are reachable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_TOKENS = 1200


class LLMNotConfigured(RuntimeError):
    """OPENROUTER_API_KEY / OPENROUTER_MODEL are not both set."""


class LLMError(RuntimeError):
    """The provider call failed or returned something unusable."""


class LLMUnavailable(LLMError):
    """Cache miss and every model in the chain is exhausted.

    Subclasses LLMError on purpose: every caller already catches LLMError and
    degrades to its deterministic path, so exhaustion needs no new handling
    anywhere. Never let it become a 500.
    """


#: Substrings meaning "try the next model", not "give up". Matched against the
#: provider's error text because the OpenAI SDK surfaces OpenRouter's routing
#: errors as generic exceptions rather than typed ones.
_RETRYABLE = (
    "429",
    "rate limit",
    "rate-limit",
    "quota",
    "temporarily",
    "no endpoints found",
    "not a valid model",
    "no such model",
    "model_not_found",
    "is not available",
    "503",
    "502",
    "overloaded",
)


def _is_retryable(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _RETRYABLE)


def is_configured() -> bool:
    """Can we reach the provider? Both key and model must be set."""
    return settings.llm_configured


def is_available() -> bool:
    """Can we produce model output *at all* — live or from the warm cache?

    Features gate on this rather than `is_configured`, because a container that
    ships a warm cache but no API key can still serve everything that was warmed.
    Gating on `is_configured` made the cache dead weight in exactly the deployment
    it was built for: `precomputed/llm/` is in the image, the key is not.
    """
    return is_configured() or cache_stats()["entries"] > 0


def _headers() -> dict[str, str]:
    headers = {"X-Title": settings.openrouter_app_name}
    if settings.openrouter_site_url:
        headers["HTTP-Referer"] = settings.openrouter_site_url
    return headers


_client = None


def get_client():
    """Lazily construct the OpenAI-compatible client aimed at OpenRouter."""
    global _client
    if not is_configured():
        raise LLMNotConfigured(
            "Set OPENROUTER_API_KEY and OPENROUTER_MODEL in .env to enable LLM features."
        )
    if _client is None:
        from openai import OpenAI  # imported lazily so the API boots without the SDK

        _client = OpenAI(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            default_headers=_headers(),
            timeout=DEFAULT_TIMEOUT,
        )
    return _client


def _with_online(name: str, online: bool) -> str:
    if online and not name.endswith(":online"):
        return f"{name}:online"
    return name


def model_name(*, online: bool = False) -> str:
    """The configured primary model, optionally as its `:online` variant."""
    return _with_online(settings.openrouter_model or "", online)


# ---------------------------------------------------------------------------
# Response cache
# ---------------------------------------------------------------------------
def _cache_key(model: str, messages: list[dict[str, str]]) -> str:
    """Stable hash of (model, messages).

    Hashing the exact messages is what makes write-at-request-time safe: a new
    question can only add an entry, never overwrite one that was warmed.
    """
    payload = json.dumps(
        {"model": model, "messages": messages}, sort_keys=True, ensure_ascii=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _cache_path(key: str) -> Path:
    return settings.llm_cache_dir / f"{key}.json"


def cache_read(model: str, messages: list[dict[str, str]]) -> str | None:
    if not settings.llm_cache_enabled:
        return None
    path = _cache_path(_cache_key(model, messages))
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)["response"]
    except (json.JSONDecodeError, KeyError, OSError):
        logger.warning("unreadable LLM cache entry, ignoring: %s", path)
        return None


def cache_read_any(messages: list[dict[str, str]]) -> str | None:
    """Find a cached answer for these messages under *any* model.

    Two situations need this, and both are ordinary rather than exotic:

      * The image ships `precomputed/llm/` but the container has no
        OPENROUTER_MODEL, so there is no model name to build a key from. Without
        this, a warm cache is unreadable exactly where it was meant to be used.
      * The cache was warmed with one model and the deployment is configured for
        another. The answer is still a good answer; refusing it would mean a live
        call for something already paid for.

    A linear scan over a few dozen small files. If this ever holds thousands of
    entries, add a messages-only index — do not make it clever before then.
    """
    if not settings.llm_cache_enabled or not settings.llm_cache_dir.is_dir():
        return None
    for path in sorted(settings.llm_cache_dir.glob("*.json")):
        try:
            with path.open(encoding="utf-8") as fh:
                entry = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue
        if entry.get("messages") == messages:
            logger.debug("LLM cache hit under %s (any-model lookup)", entry.get("model"))
            return entry.get("response")
    return None


def cache_write(model: str, messages: list[dict[str, str]], response: str) -> Path | None:
    """Write one entry. Returns its path, or None when caching is switched off."""
    if not settings.llm_cache_enabled:
        return None
    path = _cache_path(_cache_key(model, messages))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump({"model": model, "messages": messages, "response": response}, fh, indent=1)
        fh.write("\n")
    return path


def _cache_write_quietly(model: str, messages: list[dict[str, str]], response: str) -> None:
    """cache_write, with a read-only or full disk downgraded to a log line.

    A cache that cannot be written is a slow demo. An exception here would be a
    broken one.
    """
    try:
        cache_write(model, messages, response)
    except OSError as exc:
        logger.warning("could not write the LLM cache: %s", exc)


def cache_stats() -> dict[str, Any]:
    directory = settings.llm_cache_dir
    entries = list(directory.glob("*.json")) if directory.is_dir() else []
    return {
        "enabled": settings.llm_cache_enabled,
        "entries": len(entries),
        "path": str(directory),
    }


def complete(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.2,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    online: bool = False,
    response_format: dict[str, Any] | None = None,
    allow_network: bool = True,
) -> str:
    """One completion, returned as text.

    Reads the cache first for every model in the chain, so a cached answer from a
    fallback still counts as a hit. Then tries each model in turn, moving on for a
    rate limit or a delisted slug, and failing hard on anything else — a malformed
    request is a bug and should not be retried against four models.

    Raises LLMUnavailable when nothing is left to try. Callers degrade; they do
    not turn it into a 500.
    """
    resolved = [_with_online(model, online) for model in settings.model_chain]

    for model in resolved:
        cached = cache_read(model, messages)
        if cached is not None:
            logger.debug("LLM cache hit (%s)", model)
            return cached

    # Nothing under the configured chain — but the warmed answer may be filed
    # under a model this deployment does not name. See cache_read_any.
    cached = cache_read_any(messages)
    if cached is not None:
        return cached

    if not resolved:
        # LLMUnavailable, not LLMNotConfigured: every caller already degrades on
        # LLMError, of which this is one.
        raise LLMUnavailable(
            "OPENROUTER_MODEL is not set and nothing matching is in the warm cache."
        )

    if not allow_network:
        raise LLMUnavailable("cache miss, and this call was told not to use the network")
    if not is_configured():
        raise LLMNotConfigured(
            "Set OPENROUTER_API_KEY and OPENROUTER_MODEL in .env to enable LLM features."
        )

    text, answered_by = _call_chain(
        messages,
        resolved,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format=response_format,
    )
    # Write through: this request already paid for the answer, so an identical
    # one must not pay again.
    _cache_write_quietly(answered_by, messages, text)
    return text


def _call_chain(
    messages: list[dict[str, str]],
    resolved: list[str],
    *,
    temperature: float,
    max_tokens: int,
    response_format: dict[str, Any] | None,
) -> tuple[str, str]:
    """Try each model in turn. Returns (text, the model that answered).

    Which model answered is part of the cache key, so it has to come back out —
    a fallback's answer filed under the primary's name would never be read again.
    """
    client = get_client()
    failures: list[str] = []

    for model in resolved:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            kwargs["response_format"] = response_format
        try:
            completion = client.chat.completions.create(**kwargs)
        except Exception as exc:
            failures.append(f"{model}: {exc}")
            if _is_retryable(exc):
                logger.info("model %s unavailable, trying the next: %s", model, exc)
                continue
            logger.warning("LLM call failed on %s: %s", model, exc)
            raise LLMError(str(exc)) from exc

        if not completion.choices:
            failures.append(f"{model}: provider returned no choices")
            continue
        return (completion.choices[0].message.content or "").strip(), model

    raise LLMUnavailable("every model in the chain failed — " + "; ".join(failures))


def warm(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.2,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    online: bool = False,
    response_format: dict[str, Any] | None = None,
) -> str:
    """Populate the cache for these exact messages. Returns "hit" | "warmed".

    Skips anything already cached, so re-running after adding one pond costs one
    pond's worth of requests rather than the whole bundle's.
    """
    resolved = [_with_online(model, online) for model in settings.model_chain]
    if any(cache_read(model, messages) is not None for model in resolved):
        return "hit"
    complete(
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        online=online,
        response_format=response_format,
    )
    return "warmed"


def complete_json(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.0,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    online: bool = False,
    allow_network: bool = True,
) -> Any:
    """Completion parsed as JSON.

    Asks for JSON mode, then still parses defensively — some OpenRouter-routed
    models wrap JSON in prose or a fenced block regardless of what was requested.
    """
    text = complete(
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        online=online,
        response_format={"type": "json_object"},
        allow_network=allow_network,
    )
    return parse_json(text)


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fenced = _FENCE_RE.search(text)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass

    # Last resort: the outermost {...} or [...] in the response.
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue

    raise LLMError(f"could not parse JSON from model response: {text[:200]!r}")


def status() -> dict[str, Any]:
    """Surfaced at /api/health so the UI can grey out LLM panels honestly."""
    return {
        "configured": is_configured(),
        "model": settings.openrouter_model,
        "model_chain": settings.model_chain,
        "cache": cache_stats(),
        "base_url": settings.openrouter_base_url,
        "search_provider": settings.search_provider,
        "search_configured": settings.search_provider == "openrouter_online"
        and is_configured()
        or bool(settings.search_api_key),
    }
