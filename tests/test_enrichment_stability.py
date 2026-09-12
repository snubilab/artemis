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

    def test_should_produce_a_different_hash_when_the_document_order_differs(self):
        """Order is input, not noise, so it must reach the key.

        This replaces an earlier ``test_order_independent_hash``, which asserted the
        opposite. That assertion was the defect's own contract: it is satisfied only
        by a sort, and the sort is what put LEADER's eleven "at least 1 of the
        following" members at top level in alphabetical order, AND-combined by Circe
        into an empty cohort. Order-insensitivity is also unsafe on its own terms --
        it makes a re-parse that legitimately reorders criteria reuse the previous
        run's cached IR, which is indistinguishable in the output from the reorder
        having had no effect.
        """
        trial_a = _make_trial(inclusion_criteria=["Age >= 18", "No prior therapy"])
        trial_b = _make_trial(inclusion_criteria=["No prior therapy", "Age >= 18"])
        norm_a = _normalize_trial_data_for_stable_hash(trial_a)
        norm_b = _normalize_trial_data_for_stable_hash(trial_b)
        assert norm_a.inclusion_criteria != norm_b.inclusion_criteria
        assert _hash_criteria(norm_a) != _hash_criteria(norm_b)

    def test_does_not_mutate_original(self):
        """Pure function: original trial_data is unchanged."""
        original_criteria = ["  Age >= 18  ", "  Age >= 18  "]
        trial = _make_trial(inclusion_criteria=original_criteria[:])
        _normalize_trial_data_for_stable_hash(trial)
        assert trial.inclusion_criteria == original_criteria


class TestNormalizePreservesDocumentOrder:
    """The list the model is handed must arrive in the order the document wrote it.

    ``parse_nct`` rebinds ``trial_data`` to this function's return value and builds
    the prompt from it, so whatever order this function produces is the order the
    model reads -- and ``_format_criteria`` numbers the lines, which presents that
    order to the model as authoritative.
    """

    # Verbatim from LEADER's supplement (NCT01179048), in the order
    # `extract_eligibility_from_text` yields them. The header at index 0 names its
    # cardinality and ends in a colon; indices 1-3 are three of its members. That
    # relationship exists ONLY in the order.
    LEADER_HEAD = [
        "Prior cardiovascular disease cohort: age \u226550 and \u22651 of the following criteria:",
        "Prior MI",
        "Prior stroke or TIA",
        "Chronic heart failure NYHA class II-III",
    ]

    def test_should_keep_a_list_header_adjacent_to_its_members(self):
        """The real case: alphabetising splits the header from every member.

        Sorted, the header lands between "Prior MI" and "Prior stroke or TIA" while
        "Chronic heart failure" moves to the front -- and Circe AND-combines the
        resulting top-level InclusionRules.
        """
        trial = _make_trial(inclusion_criteria=list(self.LEADER_HEAD))
        result = _normalize_trial_data_for_stable_hash(trial)
        assert result.inclusion_criteria == self.LEADER_HEAD

    def test_should_preserve_document_order_for_exclusion_criteria_too(self):
        ordered = ["Type 1 diabetes", "Acute coronary event within 14 days", "Breastfeeding"]
        trial = _make_trial(exclusion_criteria=list(ordered))
        result = _normalize_trial_data_for_stable_hash(trial)
        assert result.exclusion_criteria == ordered

    def test_should_keep_the_first_occurrence_position_when_deduplicating(self):
        """Dedup must not be an excuse to reorder: the survivor keeps its own slot."""
        trial = _make_trial(
            inclusion_criteria=["Zeta criterion", "Alpha criterion", "  Zeta criterion  "],
        )
        result = _normalize_trial_data_for_stable_hash(trial)
        assert result.inclusion_criteria == ["Zeta criterion", "Alpha criterion"]

    def test_should_still_clean_whitespace_while_preserving_order(self):
        """The two purposes hold together, not one at the other's expense."""
        trial = _make_trial(
            inclusion_criteria=["  Zeta\u00a0>=\u00a01  ", "Alpha  >=  2"],
        )
        result = _normalize_trial_data_for_stable_hash(trial)
        assert result.inclusion_criteria == ["Zeta >= 1", "Alpha >= 2"]
