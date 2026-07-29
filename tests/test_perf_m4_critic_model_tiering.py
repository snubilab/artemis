"""
SPEC-PERF-001 M4: Critic Model Tiering — Tests for domain-aware model selection.

Tests:
- Well-defined domains (Condition, Drug, Measurement) use gpt-4o-mini
- Ambiguous domains (Observation, Procedure, unknown) use gpt-4o
- AGENT2_CRITIC_MODEL_TIER env var overrides:
  - "auto" (default): domain-based selection
  - "gpt-4o": always gpt-4o
  - "gpt-4o-mini": always gpt-4o-mini
"""

import os
from unittest.mock import patch

import pytest

from src.agents.agent2.critic import select_critic_model


class TestAutoModeTiering:
    """Verify domain-based model selection in 'auto' mode.

    Auto mode became opt-in on 2026-07-29. It used to be the default, which meant
    Condition, Drug and Measurement silently resolved to the literal "gpt-4o-mini"
    — no vllm/ prefix, so it bypassed LLM_MODEL entirely and billed OpenAI even
    when the pipeline was configured to run locally. The tiering itself is
    unchanged and still worth having; only its default flipped, so these tests now
    ask for it explicitly. See tests/test_model_selection_is_uniform.py.
    """

    @pytest.fixture(autouse=True)
    def _enable_auto_mode(self, monkeypatch):
        monkeypatch.setenv("AGENT2_CRITIC_MODEL_TIER", "auto")

    def test_condition_uses_mini(self):
        """Condition domain should use gpt-4o-mini."""
        assert select_critic_model("Condition") == "gpt-4o-mini"

    def test_drug_uses_mini(self):
        """Drug domain should use gpt-4o-mini."""
        assert select_critic_model("Drug") == "gpt-4o-mini"

    def test_measurement_uses_mini(self):
        """Measurement domain should use gpt-4o-mini."""
        assert select_critic_model("Measurement") == "gpt-4o-mini"

    def test_observation_uses_full(self):
        """Observation domain should use gpt-4o."""
        assert select_critic_model("Observation") == "gpt-4o"

    def test_procedure_uses_full(self):
        """Procedure domain should use gpt-4o."""
        assert select_critic_model("Procedure") == "gpt-4o"

    def test_none_domain_uses_full(self):
        """No domain hint should use gpt-4o."""
        assert select_critic_model(None) == "gpt-4o"

    def test_unknown_domain_uses_full(self):
        """Unknown domain should use gpt-4o."""
        assert select_critic_model("SomethingElse") == "gpt-4o"


class TestFollowIsTheDefault:
    """The default must be "whatever LLM_MODEL says", with no env var set.

    This is the regression that matters: a returned literal has no vllm/ prefix,
    so get_llm falls through to OpenRouter and the configured model is bypassed.
    """

    @pytest.fixture(autouse=True)
    def _no_tier_env(self, monkeypatch):
        monkeypatch.delenv("AGENT2_CRITIC_MODEL_TIER", raising=False)

    @pytest.mark.parametrize(
        "domain", ["Condition", "Drug", "Measurement", "Observation", "Procedure", None]
    )
    def test_every_domain_follows_llm_model(self, domain):
        assert select_critic_model(domain) is None


class TestEnvVarOverride:
    """Verify AGENT2_CRITIC_MODEL_TIER env var overrides."""

    def test_force_gpt4o(self):
        """AGENT2_CRITIC_MODEL_TIER=gpt-4o should always use gpt-4o."""
        with patch.dict(os.environ, {"AGENT2_CRITIC_MODEL_TIER": "gpt-4o"}):
            assert select_critic_model("Condition") == "gpt-4o"
            assert select_critic_model("Drug") == "gpt-4o"

    def test_force_gpt4o_mini(self):
        """AGENT2_CRITIC_MODEL_TIER=gpt-4o-mini should always use gpt-4o-mini."""
        with patch.dict(os.environ, {"AGENT2_CRITIC_MODEL_TIER": "gpt-4o-mini"}):
            assert select_critic_model("Observation") == "gpt-4o-mini"
            assert select_critic_model(None) == "gpt-4o-mini"

    def test_auto_mode_explicit(self):
        """AGENT2_CRITIC_MODEL_TIER=auto should use domain-based selection."""
        with patch.dict(os.environ, {"AGENT2_CRITIC_MODEL_TIER": "auto"}):
            assert select_critic_model("Condition") == "gpt-4o-mini"
            assert select_critic_model("Observation") == "gpt-4o"
