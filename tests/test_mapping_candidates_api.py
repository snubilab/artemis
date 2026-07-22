"""Tests for GET mapping-candidates endpoint and pipeline threading (SPEC-UI-003 Task 3).

RED phase: All tests written before implementation.

Coverage:
1. test_get_mapping_candidates_returns_metadata — mock service, verify 200 with CriterionMappingMetadata
2. test_get_mapping_candidates_no_artifact_returns_404 — no eligibility artifacts → 404
3. test_get_mapping_candidates_criterion_not_found_returns_404 — artifact exists but no matching criterion_id → 404
4. test_criterion_mapping_meta_stored_in_artifact_payload — _build_process_eligibility_artifact_payload
   includes criterionMappingMetadata key in payload
5. test_build_seeded_eligibility_rule_includes_mapping_metadata — return dict has _mapping_metadata key
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# HTTP-client tests require fastapi; skip gracefully in local envs without it
pytest.importorskip("fastapi", reason="fastapi not installed in this environment")

from src.api.models.tte import CriterionMappingMetadata, MappingCandidateItem
from src.models.ir import ProvisionalSectionSource, ProvisionalStudyIR


def _make_mapping_quality_signal() -> Any:
    from src.api.models.tte import MappingQualitySignal

    return MappingQualitySignal(status="ok", seedCount=1)


def _make_capability_signal() -> Any:
    from src.api.models.tte import CapabilitySignal

    return CapabilitySignal(
        owner="test",
        fidelity="high",
        fidelityNote="test",
        stageKind="agent",
    )


def _create_test_client():
    """Create a minimal test client with only the TTE router."""
    from src.api.main import create_app
    from testclient_compat import CompatTestClient

    return CompatTestClient(create_app())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_criterion_mapping_metadata() -> CriterionMappingMetadata:
    return CriterionMappingMetadata(
        allCandidates=[
            MappingCandidateItem(
                conceptId=4329847,
                conceptName="Myocardial infarction",
                score=0.92,
                source="agent2",
                included=True,
            )
        ],
        rerankConfidence=None,
        rerankMethod="agent2",
        queryUsed="prior MI",
        selectedConceptIds=[4329847],
    )


def _make_artifact(
    artifact_id: str,
    kind: str,
    criterion_mapping_metadata: dict[str, Any] | None = None,
) -> MagicMock:
    artifact = MagicMock()
    artifact.id = artifact_id
    artifact.kind = kind
    payload: dict[str, Any] = {}
    if criterion_mapping_metadata is not None:
        payload["criterionMappingMetadata"] = criterion_mapping_metadata
    artifact.payload = payload
    return artifact


def _get_service() -> Any:
    from src.services.tte_service import TTEService

    return TTEService.__new__(TTEService)


# ---------------------------------------------------------------------------
# Test: GET endpoint returns CriterionMappingMetadata on success (200)
# ---------------------------------------------------------------------------


class TestGetMappingCandidatesReturnsMetadata:
    """Happy-path: artifact exists and contains mapping metadata for the criterion."""

    def test_get_mapping_candidates_returns_metadata(self) -> None:
        # Arrange
        meta = _make_criterion_mapping_metadata()
        artifact = _make_artifact(
            "art-001",
            "eligibility_processing",
            criterion_mapping_metadata={"5": meta.model_dump()},
        )

        mock_service = MagicMock()
        mock_service.list_artifacts.return_value = [artifact]
        mock_service.get_artifact.return_value = artifact

        client = _create_test_client()

        with patch("src.api.tte.get_tte_service", return_value=mock_service):
            # Act
            response = client.get("/tte/studies/1/criteria/5/mapping-candidates")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["rerankMethod"] == "agent2"
        assert data["queryUsed"] == "prior MI"
        assert len(data["allCandidates"]) == 1
        assert data["allCandidates"][0]["conceptId"] == 4329847


# ---------------------------------------------------------------------------
# Test: GET endpoint returns 404 when no eligibility artifacts
# ---------------------------------------------------------------------------


class TestGetMappingCandidatesNoArtifact:
    """No eligibility_processing artifacts → 404."""

    def test_get_mapping_candidates_no_artifact_returns_404(self) -> None:
        # Arrange
        # Only non-eligibility-processing artifact
        other_artifact = _make_artifact("art-002", "cohort_generation")

        mock_service = MagicMock()
        mock_service.list_artifacts.return_value = [other_artifact]

        client = _create_test_client()

        with patch("src.api.tte.get_tte_service", return_value=mock_service):
            # Act
            response = client.get("/tte/studies/1/criteria/5/mapping-candidates")

        # Assert
        assert response.status_code == 404
        assert "No eligibility processing artifact" in response.json()["detail"]

    def test_get_mapping_candidates_empty_artifact_list_returns_404(self) -> None:
        # Arrange
        mock_service = MagicMock()
        mock_service.list_artifacts.return_value = []

        client = _create_test_client()

        with patch("src.api.tte.get_tte_service", return_value=mock_service):
            # Act
            response = client.get("/tte/studies/1/criteria/99/mapping-candidates")

        # Assert
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Test: GET endpoint returns 404 when criterion_id not in metadata
# ---------------------------------------------------------------------------


class TestGetMappingCandidatesCriterionNotFound:
    """Artifact exists but has no metadata for the requested criterion_id."""

    def test_get_mapping_candidates_criterion_not_found_returns_404(self) -> None:
        # Arrange
        meta = _make_criterion_mapping_metadata()
        # Metadata exists for criterion 5, but we request criterion 99
        artifact = _make_artifact(
            "art-003",
            "eligibility_processing",
            criterion_mapping_metadata={"5": meta.model_dump()},
        )

        mock_service = MagicMock()
        mock_service.list_artifacts.return_value = [artifact]
        mock_service.get_artifact.return_value = artifact

        client = _create_test_client()

        with patch("src.api.tte.get_tte_service", return_value=mock_service):
            # Act
            response = client.get("/tte/studies/1/criteria/99/mapping-candidates")

        # Assert
        assert response.status_code == 404
        assert "99" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Test: criterionMappingMetadata stored in artifact payload
# ---------------------------------------------------------------------------


class TestCriterionMappingMetaInPayload:
    """_build_process_eligibility_artifact_payload should include criterionMappingMetadata."""

    def test_criterion_mapping_meta_stored_in_artifact_payload(self) -> None:
        # Arrange
        service = _get_service()

        meta = _make_criterion_mapping_metadata()
        fake_circe: dict[str, Any] = {
            "ConceptSets": [],
            "PrimaryCriteria": {
                "CriteriaList": [{"ConditionOccurrence": {"CodesetId": 1}}],
                "ObservationWindow": {"PriorDays": 365, "PostDays": 0},
                "PrimaryCriteriaLimit": {"Type": "First"},
            },
            "InclusionRules": [],
            # Private key injected by _build_seeded_target_circe
            "_criterionMappingMetadata": {"3": meta.model_dump()},
        }

        study: dict[str, Any] = {"id": 1, "name": "Study 1"}

        provisional_ir = MagicMock(spec=ProvisionalStudyIR)
        section_source = MagicMock(spec=ProvisionalSectionSource)
        section_source.source = "test"
        section_source.fallback_used = False
        section_source.fragments = []

        with (
            patch.object(service, "_build_seeded_target_circe", return_value=dict(fake_circe)),
            patch.object(service, "_build_eligibility_suggestion", return_value={
                "targetCohortName": "Target",
                "inclusionCriteria": [],
                "exclusionCriteria": [],
            }),
            patch.object(service, "_build_mapping_quality_signal", return_value=_make_mapping_quality_signal()),
            patch.object(service, "_get_capability_signal", return_value=_make_capability_signal()),
            patch.object(service, "_apply_draft_concept_set_metadata", side_effect=lambda c, *a: c),
        ):
            # Act
            payload, _meta, status = service._build_process_eligibility_artifact_payload(
                study=study,
                provisional_ir=provisional_ir,
                section_source=section_source,
            )

        # Assert
        assert status == "completed"
        assert "criterionMappingMetadata" in payload
        assert "3" in payload["criterionMappingMetadata"]

    def test_private_circe_key_removed_from_structured_expression(self) -> None:
        """_criterionMappingMetadata must be removed from structured_expression before storage."""
        # Arrange
        service = _get_service()

        meta = _make_criterion_mapping_metadata()
        fake_circe: dict[str, Any] = {
            "ConceptSets": [],
            "PrimaryCriteria": {
                "CriteriaList": [{"ConditionOccurrence": {"CodesetId": 1}}],
                "ObservationWindow": {"PriorDays": 365, "PostDays": 0},
                "PrimaryCriteriaLimit": {"Type": "First"},
            },
            "InclusionRules": [],
            "_criterionMappingMetadata": {"3": meta.model_dump()},
        }

        study: dict[str, Any] = {"id": 1, "name": "Study 1"}

        provisional_ir = MagicMock(spec=ProvisionalStudyIR)
        section_source = MagicMock(spec=ProvisionalSectionSource)
        section_source.source = "test"
        section_source.fallback_used = False
        section_source.fragments = []

        with (
            patch.object(service, "_build_seeded_target_circe", return_value=dict(fake_circe)),
            patch.object(service, "_build_eligibility_suggestion", return_value={
                "targetCohortName": "Target",
                "inclusionCriteria": [],
                "exclusionCriteria": [],
            }),
            patch.object(service, "_build_mapping_quality_signal", return_value=_make_mapping_quality_signal()),
            patch.object(service, "_get_capability_signal", return_value=_make_capability_signal()),
            patch.object(service, "_apply_draft_concept_set_metadata", side_effect=lambda c, *a: c),
        ):
            # Act
            payload, _meta, _status = service._build_process_eligibility_artifact_payload(
                study=study,
                provisional_ir=provisional_ir,
                section_source=section_source,
            )

        # Assert: structured expression stored in payload must NOT contain private key
        structured = payload["proposedChanges"]["eligibility"]["structuredExpression"]
        assert "_criterionMappingMetadata" not in structured


# ---------------------------------------------------------------------------
# Test: _build_seeded_eligibility_rule includes _mapping_metadata
# ---------------------------------------------------------------------------


class TestBuildSeededEligibilityRuleIncludesMappingMetadata:
    """_build_seeded_eligibility_rule should include _mapping_metadata in return dict."""

    def test_build_seeded_eligibility_rule_includes_mapping_metadata(self) -> None:
        # Arrange
        service = _get_service()

        meta = _make_criterion_mapping_metadata()
        mock_mapped = {
            "name": "Prior MI",
            "expression": {"items": []},
            "domain": "Condition",
            "mapping_metadata": meta,
        }

        criterion: dict[str, Any] = {
            "id": 7,
            "description": "Prior MI",
            "domain": "Condition",
        }

        with patch.object(service, "_recommend_seeded_concept_set", return_value=mock_mapped):
            # Act
            result = service._build_seeded_eligibility_rule(
                criterion=criterion,
                codeset_id=2,
                exclusion=False,
            )

        # Assert
        assert "_mapping_metadata" in result
        assert result["_mapping_metadata"] is meta

    def test_build_seeded_eligibility_rule_mapping_metadata_none_when_absent(self) -> None:
        """When _recommend_seeded_concept_set returns no mapping_metadata, _mapping_metadata is None."""
        # Arrange
        service = _get_service()

        # Simulate the placeholder / RAG-fallback path that has no mapping_metadata
        mock_mapped = {
            "name": "Prior MI",
            "expression": {"items": []},
            "domain": "Condition",
            # no "mapping_metadata" key
        }

        criterion: dict[str, Any] = {
            "id": 8,
            "description": "Prior MI",
            "domain": "Condition",
        }

        with patch.object(service, "_recommend_seeded_concept_set", return_value=mock_mapped):
            # Act
            result = service._build_seeded_eligibility_rule(
                criterion=criterion,
                codeset_id=3,
                exclusion=False,
            )

        # Assert
        assert "_mapping_metadata" in result
        assert result["_mapping_metadata"] is None
