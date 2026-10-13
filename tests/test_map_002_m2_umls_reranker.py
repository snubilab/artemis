"""
Tests for SPEC-MAP-002 M2: reranker domain-aware, critic inclusive prompt.

M2a (UMLS MRSTY strict filter) went with the UMLS expander.
M2b: Reranker domain grounding prompt
M2c: Critic inclusive prompt (tested via prompt content)
"""

import os
from unittest.mock import patch, MagicMock


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
                # The rule, stated without an abbreviation glossary or a counterexample:
                # both are examples (AGENTS.md § PROMPTS AND TEXT RULES, rule 1).
                assert "in the sense it has within that domain" in prompt_text
                assert "Do NOT select concepts from an unrelated clinical domain" in prompt_text
                assert "MI = Myocardial Infarction" not in prompt_text
                assert "milia" not in prompt_text

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
                assert "in the sense it has within that domain" not in prompt_text


class TestCriticInclusivePrompt:
    """M2c: Critic inclusive prompt for broad queries."""

    def test_critic_prompt_includes_inclusive_guidance(self):
        """Critic system prompt includes narrower kinds and rejects broader parents.

        The earlier "prefer broad ancestors / false negatives are worse" guidance was
        replaced by prompt evolution on 2026-10-11 (per-criterion F1 against gold).
        """
        with patch("src.agents.agent2.critic.get_llm") as mock_llm:
            mock_llm.return_value = MagicMock()
            from src.agents.agent2.critic import ConceptCritic
            import src.agents.agent2.critic as critic_mod
            critic_mod._critic_instance = None
            critic = ConceptCritic()
            prompt_text = critic.prompt.messages[0].prompt.template
            assert "more specific kind" in prompt_text
            assert "BROADER than the query" in prompt_text
