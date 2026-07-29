"""Every cache key must carry the resolved LLM model.

This is a class test, not an instance test. The same defect — a key built from
the criterion text alone — was found in three separate caches, and each one
returns another model's answer as a cache hit that looks identical to a fresh
one. A new cache added without the model in its key belongs in CACHES below.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from unittest.mock import Mock, patch

import pytest

from src.agents.agent1.parser import LogicDecomposer
from src.agents.agent2.critic_cache import CriticCache
from src.agents.agent2.criterion_cache import CriterionCacheEntry, CriterionResultCache
from src.settings import settings

MODEL_A = "vllm/probe-model-a"
MODEL_B = "gpt-probe-model-b"
TEXT = "History of Stroke"


@contextmanager
def using_model(model: str) -> Iterator[None]:
    """resolve_model() reads settings live, so setting the attribute is enough."""
    previous = settings.LLM_MODEL
    settings.LLM_MODEL = model
    try:
        yield
    finally:
        settings.LLM_MODEL = previous


def _entry() -> CriterionCacheEntry:
    return CriterionCacheEntry(
        concept_ids=[201826],
        expression={},
        name=TEXT,
        domain="Condition",
        created_at="2026-07-29T00:00:00Z",
    )


def _criterion_cache_hits_across_model_switch() -> bool:
    cache = CriterionResultCache(max_entries=8, ttl_hours=1.0)
    with using_model(MODEL_A):
        cache.put(TEXT, "Condition", _entry())
    with using_model(MODEL_B):
        return cache.get(TEXT, "Condition") is not None


def _critic_cache_hits_across_model_switch() -> bool:
    cache = CriticCache(max_entries=8, ttl_hours=1)
    with using_model(MODEL_A):
        cache.put(cache.make_key(TEXT, "Condition"), [201826])
    with using_model(MODEL_B):
        return cache.get(cache.make_key(TEXT, "Condition")) is not None


def _agent1_ir_cache_hits_across_model_switch() -> bool:
    with patch("src.agents.agent1.parser.get_llm", return_value=Mock()):
        with using_model(MODEL_A):
            key_a = LogicDecomposer().model_name
        with using_model(MODEL_B):
            key_b = LogicDecomposer().model_name
    return key_a == key_b


CACHES: dict[str, Callable[[], bool]] = {
    "agent2_criterion_cache": _criterion_cache_hits_across_model_switch,
    "agent2_critic_cache": _critic_cache_hits_across_model_switch,
    "agent1_ir_cache": _agent1_ir_cache_hits_across_model_switch,
}


@pytest.mark.parametrize("name", sorted(CACHES))
def test_switching_llm_model_must_not_hit_another_models_entry(name: str) -> None:
    assert not CACHES[name](), (
        f"{name} served an entry written under {MODEL_A} while the resolved "
        f"model was {MODEL_B}"
    )


@pytest.mark.parametrize("name", sorted(CACHES))
def test_same_model_still_hits(name: str) -> None:
    """The keys must discriminate on model, not simply never match."""
    with using_model(MODEL_A):
        if name == "agent2_criterion_cache":
            cache = CriterionResultCache(max_entries=8, ttl_hours=1.0)
            cache.put(TEXT, "Condition", _entry())
            assert cache.get(TEXT, "Condition") is not None
        elif name == "agent2_critic_cache":
            critic_cache = CriticCache(max_entries=8, ttl_hours=1)
            key = critic_cache.make_key(TEXT, "Condition")
            critic_cache.put(key, [201826])
            assert critic_cache.get(critic_cache.make_key(TEXT, "Condition")) is not None
        else:
            with patch("src.agents.agent1.parser.get_llm", return_value=Mock()):
                assert LogicDecomposer().model_name == LogicDecomposer().model_name


def test_agent1_model_key_is_the_resolved_model_not_a_placeholder() -> None:
    with patch("src.agents.agent1.parser.get_llm", return_value=Mock()):
        with using_model(MODEL_A):
            assert LogicDecomposer().model_name == MODEL_A
