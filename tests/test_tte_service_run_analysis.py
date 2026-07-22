"""Tests for run_analysis() auto-apply of analysis_result artifact.

Verifies that after run_analysis() completes, the analysis_result artifact
is automatically applied so study.results.mode updates from
"webapi_generation" to "analysis".
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.services.tte_service import TTEService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service() -> TTEService:
    """Create a TTEService instance with mocked store and external deps."""
    svc = TTEService.__new__(TTEService)
    svc.store = MagicMock()
    return svc


def _fake_study(study_id: int = 1, version: int = 1) -> dict[str, Any]:
    return {
        "id": study_id,
        "version": version,
        "name": "Test Study",
        "results": {
            "mode": "webapi_generation",
            "sourceKey": "SYNTHEA_CDM",
        },
        "analysisSettings": {"psMethod": "1:1"},
        "treatmentArms": [],
        "outcomes": [],
        "eligibility": {},
    }


def _fake_analysis_results() -> dict[str, Any]:
    return {
        "mode": "analysis",
        "sourceKey": "SYNTHEA_CDM",
        "generatedBy": "agent5",
        "tables": {},
    }


# ---------------------------------------------------------------------------
# RED: test that run_analysis auto-applies the artifact
# ---------------------------------------------------------------------------

class TestRunAnalysisAutoApply:
    """run_analysis() must call apply_artifact() after creating the artifact."""

    def test_apply_artifact_called_after_run_analysis(self) -> None:
        """After run_analysis() succeeds, apply_artifact should be called
        with the new artifact id and ["results"] section.
        """
        svc = _make_service()
        study_id = 42
        study = _fake_study(study_id=study_id, version=3)
        analysis_results = _fake_analysis_results()

        artifact_id = "artifact-999"
        artifact_payload = {
            "proposedChanges": {"results": analysis_results},
            "rationale": [],
            "meta": {"status": "ok", "summary": "Analysis done"},
        }
        artifact = {
            "id": artifact_id,
            "studyId": study_id,
            "studyVersion": 3,
            "kind": "analysis_result",
            "status": "completed",
            "payload": artifact_payload,
        }
        completed_job = {
            "id": "job-1",
            "status": "completed",
            "artifactId": artifact_id,
            "finishedAt": "2026-03-31T00:00:00Z",
        }
        meta_dict = {"status": "ok", "summary": "Analysis done"}

        svc.store.get_study.return_value = study
        svc.store.create_job.return_value = {"id": "job-1", "status": "running"}
        svc.store.create_artifact.return_value = artifact
        svc.store.update_job.return_value = completed_job

        # Patch _build_analysis_artifact_payload and _find_latest_artifact
        with (
            patch.object(
                svc,
                "_build_analysis_artifact_payload",
                return_value=(artifact_payload, meta_dict),
            ),
            patch.object(svc, "_find_latest_artifact", return_value=None),
            patch.object(svc, "apply_artifact") as mock_apply,
        ):
            svc.run_analysis(study_id)

        mock_apply.assert_called_once_with(artifact_id, ["results"], 3)

    def test_study_results_mode_becomes_analysis_after_run(self) -> None:
        """After run_analysis() completes and auto-apply succeeds,
        the study stored in store should have results.mode == 'analysis'.
        """
        svc = _make_service()
        study_id = 42
        study = _fake_study(study_id=study_id, version=3)
        analysis_results = _fake_analysis_results()

        artifact_id = "artifact-999"
        artifact_payload = {
            "proposedChanges": {"results": analysis_results},
            "rationale": [],
            "meta": {"status": "ok", "summary": "Analysis done"},
        }
        artifact = {
            "id": artifact_id,
            "studyId": study_id,
            "studyVersion": 3,
            "kind": "analysis_result",
            "status": "completed",
            "payload": artifact_payload,
        }
        completed_job = {
            "id": "job-1",
            "status": "completed",
            "artifactId": artifact_id,
            "finishedAt": "2026-03-31T00:00:00Z",
        }
        meta_dict = {"status": "ok", "summary": "Analysis done"}

        updated_study = deepcopy(study)
        updated_study["results"] = analysis_results
        updated_study["results"]["appliedAt"] = "2026-03-31T00:00:00Z"

        svc.store.get_study.return_value = study
        svc.store.create_job.return_value = {"id": "job-1", "status": "running"}
        svc.store.create_artifact.return_value = artifact
        svc.store.update_job.return_value = completed_job

        applied_results: list[dict[str, Any]] = []

        def _fake_apply(artifact_id_: str, sections: list[str], version: int):
            # Simulate what apply_artifact does: update store
            applied_results.append({"artifact_id": artifact_id_, "sections": sections})
            svc.store.get_study.return_value = updated_study

        with (
            patch.object(
                svc,
                "_build_analysis_artifact_payload",
                return_value=(artifact_payload, meta_dict),
            ),
            patch.object(svc, "_find_latest_artifact", return_value=None),
            patch.object(svc, "apply_artifact", side_effect=_fake_apply),
        ):
            svc.run_analysis(study_id)

        assert len(applied_results) == 1
        assert applied_results[0]["sections"] == ["results"]
        # The updated study should have mode=analysis
        final_study = svc.store.get_study(study_id)
        assert final_study["results"]["mode"] == "analysis"

    def test_auto_apply_failure_does_not_raise(self) -> None:
        """If apply_artifact() raises, run_analysis should log a warning
        but NOT propagate the exception — it still returns a valid response.
        """
        svc = _make_service()
        study_id = 42
        study = _fake_study(study_id=study_id, version=1)
        analysis_results = _fake_analysis_results()

        artifact_id = "artifact-111"
        artifact_payload = {
            "proposedChanges": {"results": analysis_results},
            "rationale": [],
            "meta": {"status": "ok", "summary": "Analysis done"},
        }
        artifact = {
            "id": artifact_id,
            "studyId": study_id,
            "studyVersion": 1,
            "kind": "analysis_result",
            "status": "completed",
            "payload": artifact_payload,
        }
        completed_job = {
            "id": "job-2",
            "status": "completed",
            "artifactId": artifact_id,
            "finishedAt": "2026-03-31T00:00:00Z",
        }
        meta_dict = {"status": "ok", "summary": "Analysis done"}

        svc.store.get_study.return_value = study
        svc.store.create_job.return_value = {"id": "job-2", "status": "running"}
        svc.store.create_artifact.return_value = artifact
        svc.store.update_job.return_value = completed_job

        with (
            patch.object(
                svc,
                "_build_analysis_artifact_payload",
                return_value=(artifact_payload, meta_dict),
            ),
            patch.object(svc, "_find_latest_artifact", return_value=None),
            patch.object(svc, "apply_artifact", side_effect=ValueError("version conflict")),
        ):
            # Should NOT raise even though apply_artifact raises
            response = svc.run_analysis(study_id)

        assert response.status == "completed"
        assert response.artifactId == artifact_id

    def test_auto_apply_skipped_when_no_proposed_results(self) -> None:
        """When proposedChanges.results is absent (precondition failure),
        apply_artifact should NOT be called.
        """
        svc = _make_service()
        study_id = 42
        study = _fake_study(study_id=study_id, version=1)

        artifact_id = "artifact-222"
        # No results in proposedChanges — precondition failed
        artifact_payload = {
            "proposedChanges": {},
            "rationale": ["Analysis preconditions not met."],
            "meta": {"status": "not_ready", "summary": ""},
        }
        artifact = {
            "id": artifact_id,
            "studyId": study_id,
            "studyVersion": 1,
            "kind": "analysis_result",
            "status": "completed",
            "payload": artifact_payload,
        }
        completed_job = {
            "id": "job-3",
            "status": "completed",
            "artifactId": artifact_id,
            "finishedAt": "2026-03-31T00:00:00Z",
        }
        meta_dict = {"status": "not_ready", "summary": ""}

        svc.store.get_study.return_value = study
        svc.store.create_job.return_value = {"id": "job-3", "status": "running"}
        svc.store.create_artifact.return_value = artifact
        svc.store.update_job.return_value = completed_job

        with (
            patch.object(
                svc,
                "_build_analysis_artifact_payload",
                return_value=(artifact_payload, meta_dict),
            ),
            patch.object(svc, "_find_latest_artifact", return_value=None),
            patch.object(svc, "apply_artifact") as mock_apply,
        ):
            svc.run_analysis(study_id)

        mock_apply.assert_not_called()
