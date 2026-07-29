"""
Tests for SPEC-MAP-002 M3: Critic self-reflection with counterevidence.

Validates the two-pass critic behavior where Pass 1 evaluates concepts
and Pass 2 reflects on selections to detect abbreviation confusion,
domain mismatch, etc.
"""

import os
from unittest.mock import patch, MagicMock

import pytest

from src.agents.agent2.critic import ConceptCritic, CriticSelection


class TestCriticSelectionModel:
    """Test enhanced CriticSelection model with reflection fields."""

    def test_default_values(self):
        """Default CriticSelection has backward-compatible defaults."""
        sel = CriticSelection(
            concept_id=12345,
            relevant=True,
            reasoning="Direct match"
        )
        assert sel.confidence == 1.0
        assert sel.potential_issue == "none"
        assert sel.assessment == "correct"
        assert sel.recommended_action == "keep"

    def test_contradicted_assessment(self):
        """CriticSelection can represent a contradicted concept."""
        sel = CriticSelection(
            concept_id=12345,
            relevant=True,
            reasoning="Initially looked relevant",
            confidence=0.2,
            potential_issue="abbreviation_confusion",
            assessment="contradicted",
            recommended_action="drop",
        )
        assert sel.assessment == "contradicted"
        assert sel.recommended_action == "drop"
        assert sel.confidence == 0.2

    def test_partially_supported(self):
        """CriticSelection can represent a partially supported concept."""
        sel = CriticSelection(
            concept_id=12345,
            relevant=True,
            reasoning="May be relevant",
            confidence=0.6,
            potential_issue="too_specific",
            assessment="partially_supported",
            recommended_action="rerank",
        )
        assert sel.assessment == "partially_supported"


class TestCriticSelfReflection:
    """Test self-reflection behavior in ConceptCritic.evaluate()."""

    def _make_kg_concept(self, concept_id, name="Test", domain="Condition"):
        mock = MagicMock()
        mock.concept_id = concept_id
        mock.concept_name = name
        mock.domain_id = domain
        mock.vocabulary_id = "SNOMED"
        mock.relationship = "seed"
        return mock

    @pytest.fixture
    def critic_with_reflect(self):
        """Create critic with self-reflection enabled."""
        with patch.dict(os.environ, {"AGENT2_CRITIC_SELF_REFLECT": "true"}), \
             patch("src.agents.agent2.critic.get_llm") as mock_llm:
            mock_llm.return_value = MagicMock()
            import src.agents.agent2.critic as critic_mod
            critic_mod._critic_instance = None
            c = ConceptCritic()
            # Verify self-reflect is on
            assert c._self_reflect is True
            return c

    @pytest.fixture
    def critic_without_reflect(self):
        """Create critic with self-reflection disabled."""
        with patch.dict(os.environ, {"AGENT2_CRITIC_SELF_REFLECT": "false"}), \
             patch("src.agents.agent2.critic.get_llm") as mock_llm:
            mock_llm.return_value = MagicMock()
            import src.agents.agent2.critic as critic_mod
            critic_mod._critic_instance = None
            c = ConceptCritic()
            assert c._self_reflect is False
            return c

    def _run_evaluate(self, critic, mock_result, query, seed_ids, kg, domain_hint="Condition"):
        """Helper to run evaluate with mocked chain and cache.

        select_critic_model returns None to mean "follow LLM_MODEL", which is what
        _default_chain already holds — so None is what routes evaluate() through the
        mocked chain below. This used to patch in "gpt-4o", which was the old
        sentinel for the same thing; any other value makes evaluate() build a fresh
        model and chain and the mock never runs.
        """
        with patch.object(critic, "_cache") as mock_cache, \
             patch("src.agents.agent2.critic.select_critic_model", return_value=None):
            mock_cache.make_key.return_value = "key"
            mock_cache.get.return_value = None

            mock_chain = MagicMock()
            mock_chain.invoke.return_value = mock_result
            critic._default_chain = mock_chain

            return critic.evaluate(query, seed_ids, kg, domain_hint=domain_hint)

    def test_contradicted_concept_is_dropped(self, critic_with_reflect):
        """Concept with assessment=contradicted should be filtered out."""
        critic = critic_with_reflect
        kg = [self._make_kg_concept(100, "Milia", "Condition")]

        mock_result = {
            "selected_concepts": [
                {
                    "concept_id": 100,
                    "relevant": True,
                    "reasoning": "Initially matched MI query",
                    "confidence": 0.1,
                    "potential_issue": "abbreviation_confusion",
                    "assessment": "contradicted",
                    "recommended_action": "drop",
                }
            ],
            "overall_reasoning": "MI likely means Myocardial Infarction, not milia"
        }

        result = self._run_evaluate(critic, mock_result, "MI", [100], kg)

        # Contradicted concept should be dropped; falls back to seed
        assert result == [100]  # Fallback to seed_concept_ids

    def test_correct_concept_is_kept(self, critic_with_reflect):
        """Concept with assessment=correct should be kept."""
        critic = critic_with_reflect
        kg = [self._make_kg_concept(200, "Myocardial infarction", "Condition")]

        mock_result = {
            "selected_concepts": [
                {
                    "concept_id": 200,
                    "relevant": True,
                    "reasoning": "Direct match for MI",
                    "confidence": 0.95,
                    "potential_issue": "none",
                    "assessment": "correct",
                    "recommended_action": "keep",
                }
            ],
            "overall_reasoning": "Correct match"
        }

        result = self._run_evaluate(critic, mock_result, "MI", [200], kg)
        assert 200 in result

    def test_domain_mismatch_detected(self, critic_with_reflect):
        """Concept with domain_mismatch is dropped when contradicted."""
        critic = critic_with_reflect
        kg = [
            self._make_kg_concept(300, "Some Procedure", "Procedure"),
            self._make_kg_concept(400, "Real Condition", "Condition"),
        ]

        mock_result = {
            "selected_concepts": [
                {
                    "concept_id": 300,
                    "relevant": True,
                    "reasoning": "Matched keyword",
                    "confidence": 0.15,
                    "potential_issue": "domain_mismatch",
                    "assessment": "contradicted",
                    "recommended_action": "drop",
                },
                {
                    "concept_id": 400,
                    "relevant": True,
                    "reasoning": "Correct condition match",
                    "confidence": 0.9,
                    "potential_issue": "none",
                    "assessment": "correct",
                    "recommended_action": "keep",
                }
            ],
            "overall_reasoning": "Domain filtering applied"
        }

        result = self._run_evaluate(critic, mock_result, "test", [300, 400], kg)

        assert 300 not in result
        assert 400 in result

    def test_self_reflect_false_no_filtering(self, critic_without_reflect):
        """With self_reflect=false, contradicted assessment is ignored."""
        critic = critic_without_reflect
        kg = [self._make_kg_concept(100, "Milia", "Condition")]

        mock_result = {
            "selected_concepts": [
                {
                    "concept_id": 100,
                    "relevant": True,
                    "reasoning": "Matched",
                    "confidence": 0.1,
                    "potential_issue": "abbreviation_confusion",
                    "assessment": "contradicted",
                    "recommended_action": "drop",
                }
            ],
            "overall_reasoning": "No filtering"
        }

        result = self._run_evaluate(critic, mock_result, "MI", [100], kg)

        # With self-reflect off, concept is kept despite "contradicted"
        assert 100 in result

    def test_partially_supported_with_drop_action_is_filtered(self, critic_with_reflect):
        """Concept with assessment=partially_supported and recommended_action=drop should be filtered.

        Seed ID (501) differs from the candidate (500) so the fallback does not
        resurrect the dropped concept.
        """
        critic = critic_with_reflect
        # Provide seed concept (501) separate from the candidate (500)
        kg = [
            self._make_kg_concept(500, "Vague Measurement", "Measurement"),
            self._make_kg_concept(501, "Specific Lab Value", "Measurement"),
        ]

        mock_result = {
            "selected_concepts": [
                {
                    "concept_id": 500,
                    "relevant": True,
                    "reasoning": "Partial match but too ambiguous",
                    "confidence": 0.4,
                    "potential_issue": "too_broad",
                    "assessment": "partially_supported",
                    "recommended_action": "drop",
                },
                {
                    "concept_id": 501,
                    "relevant": True,
                    "reasoning": "Good specific match",
                    "confidence": 0.85,
                    "potential_issue": "none",
                    "assessment": "correct",
                    "recommended_action": "keep",
                },
            ],
            "overall_reasoning": "Concept 500 is too ambiguous to include"
        }

        result = self._run_evaluate(critic, mock_result, "lab test", [501], kg)

        # Drop action must be honoured even when assessment is only partially_supported
        assert 500 not in result
        # The correct concept is still present
        assert 501 in result

    def test_self_reflect_prompt_present(self):
        """When self-reflect is enabled, prompt includes reflection instructions."""
        with patch.dict(os.environ, {"AGENT2_CRITIC_SELF_REFLECT": "true"}), \
             patch("src.agents.agent2.critic.get_llm") as mock_llm:
            mock_llm.return_value = MagicMock()
            import src.agents.agent2.critic as critic_mod
            critic_mod._critic_instance = None
            c = ConceptCritic()
            prompt_text = c.prompt.messages[0].prompt.template
            assert "SELF-REFLECTION PASS" in prompt_text
            assert "abbreviation confusion" in prompt_text

    def test_self_reflect_prompt_absent_when_disabled(self):
        """When self-reflect is disabled, prompt omits reflection instructions."""
        with patch.dict(os.environ, {"AGENT2_CRITIC_SELF_REFLECT": "false"}), \
             patch("src.agents.agent2.critic.get_llm") as mock_llm:
            mock_llm.return_value = MagicMock()
            import src.agents.agent2.critic as critic_mod
            critic_mod._critic_instance = None
            c = ConceptCritic()
            prompt_text = c.prompt.messages[0].prompt.template
            assert "SELF-REFLECTION PASS" not in prompt_text
