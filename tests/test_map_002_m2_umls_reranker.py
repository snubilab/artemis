"""
Tests for SPEC-MAP-002 M2: UMLS strict filter, reranker domain-aware,
critic inclusive prompt.

M2a: UMLS MRSTY strict filter for short queries
M2b: Reranker domain grounding prompt
M2c: Critic inclusive prompt (tested via prompt content)
"""

import os
from unittest.mock import patch, MagicMock

import pytest

from src.agents.agent2.umls_synonym_expander import UMLSSynonymExpander


class TestUMLSStrictFilter:
    """M2a: UMLS MRSTY strict filter for short/abbreviation queries."""

    @pytest.fixture
    def expander(self, tmp_path):
        """Create a mock expander with MRSTY support."""
        # Bypass real DB init
        exp = UMLSSynonymExpander.__new__(UMLSSynonymExpander)
        exp.db_path = str(tmp_path / "fake.sqlite")
        exp._conn = MagicMock()
        exp._available = True
        exp._has_mrsty = True
        return exp

    def test_short_query_with_domain_drops_non_matching(self, expander):
        """Short query 'MI' + domain=Condition -> drops non-Condition CUIs."""
        # Mock: no CUI matches Condition semantic types
        with patch.object(expander, "_cui_matches_sty", return_value=False):
            result = expander._filter_cuis_by_domain(
                ["C0001", "C0002"], "Condition", query="MI"
            )

        # Strict mode: short query + domain -> drop all non-matching
        assert result == []

    def test_long_query_keeps_all_on_no_match(self, expander):
        """Long query 'Myocardial infarction' -> keeps all CUIs (not abbreviation)."""
        with patch.object(expander, "_cui_matches_sty", return_value=False):
            result = expander._filter_cuis_by_domain(
                ["C0001", "C0002"], "Condition", query="Myocardial infarction"
            )

        # Long query: fallback to keeping all
        assert result == ["C0001", "C0002"]

    def test_short_query_without_domain_keeps_all(self, expander):
        """Short query without domain_hint -> keeps all."""
        with patch.object(expander, "_cui_matches_sty", return_value=False):
            result = expander._filter_cuis_by_domain(
                ["C0001"], None, query="MI"
            )

        # No domain_hint: method returns early before strict check
        assert result == ["C0001"]

    def test_strict_env_false_keeps_all(self, expander):
        """When AGENT2_UMLS_STRICT=false, even short query keeps all."""
        with patch.dict(os.environ, {"AGENT2_UMLS_STRICT": "false"}), \
             patch.object(expander, "_cui_matches_sty", return_value=False):
            result = expander._filter_cuis_by_domain(
                ["C0001", "C0002"], "Condition", query="MI"
            )

        # Strict disabled: fallback to keeping all
        assert result == ["C0001", "C0002"]

    def test_matching_cuis_returned_normally(self, expander):
        """When MRSTY filter finds matches, returns them (no strict needed)."""
        def mock_match(cui, stys):
            return cui == "C0001"  # Only first CUI matches

        with patch.object(expander, "_cui_matches_sty", side_effect=mock_match):
            result = expander._filter_cuis_by_domain(
                ["C0001", "C0002"], "Condition", query="MI"
            )

        assert result == ["C0001"]

    def test_exactly_5_chars_is_short(self, expander):
        """Query with exactly 5 chars is treated as short/abbreviation-like."""
        with patch.object(expander, "_cui_matches_sty", return_value=False):
            result = expander._filter_cuis_by_domain(
                ["C0001"], "Condition", query="ABCDE"
            )
        assert result == []

    def test_6_chars_is_long(self, expander):
        """Query with 6 chars is not treated as short."""
        with patch.object(expander, "_cui_matches_sty", return_value=False):
            result = expander._filter_cuis_by_domain(
                ["C0001"], "Condition", query="ABCDEF"
            )
        assert result == ["C0001"]


class TestRerankerDomainAware:
    """M2b: Reranker domain grounding prompt."""

    def test_domain_grounding_in_prompt_when_enabled(self):
        """When AGENT2_RERANKER_DOMAIN_AWARE=true, prompt includes domain grounding."""
        with patch.dict(os.environ, {"AGENT2_RERANKER_DOMAIN_AWARE": "true"}):
            # Need to mock LLM to avoid actual API calls
            with patch("src.agents.agent2.reranker.get_llm") as mock_llm:
                mock_llm.return_value = MagicMock()
                from importlib import reload
                import src.agents.agent2.reranker as reranker_mod
                # Reset singleton
                reranker_mod._reranker_instance = None
                reranker = reranker_mod.ConceptReranker()
                prompt_text = reranker.prompt.messages[0].prompt.template
                assert "MI = Myocardial Infarction" in prompt_text
                assert "milia" in prompt_text

    def test_no_domain_grounding_when_disabled(self):
        """When AGENT2_RERANKER_DOMAIN_AWARE=false, prompt has no domain grounding."""
        with patch.dict(os.environ, {"AGENT2_RERANKER_DOMAIN_AWARE": "false"}):
            with patch("src.agents.agent2.reranker.get_llm") as mock_llm:
                mock_llm.return_value = MagicMock()
                from importlib import reload
                import src.agents.agent2.reranker as reranker_mod
                reranker_mod._reranker_instance = None
                reranker = reranker_mod.ConceptReranker()
                prompt_text = reranker.prompt.messages[0].prompt.template
                assert "MI = Myocardial Infarction" not in prompt_text


class TestCriticInclusivePrompt:
    """M2c: Critic inclusive prompt for broad queries."""

    def test_critic_prompt_includes_inclusive_guidance(self):
        """Critic system prompt should include guidance for broad categories."""
        with patch("src.agents.agent2.critic.get_llm") as mock_llm:
            mock_llm.return_value = MagicMock()
            from src.agents.agent2.critic import ConceptCritic
            import src.agents.agent2.critic as critic_mod
            critic_mod._critic_instance = None
            critic = ConceptCritic()
            prompt_text = critic.prompt.messages[0].prompt.template
            assert "false negatives" in prompt_text
            assert "ancestor concept with includeDescendants=true" in prompt_text
