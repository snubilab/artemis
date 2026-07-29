"""One setting must move every LLM call site.

Three places used to pin their own model, each locally reasonable and collectively
making the pipeline unconfigurable:

  - the comparator hardcoded vllm/snuh/hari-q3-8b
  - the Agent 2 critic returned a literal "gpt-4o-mini" for Condition, Drug and
    Measurement — the three domains carrying nearly every criterion in a trial
  - the classifier defaulted to a specific 8B model

The critic one was the dangerous shape: "gpt-4o-mini" has no vllm/ prefix, so it fell
through to OpenRouter no matter what LLM_MODEL said. A benchmark table labelled with a
local model would have been mostly produced by OpenAI, and nothing in the output would
have revealed it. These tests exist so that cannot come back.
"""
from __future__ import annotations

import importlib
import sys
from typing import Any

import pytest

# Reloading settings is what makes an env change visible; import order matters.
_MODULES = (
    "src.settings",
    "src.utils.llm",
    "src.agents.comparator.recommender",
    "src.agents.agent2.critic",
    "src.agents.agent1.threshold_classifier",
)

TARGETS = [
    "vllm/snuh/hari-q3-8b",
    "vllm/google/medgemma-27b-text-it",
    "gpt-4o",
]


def _reload_with(monkeypatch: pytest.MonkeyPatch, llm_model: str, tier: str | None) -> dict[str, Any]:
    monkeypatch.setenv("LLM_MODEL", llm_model)
    monkeypatch.delenv("COMPARATOR_LLM_MODEL", raising=False)
    if tier is None:
        monkeypatch.delenv("AGENT2_CRITIC_MODEL_TIER", raising=False)
    else:
        monkeypatch.setenv("AGENT2_CRITIC_MODEL_TIER", tier)

    for name in _MODULES:
        if name in sys.modules:
            importlib.reload(sys.modules[name])

    from src.agents.agent1 import threshold_classifier as clf
    from src.agents.agent2 import critic as cri
    from src.agents.comparator import recommender as rec
    from src.utils.llm import resolve_model

    return {
        "comparator": resolve_model(rec.DEFAULT_LLM_MODEL),
        "critic_well_defined": resolve_model(cri.select_critic_model("Drug")),
        "critic_other": resolve_model(cri.select_critic_model("Observation")),
        "classifier": resolve_model(clf.DEFAULT_MODEL),
    }


@pytest.mark.parametrize("target", TARGETS)
def test_llm_model_moves_every_call_site(monkeypatch: pytest.MonkeyPatch, target: str) -> None:
    resolved = _reload_with(monkeypatch, target, tier=None)
    assert set(resolved.values()) == {target}, (
        f"these call sites did not follow LLM_MODEL={target}: "
        f"{ {k: v for k, v in resolved.items() if v != target} }"
    )


def test_critic_does_not_smuggle_openai_in_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """The specific regression: a local model configured, OpenAI actually used."""
    resolved = _reload_with(monkeypatch, "vllm/snuh/hari-q3-8b", tier=None)
    for site, model in resolved.items():
        assert model.startswith("vllm/"), f"{site} resolved to {model!r}, which is not local"


def test_explicit_tiering_still_works_when_asked_for(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cost tiering is not removed, only made opt-in."""
    resolved = _reload_with(monkeypatch, "gpt-4o", tier="auto")
    assert resolved["critic_well_defined"] == "gpt-4o-mini"
    assert resolved["critic_other"] == "gpt-4o"


def test_a_literal_tier_value_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    resolved = _reload_with(monkeypatch, "gpt-4o", tier="vllm/google/medgemma-27b-text-it")
    assert resolved["critic_well_defined"] == "vllm/google/medgemma-27b-text-it"


def test_comparator_override_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPARATOR_LLM_MODEL", "vllm/other-model")
    monkeypatch.setenv("LLM_MODEL", "gpt-4o")
    for name in _MODULES:
        if name in sys.modules:
            importlib.reload(sys.modules[name])
    from src.agents.comparator import recommender as rec
    from src.utils.llm import resolve_model

    assert resolve_model(rec.DEFAULT_LLM_MODEL) == "vllm/other-model"
