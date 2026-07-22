"""Tests for outcome-eligibility bridge: extraction helper and method signatures."""

import inspect

import pytest

from src.services.tte_service import TTEService


class TestExtractEligibilityConceptIdsForOutcome:
    """Test suite for outcome-to-eligibility concept ID extraction."""

    def _make_criterion(self, crit_id: str, description: str, domain: str = "Condition") -> dict:
        return {"id": crit_id, "description": description, "domain": domain}

    def _make_mapping(self, crit_id: str, concept_ids: list[int]) -> dict:
        return {str(crit_id): {"selectedConceptIds": concept_ids}}

    def test_exact_match_returns_concept_ids(self):
        # Arrange
        criteria = [self._make_criterion("1", "Stroke")]
        mapping = self._make_mapping("1", [4043731, 4110192])

        # Act
        result = TTEService._extract_eligibility_concept_ids_for_outcome(
            outcome_label="Stroke",
            criteria=criteria,
            criterion_mapping_metadata=mapping,
        )

        # Assert
        assert sorted(result) == [4043731, 4110192]

    def test_or_separated_label_matches_multiple_criteria(self):
        # Arrange
        criteria = [
            self._make_criterion("1", "Stroke"),
            self._make_criterion("2", "Systemic Embolism"),
        ]
        mapping = {
            "1": {"selectedConceptIds": [4043731]},
            "2": {"selectedConceptIds": [316139]},
        }

        # Act
        result = TTEService._extract_eligibility_concept_ids_for_outcome(
            outcome_label="Stroke or Systemic Embolism",
            criteria=criteria,
            criterion_mapping_metadata=mapping,
        )

        # Assert
        assert sorted(result) == [316139, 4043731]

    def test_no_match_returns_empty_list(self):
        # Arrange
        criteria = [self._make_criterion("1", "Diabetes")]
        mapping = self._make_mapping("1", [201826])

        # Act
        result = TTEService._extract_eligibility_concept_ids_for_outcome(
            outcome_label="Stroke",
            criteria=criteria,
            criterion_mapping_metadata=mapping,
        )

        # Assert
        assert result == []

    def test_empty_criteria_returns_empty_list(self):
        # Act
        result = TTEService._extract_eligibility_concept_ids_for_outcome(
            outcome_label="Stroke",
            criteria=[],
            criterion_mapping_metadata={},
        )

        # Assert
        assert result == []

    def test_missing_mapping_metadata_skips_criterion(self):
        # Arrange
        criteria = [
            self._make_criterion("1", "Stroke"),
            self._make_criterion("2", "Systemic Embolism"),
        ]
        # Only criterion "1" has mapping; "2" is missing
        mapping = self._make_mapping("1", [4043731])

        # Act
        result = TTEService._extract_eligibility_concept_ids_for_outcome(
            outcome_label="Stroke or Systemic Embolism",
            criteria=criteria,
            criterion_mapping_metadata=mapping,
        )

        # Assert
        assert result == [4043731]

    def test_deduplicates_concept_ids_across_criteria(self):
        # Arrange
        criteria = [
            self._make_criterion("1", "Stroke"),
            self._make_criterion("2", "Ischemic Stroke"),
        ]
        mapping = {
            "1": {"selectedConceptIds": [4043731, 4110192]},
            "2": {"selectedConceptIds": [4110192, 443454]},
        }

        # Act
        result = TTEService._extract_eligibility_concept_ids_for_outcome(
            outcome_label="Stroke",
            criteria=criteria,
            criterion_mapping_metadata=mapping,
        )

        # Assert - both criteria match ("stroke" is substring of both descriptions)
        assert sorted(result) == [443454, 4043731, 4110192]

    def test_case_insensitive_matching(self):
        # Arrange
        criteria = [self._make_criterion("1", "STROKE")]
        mapping = self._make_mapping("1", [4043731])

        # Act
        result = TTEService._extract_eligibility_concept_ids_for_outcome(
            outcome_label="stroke",
            criteria=criteria,
            criterion_mapping_metadata=mapping,
        )

        # Assert
        assert result == [4043731]

    def test_comma_separated_label(self):
        # Arrange
        criteria = [
            self._make_criterion("1", "Stroke"),
            self._make_criterion("2", "Heart Failure"),
        ]
        mapping = {
            "1": {"selectedConceptIds": [4043731]},
            "2": {"selectedConceptIds": [316139]},
        }

        # Act
        result = TTEService._extract_eligibility_concept_ids_for_outcome(
            outcome_label="Stroke, Heart Failure",
            criteria=criteria,
            criterion_mapping_metadata=mapping,
        )

        # Assert
        assert sorted(result) == [316139, 4043731]

    def test_all_metadata_empty_returns_empty(self):
        # Arrange — criteria exist but mapping metadata is completely empty
        criteria = [
            self._make_criterion("1", "Stroke"),
            self._make_criterion("2", "Diabetes"),
        ]

        # Act
        result = TTEService._extract_eligibility_concept_ids_for_outcome(
            outcome_label="Stroke",
            criteria=criteria,
            criterion_mapping_metadata={},
        )

        # Assert
        assert result == []


class TestBuildSeededConditionCirceSignature:
    """Verify _build_seeded_condition_circe accepts new params."""

    def test_accepts_pre_fetched_candidates_param(self):
        svc = TTEService.__new__(TTEService)
        sig = inspect.signature(svc._build_seeded_condition_circe)
        assert "pre_fetched_candidates" in sig.parameters
        assert "expected_domain" in sig.parameters

    def test_single_codeset_circe_accepts_pre_fetched(self):
        svc = TTEService.__new__(TTEService)
        sig = inspect.signature(svc._build_seeded_single_codeset_circe)
        assert "pre_fetched_candidates" in sig.parameters


class TestMaterializeSeededOutcomeCohorts:
    """Verify _materialize_seeded_outcome_cohorts accepts eligibility params."""

    def test_accepts_eligibility_params(self):
        svc = TTEService.__new__(TTEService)
        sig = inspect.signature(svc._materialize_seeded_outcome_cohorts)
        assert "eligibility" in sig.parameters
        assert "criterion_mapping_metadata" in sig.parameters
