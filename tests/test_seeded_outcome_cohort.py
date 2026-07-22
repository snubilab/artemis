"""Tests for _materialize_seeded_outcome_cohorts orphan dict bug.

The bug: `primary = outcomes.get("primary") or {}` creates an orphaned dict
when primary is None or {} (both falsy), so `primary["cohortId"] = ...`
never propagates back to `outcomes["primary"]`.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.api.models.tte import (
    CapabilitySignal,
    SeededCohortGenerationItem,
    SeededCohortSectionDiagnostic,
)
from src.services.tte_service import TTEService


FAKE_COHORT_ID = 42


def _make_fake_item(
    *,
    section: str = "outcomes",
    item_key: str = "primary",
    role: str = "primary_outcome",
    label: str = "Primary outcome",
) -> SeededCohortGenerationItem:
    return SeededCohortGenerationItem(
        section=section,
        itemKey=item_key,
        role=role,
        label=label,
        status="created",
        cohortDefinitionId=FAKE_COHORT_ID,
        cohortDefinitionName=f"[Seeded] {label}",
    )


def _make_service() -> TTEService:
    """Create a TTEService with mocked dependencies."""
    service = object.__new__(TTEService)
    return service


def _patch_materialize(service: TTEService):
    """Patch _materialize_seeded_cohort_item to return a fake created item."""
    return patch.object(
        service,
        "_materialize_seeded_cohort_item",
        side_effect=lambda *, client, study_id, study_name, section,
                          item_key, role, label, seed_text,
                          existing_cohort_id, expression_builder: _make_fake_item(
            section=section, item_key=item_key, role=role, label=label,
        ),
    )


class TestPrimaryOutcomeCohortIdPropagation:
    """Verify cohortId propagates back to outcomes dict for primary outcome."""

    def test_primary_none_gets_cohort_id(self) -> None:
        """When outcomes['primary'] is None, cohortId must propagate."""
        service = _make_service()
        outcomes: dict = {"primary": None, "secondary": []}
        client = MagicMock()

        with _patch_materialize(service):
            service._materialize_seeded_outcome_cohorts(
                client=client,
                study_id=1,
                study_name="Test Study",
                outcomes=outcomes,
            )

        assert outcomes["primary"] is not None
        assert outcomes["primary"]["cohortId"] == FAKE_COHORT_ID

    def test_primary_empty_dict_gets_cohort_id(self) -> None:
        """When outcomes['primary'] is {} (falsy), cohortId must propagate."""
        service = _make_service()
        outcomes: dict = {"primary": {}, "secondary": []}
        client = MagicMock()

        with _patch_materialize(service):
            service._materialize_seeded_outcome_cohorts(
                client=client,
                study_id=1,
                study_name="Test Study",
                outcomes=outcomes,
            )

        assert outcomes["primary"]["cohortId"] == FAKE_COHORT_ID

    def test_primary_missing_key_gets_cohort_id(self) -> None:
        """When 'primary' key is absent, cohortId must propagate."""
        service = _make_service()
        outcomes: dict = {"secondary": []}
        client = MagicMock()

        with _patch_materialize(service):
            service._materialize_seeded_outcome_cohorts(
                client=client,
                study_id=1,
                study_name="Test Study",
                outcomes=outcomes,
            )

        assert "primary" in outcomes
        assert outcomes["primary"]["cohortId"] == FAKE_COHORT_ID

    def test_primary_with_existing_data_preserves_name(self) -> None:
        """Primary with cohortName/description + cohortId=None keeps name, gains cohortId."""
        service = _make_service()
        outcomes: dict = {
            "primary": {
                "cohortName": "Stroke",
                "description": "Ischemic stroke",
                "cohortId": None,
            },
            "secondary": [],
        }
        client = MagicMock()

        with _patch_materialize(service):
            service._materialize_seeded_outcome_cohorts(
                client=client,
                study_id=1,
                study_name="Test Study",
                outcomes=outcomes,
            )

        assert outcomes["primary"]["cohortName"] == "Stroke"
        assert outcomes["primary"]["description"] == "Ischemic stroke"
        assert outcomes["primary"]["cohortId"] == FAKE_COHORT_ID


class TestSecondaryOutcomes:
    """Verify secondary outcome handling."""

    def test_secondary_empty_list_no_crash(self) -> None:
        """Empty secondary list should not crash."""
        service = _make_service()
        outcomes: dict = {"primary": {"cohortName": "Stroke"}, "secondary": []}
        client = MagicMock()

        with _patch_materialize(service):
            result = service._materialize_seeded_outcome_cohorts(
                client=client,
                study_id=1,
                study_name="Test Study",
                outcomes=outcomes,
            )

        assert isinstance(result, SeededCohortSectionDiagnostic)
        assert result.section == "outcomes"


# ---------------------------------------------------------------------------
# Integration-level: _build_seeded_cohort_artifact_payload
# ---------------------------------------------------------------------------

def _ok_section_diag(section: str) -> SeededCohortSectionDiagnostic:
    """Return a trivially-successful section diagnostic."""
    return SeededCohortSectionDiagnostic(
        section=section,
        status="completed",
        generatedCount=1,
        failedCount=0,
        skippedCount=0,
        items=[],
    )


def _fake_capability_signal() -> CapabilitySignal:
    return CapabilitySignal(
        owner="test",
        fidelity="high",
        fidelityNote="stub",
        stageKind="agent",
    )


class TestBuildSeededCohortPayloadOutcomes:
    """Verify that outcomes appear in proposedChanges when primary was None."""

    @staticmethod
    def _make_study(*, primary_outcome: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "name": "Payload Test Study",
            "eligibility": {"targetCohortName": "Target"},
            "treatmentArms": [{"armName": "Arm1"}],
            "outcomes": {"primary": primary_outcome, "secondary": []},
        }

    def test_outcomes_in_proposed_changes_when_primary_was_none(self) -> None:
        """When primary outcome starts as None, the payload must include outcomes in proposedChanges."""
        service = _make_service()
        study = self._make_study(primary_outcome=None)

        def fake_materialize_outcomes(*, client, study_id, study_name, outcomes, **_kw):
            """Simulate _materialize_seeded_outcome_cohorts populating primary."""
            outcomes["primary"] = {"cohortId": FAKE_COHORT_ID, "cohortName": "[Seeded] Primary outcome"}
            return _ok_section_diag("outcomes")

        with (
            patch.object(service, "_get_capability_signal", return_value=_fake_capability_signal()),
            patch("src.services.tte_service.WebAPIClient"),
            patch.object(
                service,
                "_materialize_seeded_target_cohort",
                return_value=_ok_section_diag("eligibility"),
            ),
            patch.object(
                service,
                "_materialize_seeded_treatment_cohorts",
                return_value=_ok_section_diag("treatmentArms"),
            ),
            patch.object(
                service,
                "_materialize_seeded_outcome_cohorts",
                side_effect=fake_materialize_outcomes,
            ),
        ):
            payload, _meta = service._build_seeded_cohort_artifact_payload(
                study_id=1,
                study=study,
            )

        assert "outcomes" in payload["proposedChanges"], (
            "outcomes must appear in proposedChanges when primary was None"
        )
        proposed_primary = payload["proposedChanges"]["outcomes"]["primary"]
        assert proposed_primary["cohortId"] == FAKE_COHORT_ID

    def test_outcomes_absent_when_unchanged(self) -> None:
        """When outcomes are not modified, proposedChanges must not contain outcomes."""
        service = _make_service()
        study = self._make_study(primary_outcome={"cohortId": 99, "cohortName": "Existing"})

        def noop_materialize_outcomes(*, client, study_id, study_name, outcomes, **_kw):
            """Simulate no changes to outcomes."""
            return _ok_section_diag("outcomes")

        with (
            patch.object(service, "_get_capability_signal", return_value=_fake_capability_signal()),
            patch("src.services.tte_service.WebAPIClient"),
            patch.object(
                service,
                "_materialize_seeded_target_cohort",
                return_value=_ok_section_diag("eligibility"),
            ),
            patch.object(
                service,
                "_materialize_seeded_treatment_cohorts",
                return_value=_ok_section_diag("treatmentArms"),
            ),
            patch.object(
                service,
                "_materialize_seeded_outcome_cohorts",
                side_effect=noop_materialize_outcomes,
            ),
        ):
            payload, _meta = service._build_seeded_cohort_artifact_payload(
                study_id=1,
                study=study,
            )

        assert "outcomes" not in payload["proposedChanges"], (
            "outcomes must not appear when unchanged"
        )
