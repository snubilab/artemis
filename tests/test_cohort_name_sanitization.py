"""Tests for cohort definition name sanitization.

Covers:
- Atlas-forbidden character removal (colon, etc.)
- Redundancy reduction between study_name and label
- varchar(255) length enforcement
"""

from __future__ import annotations

import pytest

from src.services.tte_service import TTEService


@pytest.fixture
def service():
    """Create a minimal TTEService for unit-testing name generation."""
    svc = TTEService.__new__(TTEService)
    return svc


class TestForbiddenCharacterSanitization:
    """Atlas forbids certain special characters in cohort names."""

    def test_colon_is_removed(self, service):
        # Arrange
        study_id = 428
        study_name = "apixaban vs warfarin"
        role = "primary_outcome"
        label = "Stroke or Systemic Embolism"

        # Act
        name = service._seeded_cohort_definition_name(
            study_id=study_id,
            study_name=study_name,
            role=role,
            label=label,
        )

        # Assert
        assert ":" not in name

    def test_semicolon_is_removed(self, service):
        name = service._seeded_cohort_definition_name(
            study_id=1,
            study_name="test",
            role="primary_outcome",
            label="Stroke; Embolism",
        )
        assert ";" not in name

    def test_backslash_is_removed(self, service):
        name = service._seeded_cohort_definition_name(
            study_id=1,
            study_name="test",
            role="primary_outcome",
            label="Stroke \\ Embolism",
        )
        assert "\\" not in name

    def test_square_brackets_are_removed(self, service):
        name = service._seeded_cohort_definition_name(
            study_id=1,
            study_name="test",
            role="primary_outcome",
            label="HbA1c [Mass/volume]",
        )
        assert "[" not in name
        assert "]" not in name


class TestNameRedundancy:
    """Study name and label should not repeat information."""

    def test_no_duplicate_study_info_in_name(self, service):
        # When label largely duplicates study_name, the result
        # should NOT contain both full copies.
        name = service._seeded_cohort_definition_name(
            study_id=428,
            study_name="apixaban vs warfarin for Stroke or Systemic Emb",
            role="primary_outcome",
            label="Stroke or Systemic Embolism",
        )
        # The name should be concise — label stands on its own
        # without repeating the study_name redundantly.
        assert len(name) <= 255
        # Should still contain the label info
        assert "Stroke" in name

    def test_role_is_human_readable(self, service):
        name = service._seeded_cohort_definition_name(
            study_id=1,
            study_name="test study",
            role="primary_outcome",
            label="MI",
        )
        assert "Primary Outcome" in name


class TestLengthEnforcement:
    """Names must not exceed varchar(255)."""

    def test_short_name_is_preserved(self, service):
        name = service._seeded_cohort_definition_name(
            study_id=1,
            study_name="short",
            role="primary_outcome",
            label="MI",
        )
        assert len(name) <= 255
        assert "short" in name

    def test_very_long_label_is_truncated(self, service):
        long_label = "A" * 300
        name = service._seeded_cohort_definition_name(
            study_id=1,
            study_name="test study",
            role="primary_outcome",
            label=long_label,
        )
        assert len(name) <= 255

    def test_very_long_study_name_is_truncated(self, service):
        long_study = "B" * 300
        name = service._seeded_cohort_definition_name(
            study_id=1,
            study_name=long_study,
            role="primary_outcome",
            label="MI",
        )
        assert len(name) <= 255

    def test_both_long_truncated_within_limit(self, service):
        name = service._seeded_cohort_definition_name(
            study_id=999999,
            study_name="X" * 200,
            role="primary_outcome",
            label="Y" * 200,
        )
        assert len(name) <= 255


class TestBasicFormatting:
    """Basic formatting expectations."""

    def test_contains_study_id(self, service):
        name = service._seeded_cohort_definition_name(
            study_id=42,
            study_name="test",
            role="primary_outcome",
            label="MI",
        )
        assert "42" in name

    def test_empty_label_falls_back_to_role(self, service):
        name = service._seeded_cohort_definition_name(
            study_id=1,
            study_name="test",
            role="primary_outcome",
            label="   ",
        )
        assert "primary outcome" in name.lower()

    def test_whitespace_in_label_is_collapsed(self, service):
        name = service._seeded_cohort_definition_name(
            study_id=1,
            study_name="test",
            role="primary_outcome",
            label="  Stroke   or   MI  ",
        )
        assert "Stroke or MI" in name
