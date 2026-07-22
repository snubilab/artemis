"""Integration tests for HITL mapping flow (SPEC-UI-003 Task 7).

RED phase: Tests written before running to verify cross-layer integration.
GREEN phase: All tests should pass because Tasks 1-4 already implement the logic.

Tests:
1. test_metadata_stored_in_artifact_and_retrievable_via_api
2. test_backward_compat_artifact_without_mapping_metadata_loads_ok
3. test_demographic_criterion_returns_404_for_mapping_candidates
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# HTTP-client tests require fastapi; skip gracefully in local envs without it
pytest.importorskip("fastapi", reason="fastapi not installed in this environment")


def _create_test_client():
    """Create a minimal test client with only the TTE router."""
    from src.api.main import create_app
    from testclient_compat import CompatTestClient

    return CompatTestClient(create_app())


def _make_criterion_mapping_metadata() -> Any:
    from src.api.models.tte import CriterionMappingMetadata, MappingCandidateItem

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
        rerankConfidence=0.88,
        rerankMethod="agent2",
        queryUsed="prior myocardial infarction",
        selectedConceptIds=[4329847],
    )


def _make_artifact(
    artifact_id: str,
    kind: str,
    payload: dict[str, Any] | None = None,
) -> MagicMock:
    """Build a mock artifact with the given kind and payload."""
    artifact = MagicMock()
    artifact.id = artifact_id
    artifact.kind = kind
    artifact.payload = payload if payload is not None else {}
    return artifact


# ---------------------------------------------------------------------------
# Test 1: End-to-end metadata flow
# After process-eligibility completes, criterionMappingMetadata is stored in
# the artifact payload and GET mapping-candidates returns it.
# ---------------------------------------------------------------------------


class TestMetadataStoredInArtifactAndRetrievableViaApi:
    """End-to-end: artifact payload has criterionMappingMetadata → GET returns it."""

    def test_metadata_stored_in_artifact_and_retrievable_via_api(self) -> None:
        # Arrange
        meta = _make_criterion_mapping_metadata()
        artifact = _make_artifact(
            "art-001",
            "eligibility_processing",
            payload={"criterionMappingMetadata": {"5": meta.model_dump()}},
        )

        mock_service = MagicMock()
        mock_service.list_artifacts.return_value = [artifact]
        mock_service.get_artifact.return_value = artifact

        client = _create_test_client()

        with patch("src.api.tte.get_tte_service", return_value=mock_service):
            # Act
            response = client.get("/tte/studies/1/criteria/5/mapping-candidates")

        # Assert: 200 with the stored metadata
        assert response.status_code == 200
        data = response.json()
        assert data["rerankMethod"] == "agent2"
        assert data["rerankConfidence"] == pytest.approx(0.88)
        assert data["queryUsed"] == "prior myocardial infarction"
        assert len(data["allCandidates"]) == 1
        assert data["allCandidates"][0]["conceptId"] == 4329847
        assert data["selectedConceptIds"] == [4329847]


# ---------------------------------------------------------------------------
# Test 2: Backward compatibility
# Old artifacts without criterionMappingMetadata still load without crashing.
# The endpoint returns 404 (not a 500 KeyError/AttributeError).
# ---------------------------------------------------------------------------


class TestBackwardCompatArtifactWithoutMappingMetadataLoadsOk:
    """Old artifact with no criterionMappingMetadata key must not crash; returns 404."""

    def test_backward_compat_artifact_without_mapping_metadata_loads_ok(self) -> None:
        # Arrange: old-style payload — no criterionMappingMetadata key at all
        old_payload: dict[str, Any] = {
            "proposedChanges": {
                "eligibility": {
                    "structuredExpression": {},
                }
            },
            "eligibilityStatus": "completed",
        }
        artifact = _make_artifact("art-002", "eligibility_processing", payload=old_payload)

        mock_service = MagicMock()
        mock_service.list_artifacts.return_value = [artifact]
        mock_service.get_artifact.return_value = artifact

        client = _create_test_client()

        with patch("src.api.tte.get_tte_service", return_value=mock_service):
            # Act
            response = client.get("/tte/studies/1/criteria/5/mapping-candidates")

        # Assert: must NOT be 500. Must be 404 (criterion metadata not found).
        # The endpoint uses .get() so no KeyError should occur.
        assert response.status_code == 404
        detail = response.json()["detail"]
        # Either "No eligibility processing artifact" or contains the criterion id
        assert "5" in detail or "No eligibility processing artifact" in detail


# ---------------------------------------------------------------------------
# Test 3: Demographic criteria
# GET mapping-candidates returns 404 for criteria with demographic domains.
# Demographic criteria are skipped by the mapping pipeline so no metadata is stored.
# ---------------------------------------------------------------------------


class TestDemographicCriterionReturns404ForMappingCandidates:
    """Demographic criteria have no mapping metadata → GET returns 404."""

    def test_demographic_criterion_returns_404_for_mapping_candidates(self) -> None:
        # Arrange: artifact exists but has mapping metadata only for non-demographic criterion 5.
        # Criterion 3 is "Age" (demographic) and was never processed by the mapping agent.
        meta = _make_criterion_mapping_metadata()
        artifact = _make_artifact(
            "art-003",
            "eligibility_processing",
            payload={
                "criterionMappingMetadata": {
                    "5": meta.model_dump(),
                    # criterion 3 (Age) intentionally absent
                }
            },
        )

        mock_service = MagicMock()
        mock_service.list_artifacts.return_value = [artifact]
        mock_service.get_artifact.return_value = artifact

        client = _create_test_client()

        with patch("src.api.tte.get_tte_service", return_value=mock_service):
            # Act: request mapping candidates for demographic criterion 3
            response = client.get("/tte/studies/1/criteria/3/mapping-candidates")

        # Assert: 404 because no metadata was stored for demographic criterion
        assert response.status_code == 404
        detail = response.json()["detail"]
        assert "3" in detail
