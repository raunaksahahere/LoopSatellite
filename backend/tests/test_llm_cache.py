"""The LLM response cache, the retry policy, and the warm path.

The golden rule applied to the language model: a demo should make zero API calls.
Everything here runs with the provider stubbed out — a test that called OpenRouter
would be slow, billed, and would fail on a machine with no key.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core import config
from app.services.llm import client

MESSAGES = [
    {"role": "system", "content": "You are a test."},
    {"role": "user", "content": "Say ok."},
]


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """A real cache directory, isolated from the shipped one."""
    settings = config.get_settings()
    monkeypatch.setattr(type(settings), "llm_cache_dir", property(lambda _: tmp_path))
    monkeypatch.setattr(settings, "llm_cache_enabled", True)
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(settings, "gemini_model", "test/primary")
    # No sleeping in tests. The backoff itself is asserted separately.
    monkeypatch.setattr(settings, "llm_retry_base_delay", 0.0)
    monkeypatch.setattr(settings, "llm_max_retries", 2)
    return tmp_path


class _Provider:
    """Stand-in for the OpenAI client. Records calls; can be told to fail."""

    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.calls: list[str] = []
        self.chat = self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        model = kwargs["model"]
        self.calls.append(model)
        outcome = self.behaviour(model)
        if isinstance(outcome, Exception):
            raise outcome

        class _Msg:
            content = outcome

        class _Choice:
            message = _Msg()

        class _Completion:
            choices: tuple = (_Choice(),)

        return _Completion()


def install(monkeypatch, behaviour) -> _Provider:
    provider = _Provider(behaviour)
    monkeypatch.setattr(client, "get_client", lambda: provider)
    return provider


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
def test_a_second_identical_call_makes_no_request(cache, monkeypatch):
    provider = install(monkeypatch, lambda m: "first answer")

    assert client.complete(MESSAGES) == "first answer"
    assert len(provider.calls) == 1

    assert client.complete(MESSAGES) == "first answer"
    assert len(provider.calls) == 1, "the second call should have been served from cache"


def test_a_different_question_is_a_different_entry(cache, monkeypatch):
    provider = install(monkeypatch, lambda m: "answer")
    client.complete(MESSAGES)
    client.complete([*MESSAGES[:1], {"role": "user", "content": "Say something else."}])
    assert len(provider.calls) == 2
    assert len(list(Path(cache).glob("*.json"))) == 2


def test_a_new_question_never_overwrites_a_warmed_one(cache, monkeypatch):
    """Why write-at-request-time is safe: the key is a hash of the exact messages,
    so whatever gets asked on stage cannot alter what was warmed and checked."""
    install(monkeypatch, lambda m: "warmed answer")
    client.complete(MESSAGES)
    warmed = client.cache_read("test/primary", MESSAGES)

    install(monkeypatch, lambda m: "live answer")
    client.complete([*MESSAGES[:1], {"role": "user", "content": "Something new."}])

    assert client.cache_read("test/primary", MESSAGES) == warmed


def test_a_cached_answer_is_served_with_no_network_at_all(cache, monkeypatch):
    install(monkeypatch, lambda m: "cached")
    client.complete(MESSAGES)

    def explode():
        raise AssertionError("a cache hit must not construct a provider client")

    monkeypatch.setattr(client, "get_client", explode)
    assert client.complete(MESSAGES) == "cached"


def test_allow_network_false_refuses_rather_than_calling(cache, monkeypatch):
    install(monkeypatch, lambda m: "should not happen")
    with pytest.raises(client.LLMUnavailable):
        client.complete(MESSAGES, allow_network=False)


def test_an_unreadable_entry_is_ignored_not_fatal(cache, monkeypatch):
    install(monkeypatch, lambda m: "fresh")
    client.complete(MESSAGES)
    for path in Path(cache).glob("*.json"):
        path.write_text("{ this is not json", encoding="utf-8")
    assert client.complete(MESSAGES) == "fresh"


def test_caching_can_be_switched_off(cache, monkeypatch):
    monkeypatch.setattr(config.get_settings(), "llm_cache_enabled", False)
    provider = install(monkeypatch, lambda m: "uncached")
    client.complete(MESSAGES)
    client.complete(MESSAGES)
    assert len(provider.calls) == 2


# ---------------------------------------------------------------------------
# Retry policy — one provider, so a 429 means wait, not "try someone else"
# ---------------------------------------------------------------------------
def test_a_rate_limit_is_retried_and_then_succeeds(cache, monkeypatch):
    calls = {"n": 0}

    def behaviour(model):
        calls["n"] += 1
        if calls["n"] == 1:
            return RuntimeError("Error code: 429 - RESOURCE_EXHAUSTED: rate limit")
        return "answered on the retry"

    provider = install(monkeypatch, behaviour)
    assert client.complete(MESSAGES) == "answered on the retry"
    assert len(provider.calls) == 2


def test_a_persistent_rate_limit_raises_llm_unavailable(cache, monkeypatch):
    provider = install(monkeypatch, lambda m: RuntimeError("429 rate limit"))
    with pytest.raises(client.LLMUnavailable):
        client.complete(MESSAGES)
    # 1 initial attempt + llm_max_retries
    assert len(provider.calls) == 3


def test_a_malformed_request_fails_immediately(cache, monkeypatch):
    """A 400 is a bug in our prompt. Sleeping three times before reporting it
    helps nobody."""
    provider = install(
        monkeypatch,
        lambda m: RuntimeError("Error code: 400 - INVALID_ARGUMENT: bad request"),
    )
    with pytest.raises(client.LLMError):
        client.complete(MESSAGES)
    assert len(provider.calls) == 1, "a 400 must not be retried"


def test_a_retired_model_fails_immediately(cache, monkeypatch):
    """Under OpenRouter a dead slug meant 'try the next one'. There is no next
    one here, so a 404 on the model is a config mistake to surface at once —
    this is exactly what gemini-2.0-flash-lite does today."""
    provider = install(
        monkeypatch,
        lambda m: RuntimeError(
            "Error code: 404 - This model models/gemini-2.0-flash-lite is no longer available."
        ),
    )
    with pytest.raises(client.LLMError):
        client.complete(MESSAGES)
    assert len(provider.calls) == 1


def test_backoff_grows_and_honours_retry_after(monkeypatch):
    settings = config.get_settings()
    monkeypatch.setattr(settings, "llm_retry_base_delay", 1.0)

    plain = RuntimeError("429")
    assert client._retry_after_seconds(plain, 0) == 1.0
    assert client._retry_after_seconds(plain, 1) == 2.0
    assert client._retry_after_seconds(plain, 2) == 4.0

    class _WithHeader(RuntimeError):
        response = type("R", (), {"headers": {"retry-after": "7"}})()

    assert client._retry_after_seconds(_WithHeader("429"), 0) == 7.0


def test_a_timeout_is_retried_not_treated_as_a_config_bug(cache, monkeypatch):
    """httpx spells it "Request timed out." — no substring "timeout" in sight.

    Matching only the latter classified a hung socket as non-retryable, so a
    stalled free-tier endpoint failed on the first attempt instead of backing off.
    """
    provider = install(monkeypatch, lambda m: RuntimeError("Request timed out."))
    with pytest.raises(client.LLMUnavailable):
        client.complete(MESSAGES)
    assert len(provider.calls) == 3


def test_the_total_budget_stops_retrying_before_the_deadline(cache, monkeypatch):
    """Three retries each waiting a `Retry-After: 60` is minutes of a held web
    request. The budget gives up early so the caller can render its
    deterministic answer instead."""
    settings = config.get_settings()
    monkeypatch.setattr(settings, "llm_total_budget", 0.5)
    monkeypatch.setattr(settings, "llm_retry_base_delay", 30.0)

    slept: list[float] = []
    monkeypatch.setattr(client.time, "sleep", slept.append)

    provider = install(monkeypatch, lambda m: RuntimeError("429 rate limit"))
    with pytest.raises(client.LLMUnavailable):
        client.complete(MESSAGES)
    assert slept == [], "a 30s wait must not be taken inside a 0.5s budget"
    assert len(provider.calls) == 1


def test_each_attempt_is_capped_by_the_remaining_budget(cache, monkeypatch):
    """A 30s socket timeout with 4s of budget left would blow through it, so the
    per-request timeout is min(configured, remaining)."""
    settings = config.get_settings()
    monkeypatch.setattr(settings, "llm_request_timeout", 30.0)
    monkeypatch.setattr(settings, "llm_total_budget", 2.0)

    seen: list[float] = []

    def behaviour(model):
        return "fine"

    provider = install(monkeypatch, behaviour)
    original = provider.create

    def spy(**kwargs):
        seen.append(kwargs["timeout"])
        return original(**kwargs)

    monkeypatch.setattr(provider, "create", spy)
    client.complete(MESSAGES)
    assert seen and seen[0] <= 2.0


def test_llm_unavailable_is_an_llm_error(cache):
    """Every feature already catches LLMError and degrades. Exhaustion must land
    in those handlers without any of them being changed."""
    assert issubclass(client.LLMUnavailable, client.LLMError)


# ---------------------------------------------------------------------------
# Warm
# ---------------------------------------------------------------------------
def test_warm_skips_what_is_already_cached(cache, monkeypatch):
    provider = install(monkeypatch, lambda m: "answer")
    assert client.warm(MESSAGES) == "warmed"
    assert client.warm(MESSAGES) == "hit"
    assert len(provider.calls) == 1


def test_the_warmed_examples_match_the_ones_on_screen():
    """An example printed under the search box that is not warmed is the slowest
    possible thing for someone to click."""
    from app import llm_warm

    source = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "src"
        / "components"
        / "llm"
        / "NLQueryBar.tsx"
    ).read_text(encoding="utf-8")
    block = re.search(r"const EXAMPLES = \[(.*?)\]", source, re.DOTALL)
    assert block, "could not find the EXAMPLES list in NLQueryBar.tsx"
    on_screen = re.findall(r"'([^']+)'", block.group(1))

    assert sorted(on_screen) == sorted(llm_warm.NL_EXAMPLES), (
        "NLQueryBar.tsx and llm_warm.NL_EXAMPLES have drifted:\n"
        f"  on screen: {sorted(on_screen)}\n"
        f"  warmed   : {sorted(llm_warm.NL_EXAMPLES)}"
    )


def test_warm_all_reports_rather_than_raising_when_unconfigured(monkeypatch):
    from app import llm_warm

    monkeypatch.setattr(client, "is_configured", lambda: False)
    counts = llm_warm.warm_all()
    assert counts == {"warmed": 0, "hit": 0, "skipped": 0, "failed": 0}


# ---------------------------------------------------------------------------
# A shipped cache must be readable with no configuration at all
# ---------------------------------------------------------------------------
def test_a_warmed_answer_is_found_with_no_model_configured(cache, monkeypatch):
    """The deployment this was built for: the image ships precomputed/llm/, the
    container has no GEMINI_MODEL, and the answer must still come back."""
    install(monkeypatch, lambda m: "warmed by the primary")
    client.complete(MESSAGES)

    settings = config.get_settings()
    monkeypatch.setattr(settings, "gemini_model", "")
    monkeypatch.setattr(settings, "gemini_api_key", None)

    assert client.is_available(), "a warm cache alone should count as available"
    assert client.complete(MESSAGES) == "warmed by the primary"


def test_a_warmed_answer_is_found_under_a_different_model(cache, monkeypatch):
    """Warmed with one model, deployed with another. The answer already exists."""
    install(monkeypatch, lambda m: "warmed by the old model")
    client.complete(MESSAGES)

    monkeypatch.setattr(config.get_settings(), "gemini_model", "test/some-other-model")

    def explode():
        raise AssertionError("should have been served from the cache")

    monkeypatch.setattr(client, "get_client", explode)
    assert client.complete(MESSAGES) == "warmed by the old model"


def test_nothing_configured_and_nothing_cached_degrades(cache, monkeypatch):
    settings = config.get_settings()
    monkeypatch.setattr(settings, "gemini_model", "")
    with pytest.raises(client.LLMUnavailable):
        client.complete(MESSAGES)


def test_is_available_is_false_with_no_key_and_an_empty_cache(cache, monkeypatch):
    monkeypatch.setattr(config.get_settings(), "gemini_api_key", None)
    assert not client.is_available()
