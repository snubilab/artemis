"""
Interaction regression tests for ConceptCritic._apply_self_reflection_filter.

Covers the fix for Ablation Run E over-pruning: KG-validated concepts with
confidence > 0.5 should be preserved even when the Critic marks them as
"contradicted" or recommends "drop".

Test scenarios:
  1. KG concept, confidence 0.7, contradicted  -> PRESERVED
  2. Non-KG concept, contradicted              -> DROPPED
  3. KG concept, confidence 0.2, contradicted  -> DROPPED
  4. self_reflect=false                        -> no filtering at all
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from src.agents.agent2.critic import ConceptCritic


# ── helpers ──────────────────────────────────────────────────

def _make_kg_concept(concept_id: int, name: str = "Test", domain: str = "Condition"):
    mock = MagicMock()
    mock.concept_id = concept_id
    mock.concept_name = name
    mock.domain_id = domain
    mock.vocabulary_id = "SNOMED"
    mock.relationship = "child"
    return mock


def _build_critic(self_reflect: bool) -> ConceptCritic:
    """Instantiate ConceptCritic with self-reflection toggled."""
    env_val = "true" if self_reflect else "false"
    with patch.dict(os.environ, {"AGENT2_CRITIC_SELF_REFLECT": env_val}), \
         patch("src.agents.agent2.critic.get_llm") as mock_get_llm:
        mock_get_llm.return_value = MagicMock()
        import src.agents.agent2.critic as critic_mod
        critic_mod._critic_instance = None
        return ConceptCritic()


def _run_evaluate(critic: ConceptCritic, mock_result: dict, query: str,
                  seed_ids: list, kg_list: list, kg_concept_ids=None):
    """Run evaluate() with a mocked LLM chain and empty cache."""
    # None means "follow LLM_MODEL", which routes evaluate() through _default_chain —
    # the chain this helper replaces with a mock. "gpt-4o" was the old sentinel for the
    # same thing; after the default flipped it became a real request for a specific
    # model, so evaluate() built a live OpenAI client and these tests made billed calls
    # whose responses decided the assertions.
    with patch.object(critic, "_cache") as mock_cache, \
         patch("src.agents.agent2.critic.select_critic_model", return_value=None):
        mock_cache.make_key.return_value = "test-key"
        mock_cache.get.return_value = None  # Force fresh evaluation

        mock_chain = MagicMock()
        mock_chain.invoke.return_value = mock_result
        critic._default_chain = mock_chain

        return critic.evaluate(
            query, seed_ids, kg_list,
            kg_concept_ids=kg_concept_ids,
        )


# ── Test Cases ────────────────────────────────────────────────

class TestApplySelfReflectionFilter:
    """Unit tests for _apply_self_reflection_filter method directly."""

    def test_kg_concept_high_confidence_contradicted_is_preserved(self):
        """Scenario 1: KG concept + confidence=0.7 + contradicted -> PRESERVED."""
        critic = _build_critic(self_reflect=True)
        selections = [
            {
                "concept_id": 4099974,
                "relevant": True,
                "reasoning": "KG-expanded stroke subtype, critic flagged uncertainty",
                "confidence": 0.7,
                "potential_issue": "too_specific",
                "assessment": "contradicted",
                "recommended_action": "drop",
            }
        ]
        kg_concept_ids = {4099974}

        result = critic._apply_self_reflection_filter(selections, kg_concept_ids)

        assert len(result) == 1, "KG concept with confidence 0.7 must be preserved"
        assert result[0]["concept_id"] == 4099974

    def test_non_kg_concept_contradicted_is_dropped(self):
        """Scenario 2: Non-KG concept + contradicted -> DROPPED."""
        critic = _build_critic(self_reflect=True)
        selections = [
            {
                "concept_id": 9999,
                "relevant": True,
                "reasoning": "Matched keyword but not KG-validated",
                "confidence": 0.7,  # High confidence but not from KG
                "potential_issue": "abbreviation_confusion",
                "assessment": "contradicted",
                "recommended_action": "drop",
            }
        ]
        # kg_concept_ids does NOT contain 9999
        kg_concept_ids = {4099974}

        result = critic._apply_self_reflection_filter(selections, kg_concept_ids)

        assert len(result) == 0, "Non-KG contradicted concept must be dropped"

    def test_kg_concept_low_confidence_contradicted_is_dropped(self):
        """Scenario 3: KG concept + confidence=0.2 + contradicted -> DROPPED."""
        critic = _build_critic(self_reflect=True)
        selections = [
            {
                "concept_id": 4099974,
                "relevant": True,
                "reasoning": "KG-expanded but very uncertain",
                "confidence": 0.2,  # Below 0.5 threshold
                "potential_issue": "domain_mismatch",
                "assessment": "contradicted",
                "recommended_action": "drop",
            }
        ]
        kg_concept_ids = {4099974}

        result = critic._apply_self_reflection_filter(selections, kg_concept_ids)

        assert len(result) == 0, "KG concept with confidence 0.2 must still be dropped"

    def test_no_kg_context_contradicted_is_dropped(self):
        """With kg_concept_ids=None, contradicted concepts are dropped (no preservation)."""
        critic = _build_critic(self_reflect=True)
        selections = [
            {
                "concept_id": 4099974,
                "relevant": True,
                "reasoning": "Some concept",
                "confidence": 0.8,
                "potential_issue": "none",
                "assessment": "contradicted",
                "recommended_action": "drop",
            }
        ]

        result = critic._apply_self_reflection_filter(selections, kg_concept_ids=None)

        assert len(result) == 0, "Without KG context, contradicted concept must be dropped"

    def test_correct_concept_always_preserved(self):
        """Concepts with assessment=correct are never dropped by the filter."""
        critic = _build_critic(self_reflect=True)
        selections = [
            {
                "concept_id": 200,
                "relevant": True,
                "reasoning": "Direct match",
                "confidence": 0.95,
                "potential_issue": "none",
                "assessment": "correct",
                "recommended_action": "keep",
            }
        ]
        result = critic._apply_self_reflection_filter(selections, kg_concept_ids=set())

        assert len(result) == 1
        assert result[0]["concept_id"] == 200

    def test_boundary_confidence_exactly_half(self):
        """Confidence exactly 0.5 is not > 0.5, so KG concept is dropped."""
        critic = _build_critic(self_reflect=True)
        selections = [
            {
                "concept_id": 555,
                "relevant": True,
                "reasoning": "Borderline KG concept",
                "confidence": 0.5,
                "potential_issue": "too_specific",
                "assessment": "contradicted",
                "recommended_action": "drop",
            }
        ]
        kg_concept_ids = {555}

        result = critic._apply_self_reflection_filter(selections, kg_concept_ids)

        # confidence=0.5 is NOT > 0.5, so it should be dropped
        assert len(result) == 0, "Confidence exactly 0.5 is not above threshold"


class TestEvaluateSelfReflectOff:
    """Scenario 4: self_reflect=false -> no filtering at all."""

    def test_self_reflect_false_no_filtering(self):
        """With self-reflection disabled, contradicted concepts pass through unchanged."""
        critic = _build_critic(self_reflect=False)
        assert critic._self_reflect is False

        kg = [_make_kg_concept(100, "Milia", "Condition")]
        mock_result = {
            "selected_concepts": [
                {
                    "concept_id": 100,
                    "relevant": True,
                    "reasoning": "Matched query",
                    "confidence": 0.1,
                    "potential_issue": "abbreviation_confusion",
                    "assessment": "contradicted",
                    "recommended_action": "drop",
                }
            ],
            "overall_reasoning": "No filtering expected",
        }

        result = _run_evaluate(
            critic, mock_result, "MI", [100], kg, kg_concept_ids={100}
        )

        # With self-reflect off, the contradicted concept is NOT filtered
        assert 100 in result, "self_reflect=false must not filter any concepts"


class TestEvaluateKGPreservationIntegration:
    """Integration tests for KG preservation via evaluate() method."""

    def test_kg_concept_preserved_via_evaluate(self):
        """Stroke KG-expanded concepts with confidence 0.7 survive evaluate()."""
        critic = _build_critic(self_reflect=True)

        stroke_kg_id = 4099974
        kg = [_make_kg_concept(stroke_kg_id, "Completed stroke", "Condition")]
        kg_concept_ids = {stroke_kg_id}

        mock_result = {
            "selected_concepts": [
                {
                    "concept_id": stroke_kg_id,
                    "relevant": True,
                    "reasoning": "KG-expanded stroke subtype",
                    "confidence": 0.7,
                    "potential_issue": "too_specific",
                    "assessment": "contradicted",
                    "recommended_action": "drop",
                }
            ],
            "overall_reasoning": "Critic uncertain about specificity",
        }

        result = _run_evaluate(
            critic, mock_result, "history of stroke",
            [stroke_kg_id], kg, kg_concept_ids=kg_concept_ids,
        )

        assert stroke_kg_id in result, (
            "KG-validated stroke concept with confidence 0.7 must survive evaluate()"
        )

    def test_mixed_kg_non_kg_filtering(self):
        """KG concept is preserved, non-KG contradicted concept is dropped."""
        critic = _build_critic(self_reflect=True)

        kg_id = 375557   # Cerebral embolism (KG-expanded)
        non_kg_id = 9001  # Non-KG spurious match

        kg = [
            _make_kg_concept(kg_id, "Cerebral embolism", "Condition"),
            _make_kg_concept(non_kg_id, "Spurious match", "Procedure"),
        ]
        kg_concept_ids = {kg_id}  # Only kg_id is from KG expansion

        mock_result = {
            "selected_concepts": [
                {
                    "concept_id": kg_id,
                    "relevant": True,
                    "reasoning": "KG-validated stroke subtype",
                    "confidence": 0.75,
                    "potential_issue": "too_specific",
                    "assessment": "contradicted",
                    "recommended_action": "drop",
                },
                {
                    "concept_id": non_kg_id,
                    "relevant": True,
                    "reasoning": "Matched text but wrong domain",
                    "confidence": 0.8,
                    "potential_issue": "domain_mismatch",
                    "assessment": "contradicted",
                    "recommended_action": "drop",
                },
            ],
            "overall_reasoning": "Mixed quality results",
        }

        result = _run_evaluate(
            critic, mock_result, "stroke", [kg_id, non_kg_id], kg,
            kg_concept_ids=kg_concept_ids,
        )

        assert kg_id in result, "KG-validated concept must be preserved"
        assert non_kg_id not in result, "Non-KG contradicted concept must be dropped"
