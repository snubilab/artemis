"""A mapping cached under one critic must not be replayed under another.

Both mapping caches keyed only on LLM_MODEL. Agent 2's critic does not necessarily
use that model -- AGENT2_CRITIC_MODEL_TIER overrides it per domain. Probed live with
LLM_MODEL held constant, tier None / "auto" / "gpt-4o" selected critic models
None / gpt-4o-mini / gpt-4o and produced the SAME key, so a mapping computed under
one provider replayed under another while provenance reported the current
configuration.

That is the failure this whole benchmark exists to avoid: the cache makes a model
comparison cheap, and a colliding key makes it meaningless in a way no output
shows. Found by an adversarial review, not by a run going wrong.
"""
from __future__ import annotations

import pytest

from src.agents.agent2.critic_cache import CriticCache
from src.agents.agent2.criterion_cache import CriterionResultCache

LOCAL = "vllm/Qwen/Qwen2.5-7B-Instruct"


@pytest.fixture(autouse=True)
def stable_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM_MODEL is held constant on purpose -- the tier is the only variable."""
    monkeypatch.setenv("LLM_MODEL", LOCAL)
    monkeypatch.setenv("EMBEDDING_MODEL", "minilm")
    monkeypatch.delenv("AGENT2_CRITIC_MODEL_TIER", raising=False)
    monkeypatch.delenv("AGENT2_CRITIC_SELF_REFLECT", raising=False)


def _criterion_key() -> str:
    return CriterionResultCache._make_key("diabetes", "Condition", "minilm", LOCAL)


@pytest.mark.parametrize("cache_key", [_criterion_key, lambda: CriticCache.make_key("diabetes", "Condition")])
def test_the_tier_changes_the_key(cache_key, monkeypatch: pytest.MonkeyPatch) -> None:
    keys = {}
    for tier in (None, "auto", "gpt-4o"):
        monkeypatch.delenv("AGENT2_CRITIC_MODEL_TIER", raising=False)
        if tier is not None:
            monkeypatch.setenv("AGENT2_CRITIC_MODEL_TIER", tier)
        keys[tier] = cache_key()

    assert len(set(keys.values())) == 3, (
        f"tiers collided onto the same key: {keys}"
    )


def test_self_reflection_changes_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """It filters concepts out of the result, so the two are not interchangeable."""
    monkeypatch.setenv("AGENT2_CRITIC_SELF_REFLECT", "true")
    on = _criterion_key()
    monkeypatch.setenv("AGENT2_CRITIC_SELF_REFLECT", "false")
    off = _criterion_key()

    assert on != off


def test_the_model_still_changes_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """The original guarantee must survive the new one."""
    a = CriterionResultCache._make_key("diabetes", "Condition", "minilm", LOCAL)
    b = CriterionResultCache._make_key("diabetes", "Condition", "minilm", "gpt-4o")

    assert a != b


def test_identical_configuration_still_hits() -> None:
    """A key that never repeats is a cache that never works."""
    assert _criterion_key() == _criterion_key()
