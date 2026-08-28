"""Swappable web-search backend for evidence corroboration.

Two ways to get results, chosen by SEARCH_PROVIDER:

  tavily / serper    Fetch results here and hand them to the model as context.
  none               Refuse; the caller reports honestly that no search ran.

There used to be a third, `openrouter_online`, which let the model's `:online`
variant do its own retrieval. Google AI Studio has no equivalent, so it was
removed with the provider rather than left to fail at request time. Fetching
here is arguably better anyway: the results are visible in the logs and the same
for every model.

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


def web_search(query: str) -> list[dict[str, Any]]:
    """Fetch search results for the model to read. Raises SearchUnavailable."""
    provider = (settings.search_provider or "none").lower()

    if provider == "tavily":
        return _tavily(query)
    if provider == "serper":
        return _serper(query)
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
