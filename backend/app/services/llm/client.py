"""The one and only LLM client.

Every LLM feature imports from here. No feature constructs its own API call, so
there is exactly one place where the model, the key, the headers and the
timeouts are decided.

Thin wrapper around the OpenAI SDK pointed at **Google AI Studio's
OpenAI-compatible endpoint**. The model name is never hardcoded — it comes from
GEMINI_MODEL.

Why the OpenAI SDK and not google-genai: the four features use only `model`,
`messages`, `temperature`, `max_tokens` and `response_format` — no tools, no
streaming — and all of it is supported through the compatibility layer. Probed
before the migration: `response_format={"type": "json_object"}` returns bare JSON,
while the same call without it returns a ```json fence. The parameter is honored,
not silently ignored.

Three things make this survive a demo
-------------------------------------
**Retry with backoff.** The free tier is a single provider, so there is no chain
to fall down: a 429 means "wait", not "try someone else". Requests are retried
`LLM_MAX_RETRIES` times with exponential backoff, honouring `Retry-After` when the
API sends one — all of it inside a wall-clock budget (`LLM_TOTAL_BUDGET`), with an
explicit per-request timeout (`LLM_REQUEST_TIMEOUT`) so a stalled socket cannot
hold a web request open. On exhaustion the caller gets LLMUnavailable and degrades.

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
import time
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

DEFAULT_MAX_TOKENS = 1200


class LLMNotConfigured(RuntimeError):
    """GEMINI_API_KEY / GEMINI_MODEL are not both set."""


class LLMError(RuntimeError):
    """The provider call failed or returned something unusable."""


class LLMUnavailable(LLMError):
    """Cache miss, and the provider is still rate limited after every retry.

    Subclasses LLMError on purpose: every caller already catches LLMError and
    degrades to its deterministic path, so exhaustion needs no new handling
    anywhere. Never let it become a 500.
    """


#: Substrings meaning "wait and try again", not "give up". Matched against the
#: error text because the OpenAI SDK surfaces Google's errors as generic
#: exceptions rather than typed ones.
#:
#: Deliberately excludes model-not-found. Under OpenRouter a dead slug meant
#: "try the next one"; here there is no next one, and a 404 on the model is a
#: configuration mistake that should surface immediately rather than after
#: three sleeps. `gemini-2.0-flash-lite` 404s exactly this way today.
_RETRYABLE = (
    "429",
    "rate limit",
    "rate-limit",
    "quota",
    "resource_exhausted",
    "temporarily",
    "unavailable",
    "503",
    "502",
    "500",
    "overloaded",
    "deadline",
    # Both spellings: httpx says "Request timed out.", Google says "timeout".
    # Matching only the latter made a hung socket look like a config bug and
    # skip the retry entirely.
    "timeout",
    "timed out",
    "connection error",
    "apiconnectionerror",
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


_client = None


def get_client():
    """Lazily construct the OpenAI-compatible client aimed at Google AI Studio.

    No HTTP-Referer / X-Title headers: those were OpenRouter attribution and mean
    nothing to Google.
    """
    global _client
    if not is_configured():
        raise LLMNotConfigured(
            "Set GEMINI_API_KEY in .env to enable LLM features."
        )
    if _client is None:
        from openai import OpenAI  # imported lazily so the API boots without the SDK

        _client = OpenAI(
            api_key=settings.gemini_api_key,
            base_url=settings.gemini_base_url,
            # Explicit, not the SDK default: a free-tier endpoint under load can
            # stall rather than refuse, and an unbounded socket read would hold a
            # web request open behind it. Also passed per-call in
            # `_call_with_retry`, so a shrinking budget can tighten it.
            timeout=settings.llm_request_timeout,
            max_retries=0,  # retries are ours; the SDK's would hide them from the budget
        )
    return _client


def model_name() -> str:
    """The configured model.

    There is no `:online` variant here. That was an OpenRouter construct that made
    a model do its own web search; Google has no equivalent, so evidence
    corroboration fetches results server-side and passes them as context.
    """
    return settings.gemini_model or ""


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
        GEMINI_MODEL, so there is no model name to build a key from. Without
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
    response_format: dict[str, Any] | None = None,
    allow_network: bool = True,
) -> str:
    """One completion, returned as text.

    Reads the cache first — including `cache_read_any`, which matches on messages
    alone, so entries warmed under a previous provider still answer. Then calls
    the model, retrying a rate limit with backoff and failing fast on anything
    else: a malformed request or a wrong model name is a bug, and sleeping three
    times before reporting it helps nobody.

    Raises LLMUnavailable when the provider is still rate limited after every
    retry. Callers degrade; they do not turn it into a 500.
    """
    model = settings.gemini_model

    if model:
        cached = cache_read(model, messages)
        if cached is not None:
            logger.debug("LLM cache hit (%s)", model)
            return cached

    # Nothing under the configured model — but the warmed answer may be filed
    # under one this deployment does not name, including a previous provider's.
    # See cache_read_any; this is why migrating providers costs no re-warm.
    cached = cache_read_any(messages)
    if cached is not None:
        return cached

    if not allow_network:
        raise LLMUnavailable("cache miss, and this call was told not to use the network")
    if not model:
        raise LLMUnavailable(
            "GEMINI_MODEL is not set and nothing matching is in the warm cache."
        )
    if not is_configured():
        raise LLMNotConfigured("Set GEMINI_API_KEY in .env to enable LLM features.")

    text = _call_with_retry(
        messages,
        model,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format=response_format,
    )
    # Write through: this request already paid for the answer, so an identical
    # one must not pay again.
    _cache_write_quietly(model, messages, text)
    return text


def _retry_after_seconds(exc: Exception, attempt: int) -> float:
    """How long to wait. Google's Retry-After if it sent one, else exponential."""
    header_value = None
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            header_value = response.headers.get("retry-after")
        except Exception:  # noqa: BLE001 - a header lookup must never mask the 429
            header_value = None
    if header_value:
        try:
            return min(float(header_value), 60.0)
        except (TypeError, ValueError):
            pass
    return settings.llm_retry_base_delay * (2**attempt)


def _call_with_retry(
    messages: list[dict[str, str]],
    model: str,
    *,
    temperature: float,
    max_tokens: int,
    response_format: dict[str, Any] | None,
) -> str:
    """Call the model, retrying a rate limit with exponential backoff.

    One provider, so there is nothing to fall over to — waiting is the only
    correct response to a 429, and the free tier's limits are per-minute.
    """
    client = get_client()
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        kwargs["response_format"] = response_format

    deadline = time.monotonic() + settings.llm_total_budget
    last: str = ""
    for attempt in range(settings.llm_max_retries + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            last = last or "budget exhausted before the first attempt"
            break
        try:
            # Never let one attempt outlive the budget: a 30s socket timeout with
            # 4s of budget left would blow through it.
            completion = client.chat.completions.create(
                **kwargs, timeout=min(settings.llm_request_timeout, remaining)
            )
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
            if not _is_retryable(exc):
                # A 400 or a 404 on the model is a configuration bug. Surface it
                # now rather than after three sleeps.
                logger.warning("LLM call failed on %s: %s", model, exc)
                raise LLMError(str(exc)) from exc
            if attempt == settings.llm_max_retries:
                break
            delay = _retry_after_seconds(exc, attempt)
            # Sleeping past the deadline only to fail is time the caller could
            # have spent rendering its deterministic answer.
            if time.monotonic() + delay >= deadline:
                last = f"{last} (gave up: {delay:.0f}s wait exceeds the remaining budget)"
                break
            logger.info(
                "rate limited on %s, retrying in %.1fs (attempt %d/%d)",
                model, delay, attempt + 1, settings.llm_max_retries,
            )
            time.sleep(delay)
            continue

        if not completion.choices:
            last = "provider returned no choices"
            break
        return (completion.choices[0].message.content or "").strip()

    raise LLMUnavailable(
        f"{model} still unavailable after {settings.llm_max_retries} retries "
        f"within {settings.llm_total_budget:.0f}s — {last}"
    )


def warm(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.2,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    response_format: dict[str, Any] | None = None,
) -> str:
    """Populate the cache for these exact messages. Returns "hit" | "warmed".

    Skips anything already cached, so re-running after adding one pond costs one
    pond's worth of requests rather than the whole bundle's.
    """
    if cache_read(settings.gemini_model, messages) is not None or (
        cache_read_any(messages) is not None
    ):
        return "hit"
    complete(
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format=response_format,
    )
    return "warmed"


def complete_json(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.0,
    max_tokens: int = DEFAULT_MAX_TOKENS,
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
        "model": settings.gemini_model,
        "provider": "google-ai-studio",
        "cache": cache_stats(),
        "base_url": settings.gemini_base_url,
        "search_provider": settings.search_provider,
        # No provider-side search here, so this is purely "is a search key set".
        "search_configured": settings.search_provider in ("tavily", "serper")
        and bool(settings.search_api_key),
    }
