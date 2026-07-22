"""Tests for mapping metadata capture in the recommendation pipeline (SPEC-UI-003 Task 2).

RED phase: All tests written before implementation.

Strategy: The Agent2 path uses local imports inside a try block. To avoid pulling in
real Agent2/ChromaDB/settings, we inject fake modules into sys.modules before the
import executes, then clean them up afterwards.
"""

import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.api.models.tte import CriterionMappingMetadata, MappingCandidateItem


# ---------------------------------------------------------------------------
# Helpers: minimal stubs for Agent2 and ConceptSetRecommender objects
# ---------------------------------------------------------------------------


def _make_concept_candidate(concept_id: int, concept_name: str, score: float = 0.8, source: str = "rag") -> Any:
    """Return a ConceptCandidate-like object with the fields we need."""
    candidate = MagicMock()
    candidate.concept_id = concept_id
    candidate.concept_name = concept_name
    candidate.score = score
    candidate.source = source
    return candidate


def _make_atlas_expression_with_items(concept_ids: list[int]) -> dict[str, Any]:
    """Build a minimal Atlas JSON expression dict with the given concept IDs."""
    return {
        "items": [
            {
                "concept": {
                    "CONCEPT_ID": cid,
                    "CONCEPT_NAME": f"Concept {cid}",
                },
                "includeDescendants": True,
                "isExcluded": False,
            }
            for cid in concept_ids
        ]
    }


def _make_agent2_mapping_result(concept_ids: list[int]) -> Any:
    """Return a minimal Agent2 mapping result mock."""
    result = MagicMock()
    result.concept_ids = concept_ids
    result.overbroad_concept_ids = []
    return result


def _make_recommendation(concept_ids: list[int], name: str = "Test Concept Set") -> Any:
    """Return a minimal recommendation mock (expression builder output)."""
    rec = MagicMock()
    rec.name = name
    expression_mock = MagicMock()
    expression_mock.to_atlas_json.return_value = _make_atlas_expression_with_items(concept_ids)
    rec.expression = expression_mock
    return rec


def _make_rag_recommendation(concept_ids: list[int], name: str = "RAG Concept Set") -> Any:
    """Return a minimal RAG ConceptSetRecommender recommendation mock."""
    rec = MagicMock()
    rec.name = name
    expression_mock = MagicMock()
    expression_mock.to_atlas_json.return_value = _make_atlas_expression_with_items(concept_ids)
    rec.expression = expression_mock
    return rec


class _FakeAgent2WorkflowModule:
    """Fake module for src.agents.agent2.workflow to avoid ChromaDB/settings imports."""

    def __init__(self, mapping_result: Any) -> None:
        self._mapping_result = mapping_result

    @property
    def Agent2Workflow(self) -> type:
        mapping_result = self._mapping_result

        class _FakeWorkflow:
            def process_with_details(self, seed: str, **kwargs: Any) -> Any:
                return mapping_result

        return _FakeWorkflow


class _FakeExpressionBuilderModule:
    """Fake module for src.agents.conceptset.expression_builder."""

    def __init__(self, recommendation: Any) -> None:
        self._recommendation = recommendation

    def get_expression_builder(self) -> Any:
        recommendation = self._recommendation

        class _FakeBuilder:
            def build_expression(self, candidates: Any, **kwargs: Any) -> Any:
                return recommendation

        return _FakeBuilder()


def _patch_agent2_imports(mapping_result: Any, recommendation: Any):
    """Context manager that injects fake Agent2 and ExpressionBuilder modules into sys.modules."""
    fake_wf_module = _FakeAgent2WorkflowModule(mapping_result)
    fake_builder_module = _FakeExpressionBuilderModule(recommendation)

    return patch.dict(
        sys.modules,
        {
            "src.agents.agent2.workflow": fake_wf_module,
            "src.agents.conceptset.expression_builder": fake_builder_module,
        },
    )


def _get_service() -> Any:
    from src.services.tte_service import TTEService

    return TTEService.__new__(TTEService)


# ---------------------------------------------------------------------------
# Test: Agent2 primary path returns mapping_metadata
# ---------------------------------------------------------------------------


class TestAgent2PathReturnsMetadata:
    """_recommend_seeded_concept_set (Agent2 path) should include mapping_metadata."""

    def test_result_contains_mapping_metadata_key(self) -> None:
        """Result dict contains 'mapping_metadata' key when Agent2 path succeeds."""
        # Arrange
        service = _get_service()

        candidates = [
            _make_concept_candidate(4329847, "Myocardial infarction", score=0.95, source="rag"),
            _make_concept_candidate(312327, "Coronary arteriosclerosis", score=0.72, source="ontology"),
        ]
        mapping_result = _make_agent2_mapping_result([4329847])
        recommendation = _make_recommendation([4329847])

        with (
            _patch_agent2_imports(mapping_result, recommendation),
            patch.object(service, "_fetch_concept_candidates", return_value=candidates),
            patch.object(service, "_resolve_seeded_domain", return_value="Condition"),
        ):
            # Act
            result = service._recommend_seeded_concept_set("myocardial infarction")

        # Assert
        assert "mapping_metadata" in result

    def test_mapping_metadata_is_criterion_mapping_metadata_instance(self) -> None:
        """mapping_metadata is an instance of CriterionMappingMetadata."""
        service = _get_service()

        candidates = [_make_concept_candidate(4329847, "Myocardial infarction", score=0.95, source="rag")]
        mapping_result = _make_agent2_mapping_result([4329847])
        recommendation = _make_recommendation([4329847])

        with (
            _patch_agent2_imports(mapping_result, recommendation),
            patch.object(service, "_fetch_concept_candidates", return_value=candidates),
            patch.object(service, "_resolve_seeded_domain", return_value="Condition"),
        ):
            result = service._recommend_seeded_concept_set("myocardial infarction")

        assert isinstance(result["mapping_metadata"], CriterionMappingMetadata)

    def test_mapping_metadata_rerank_method_is_agent2(self) -> None:
        """rerankMethod is 'agent2' on the Agent2 path."""
        service = _get_service()

        candidates = [_make_concept_candidate(4329847, "Myocardial infarction", score=0.95)]
        mapping_result = _make_agent2_mapping_result([4329847])
        recommendation = _make_recommendation([4329847])

        with (
            _patch_agent2_imports(mapping_result, recommendation),
            patch.object(service, "_fetch_concept_candidates", return_value=candidates),
            patch.object(service, "_resolve_seeded_domain", return_value="Condition"),
        ):
            result = service._recommend_seeded_concept_set("myocardial infarction")

        assert result["mapping_metadata"].rerankMethod == "agent2"

    def test_mapping_metadata_query_used_matches_normalized_seed(self) -> None:
        """queryUsed is the normalized seed text (whitespace collapsed and stripped)."""
        service = _get_service()

        candidates = [_make_concept_candidate(4329847, "Myocardial infarction", score=0.95)]
        mapping_result = _make_agent2_mapping_result([4329847])
        recommendation = _make_recommendation([4329847])

        with (
            _patch_agent2_imports(mapping_result, recommendation),
            patch.object(service, "_fetch_concept_candidates", return_value=candidates),
            patch.object(service, "_resolve_seeded_domain", return_value="Condition"),
        ):
            result = service._recommend_seeded_concept_set("  myocardial   infarction  ")

        # Normalized: leading/trailing spaces stripped, internal spaces collapsed
        assert result["mapping_metadata"].queryUsed == "myocardial infarction"


# ---------------------------------------------------------------------------
# Test: mapping_metadata marks included vs. rejected candidates
# ---------------------------------------------------------------------------


class TestMappingMetadataInclusionFlags:
    """included=True for concepts in the final expression, False for those filtered out."""

    def test_candidate_in_expression_has_included_true(self) -> None:
        """A candidate whose concept_id appears in the expression items has included=True."""
        service = _get_service()

        # 3 candidates, only concept 4329847 ends up in the expression
        candidates = [
            _make_concept_candidate(4329847, "Myocardial infarction", score=0.95),
            _make_concept_candidate(312327, "Coronary arteriosclerosis", score=0.72),
            _make_concept_candidate(4185932, "Acute MI", score=0.60),
        ]
        mapping_result = _make_agent2_mapping_result([4329847, 312327, 4185932])
        # Expression only has concept 4329847
        recommendation = _make_recommendation([4329847])

        with (
            _patch_agent2_imports(mapping_result, recommendation),
            patch.object(service, "_fetch_concept_candidates", return_value=candidates),
            patch.object(service, "_resolve_seeded_domain", return_value="Condition"),
        ):
            result = service._recommend_seeded_concept_set("myocardial infarction")

        meta = result["mapping_metadata"]
        by_id = {c.conceptId: c for c in meta.allCandidates}

        assert by_id[4329847].included is True
        assert by_id[312327].included is False
        assert by_id[4185932].included is False

    def test_selected_concept_ids_match_expression_items(self) -> None:
        """selectedConceptIds matches concept IDs from the Atlas expression items."""
        service = _get_service()

        candidates = [
            _make_concept_candidate(4329847, "Myocardial infarction", score=0.95),
            _make_concept_candidate(312327, "Coronary arteriosclerosis", score=0.72),
        ]
        mapping_result = _make_agent2_mapping_result([4329847, 312327])
        recommendation = _make_recommendation([4329847])  # only 1 concept selected

        with (
            _patch_agent2_imports(mapping_result, recommendation),
            patch.object(service, "_fetch_concept_candidates", return_value=candidates),
            patch.object(service, "_resolve_seeded_domain", return_value="Condition"),
        ):
            result = service._recommend_seeded_concept_set("myocardial infarction")

        assert result["mapping_metadata"].selectedConceptIds == [4329847]

    def test_all_candidates_present_in_all_candidates_list(self) -> None:
        """allCandidates contains all input candidates."""
        service = _get_service()

        candidates = [
            _make_concept_candidate(4329847, "Myocardial infarction", score=0.95),
            _make_concept_candidate(312327, "Coronary arteriosclerosis", score=0.72),
            _make_concept_candidate(4185932, "Acute MI", score=0.60),
        ]
        mapping_result = _make_agent2_mapping_result([4329847, 312327, 4185932])
        recommendation = _make_recommendation([4329847])

        with (
            _patch_agent2_imports(mapping_result, recommendation),
            patch.object(service, "_fetch_concept_candidates", return_value=candidates),
            patch.object(service, "_resolve_seeded_domain", return_value="Condition"),
        ):
            result = service._recommend_seeded_concept_set("myocardial infarction")

        assert len(result["mapping_metadata"].allCandidates) == 3


# ---------------------------------------------------------------------------
# Test: RAG fallback path returns mapping_metadata
# ---------------------------------------------------------------------------


class TestRagFallbackReturnsMetadata:
    """_recommend_seeded_concept_set_rag_fallback should include mapping_metadata."""

    def _make_rag_response(self, concept_ids: list[int]) -> Any:
        response = MagicMock()
        rec = _make_rag_recommendation(concept_ids)
        response.include_recommendations = [rec]
        response.fallback_reason = None
        return response

    def test_rag_fallback_result_contains_mapping_metadata(self) -> None:
        """RAG fallback returns a dict with 'mapping_metadata' key."""
        service = _get_service()

        with (
            patch.object(
                service,
                "_get_seeded_concept_set_recommender",
                return_value=MagicMock(recommend=MagicMock(return_value=self._make_rag_response([4329847]))),
            ),
            patch.object(service, "_resolve_seeded_domain", return_value="Condition"),
            patch.object(service, "_recommendation_supports_domain", return_value=True),
        ):
            result = service._recommend_seeded_concept_set_rag_fallback("myocardial infarction")

        assert "mapping_metadata" in result

    def test_rag_fallback_rerank_method_is_rag_fallback(self) -> None:
        """rerankMethod is 'rag_fallback' on the RAG fallback path."""
        service = _get_service()

        with (
            patch.object(
                service,
                "_get_seeded_concept_set_recommender",
                return_value=MagicMock(recommend=MagicMock(return_value=self._make_rag_response([4329847]))),
            ),
            patch.object(service, "_resolve_seeded_domain", return_value="Condition"),
            patch.object(service, "_recommendation_supports_domain", return_value=True),
        ):
            result = service._recommend_seeded_concept_set_rag_fallback("myocardial infarction")

        assert result["mapping_metadata"].rerankMethod == "rag_fallback"

    def test_rag_fallback_query_used_matches_seed(self) -> None:
        """queryUsed matches the normalized_seed passed to the method."""
        service = _get_service()

        with (
            patch.object(
                service,
                "_get_seeded_concept_set_recommender",
                return_value=MagicMock(recommend=MagicMock(return_value=self._make_rag_response([4329847]))),
            ),
            patch.object(service, "_resolve_seeded_domain", return_value="Condition"),
            patch.object(service, "_recommendation_supports_domain", return_value=True),
        ):
            result = service._recommend_seeded_concept_set_rag_fallback("prior MI")

        assert result["mapping_metadata"].queryUsed == "prior MI"

    def test_rag_fallback_all_candidates_have_included_true(self) -> None:
        """RAG fallback: all returned concepts are marked included=True (all are selected)."""
        service = _get_service()

        with (
            patch.object(
                service,
                "_get_seeded_concept_set_recommender",
                return_value=MagicMock(
                    recommend=MagicMock(return_value=self._make_rag_response([4329847, 312327]))
                ),
            ),
            patch.object(service, "_resolve_seeded_domain", return_value="Condition"),
            patch.object(service, "_recommendation_supports_domain", return_value=True),
        ):
            result = service._recommend_seeded_concept_set_rag_fallback("myocardial infarction")

        meta = result["mapping_metadata"]
        assert all(c.included is True for c in meta.allCandidates)

    def test_rag_fallback_rerank_confidence_is_none(self) -> None:
        """rerankConfidence is None on the RAG fallback path (no reranker available)."""
        service = _get_service()

        with (
            patch.object(
                service,
                "_get_seeded_concept_set_recommender",
                return_value=MagicMock(recommend=MagicMock(return_value=self._make_rag_response([4329847]))),
            ),
            patch.object(service, "_resolve_seeded_domain", return_value="Condition"),
            patch.object(service, "_recommendation_supports_domain", return_value=True),
        ):
            result = service._recommend_seeded_concept_set_rag_fallback("myocardial infarction")

        assert result["mapping_metadata"].rerankConfidence is None


# ---------------------------------------------------------------------------
# Test: backward compatibility — existing callers are unaffected
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Adding mapping_metadata must not break existing caller behaviour."""

    def test_expression_key_still_present_in_result(self) -> None:
        """'expression', 'name', and 'domain' keys are still present after adding mapping_metadata."""
        service = _get_service()

        candidates = [_make_concept_candidate(4329847, "Myocardial infarction", score=0.95)]
        mapping_result = _make_agent2_mapping_result([4329847])
        recommendation = _make_recommendation([4329847])

        with (
            _patch_agent2_imports(mapping_result, recommendation),
            patch.object(service, "_fetch_concept_candidates", return_value=candidates),
            patch.object(service, "_resolve_seeded_domain", return_value="Condition"),
        ):
            result = service._recommend_seeded_concept_set("myocardial infarction")

        assert "expression" in result
        assert "name" in result
        assert "domain" in result

    def test_rag_fallback_expression_key_still_present(self) -> None:
        """RAG fallback: 'expression', 'name', and 'domain' keys are still present."""
        service = _get_service()

        response = MagicMock()
        rec = _make_rag_recommendation([4329847])
        response.include_recommendations = [rec]
        response.fallback_reason = None

        with (
            patch.object(
                service,
                "_get_seeded_concept_set_recommender",
                return_value=MagicMock(recommend=MagicMock(return_value=response)),
            ),
            patch.object(service, "_resolve_seeded_domain", return_value="Condition"),
            patch.object(service, "_recommendation_supports_domain", return_value=True),
        ):
            result = service._recommend_seeded_concept_set_rag_fallback("myocardial infarction")

        assert "expression" in result
        assert "name" in result
        assert "domain" in result
