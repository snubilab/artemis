"""Tests for SPEC-UI-004: Combined treatment CIRCE and eligibility validation.

Covers:
- Task A1: _build_combined_treatment_circe
- Task A3: generate_seeded_cohorts eligibility validation
"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.api.models.tte import SeededCohortGenerationItem
from src.services.tte_service import TTEService


def _make_service() -> TTEService:
    """Create a TTEService instance with mocked external dependencies."""
    svc = TTEService.__new__(TTEService)
    svc._store = MagicMock()
    return svc


def _fake_target_circe(*, include_metadata: bool = True) -> dict[str, Any]:
    """Return a realistic target CIRCE with eligibility rules."""
    base: dict[str, Any] = {
        "ConceptSets": [
            {
                "id": 1,
                "name": "Type 2 Diabetes",
                "expression": {"items": [{"concept": {"CONCEPT_ID": 201826}}]},
            },
            {
                "id": 2,
                "name": "HbA1c",
                "expression": {"items": [{"concept": {"CONCEPT_ID": 3004410}}]},
            },
        ],
        "PrimaryCriteria": {
            "CriteriaList": [{"ConditionOccurrence": {"CodesetId": 1}}],
            "ObservationWindow": {"PriorDays": 180, "PostDays": 0},
            "PrimaryCriteriaLimit": {"Type": "First"},
        },
        "InclusionRules": [
            {
                "name": "HbA1c >= 7",
                "expression": {
                    "Type": "ALL",
                    "CriteriaList": [
                        {
                            "Criteria": {"Measurement": {"CodesetId": 2}},
                            "StartWindow": {
                                "Start": {"Days": 365, "Coeff": -1},
                                "End": {"Days": 0, "Coeff": 1},
                            },
                            "RestrictVisit": False,
                            "IgnoreObservationPeriod": False,
                            "Occurrence": {"Type": 2, "Count": 1},
                        }
                    ],
                    "DemographicCriteriaList": [],
                    "Groups": [],
                },
            }
        ],
    }
    if include_metadata:
        base["_criterionMappingMetadata"] = {"_target": {"score": 0.95}}
    return base


def _fake_drug_recommend_result() -> dict[str, Any]:
    """Return a result matching _recommend_seeded_concept_set for Drug domain."""
    return {
        "name": "Metformin",
        "domain": "Drug",
        "expression": {"items": [{"concept": {"CONCEPT_ID": 1503297}}]},
        "mapping_metadata": None,
    }


# ---------------------------------------------------------------------------
# Task A1: _build_combined_treatment_circe
# ---------------------------------------------------------------------------


class TestBuildCombinedTreatmentCirce:
    """Tests for _build_combined_treatment_circe method."""

    def _call_with_structured(
        self,
        svc: TTEService,
        eligibility: dict[str, Any],
        arm_name: str = "Metformin",
    ) -> dict[str, Any]:
        """Call _build_combined_treatment_circe with structuredExpression present.

        No mock for _build_seeded_target_circe needed -- the fast path skips it.
        """
        with (
            patch.object(
                svc,
                "_recommend_seeded_concept_set",
                return_value=_fake_drug_recommend_result(),
            ),
            patch.object(
                svc,
                "_seeded_criteria_key",
                return_value="DrugExposure",
            ),
        ):
            return svc._build_combined_treatment_circe(eligibility, arm_name)

    def _call_fallback(
        self,
        svc: TTEService,
        eligibility: dict[str, Any],
        arm_name: str = "Metformin",
    ) -> dict[str, Any]:
        """Call _build_combined_treatment_circe without structuredExpression (fallback path)."""
        with (
            patch.object(
                svc,
                "_build_seeded_target_circe",
                return_value=_fake_target_circe(),
            ) as mock_target,
            patch.object(
                svc,
                "_recommend_seeded_concept_set",
                return_value=_fake_drug_recommend_result(),
            ),
            patch.object(
                svc,
                "_seeded_criteria_key",
                return_value="DrugExposure",
            ),
        ):
            result = svc._build_combined_treatment_circe(eligibility, arm_name)
            self._last_mock_target = mock_target
            return result

    def test_contains_eligibility_rules_plus_drug(self):
        """Combined CIRCE preserves all eligibility inclusion rules and adds drug rule."""
        svc = _make_service()
        eligibility = {
            "targetCohortName": "T2DM",
            "observationWindow": {"PriorDays": 180, "PostDays": 0},
            "structuredExpression": _fake_target_circe(include_metadata=False),
        }

        result = self._call_with_structured(svc, eligibility)

        # Original eligibility had 1 inclusion rule; combined should have 2 (eligibility + drug)
        assert len(result["InclusionRules"]) == 2
        # First rule is the original eligibility rule
        assert result["InclusionRules"][0]["name"] == "HbA1c >= 7"
        # Second rule is the drug rule
        drug_rule = result["InclusionRules"][1]
        assert "DrugExposure" in str(drug_rule)

    def test_uses_eligibility_observation_window(self):
        """Combined CIRCE keeps the target's observation window, not the drug default."""
        svc = _make_service()
        eligibility = {
            "observationWindow": {"PriorDays": 180, "PostDays": 0},
            "structuredExpression": _fake_target_circe(include_metadata=False),
        }

        result = self._call_with_structured(svc, eligibility)

        assert result["PrimaryCriteria"]["ObservationWindow"] == {"PriorDays": 180, "PostDays": 0}

    def test_drug_codeset_id_no_collision(self):
        """Drug concept set ID must not collide with existing eligibility concept sets."""
        svc = _make_service()
        eligibility = {"structuredExpression": _fake_target_circe(include_metadata=False)}

        result = self._call_with_structured(svc, eligibility)

        existing_ids = {cs["id"] for cs in result["ConceptSets"][:-1]}
        drug_cs = result["ConceptSets"][-1]
        assert drug_cs["id"] not in existing_ids
        # Should be max(existing) + 1 = 3
        assert drug_cs["id"] == 3

    def test_strips_criterion_mapping_metadata(self):
        """Combined CIRCE must not contain _criterionMappingMetadata."""
        svc = _make_service()
        circe_with_meta = _fake_target_circe(include_metadata=True)
        eligibility = {"structuredExpression": circe_with_meta}

        result = self._call_with_structured(svc, eligibility)

        assert "_criterionMappingMetadata" not in result

    def test_raises_on_empty_arm_name(self):
        """Must raise ValueError when arm_name is empty."""
        svc = _make_service()
        eligibility = {}

        with pytest.raises(ValueError, match="arm_name must be a non-empty string"):
            svc._build_combined_treatment_circe(eligibility, "")

    def test_raises_on_whitespace_only_arm_name(self):
        """Must raise ValueError when arm_name is whitespace only."""
        svc = _make_service()
        eligibility = {}

        with pytest.raises(ValueError, match="arm_name must be a non-empty string"):
            svc._build_combined_treatment_circe(eligibility, "   ")

    def test_uses_structured_expression_when_available(self):
        """When structuredExpression is present, _build_seeded_target_circe must NOT be called."""
        svc = _make_service()
        eligibility = {
            "targetCohortName": "T2DM",
            "structuredExpression": _fake_target_circe(include_metadata=False),
        }

        with (
            patch.object(
                svc,
                "_build_seeded_target_circe",
            ) as mock_target,
            patch.object(
                svc,
                "_recommend_seeded_concept_set",
                return_value=_fake_drug_recommend_result(),
            ),
            patch.object(
                svc,
                "_seeded_criteria_key",
                return_value="DrugExposure",
            ),
        ):
            result = svc._build_combined_treatment_circe(eligibility, "Metformin")
            mock_target.assert_not_called()
            # Verify result still contains eligibility rules
            assert len(result["InclusionRules"]) == 2

    def test_falls_back_to_seeded_target_when_no_structured_expression(self):
        """When structuredExpression is absent, _build_seeded_target_circe IS called."""
        svc = _make_service()
        eligibility = {"targetCohortName": "T2DM", "nested": {"key": "value"}}

        result = self._call_fallback(svc, eligibility)

        self._last_mock_target.assert_called_once()
        # The argument passed should NOT be the same object (deep-copied)
        passed_elig = self._last_mock_target.call_args[0][0]
        assert passed_elig is not eligibility
        # Result should still have eligibility + drug rules
        assert len(result["InclusionRules"]) == 2

    def test_drug_concept_set_has_correct_name(self):
        """Drug concept set should use the name from _recommend_seeded_concept_set."""
        svc = _make_service()
        eligibility = {"structuredExpression": _fake_target_circe(include_metadata=False)}

        result = self._call_with_structured(svc, eligibility)

        drug_cs = result["ConceptSets"][-1]
        assert drug_cs["name"] == "Metformin"

    def test_empty_concept_sets_fallback(self):
        """When base has no ConceptSets, drug ID should be 1."""
        svc = _make_service()
        empty_circe = _fake_target_circe()
        empty_circe["ConceptSets"] = []
        eligibility = {"structuredExpression": empty_circe}

        result = self._call_with_structured(svc, eligibility)

        drug_cs = result["ConceptSets"][-1]
        assert drug_cs["id"] == 1

    def test_does_not_mutate_original_structured_expression(self):
        """The original structuredExpression dict must not be mutated."""
        svc = _make_service()
        original_circe = _fake_target_circe(include_metadata=False)
        original_rules_count = len(original_circe["InclusionRules"])
        eligibility = {"structuredExpression": original_circe}

        self._call_with_structured(svc, eligibility)

        # Original should be untouched (deep-copied before mutation)
        assert len(original_circe["InclusionRules"]) == original_rules_count


class TestBenchmarkCompatibilityRouting:
    """Tests for trial-specific benchmark compatibility auto-routing."""

    def test_builds_drug_primary_compat_circe_from_eligibility_base(self):
        svc = _make_service()
        eligibility = {
            "observationWindow": {"PriorDays": 180, "PostDays": 0},
            "structuredExpression": _fake_target_circe(include_metadata=True),
        }

        with (
            patch.object(
                svc,
                "_recommend_seeded_concept_set",
                return_value=_fake_drug_recommend_result(),
            ),
            patch.object(
                svc,
                "_seeded_primary_criteria_key",
                return_value="DrugEra",
            ),
        ):
            result = svc._build_benchmark_compat_drug_primary_circe(eligibility, "Metformin")

        assert result["PrimaryCriteria"]["CriteriaList"] == [{"DrugEra": {"CodesetId": 3}}]
        assert result["PrimaryCriteria"]["ObservationWindow"] == {"PriorDays": 180, "PostDays": 0}
        assert [rule["name"] for rule in result["InclusionRules"]] == ["HbA1c >= 7"]
        assert result["ConceptSets"][-1]["name"] == "Metformin"
        assert "_criterionMappingMetadata" not in result

    def test_materialize_treatment_uses_compat_builder_for_benchmark_trials(self):
        svc = _make_service()
        study = {
            "trialMetadata": {"nctId": "NCT00391872"},
            "comparisonMode": "explicit_comparator",
            "timeParams": {},
        }
        treatment_arms = [{"name": "ticagrelor"}, {"name": "clopidogrel"}]
        eligibility = {"structuredExpression": _fake_target_circe(include_metadata=False)}

        created_ids = iter([1160, 1161])

        def fake_materialize(*, expression_builder, section, item_key, role, label, seed_text, **_kwargs):
            expression_builder()
            return SeededCohortGenerationItem(
                section=section,
                itemKey=item_key,
                role=role,
                label=label,
                status="created",
                seedText=seed_text,
                cohortDefinitionId=next(created_ids),
                cohortDefinitionName=f"[Seeded] {label}",
            )

        with (
            patch.object(
                svc,
                "_build_benchmark_compat_drug_primary_circe",
                return_value=_fake_target_circe(include_metadata=False),
            ) as mock_compat,
            patch.object(svc, "_build_combined_treatment_circe") as mock_combined,
            patch.object(svc, "_materialize_seeded_cohort_item", side_effect=fake_materialize),
        ):
            svc._materialize_seeded_treatment_cohorts(
                client=MagicMock(),
                study_id=451,
                study_name="PLATO",
                study=study,
                treatment_arms=treatment_arms,
                eligibility=eligibility,
            )

        assert mock_compat.call_count == 2
        mock_combined.assert_not_called()
        assert [arm["cohortId"] for arm in treatment_arms] == [1160, 1161]


# ---------------------------------------------------------------------------
# Task A3: generate_seeded_cohorts eligibility validation
# ---------------------------------------------------------------------------


class TestGenerateSeededCohortsEligibilityValidation:
    """Tests for eligibility validation at the top of generate_seeded_cohorts."""

    def test_rejects_missing_eligibility(self):
        """Must raise ValueError when study has no eligibility section."""
        svc = _make_service()
        svc.store = MagicMock()
        svc.store.get_study.return_value = {
            "version": 1,
            "treatmentArms": [{"name": "Metformin"}],
        }
        svc.store.create_job.return_value = {"id": "job-1"}

        with pytest.raises(ValueError, match="Eligibility must be processed"):
            svc.generate_seeded_cohorts(study_id=1)

    def test_rejects_empty_structured_expression(self):
        """Must raise ValueError when eligibility has no structuredExpression."""
        svc = _make_service()
        svc.store = MagicMock()
        svc.store.get_study.return_value = {
            "version": 1,
            "eligibility": {"targetCohortName": "T2DM"},
            "treatmentArms": [{"name": "Metformin"}],
        }
        svc.store.create_job.return_value = {"id": "job-1"}

        with pytest.raises(ValueError, match="Eligibility must be processed"):
            svc.generate_seeded_cohorts(study_id=1)

    def test_accepts_valid_eligibility(self):
        """When eligibility has structuredExpression, validation passes."""
        svc = _make_service()
        svc.store = MagicMock()
        svc.store.get_study.return_value = {
            "version": 1,
            "eligibility": {
                "targetCohortName": "T2DM",
                "structuredExpression": {"inclusionCriteria": []},
            },
            "treatmentArms": [{"name": "Metformin"}],
        }
        svc.store.create_job.return_value = {"id": "job-1"}

        # Should not raise ValueError for eligibility validation.
        # It may raise for other reasons (WebAPI, etc.), which is fine.
        with patch.object(
            svc, "_build_seeded_cohort_artifact_payload"
        ) as mock_build:
            mock_build.return_value = (
                {"summary": "ok", "proposedChanges": {}, "meta": {"status": "ok"}},
                {"status": "ok"},
            )
            svc.store.create_artifact.return_value = {"id": "art-1"}
            svc.store.update_job.return_value = {"id": "job-1"}
            result = svc.generate_seeded_cohorts(study_id=1)
            assert result.status == "completed"


class TestStructuredTargetGuardrails:
    def test_mapping_entities_skip_target_label_when_structured_expression_is_canonical(self):
        svc = _make_service()
        study = {
            "eligibility": {
                "targetCohortName": "liraglutide",
                "structuredExpression": {
                    "ConceptSets": [
                        {
                            "id": 1,
                            "name": "Adults with T2DM",
                            "expression": {"items": [{"concept": {"CONCEPT_NAME": "Adults with T2DM"}}]},
                        }
                    ],
                    "PrimaryCriteria": {
                        "CriteriaList": [{"ConditionOccurrence": {"CodesetId": 1}}],
                    },
                    "InclusionRules": [],
                },
                "inclusionCriteria": [{"id": 1, "description": "HbA1c >= 7%"}],
                "exclusionCriteria": [],
            },
            "treatmentArms": [{"name": "liraglutide"}],
        }

        provisional_ir = svc._study_to_provisional_ir(study)

        entities = svc._build_mapping_entities_for_section(study, provisional_ir, "eligibility")

        assert [item["item_id"] for item in entities] == ["eligibility_inclusion_0"]

    def test_process_eligibility_warns_on_conflicting_target_label_but_uses_structured_display_label(self):
        svc = _make_service()
        study = {
            "name": "Canonical target study",
            "eligibility": {
                "targetCohortName": "liraglutide",
                "structuredExpression": {
                    "ConceptSets": [
                        {
                            "id": 1,
                            "name": "Adults with T2DM",
                            "expression": {"items": [{"concept": {"CONCEPT_NAME": "Adults with T2DM"}}]},
                        }
                    ],
                    "PrimaryCriteria": {
                        "CriteriaList": [{"ConditionOccurrence": {"CodesetId": 1}}],
                    },
                    "InclusionRules": [],
                },
                "inclusionCriteria": [{"id": 1, "description": "HbA1c >= 7%"}],
                "exclusionCriteria": [],
            },
            "treatmentArms": [{"name": "liraglutide"}],
        }
        provisional_ir = svc._study_to_provisional_ir(study)
        captured: dict[str, Any] = {}

        def fake_build_seeded_target_circe(eligibility: dict[str, Any]) -> dict[str, Any]:
            captured["target_name"] = eligibility.get("targetCohortName")
            return _fake_target_circe(include_metadata=False)

        with patch.object(svc, "_build_seeded_target_circe", side_effect=fake_build_seeded_target_circe):
            payload, meta, run_status = svc._build_process_eligibility_artifact_payload(
                study=study,
                provisional_ir=provisional_ir,
                section_source=provisional_ir.eligibility,
            )

        assert run_status == "completed"
        assert captured["target_name"].lower() == "adults with t2dm"
        assert payload["proposedChanges"]["eligibility"]["targetCohortName"].lower() == "adults with t2dm"
        assert meta["warnings"] == ["target_label_matches_treatment_arm"]
        assert any("display-only" in line for line in payload["rationale"])

    def test_process_eligibility_uses_mapping_metadata_for_concept_set_names(self):
        svc = _make_service()
        study = {
            "name": "Concept set metadata drift study",
            "eligibility": {
                "targetCohortName": "Adults with type 2 diabetes",
                "inclusionCriteria": [
                    {"id": 101, "description": "Cardiac surgery", "domain": "Procedure"},
                    {"id": 102, "description": "Treatment with Orlistat", "domain": "Drug"},
                ],
                "exclusionCriteria": [],
            },
            "treatmentArms": [{"name": "empagliflozin"}],
        }
        provisional_ir = svc._study_to_provisional_ir(study)
        fake_circe = {
            "ConceptSets": [
                {
                    "id": 1,
                    "name": "Adults with type 2 diabetes",
                    "expression": {"items": [{"concept": {"CONCEPT_ID": 201826}}]},
                },
                {
                    "id": 2,
                    "name": "Orlistat",
                    "expression": {"items": [{"concept": {"CONCEPT_ID": 1502826}}]},
                },
                {
                    "id": 3,
                    "name": "Cardiac surgery",
                    "expression": {"items": [{"concept": {"CONCEPT_ID": 4324124}}]},
                },
            ],
            "PrimaryCriteria": {
                "CriteriaList": [{"ConditionOccurrence": {"CodesetId": 1}}],
                "ObservationWindow": {"PriorDays": 365, "PostDays": 0},
                "PrimaryCriteriaLimit": {"Type": "First"},
            },
            "InclusionRules": [],
            "_criterionMappingMetadata": {
                "101": {"selectedConceptIds": [4324124]},
                "102": {"selectedConceptIds": [1502826]},
            },
            "_ruleIndexMeta": {
                "0": {"selectedConceptIds": [4324124]},
                "1": {"selectedConceptIds": [1502826]},
            },
        }

        with patch.object(svc, "_build_seeded_target_circe", return_value=fake_circe):
            payload, _meta, run_status = svc._build_process_eligibility_artifact_payload(
                study=study,
                provisional_ir=provisional_ir,
                section_source=provisional_ir.eligibility,
            )

        assert run_status == "completed"
        proposed = payload["proposedChanges"]["eligibility"]["inclusionCriteria"]
        assert proposed[0]["conceptSetId"] == 3
        assert proposed[0]["conceptSetName"] == "Cardiac surgery"
        assert proposed[1]["conceptSetId"] == 2
        assert proposed[1]["conceptSetName"] == "Orlistat"

    def test_process_eligibility_uses_role_aware_mapping_metadata_for_duplicate_ids(self):
        svc = _make_service()
        study = {
            "name": "Duplicate criterion ids study",
            "eligibility": {
                "targetCohortName": "Adults with type 2 diabetes",
                "inclusionCriteria": [
                    {"id": 2, "description": "Cardiac surgery", "domain": "Procedure"},
                ],
                "exclusionCriteria": [
                    {"id": 2, "description": "Treatment with Orlistat", "domain": "Drug"},
                ],
            },
            "treatmentArms": [{"name": "empagliflozin"}],
        }
        provisional_ir = svc._study_to_provisional_ir(study)
        fake_circe = {
            "ConceptSets": [
                {
                    "id": 1,
                    "name": "Adults with type 2 diabetes",
                    "expression": {"items": [{"concept": {"CONCEPT_ID": 201826}}]},
                },
                {
                    "id": 2,
                    "name": "Orlistat",
                    "expression": {"items": [{"concept": {"CONCEPT_ID": 1502826}}]},
                },
                {
                    "id": 3,
                    "name": "Cardiac surgery",
                    "expression": {"items": [{"concept": {"CONCEPT_ID": 4324124}}]},
                },
            ],
            "PrimaryCriteria": {
                "CriteriaList": [{"ConditionOccurrence": {"CodesetId": 1}}],
                "ObservationWindow": {"PriorDays": 365, "PostDays": 0},
                "PrimaryCriteriaLimit": {"Type": "First"},
            },
            "InclusionRules": [],
            "_criterionMappingMetadata": {
                "2": {"selectedConceptIds": [4324124]},
                "inclusion:2": {"selectedConceptIds": [4324124]},
                "exclusion:2": {"selectedConceptIds": [1502826]},
            },
        }

        with patch.object(svc, "_build_seeded_target_circe", return_value=fake_circe):
            payload, _meta, run_status = svc._build_process_eligibility_artifact_payload(
                study=study,
                provisional_ir=provisional_ir,
                section_source=provisional_ir.eligibility,
            )

        assert run_status == "completed"
        proposed = payload["proposedChanges"]["eligibility"]
        assert proposed["inclusionCriteria"][0]["conceptSetId"] == 3
        assert proposed["inclusionCriteria"][0]["conceptSetName"] == "Cardiac surgery"
        assert proposed["exclusionCriteria"][0]["conceptSetId"] == 2
        assert proposed["exclusionCriteria"][0]["conceptSetName"] == "Orlistat"

    def test_process_eligibility_uses_criterion_concept_set_refs_without_metadata(self):
        svc = _make_service()
        study = {
            "name": "Concept set refs without metadata study",
            "eligibility": {
                "targetCohortName": "Adults with type 2 diabetes",
                "inclusionCriteria": [
                    {"id": 101, "description": "Cardiac surgery", "domain": "Procedure"},
                ],
                "exclusionCriteria": [
                    {"id": 101, "description": "Treatment with Orlistat", "domain": "Drug"},
                ],
            },
            "treatmentArms": [{"name": "empagliflozin"}],
        }
        provisional_ir = svc._study_to_provisional_ir(study)
        fake_circe = {
            "ConceptSets": [
                {
                    "id": 1,
                    "name": "Adults with type 2 diabetes",
                    "expression": {"items": [{"concept": {"CONCEPT_ID": 201826}}]},
                },
                {
                    "id": 2,
                    "name": "Orlistat",
                    "expression": {"items": [{"concept": {"CONCEPT_ID": 1502826}}]},
                },
                {
                    "id": 3,
                    "name": "Cardiac surgery",
                    "expression": {"items": [{"concept": {"CONCEPT_ID": 4324124}}]},
                },
            ],
            "PrimaryCriteria": {
                "CriteriaList": [{"ConditionOccurrence": {"CodesetId": 1}}],
                "ObservationWindow": {"PriorDays": 365, "PostDays": 0},
                "PrimaryCriteriaLimit": {"Type": "First"},
            },
            "InclusionRules": [],
            "_criterionMappingMetadata": {},
            "_criterionConceptSetRefs": {
                "inclusion:101": 3,
                "exclusion:101": 2,
            },
        }

        with patch.object(svc, "_build_seeded_target_circe", return_value=fake_circe):
            payload, _meta, run_status = svc._build_process_eligibility_artifact_payload(
                study=study,
                provisional_ir=provisional_ir,
                section_source=provisional_ir.eligibility,
            )

        assert run_status == "completed"
        proposed = payload["proposedChanges"]["eligibility"]
        assert proposed["inclusionCriteria"][0]["conceptSetId"] == 3
        assert proposed["inclusionCriteria"][0]["conceptSetName"] == "Cardiac surgery"
        assert proposed["exclusionCriteria"][0]["conceptSetId"] == 2
        assert proposed["exclusionCriteria"][0]["conceptSetName"] == "Orlistat"

    def test_process_eligibility_fails_for_drug_like_target_without_canonical_structured_target(self):
        svc = _make_service()
        study = {
            "name": "Drug-like target study",
            "eligibility": {
                "targetCohortName": "Metformin",
                "structuredExpression": {"inclusionCriteria": [], "exclusionCriteria": []},
                "inclusionCriteria": [
                    {"id": 1, "description": "Metformin", "domain": "Drug"},
                ],
                "exclusionCriteria": [],
            },
            "treatmentArms": [{"name": "dapagliflozin"}],
        }
        provisional_ir = svc._study_to_provisional_ir(study)

        with patch.object(svc, "_build_seeded_target_circe") as mock_build_seeded_target_circe:
            payload, meta, run_status = svc._build_process_eligibility_artifact_payload(
                study=study,
                provisional_ir=provisional_ir,
                section_source=provisional_ir.eligibility,
            )

        assert run_status == "failed"
        assert meta["failureMessage"] == (
            "Target population label appears to be a treatment/drug label; provide a "
            "patient-population target or correct the structured criteria first."
        )
        assert "appears to be a treatment/drug label" in payload["summary"]
        mock_build_seeded_target_circe.assert_not_called()
