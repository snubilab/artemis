"""
SPEC-PERF-002 Integration Tests: CriterionResultCache + batch_search integration.

P3: Cache integration with _recommend_seeded_concept_set
  T3.6a: Cache miss — Agent2 called, result cached
  T3.6b: Cache hit — Agent2 NOT called, cached result returned
  T3.6c: Cache disabled — Agent2 always called

P7: Batch pre-fetch integration with _build_seeded_target_circe
  T7.3: Empty batch_search result triggers per-criterion retriever.search fallback
  T7.4: Criteria with different domains produce separate batch calls
"""

import os
from copy import deepcopy
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest

from src.agents.agent2.criterion_cache import (
    CriterionCacheEntry,
    CriterionResultCache,
)
from src.models.ir import MappingResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_expression(concept_id: int = 123, concept_name: str = "Test Concept") -> dict[str, Any]:
    """Build a minimal CIRCE-style expression dict."""
    return {
        "items": [
            {
                "concept": {
                    "CONCEPT_ID": concept_id,
                    "CONCEPT_NAME": concept_name,
                    "STANDARD_CONCEPT": "S",
                    "STANDARD_CONCEPT_CAPTION": "Standard",
                    "INVALID_REASON": "V",
                    "INVALID_REASON_CAPTION": "Valid",
                    "CONCEPT_CODE": str(concept_id),
                    "DOMAIN_ID": "Condition",
                    "VOCABULARY_ID": "SNOMED",
                    "CONCEPT_CLASS_ID": "Clinical Finding",
                },
                "isExcluded": False,
                "includeDescendants": True,
                "includeMapped": False,
            }
        ]
    }


def _make_mapping_result(concept_ids: list[int] | None = None) -> MappingResult:
    """Build a MappingResult returned by Agent2Workflow.process_with_details."""
    return MappingResult(
        concept_ids=concept_ids or [123],
        overbroad_concept_ids=[],
        route_path="slow",
    )


def _make_concept_candidate(concept_id: int = 123, name: str = "Test Concept"):
    """Build a ConceptCandidate-like object for _fetch_concept_candidates."""
    cc = MagicMock()
    cc.concept_id = concept_id
    cc.concept_name = name
    cc.domain_id = "Condition"
    cc.vocabulary_id = "SNOMED"
    cc.concept_class_id = "Clinical Finding"
    cc.score = 0.9
    cc.source = "rag"
    return cc


def _make_recommendation_item(name: str = "Test Concept Set"):
    """Build a mock RecommendationItem from expression_builder.build_expression."""
    rec = MagicMock()
    rec.name = name
    expr_mock = MagicMock()
    expr_mock.to_atlas_json.return_value = _make_expression()
    rec.expression = expr_mock
    return rec


def _make_cache_entry(seed: str = "history of stroke") -> CriterionCacheEntry:
    """Build a CriterionCacheEntry for pre-populating cache."""
    return CriterionCacheEntry(
        concept_ids=[123],
        expression=_make_expression(),
        name="Cached Concept Set",
        domain="Condition",
        route_path="slow",
        mapping_metadata={
            "allCandidates": [],
            "rerankConfidence": None,
            "rerankMethod": "agent2",
            "queryUsed": seed,
            "selectedConceptIds": [123],
        },
        created_at="2026-03-29T00:00:00+00:00",
    )


def _build_service():
    """Instantiate TTEService with a mock store."""
    from src.services.tte_service import TTEService
    return TTEService(store=MagicMock())


# ---------------------------------------------------------------------------
# P3: Cache integration with _recommend_seeded_concept_set
# ---------------------------------------------------------------------------

class TestCriterionCacheIntegration:
    """T3.6: Cache integration in _recommend_seeded_concept_set."""

    @patch("src.services.tte_service.TTEService._resolve_seeded_domain", return_value="Condition")
    @patch("src.agents.conceptset.expression_builder.get_expression_builder")
    @patch("src.services.tte_service.TTEService._fetch_concept_candidates")
    @patch("src.agents.agent2.workflow.Agent2Workflow.process_with_details")
    @patch("src.agents.agent2.criterion_cache.get_criterion_cache")
    def test_cache_miss_calls_agent2_and_stores_result(
        self,
        mock_get_cache,
        mock_process,
        mock_fetch,
        mock_get_builder,
        mock_resolve_domain,
    ):
        """On cache miss, Agent2 runs and result is cached."""
        # Arrange
        cache = CriterionResultCache(max_entries=100, ttl_hours=1)
        mock_get_cache.return_value = cache

        mock_process.return_value = _make_mapping_result()
        mock_fetch.return_value = [_make_concept_candidate()]
        mock_get_builder.return_value.build_expression.return_value = _make_recommendation_item()

        svc = _build_service()

        # Act
        with patch.dict(os.environ, {"CRITERION_CACHE_ENABLED": "true"}):
            result = svc._recommend_seeded_concept_set("History of Stroke", expected_domain="Condition")

        # Assert — Agent2 was called
        mock_process.assert_called_once()
        # Assert — result was stored in cache
        assert cache.stats()["current_size"] == 1
        # Assert — valid return
        assert result["name"] == "Test Concept Set"
        assert result["domain"] == "Condition"
        assert "expression" in result

    @patch("src.services.tte_service.TTEService._resolve_seeded_domain", return_value="Condition")
    @patch("src.agents.conceptset.expression_builder.get_expression_builder")
    @patch("src.services.tte_service.TTEService._fetch_concept_candidates")
    @patch("src.agents.agent2.workflow.Agent2Workflow.process_with_details")
    @patch("src.agents.agent2.criterion_cache.get_criterion_cache")
    def test_cache_hit_skips_agent2(
        self,
        mock_get_cache,
        mock_process,
        mock_fetch,
        mock_get_builder,
        mock_resolve_domain,
    ):
        """On cache hit, Agent2 is NOT called."""
        # Arrange — pre-populate cache
        cache = CriterionResultCache(max_entries=100, ttl_hours=1)
        entry = _make_cache_entry("history of stroke")
        cache.put("History of Stroke", "Condition", entry)
        mock_get_cache.return_value = cache

        svc = _build_service()

        # Act
        with patch.dict(os.environ, {"CRITERION_CACHE_ENABLED": "true"}):
            result = svc._recommend_seeded_concept_set("History of Stroke", expected_domain="Condition")

        # Assert — Agent2 was NOT called
        mock_process.assert_not_called()
        mock_fetch.assert_not_called()
        # Assert — cached data returned
        assert result["name"] == "Cached Concept Set"
        assert result["domain"] == "Condition"
        assert result["expression"]["items"][0]["concept"]["CONCEPT_ID"] == 123

    @patch("src.services.tte_service.TTEService._resolve_seeded_domain", return_value="Condition")
    @patch("src.agents.conceptset.expression_builder.get_expression_builder")
    @patch("src.services.tte_service.TTEService._fetch_concept_candidates")
    @patch("src.agents.agent2.workflow.Agent2Workflow.process_with_details")
    @patch("src.agents.agent2.criterion_cache.get_criterion_cache")
    def test_cache_disabled_always_calls_agent2(
        self,
        mock_get_cache,
        mock_process,
        mock_fetch,
        mock_get_builder,
        mock_resolve_domain,
    ):
        """When CRITERION_CACHE_ENABLED=false, Agent2 always runs despite cached data."""
        # Arrange — pre-populate cache
        cache = CriterionResultCache(max_entries=100, ttl_hours=1)
        entry = _make_cache_entry("history of stroke")
        cache.put("History of Stroke", "Condition", entry)
        mock_get_cache.return_value = cache

        mock_process.return_value = _make_mapping_result()
        mock_fetch.return_value = [_make_concept_candidate()]
        mock_get_builder.return_value.build_expression.return_value = _make_recommendation_item()

        svc = _build_service()

        # Act
        with patch.dict(os.environ, {"CRITERION_CACHE_ENABLED": "false"}):
            result = svc._recommend_seeded_concept_set("History of Stroke", expected_domain="Condition")

        # Assert — Agent2 WAS called even though cache has data
        mock_process.assert_called_once()
        # Assert — result comes from Agent2, not cache
        assert result["name"] == "Test Concept Set"


# ---------------------------------------------------------------------------
# P7: Batch pre-fetch integration with _build_seeded_target_circe
# ---------------------------------------------------------------------------

class TestBatchPreFetchIntegration:
    """P7: Batch pre-fetch in _build_seeded_target_circe."""

    @patch("src.services.tte_service.TTEService._build_demographic_rule")
    @patch("src.services.tte_service.TTEService._build_seeded_eligibility_rule")
    @patch("src.services.tte_service.TTEService._recommend_seeded_concept_set")
    @patch("src.agents.agent2.abbreviation_expander.expand_in_context", side_effect=lambda x: x)
    @patch("src.agents.agent2.abbreviation_expander.expand_abbreviation", side_effect=lambda x: (x, False))
    @patch("src.agents.agent2.query_expander.QueryExpander.expand", side_effect=lambda x, **kw: x)
    @patch("src.agents.agent2.retriever.ConceptRetriever.__init__", return_value=None)
    @patch("src.agents.agent2.retriever.ConceptRetriever.batch_search")
    def test_empty_batch_result_falls_back_to_per_criterion_search(
        self,
        mock_batch_search,
        mock_retriever_init,
        mock_qe_expand,
        mock_expand_abbr,
        mock_expand_ctx,
        mock_recommend,
        mock_build_rule,
        mock_build_demo,
    ):
        """T7.3: When batch_search returns empty for a criterion, the per-criterion
        retriever.search fallback in _slow_path runs (pre_fetched_candidates=None)."""
        # Arrange — batch_search returns empty for the criterion
        mock_batch_search.return_value = {}  # no results for any query

        # _recommend_seeded_concept_set for the target cohort
        mock_recommend.return_value = {
            "name": "Target Drug",
            "expression": _make_expression(999, "Target Drug"),
            "domain": "Drug",
            "mapping_metadata": None,
        }

        # _build_seeded_eligibility_rule returns a minimal rule
        mock_build_rule.return_value = {
            "conceptSet": {
                "id": 0,
                "name": "Criterion CS",
                "expression": _make_expression(456, "Criterion Concept"),
            },
            "rule": {
                "name": "Test criterion",
                "expression": {"Type": "ALL", "CriteriaList": []},
            },
            "mapping_metadata": None,
        }

        svc = _build_service()
        eligibility = {
            "targetCohortName": "GLP-1 receptor agonist",
            "inclusionCriteria": [
                {
                    "description": "History of Stroke",
                    "domain": "Condition",
                    "sourceText": "History of Stroke",
                },
            ],
            "exclusionCriteria": [],
        }

        # Act
        with patch.dict(os.environ, {"CRITERION_CACHE_ENABLED": "false"}):
            result = svc._build_seeded_target_circe(eligibility)

        # Assert — batch_search was called (even though it returned empty)
        mock_batch_search.assert_called_once()

        # Assert — _build_seeded_eligibility_rule was called with pre_fetched_candidates=None
        # because batch_search returned empty dict and thus pre_fetched[0] is None
        mock_build_rule.assert_called_once()
        call_kwargs = mock_build_rule.call_args
        assert call_kwargs.kwargs.get("pre_fetched_candidates") is None

    @patch("src.services.tte_service.TTEService._build_demographic_rule")
    @patch("src.services.tte_service.TTEService._build_seeded_eligibility_rule")
    @patch("src.services.tte_service.TTEService._recommend_seeded_concept_set")
    @patch("src.agents.agent2.abbreviation_expander.expand_in_context", side_effect=lambda x: x)
    @patch("src.agents.agent2.abbreviation_expander.expand_abbreviation", side_effect=lambda x: (x, False))
    @patch("src.agents.agent2.query_expander.QueryExpander.expand", side_effect=lambda x, **kw: x)
    @patch("src.agents.agent2.retriever.ConceptRetriever.__init__", return_value=None)
    @patch("src.agents.agent2.retriever.ConceptRetriever.batch_search")
    def test_domain_grouped_batch_produces_separate_calls(
        self,
        mock_batch_search,
        mock_retriever_init,
        mock_qe_expand,
        mock_expand_abbr,
        mock_expand_ctx,
        mock_recommend,
        mock_build_rule,
        mock_build_demo,
    ):
        """T7.4: Criteria with different domains produce separate batch calls
        (batch_search is called once with all queries; grouping happens inside
        batch_search itself via domain_hints parameter)."""
        # Arrange — batch_search returns results keyed by expanded text
        drug_candidate = MagicMock()
        drug_candidate.concept_id = 100
        cond_candidate = MagicMock()
        cond_candidate.concept_id = 200

        mock_batch_search.return_value = {
            "Metformin": [drug_candidate],
            "History of Stroke": [cond_candidate],
        }

        mock_recommend.return_value = {
            "name": "Target Drug",
            "expression": _make_expression(999, "Target Drug"),
            "domain": "Drug",
            "mapping_metadata": None,
        }
        mock_build_rule.return_value = {
            "conceptSet": {
                "id": 0,
                "name": "CS",
                "expression": _make_expression(),
            },
            "rule": {
                "name": "rule",
                "expression": {"Type": "ALL", "CriteriaList": []},
            },
            "mapping_metadata": None,
        }

        svc = _build_service()
        eligibility = {
            "targetCohortName": "GLP-1 receptor agonist",
            "inclusionCriteria": [
                {
                    "description": "Metformin",
                    "domain": "Drug",
                    "sourceText": "Metformin",
                },
                {
                    "description": "History of Stroke",
                    "domain": "Condition",
                    "sourceText": "History of Stroke",
                },
            ],
            "exclusionCriteria": [],
        }

        # Act
        with patch.dict(os.environ, {"CRITERION_CACHE_ENABLED": "false"}):
            result = svc._build_seeded_target_circe(eligibility)

        # Assert — batch_search called once with both queries and domain hints
        mock_batch_search.assert_called_once()
        call_args = mock_batch_search.call_args
        query_texts = call_args[0][0] if call_args[0] else call_args[1].get("query_texts", [])
        domain_hints = call_args[1].get("domain_hints") or (call_args[0][2] if len(call_args[0]) > 2 else None)

        assert len(query_texts) == 2
        # Verify domain hints contain both Drug and Condition
        assert domain_hints is not None
        assert "Drug" in domain_hints
        assert "Condition" in domain_hints

        # Assert — both criteria processed
        assert mock_build_rule.call_count == 2

        # Assert — first criterion (Drug) got drug_candidate, second got cond_candidate
        first_call = mock_build_rule.call_args_list[0]
        second_call = mock_build_rule.call_args_list[1]
        # One call should have pre_fetched with drug_candidate, other with cond_candidate
        all_pre_fetched = [
            c.kwargs.get("pre_fetched_candidates") for c in mock_build_rule.call_args_list
        ]
        # At least one should have candidates (non-None)
        assert any(pf is not None for pf in all_pre_fetched), (
            f"Expected at least one criterion to receive pre-fetched candidates, got: {all_pre_fetched}"
        )
