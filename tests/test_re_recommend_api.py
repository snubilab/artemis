"""Tests for POST re-recommend endpoint (SPEC-UI-003 Task 4).

RED phase: All tests written before implementation.

Coverage:
1. test_re_recommend_returns_metadata — mock pipeline, verify 200 with CriterionMappingMetadata
2. test_re_recommend_study_not_found_returns_404 — get_study raises KeyError → 404
3. test_re_recommend_criterion_not_found_returns_404 — criterion not in eligibility → 404
4. test_re_recommend_demographic_criterion_without_value_constraint_returns_200 — domain in
   DEMOGRAPHIC_DOMAINS but no valueConstraint → falls through to mapping, 200 (see the
   demographic-no-rule fallthrough contract in src/api/models/tte.py)
5. test_re_recommend_with_hint_builds_correct_query — query includes hint text
6. test_run_mapping_pipeline_for_query_returns_metadata — unit test on helper (no HTTP)
7. test_run_mapping_pipeline_for_query_empty_candidates — stage2 returns [] → empty metadata
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import importlib.util

import pytest

from src.api.models.tte import CriterionMappingMetadata, MappingCandidateItem

_fastapi_available = importlib.util.find_spec("fastapi") is not None
_skip_http = pytest.mark.skipif(not _fastapi_available, reason="fastapi not installed")


def _create_test_client():
    from src.api.main import create_app
    from testclient_compat import CompatTestClient

    return CompatTestClient(create_app())


def _make_criterion_mapping_metadata() -> CriterionMappingMetadata:
    return CriterionMappingMetadata(
        allCandidates=[
            MappingCandidateItem(
                conceptId=4329847,
                conceptName="Myocardial infarction",
                score=0.92,
                source="rag",
                included=True,
            )
        ],
        rerankConfidence=0.88,
        rerankMethod="cross_encoder",
        queryUsed="prior myocardial infarction",
        selectedConceptIds=[4329847],
    )


def _make_study_dict(
    criterion_id: int = 5,
    domain: str = "Condition",
    description: str = "Prior MI",
    source_text: str = "prior myocardial infarction",
) -> dict[str, Any]:
    """Build a minimal study dict with one inclusion criterion."""
    return {
        "id": 1,
        "name": "Test Study",
        "eligibility": {
            "inclusionCriteria": [
                {
                    "id": criterion_id,
                    "description": description,
                    "domain": domain,
                    "sourceText": source_text,
                    "conceptSetName": "",
                    "mappable": True,
                }
            ],
            "exclusionCriteria": [],
        },
    }


# ---------------------------------------------------------------------------
# Test 1: Happy path — returns 200 with CriterionMappingMetadata
# ---------------------------------------------------------------------------


@_skip_http
class TestReRecommendReturnsMetadata:
    """POST re-recommend returns 200 with fresh CriterionMappingMetadata."""

    def test_re_recommend_returns_metadata(self) -> None:
        # Arrange
        study = _make_study_dict(criterion_id=5)
        meta = _make_criterion_mapping_metadata()

        mock_service = MagicMock()
        mock_service.get_study.return_value = study
        mock_service._run_mapping_pipeline_for_query.return_value = meta

        client = _create_test_client()

        with patch("src.api.tte.get_tte_service", return_value=mock_service):
            # Act
            response = client.post(
                "/tte/studies/1/criteria/5/re-recommend",
                json={"hint": "", "topK": 10},
            )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["rerankMethod"] == "cross_encoder"
        assert data["rerankConfidence"] == pytest.approx(0.88)
        assert len(data["allCandidates"]) == 1
        assert data["allCandidates"][0]["conceptId"] == 4329847


# ---------------------------------------------------------------------------
# Test 2: Study not found → 404
# ---------------------------------------------------------------------------


@_skip_http
class TestReRecommendStudyNotFound:
    """POST re-recommend returns 404 when study does not exist."""

    def test_re_recommend_study_not_found_returns_404(self) -> None:
        # Arrange
        mock_service = MagicMock()
        mock_service.get_study.side_effect = KeyError("Study 999 not found")

        client = _create_test_client()

        with patch("src.api.tte.get_tte_service", return_value=mock_service):
            # Act
            response = client.post(
                "/tte/studies/999/criteria/5/re-recommend",
                json={"hint": ""},
            )

        # Assert
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Test 3: Criterion not found → 404
# ---------------------------------------------------------------------------


@_skip_http
class TestReRecommendCriterionNotFound:
    """POST re-recommend returns 404 when criterion_id not in eligibility."""

    def test_re_recommend_criterion_not_found_returns_404(self) -> None:
        # Arrange — study has criterion 5 but we request criterion 99
        study = _make_study_dict(criterion_id=5)
        mock_service = MagicMock()
        mock_service.get_study.return_value = study

        client = _create_test_client()

        with patch("src.api.tte.get_tte_service", return_value=mock_service):
            # Act
            response = client.post(
                "/tte/studies/1/criteria/99/re-recommend",
                json={"hint": ""},
            )

        # Assert
        assert response.status_code == 404
        assert "99" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Test 4: Demographic-domain criterion with no structured valueConstraint
# ---------------------------------------------------------------------------
#
# Contract changed: a criterion whose domain is in DEMOGRAPHIC_DOMAINS but that
# carries no valueConstraint (so no DemographicCriteriaList rule is buildable)
# and is not a group label now falls through to the same concept-set mapping
# path as any other criterion, instead of being hard-blocked with 400. This
# criterion's own description ("Age >= 18") never had a structured
# valueConstraint captured for it -- domain="Age" alone does not prove the
# value was structured -- so it is genuinely unmapped today and is the same
# shape as the still-dropped exclusion-demographic criteria the fallthrough
# fix targets. See src/api/models/tte.py's
# is_demographic_domain_but_not_a_demographic_rule for the shared predicate.


@_skip_http
class TestReRecommendDemographicCriterion:
    """POST re-recommend now maps a demographic-domain criterion that has no
    structured valueConstraint, instead of hard-blocking it with 400."""

    def test_re_recommend_demographic_criterion_without_value_constraint_returns_200(self) -> None:
        # Arrange — domain is "Age" (in DEMOGRAPHIC_DOMAINS) but no
        # valueConstraint is present, so no DemographicCriteriaList rule can
        # be built; per the fallthrough contract this is now mappable.
        study = _make_study_dict(
            criterion_id=3,
            domain="Age",
            description="Age >= 18",
            source_text="Patients at least 18 years old",
        )
        meta = _make_criterion_mapping_metadata()
        mock_service = MagicMock()
        mock_service.get_study.return_value = study
        # NOTE: the endpoint calls get_tte_service().run_mapping_pipeline_for_query(...)
        # (no leading underscore) -- src/api/tte.py:284. Test 1 above mocks the wrong
        # (underscore-prefixed) attribute name and its assertion silently never
        # exercises the mocked return value; that is a pre-existing, out-of-scope bug
        # (reproduces identically on the unmodified baseline), not touched here.
        mock_service.run_mapping_pipeline_for_query.return_value = meta

        client = _create_test_client()

        with patch("src.api.tte.get_tte_service", return_value=mock_service):
            # Act
            response = client.post(
                "/tte/studies/1/criteria/3/re-recommend",
                json={"hint": ""},
            )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["rerankMethod"] == "cross_encoder"


# ---------------------------------------------------------------------------
# Test 5: Hint is incorporated into query
# ---------------------------------------------------------------------------


@_skip_http
class TestReRecommendWithHintBuildsCorrectQuery:
    """POST re-recommend builds query from sourceText + hint."""

    def test_re_recommend_with_hint_builds_correct_query(self) -> None:
        # Arrange
        study = _make_study_dict(
            criterion_id=5,
            source_text="prior myocardial infarction",
        )
        meta = _make_criterion_mapping_metadata()

        mock_service = MagicMock()
        mock_service.get_study.return_value = study
        mock_service._run_mapping_pipeline_for_query.return_value = meta

        client = _create_test_client()

        with patch("src.api.tte.get_tte_service", return_value=mock_service):
            # Act
            response = client.post(
                "/tte/studies/1/criteria/5/re-recommend",
                json={"hint": "STEMI", "topK": 5},
            )

        # Assert
        assert response.status_code == 200
        # Verify query was built with both sourceText and hint
        call_args = mock_service._run_mapping_pipeline_for_query.call_args
        query_used = call_args[0][0] if call_args[0] else call_args[1].get("query", "")
        assert "prior myocardial infarction" in query_used
        assert "STEMI" in query_used


# ---------------------------------------------------------------------------
# Test 6: Unit test for _run_mapping_pipeline_for_query helper (no HTTP)
# ---------------------------------------------------------------------------
# Note: This test does NOT use importorskip — it runs without FastAPI.


class TestRunMappingPipelineForQuery:
    """Unit tests for TTEService._run_mapping_pipeline_for_query."""

    def test_run_mapping_pipeline_for_query_returns_metadata(self) -> None:
        # Arrange — mock stage2 search result
        mock_candidate = MagicMock()
        mock_candidate.concept_id = 4329847
        mock_candidate.concept_name = "Myocardial infarction"
        mock_candidate.score = 0.92
        mock_candidate.source = "rag"

        mock_rerank_result = MagicMock()
        mock_rerank_result.candidates = [mock_candidate]
        mock_rerank_result.confidence = 0.88
        mock_rerank_result.method = "cross_encoder"

        mock_stage2 = MagicMock()
        mock_stage2.search.return_value = [mock_candidate]

        mock_reranker_instance = MagicMock()
        mock_reranker_instance.rerank.return_value = mock_rerank_result

        mock_stage2_module = MagicMock()
        mock_stage2_module.get_stage2_pipeline.return_value = mock_stage2

        mock_reranker_module = MagicMock()
        mock_reranker_module.ClinicalReranker.return_value = mock_reranker_instance

        import sys
        with patch.dict(sys.modules, {
            "src.agents.conceptset.stage2_pipeline": mock_stage2_module,
            "src.agents.conceptset.clinical_reranker": mock_reranker_module,
        }):
            from src.services.tte_service import TTEService

            service = TTEService.__new__(TTEService)
            # Act
            result = service._run_mapping_pipeline_for_query(
                "prior myocardial infarction",
                domain="Condition",
                top_k=10,
            )

        # Assert
        assert isinstance(result, CriterionMappingMetadata)
        assert result.rerankConfidence == pytest.approx(0.88)
        assert result.rerankMethod == "cross_encoder"
        assert result.queryUsed == "prior myocardial infarction"
        assert len(result.allCandidates) == 1
        assert result.allCandidates[0].conceptId == 4329847


# ---------------------------------------------------------------------------
# Test 7: Unit test for _run_mapping_pipeline_for_query with empty candidates
# ---------------------------------------------------------------------------


class TestRunMappingPipelineForQueryEmptyCandidates:
    """_run_mapping_pipeline_for_query returns empty metadata when stage2 returns []."""

    def test_run_mapping_pipeline_for_query_empty_candidates(self) -> None:
        # Arrange
        mock_stage2 = MagicMock()
        mock_stage2.search.return_value = []

        mock_stage2_module = MagicMock()
        mock_stage2_module.get_stage2_pipeline.return_value = mock_stage2

        # Patch both modules to prevent import-time side effects (Settings loading)
        mock_reranker_module = MagicMock()

        import sys
        with patch.dict(sys.modules, {
            "src.agents.conceptset.stage2_pipeline": mock_stage2_module,
            "src.agents.conceptset.clinical_reranker": mock_reranker_module,
        }):
            from src.services.tte_service import TTEService

            service = TTEService.__new__(TTEService)
            # Act
            result = service._run_mapping_pipeline_for_query(
                "obscure criterion with no matches",
                domain=None,
                top_k=10,
            )

        # Assert
        assert isinstance(result, CriterionMappingMetadata)
        assert result.allCandidates == []
        assert result.rerankConfidence == pytest.approx(0.0)
        assert result.rerankMethod == "none"
        assert result.queryUsed == "obscure criterion with no matches"
        assert result.selectedConceptIds == []
