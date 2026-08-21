"""The one and only LLM client.

Every LLM feature imports from here. No feature constructs its own API call, so
there is exactly one place where the model, the key, the headers and the
timeouts are decided.

Thin wrapper around the OpenAI SDK pointed at OpenRouter. The model name is never
hardcoded — it comes from OPENROUTER_MODEL.

Reminder of the architectural rule this file sits underneath: nothing that calls
into this module is allowed to decide whether a pond shrank. Detection already
happened, deterministically, before any of these functions are reachable.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_TOKENS = 1200


class LLMNotConfigured(RuntimeError):
    """OPENROUTER_API_KEY / OPENROUTER_MODEL are not both set."""


class LLMError(RuntimeError):
    """The provider call failed or returned something unusable."""


def is_configured() -> bool:
    return settings.llm_configured


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


def model_name(*, online: bool = False) -> str:
    """The configured model, optionally as OpenRouter's web-search `:online` variant."""
    name = settings.openrouter_model or ""
    if online and not name.endswith(":online"):
        return f"{name}:online"
    return name


def complete(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.2,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    online: bool = False,
    response_format: dict[str, Any] | None = None,
) -> str:
    """One completion, returned as text. Raises LLMError on any provider failure."""
    client = get_client()
    kwargs: dict[str, Any] = {
        "model": model_name(online=online),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        kwargs["response_format"] = response_format
    try:
        completion = client.chat.completions.create(**kwargs)
    except Exception as exc:  # provider/network/auth — all the same to the caller
        logger.warning("LLM call failed: %s", exc)
        raise LLMError(str(exc)) from exc

    if not completion.choices:
        raise LLMError("provider returned no choices")
    return (completion.choices[0].message.content or "").strip()


def complete_json(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.0,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    online: bool = False,
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
        "base_url": settings.openrouter_base_url,
        "search_provider": settings.search_provider,
        "search_configured": settings.search_provider == "openrouter_online"
        and is_configured()
        or bool(settings.search_api_key),
    }
