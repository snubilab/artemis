"""Tests for paperStatus integration in tte_service.run_generate_from_nct (SPEC-UI-011 T4)."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.api.models.tte import PaperStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service():
    """Create a TTEService instance with a mocked store."""
    from src.services.tte_service import TTEService

    store = MagicMock()
    store.create_job.return_value = {"id": "job-1", "status": "running"}
    store.update_job.return_value = {"id": "job-1", "status": "completed"}
    store.create_artifact.return_value = {"id": "artifact-1"}
    store.get_study.return_value = {"id": 1, "version": 1}
    store.find_latest_generate_from_nct_artifact.return_value = None

    svc = TTEService.__new__(TTEService)
    svc.store = store
    return svc


def _fake_tte_study_dict() -> dict[str, Any]:
    """A minimal dict that represents a validated TTEStudy."""
    return {
        "studyType": "comparative",
        "comparisonMode": "treatment_vs_rest",
        "outcomes": {"primary": [], "secondary": [], "safety": []},
        "eligibilityCriteria": [],
        "trialMetadata": {},
    }


def _mock_tte_study_validate(payload: dict) -> MagicMock:
    m = MagicMock()
    m.model_dump.return_value = payload
    return m


# ---------------------------------------------------------------------------
# Test 1: paper_status propagates to artifact_meta when parser sets it
# ---------------------------------------------------------------------------

def test_paper_status_in_artifact_meta_when_set():
    """When parser.last_paper_status is set, artifact_meta should contain paperStatus."""
    svc = _make_service()
    expected_paper_status = PaperStatus(source="pmc_fulltext", supplement_available=True)
    study_dict = _fake_tte_study_dict()

    with (
        patch.object(
            svc,
            "_generate_with_trial_agent_from_nct",
            return_value=(study_dict, "trial_agent", None, expected_paper_status),
        ),
        patch.object(svc, "_normalize_nct_id", return_value="NCT00000001"),
        patch.object(svc, "_get_capability_signal", return_value=MagicMock(model_dump=lambda: {})),
        patch.object(svc, "_get_generate_from_nct_generator_version", return_value="v1"),
        patch.object(svc, "_build_draft_generation_proposed_changes", return_value={}),
        patch.object(svc, "_build_suggestions", return_value=[]),
        patch("src.services.tte_service.TTEStudy") as mock_tte_study,
    ):
        mock_tte_study.model_validate.return_value = _mock_tte_study_validate(study_dict)
        response = svc.run_generate_from_nct(study_id=1, nct_id="NCT00000001")

    # artifact payload written to store should include paperStatus
    create_artifact_call = svc.store.create_artifact.call_args[0][0]
    meta = create_artifact_call["payload"]["meta"]
    assert meta["paperStatus"] == expected_paper_status.model_dump()

    # CapabilityRunResponse meta should also include paperStatus
    assert response.meta["paperStatus"] == expected_paper_status.model_dump()


# ---------------------------------------------------------------------------
# Test 2: artifact_meta["paperStatus"] is None when parser returns None
# ---------------------------------------------------------------------------

def test_paper_status_none_when_parser_returns_none():
    """When parser.last_paper_status is None, artifact_meta['paperStatus'] should be None."""
    svc = _make_service()
    study_dict = _fake_tte_study_dict()

    with (
        patch.object(
            svc,
            "_generate_with_trial_agent_from_nct",
            return_value=(study_dict, "heuristic", "some error", None),
        ),
        patch.object(svc, "_normalize_nct_id", return_value="NCT00000002"),
        patch.object(svc, "_get_capability_signal", return_value=MagicMock(model_dump=lambda: {})),
        patch.object(svc, "_get_generate_from_nct_generator_version", return_value="v1"),
        patch.object(svc, "_build_draft_generation_proposed_changes", return_value={}),
        patch.object(svc, "_build_suggestions", return_value=[]),
        patch("src.services.tte_service.TTEStudy") as mock_tte_study,
    ):
        mock_tte_study.model_validate.return_value = _mock_tte_study_validate(study_dict)
        response = svc.run_generate_from_nct(study_id=1, nct_id="NCT00000002")

    create_artifact_call = svc.store.create_artifact.call_args[0][0]
    meta = create_artifact_call["payload"]["meta"]
    assert meta["paperStatus"] is None
    assert response.meta["paperStatus"] is None


# ---------------------------------------------------------------------------
# Test 3: cache hit without paperStatus in cached meta returns None gracefully
# ---------------------------------------------------------------------------

def test_paper_status_none_for_cache_hit_missing_key():
    """Cache hit from artifact without paperStatus key returns None gracefully (SC-06)."""
    svc = _make_service()
    study_dict = _fake_tte_study_dict()

    cached_artifact = {
        "id": "old-artifact",
        "payload": {
            "proposedChanges": study_dict,
            "suggestions": [],
            "meta": {
                "generationMode": "trial_agent",
                "fallbackReason": None,
                # intentionally NO "paperStatus" key — simulates old artifact
                "cacheSourceArtifactId": "old-artifact",
            },
        },
    }
    svc.store.find_latest_generate_from_nct_artifact.return_value = cached_artifact

    with (
        patch.object(svc, "_normalize_nct_id", return_value="NCT00000003"),
        patch.object(svc, "_get_capability_signal", return_value=MagicMock(model_dump=lambda: {})),
        patch.object(svc, "_get_generate_from_nct_generator_version", return_value="v1"),
        patch.object(svc, "_build_draft_generation_proposed_changes", return_value={}),
        patch("src.services.tte_service.TTEStudy") as mock_tte_study,
    ):
        mock_tte_study.model_validate.return_value = _mock_tte_study_validate(study_dict)
        response = svc.run_generate_from_nct(study_id=1, nct_id="NCT00000003")

    create_artifact_call = svc.store.create_artifact.call_args[0][0]
    meta = create_artifact_call["payload"]["meta"]
    assert meta["paperStatus"] is None
    assert response.meta["paperStatus"] is None


# ---------------------------------------------------------------------------
# Test 4: cache hit WITH paperStatus preserved from cached meta
# ---------------------------------------------------------------------------

def test_paper_status_preserved_from_cache_hit():
    """Cache hit that has paperStatus in meta should propagate it to new artifact."""
    svc = _make_service()
    study_dict = _fake_tte_study_dict()
    cached_paper_status = PaperStatus(source="pubmed_abstract").model_dump()

    cached_artifact = {
        "id": "old-artifact",
        "payload": {
            "proposedChanges": study_dict,
            "suggestions": [],
            "meta": {
                "generationMode": "trial_agent",
                "fallbackReason": None,
                "cacheSourceArtifactId": "old-artifact",
                "paperStatus": cached_paper_status,
            },
        },
    }
    svc.store.find_latest_generate_from_nct_artifact.return_value = cached_artifact

    with (
        patch.object(svc, "_normalize_nct_id", return_value="NCT00000004"),
        patch.object(svc, "_get_capability_signal", return_value=MagicMock(model_dump=lambda: {})),
        patch.object(svc, "_get_generate_from_nct_generator_version", return_value="v1"),
        patch.object(svc, "_build_draft_generation_proposed_changes", return_value={}),
        patch("src.services.tte_service.TTEStudy") as mock_tte_study,
    ):
        mock_tte_study.model_validate.return_value = _mock_tte_study_validate(study_dict)
        response = svc.run_generate_from_nct(study_id=1, nct_id="NCT00000004")

    create_artifact_call = svc.store.create_artifact.call_args[0][0]
    meta = create_artifact_call["payload"]["meta"]
    assert meta["paperStatus"] == cached_paper_status
    assert response.meta["paperStatus"] == cached_paper_status
