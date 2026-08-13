"""The reranker was asked a superlative, and a superlative always has an answer.

"Select up to N concepts that BEST match the clinical intent" is a ranking question.
Ranking a list of cardiac concepts against `qqzzxx nonexistent clinical term` returns
cardiac concepts, and the pipeline recorded that as a mapping. The reranker was not
incapable — the same reranker answered `linagliptin` with nothing at all — it was
answering the question it was given.

The gate makes the prior question explicit and separately reportable: does any
candidate denote this term? Only then does ranking happen.

The DRY test in this file exists because the top-N prompt was written out twice,
once in rerank_topn and once in rerank_topn_batch, and the batch copy is the one the
pipeline actually calls. Fixing one and not the other would have left production
behaviour untouched while every unit test went green.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agents.agent2.retriever import CandidateConcept


def _c(concept_id: int, name: str) -> CandidateConcept:
    return CandidateConcept(
        concept_id=concept_id,
        concept_name=name,
        domain_id="Condition",
        vocabulary_id="SNOMED",
        concept_class_id="Clinical Finding",
        distance=55.0,
    )


MI = _c(4329847, "Myocardial infarction")
ACS = _c(434376, "Acute coronary syndrome")
CANDIDATES = [MI, ACS]


@pytest.fixture
def reranker():
    with patch("src.agents.agent2.reranker.get_llm") as mock_llm:
        mock_llm.return_value = MagicMock()
        import src.agents.agent2.reranker as reranker_mod
        from src.agents.agent2.reranker import ConceptReranker

        reranker_mod._reranker_instance = None
        return ConceptReranker()


def _with_topn_response(reranker, response):
    chain = MagicMock()
    chain.invoke.return_value = response
    reranker._topn_chain = chain
    return reranker


class TestSingleTopN:
    def test_should_return_no_concepts_when_the_model_reports_no_match(self, reranker):
        _with_topn_response(reranker, {"query_has_match": False, "selected_ids": []})
        assert reranker.rerank_topn("qqzzxx nonexistent clinical term", CANDIDATES) == []

    def test_should_honour_no_match_even_when_ids_are_listed(self, reranker):
        """A self-contradicting answer is unreliable; the safe branch maps nothing."""
        _with_topn_response(reranker, {"query_has_match": False, "selected_ids": [4329847]})
        assert reranker.rerank_topn("qqzzxx nonexistent clinical term", CANDIDATES) == []

    def test_should_still_select_when_the_model_reports_a_match(self, reranker):
        _with_topn_response(reranker, {"query_has_match": True, "selected_ids": [4329847]})
        selected = reranker.rerank_topn("myocardial infarction", CANDIDATES)
        assert [c.concept_id for c in selected] == [4329847]

    def test_should_still_select_when_the_model_omits_the_gate(self, reranker):
        """An absent gate is not a no-match verdict — old-shape answers must still work."""
        _with_topn_response(reranker, {"selected_ids": [4329847]})
        selected = reranker.rerank_topn("myocardial infarction", CANDIDATES)
        assert [c.concept_id for c in selected] == [4329847]


class TestBatchTopN:
    """The path the pipeline actually calls."""

    def test_should_return_no_concepts_when_the_model_reports_no_match(self, reranker):
        chain = MagicMock()
        chain.batch.return_value = [{"query_has_match": False, "selected_ids": [4329847]}]
        reranker._topn_chain = chain

        results = reranker.rerank_topn_batch(
            [{"query": "qqzzxx nonexistent clinical term", "candidates": CANDIDATES}]
        )
        assert results == [[]]

    def test_should_still_select_when_the_model_reports_a_match(self, reranker):
        chain = MagicMock()
        chain.batch.return_value = [{"query_has_match": True, "selected_ids": [434376]}]
        reranker._topn_chain = chain

        results = reranker.rerank_topn_batch(
            [{"query": "acute coronary syndrome", "candidates": CANDIDATES}]
        )
        assert [c.concept_id for c in results[0]] == [434376]


class TestOneAuthoritativePrompt:
    """A hard gate against the duplicate re-growing."""

    def test_should_use_one_shared_prompt_for_single_and_batch_topn(self, reranker):
        from src.agents.agent2.reranker import TOPN_SYSTEM_PROMPT

        assert reranker._topn_prompt.messages[0].prompt.template == TOPN_SYSTEM_PROMPT

    def test_should_ask_whether_any_candidate_denotes_the_term(self):
        """Without the gate the prompt is a pure superlative, which always has an answer."""
        from src.agents.agent2.reranker import TOPN_SYSTEM_PROMPT

        assert "query_has_match" in TOPN_SYSTEM_PROMPT
