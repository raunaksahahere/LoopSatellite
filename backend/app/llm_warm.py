"""Fill `precomputed/llm/` ahead of time, so a demo makes no API calls.

The golden rule applied to the language model. LoopSatellite's README already
states the principle about geocoding — *"a demo that reaches for the network is a
demo that dies on conference wifi"* — and it applies at least as hard here: a
geocode is one HTTP round trip, a report completion is a model generating 1400
tokens while an audience watches a spinner.

What gets warmed is exactly what a demo touches:

  * the example questions printed under the search box — the ones most likely to
    be clicked, because they are the ones on screen
  * the whole-site report, and one report per flagged event
  * one grounded notice per flagged event

Every call goes through `client.warm`, which skips anything already cached, so
re-running after adding one pond costs one pond's worth of requests.

Two things deliberately not warmed
----------------------------------
**Evidence corroboration.** It runs against an `:online` model whose results
depend on what the web says today; a cached answer from last week would be worse
than an honest live miss.

**Notices with a named officer or addressee.** Those strings are part of the
prompt, so they are part of the cache key. The blank form is warmed; filling a
name in is a live call by design.

One caveat worth knowing: the notice prompt embeds today's date, so notice
entries go stale at midnight. Re-run this on the morning of a demo.
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable
from typing import Any

from app.services.detection import stl_esd
from app.services.llm import client, nl_query, regulatory_rag, report_writer

logger = logging.getLogger(__name__)

#: The questions shown as clickable chips in NLQueryBar. Kept in step by
#: `tests/test_llm_warm.py`, which fails if the frontend's list changes and this
#: one does not — an example on screen that is not warmed is the slowest possible
#: thing for someone to click.
NL_EXAMPLES = (
    "problems around the East Kolkata Wetlands within 5 km",
    "ponds in Ward 108 that lost more than 20% and never recovered",
    "high-confidence losses where buildings are visible",
    "what is going on around Haldia for 5km",
)

# Each entry must match its caller's arguments exactly. The cache key is a hash
# of (model, messages), so a different prompt is a miss and a wasted request.
_NL_KWARGS: dict[str, Any] = {
    "temperature": 0.0,
    "max_tokens": 600,
    "response_format": {"type": "json_object"},
}
_REPORT_KWARGS: dict[str, Any] = {
    "temperature": 0.3,
    "max_tokens": 1400,
    "response_format": {"type": "json_object"},
}
_NOTICE_KWARGS: dict[str, Any] = {"temperature": 0.2, "max_tokens": 1400}


def _nl_messages(question: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": nl_query.SYSTEM},
        {"role": "user", "content": nl_query._context(question)},
    ]


def _report_messages(scope: str, **kwargs: Any) -> list[dict[str, str]]:
    facts = report_writer.collect_facts(scope, **kwargs)
    return [
        {"role": "system", "content": report_writer.SYSTEM},
        {"role": "user", "content": report_writer._prompt(facts, None)},
    ]


def _notice_messages(anomaly_id: str) -> list[dict[str, str]]:
    anomaly = stl_esd.get(anomaly_id)
    if anomaly is None:
        raise KeyError(anomaly_id)
    provisions = [
        {
            "document": hit.chunk.document,
            "citation": hit.chunk.citation,
            "quote": hit.chunk.text,
            "score": hit.score,
        }
        for hit in regulatory_rag.retrieve(anomaly)
    ]
    if not provisions:
        # Nothing retrieved means the drafter refuses to draft and never reaches
        # the model. Nothing to warm, and warming it would be a lie.
        raise LookupError(f"{anomaly_id}: no provision retrieved, so no notice is drafted")
    return [
        {"role": "system", "content": regulatory_rag.SYSTEM},
        {
            "role": "user",
            "content": regulatory_rag._build_prompt(anomaly, provisions, None, None, None),
        },
    ]


Job = tuple[str, Callable[[], list[dict[str, str]]], dict[str, Any]]


def jobs(limit: int | None = None) -> list[Job]:
    """(label, build the messages, kwargs) — messages built lazily so one broken
    event does not stop the rest being warmed."""
    out: list[Job] = []

    for question in NL_EXAMPLES:
        out.append((f"query «{question[:40]}…»", lambda q=question: _nl_messages(q), _NL_KWARGS))

    out.append(("report (whole site)", lambda: _report_messages("all"), _REPORT_KWARGS))

    anomalies = stl_esd.all_anomalies()
    if limit:
        anomalies = anomalies[:limit]
    for anomaly in anomalies:
        aid = anomaly["id"]
        out.append(
            (f"report {aid}", lambda a=aid: _report_messages("anomaly", anomaly_id=a), _REPORT_KWARGS)
        )
        out.append((f"notice {aid}", lambda a=aid: _notice_messages(a), _NOTICE_KWARGS))

    return out


def warm_all(limit: int | None = None) -> dict[str, int]:
    """Warm everything a demo touches. Never raises — reports counts instead."""
    counts = {"warmed": 0, "hit": 0, "skipped": 0, "failed": 0}

    if not client.is_configured():
        logger.warning(
            "No model configured, so there is nothing to warm. Every feature will use "
            "its deterministic fallback, which is a valid way to demo."
        )
        return counts

    for label, build, kwargs in jobs(limit):
        try:
            messages = build()
        except (KeyError, LookupError) as exc:
            counts["skipped"] += 1
            print(f"  skip    {label}: {exc}")
            continue

        try:
            result = client.warm(messages, **kwargs)
        except client.LLMError as exc:
            counts["failed"] += 1
            print(f"  FAILED  {label}: {str(exc)[:130]}")
            continue

        counts[result] += 1
        print(f"  {result:<7} {label}")

    return counts


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, help="only warm the first N events")
    args = ap.parse_args()

    print(f"Warming the LLM cache into {client.cache_stats()['path']}")
    counts = warm_all(args.limit)
    print(
        f"\n  warmed {counts['warmed']} · already cached {counts['hit']} · "
        f"skipped {counts['skipped']} · failed {counts['failed']}"
    )
    if counts["failed"]:
        print(
            "\nSome entries failed. Check OPENROUTER_MODEL is a chat model (not an "
            "embedding one) and that OPENROUTER_MODEL_FALLBACKS gives it somewhere to "
            "fall back to."
        )


if __name__ == "__main__":
    main()
