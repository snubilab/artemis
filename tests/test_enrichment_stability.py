"""
Tests for enrichment source normalization stability (P3).

Verifies that _normalize_trial_data_for_stable_hash() produces a stable,
deduplicated, whitespace-clean representation so that the same logical
criteria always map to the same prompt hash.
"""
import hashlib

import pytest

from src.agents.agent1.nct_fetcher import TrialData
from src.agents.agent1.parser import _normalize_trial_data_for_stable_hash


def _make_trial(**kwargs) -> TrialData:
    defaults = dict(
        nct_id="NCT00000001",
        title="Test Trial",
        inclusion_criteria=[],
        exclusion_criteria=[],
    )
    defaults.update(kwargs)
    return TrialData(**defaults)


def _hash_criteria(trial: TrialData) -> str:
    """Reproduce the prompt hash key used in parse_nct()."""
    content = "|".join(trial.inclusion_criteria) + "||" + "|".join(trial.exclusion_criteria)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


class TestNormalizeStripsWhitespace:
    def test_leading_trailing_whitespace_removed(self):
        trial = _make_trial(
            inclusion_criteria=["  Age >= 18  ", "No prior therapy"],
            exclusion_criteria=["  Pregnant  "],
        )
        result = _normalize_trial_data_for_stable_hash(trial)
        assert result.inclusion_criteria == ["Age >= 18", "No prior therapy"]
        assert result.exclusion_criteria == ["Pregnant"]

    def test_internal_multiple_spaces_collapsed(self):
        trial = _make_trial(inclusion_criteria=["Age  >=  18"])
        result = _normalize_trial_data_for_stable_hash(trial)
        assert result.inclusion_criteria == ["Age >= 18"]

    def test_non_breaking_space_removed(self):
        trial = _make_trial(inclusion_criteria=["Age\u00a0>=\u00a018"])
        result = _normalize_trial_data_for_stable_hash(trial)
        assert result.inclusion_criteria == ["Age >= 18"]

    def test_whitespace_normalized_hash_is_stable(self):
        trial_clean = _make_trial(inclusion_criteria=["Age >= 18", "No prior therapy"])
        trial_dirty = _make_trial(inclusion_criteria=["  Age >= 18  ", "No  prior  therapy"])
        norm_clean = _normalize_trial_data_for_stable_hash(trial_clean)
        norm_dirty = _normalize_trial_data_for_stable_hash(trial_dirty)
        assert _hash_criteria(norm_clean) == _hash_criteria(norm_dirty)


class TestNormalizeDeduplicates:
    def test_exact_duplicates_removed(self):
        trial = _make_trial(
            inclusion_criteria=["Age >= 18", "Age >= 18", "No prior therapy"],
        )
        result = _normalize_trial_data_for_stable_hash(trial)
        assert result.inclusion_criteria.count("Age >= 18") == 1

    def test_whitespace_duplicates_removed(self):
        trial = _make_trial(
            inclusion_criteria=["Age >= 18", "  Age >= 18  "],
        )
        result = _normalize_trial_data_for_stable_hash(trial)
        assert len(result.inclusion_criteria) == 1
        assert result.inclusion_criteria[0] == "Age >= 18"

    def test_exclusion_duplicates_removed(self):
        trial = _make_trial(
            exclusion_criteria=["Pregnant", "Pregnant", "Breastfeeding"],
        )
        result = _normalize_trial_data_for_stable_hash(trial)
        assert result.exclusion_criteria.count("Pregnant") == 1


class TestNormalizeIsDeterministic:
    def test_same_input_twice_produces_same_output(self):
        trial = _make_trial(
            inclusion_criteria=["No prior therapy", "Age >= 18"],
            exclusion_criteria=["Pregnant", "Active infection"],
        )
        result1 = _normalize_trial_data_for_stable_hash(trial)
        result2 = _normalize_trial_data_for_stable_hash(trial)
        assert result1.inclusion_criteria == result2.inclusion_criteria
        assert result1.exclusion_criteria == result2.exclusion_criteria

    def test_order_independent_hash(self):
        """Criteria in different order → same normalized list → same hash."""
        trial_a = _make_trial(inclusion_criteria=["Age >= 18", "No prior therapy"])
        trial_b = _make_trial(inclusion_criteria=["No prior therapy", "Age >= 18"])
        norm_a = _normalize_trial_data_for_stable_hash(trial_a)
        norm_b = _normalize_trial_data_for_stable_hash(trial_b)
        assert norm_a.inclusion_criteria == norm_b.inclusion_criteria
        assert _hash_criteria(norm_a) == _hash_criteria(norm_b)

    def test_does_not_mutate_original(self):
        """Pure function: original trial_data is unchanged."""
        original_criteria = ["  Age >= 18  ", "  Age >= 18  "]
        trial = _make_trial(inclusion_criteria=original_criteria[:])
        _normalize_trial_data_for_stable_hash(trial)
        assert trial.inclusion_criteria == original_criteria
