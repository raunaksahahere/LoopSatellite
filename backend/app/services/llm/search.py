"""Swappable web-search backend for evidence corroboration.

Three ways to get results, chosen by SEARCH_PROVIDER:

  openrouter_online  Let the model's `:online` variant do the retrieval. Returns
                     no pre-fetched results — `web_search` reports `online=True`
                     and the caller passes that through to the completion.
  tavily / serper    Fetch results here and hand them to the model as context.
  none               Refuse; the caller reports honestly that no search ran.

Keeping this behind one function means swapping providers touches this file only.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

TIMEOUT = 20.0
MAX_RESULTS = 8


class SearchUnavailable(RuntimeError):
    """No usable search provider is configured, or the provider failed."""


def web_search(query: str) -> tuple[list[dict[str, Any]], bool]:
    """Return (results, use_online_model).

    When `use_online_model` is True the results list is empty by design — the
    retrieval happens inside the model call instead of here.
    """
    provider = (settings.search_provider or "none").lower()

    if provider == "openrouter_online":
        return [], True
    if provider == "tavily":
        return _tavily(query), False
    if provider == "serper":
        return _serper(query), False
    raise SearchUnavailable(f"SEARCH_PROVIDER={provider!r}")


def _tavily(query: str) -> list[dict[str, Any]]:
    if not settings.search_api_key:
        raise SearchUnavailable("SEARCH_API_KEY is not set for the tavily provider")
    try:
        response = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": settings.search_api_key,
                "query": query,
                "max_results": MAX_RESULTS,
                "search_depth": "advanced",
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise SearchUnavailable(f"tavily request failed: {exc}") from exc

    return [
        {
            "title": r.get("title"),
            "url": r.get("url"),
            "snippet": r.get("content"),
            "published": r.get("published_date"),
        }
        for r in payload.get("results", [])[:MAX_RESULTS]
    ]


def _serper(query: str) -> list[dict[str, Any]]:
    if not settings.search_api_key:
        raise SearchUnavailable("SEARCH_API_KEY is not set for the serper provider")
    try:
        response = httpx.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": settings.search_api_key},
            json={"q": query, "num": MAX_RESULTS, "gl": "in"},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise SearchUnavailable(f"serper request failed: {exc}") from exc

    return [
        {
            "title": r.get("title"),
            "url": r.get("link"),
            "snippet": r.get("snippet"),
            "published": r.get("date"),
        }
        for r in payload.get("organic", [])[:MAX_RESULTS]
    ]
