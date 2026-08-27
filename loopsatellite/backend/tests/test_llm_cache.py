"""The LLM response cache, the model chain, and the warm path.

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
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "openrouter_model", "test/primary")
    monkeypatch.setattr(settings, "openrouter_model_fallbacks", "test/backup")
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
# Model chain
# ---------------------------------------------------------------------------
def test_a_rate_limit_falls_through_to_the_next_model(cache, monkeypatch):
    def behaviour(model):
        if model == "test/primary":
            return RuntimeError("Error code: 429 - rate limit exceeded")
        return "answered by the backup"

    provider = install(monkeypatch, behaviour)
    assert client.complete(MESSAGES) == "answered by the backup"
    assert provider.calls == ["test/primary", "test/backup"]


def test_a_fallbacks_answer_is_cached_under_the_model_that_gave_it(cache, monkeypatch):
    """A fallback's answer filed under the primary's name would never be read again."""

    def behaviour(model):
        if model == "test/primary":
            return RuntimeError("429 rate limit")
        return "backup answer"

    install(monkeypatch, behaviour)
    client.complete(MESSAGES)
    assert client.cache_read("test/backup", MESSAGES) == "backup answer"
    assert client.cache_read("test/primary", MESSAGES) is None


def test_a_cached_fallback_answer_still_counts_as_a_hit(cache, monkeypatch):
    def behaviour(model):
        if model == "test/primary":
            return RuntimeError("429 rate limit")
        return "backup answer"

    provider = install(monkeypatch, behaviour)
    client.complete(MESSAGES)
    before = len(provider.calls)
    assert client.complete(MESSAGES) == "backup answer"
    assert len(provider.calls) == before


def test_a_malformed_request_fails_immediately(cache, monkeypatch):
    """A 400 is a bug in our prompt. Retrying it against every model wastes time
    and money and still fails — this is exactly what an embedding model in
    OPENROUTER_MODEL produced."""
    provider = install(
        monkeypatch,
        lambda m: RuntimeError(
            "Error code: 400 - is an embedding model and cannot be used with "
            "the chat/completions endpoint"
        ),
    )
    with pytest.raises(client.LLMError):
        client.complete(MESSAGES)
    assert provider.calls == ["test/primary"], "a 400 must not be retried down the chain"


def test_exhausting_the_chain_raises_llm_unavailable(cache, monkeypatch):
    install(monkeypatch, lambda m: RuntimeError("503 overloaded"))
    with pytest.raises(client.LLMUnavailable):
        client.complete(MESSAGES)


def test_llm_unavailable_is_an_llm_error(cache):
    """Every feature already catches LLMError and degrades. Exhaustion must land
    in those handlers without any of them being changed."""
    assert issubclass(client.LLMUnavailable, client.LLMError)


def test_the_chain_deduplicates_and_keeps_order():
    settings = config.get_settings()
    original = (settings.openrouter_model, settings.openrouter_model_fallbacks)
    try:
        settings.openrouter_model = "a"
        settings.openrouter_model_fallbacks = "b, a , c,"
        assert settings.model_chain == ["a", "b", "c"]
    finally:
        settings.openrouter_model, settings.openrouter_model_fallbacks = original


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
    container has no OPENROUTER_MODEL, and the answer must still come back."""
    install(monkeypatch, lambda m: "warmed by the primary")
    client.complete(MESSAGES)

    settings = config.get_settings()
    monkeypatch.setattr(settings, "openrouter_model", None)
    monkeypatch.setattr(settings, "openrouter_model_fallbacks", "")
    monkeypatch.setattr(settings, "openrouter_api_key", None)

    assert client.is_available(), "a warm cache alone should count as available"
    assert client.complete(MESSAGES) == "warmed by the primary"


def test_a_warmed_answer_is_found_under_a_different_model(cache, monkeypatch):
    """Warmed with one model, deployed with another. The answer already exists."""
    install(monkeypatch, lambda m: "warmed by the old model")
    client.complete(MESSAGES)

    monkeypatch.setattr(config.get_settings(), "openrouter_model", "test/some-other-model")
    monkeypatch.setattr(config.get_settings(), "openrouter_model_fallbacks", "")

    def explode():
        raise AssertionError("should have been served from the cache")

    monkeypatch.setattr(client, "get_client", explode)
    assert client.complete(MESSAGES) == "warmed by the old model"


def test_nothing_configured_and_nothing_cached_degrades(cache, monkeypatch):
    settings = config.get_settings()
    monkeypatch.setattr(settings, "openrouter_model", None)
    monkeypatch.setattr(settings, "openrouter_model_fallbacks", "")
    with pytest.raises(client.LLMUnavailable):
        client.complete(MESSAGES)


def test_is_available_is_false_with_no_key_and_an_empty_cache(cache, monkeypatch):
    monkeypatch.setattr(config.get_settings(), "openrouter_api_key", None)
    assert not client.is_available()
