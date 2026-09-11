"""The gold-overlap scorer can see a bound, and says so separately.

`scripts/conceptset_overlap_eval.py` reads the `ConceptSets` section and nothing else.
Before this module, `rg 'ValueAsNumber|RangeHigh|Extent' scripts/conceptset_overlap_eval.py`
exited 1: a concept set is a bag of concept ids, and a bound lives on the RULE that
reads the set, so no amount of concept overlap can see one.

The consequence, measured: `9ec4b3a` corrected EMPA-REG's HbA1c band from `< 10.0` to
`<= 10.0` and both recall and precision moved by exactly 0.0000. Not "no improvement" --
not measurable. A whole class of defect was invisible to the project's quality metric,
in both directions.

This measure is reported BESIDE the macro numbers and never folded into them. The
macro numbers are the comparison baseline across many runs and `AGENTS.md` pins how
they are computed (per criterion, 1:1, macro-averaged, never micro/pooled); changing
them to include a different quantity would break every historical comparison.

Pairing is NOT re-derived. `pair_concept_sets` already decides which generated set
answers which gold set, and a second pairing rule would be a second answer to the same
question -- so bounds are looked up through the pair the scorer already made.

Four outcomes, and the fourth is the one that keeps the measure honest:

  exact             operator, value and extent all agree
  operator_only     value and extent agree, operator does not -- `gte 3` vs `gt 3.0`,
                    which is the off-by-one class `9ec4b3a` was about, measured on
                    CAROLINA's ALT, AST and alkaline phosphatase
  value             the numbers themselves differ
  polarity_flip     the operators are COMPLEMENTS over the same number -- gold writes
                    `BMI gt 45` as an exclusion where the generated cohort writes
                    `BMI lte 45` as an inclusion. Measured on CAROLINA BMI, CAROLINA
                    HbA1c (`!bt` vs `bt`) and EMPA-REG BMI: 3 pairs that are NOT
                    disagreements. Folding them into `operator_only` would have the
                    measure report defects that are not there, which is the failure
                    mode that gets a metric switched off.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.conceptset_overlap_eval import (
    GOLD_DIR,
    TRIALS,
    ResolvedSet,
    bound_agreement,
    cohort_bounds,
    pair_concept_sets,
)

GENERATED_DIR = Path("output/site_gap/2026-09-13/circe_new")


def _measurement(codeset_id: int, attr: str, op: str, value, extent=None) -> dict:
    bound = {"Op": op, "Value": value}
    if extent is not None:
        bound["Extent"] = extent
    return {
        "name": f"rule over {codeset_id}",
        "expression": {
            "Type": "ALL",
            "CriteriaList": [
                {"Criteria": {"Measurement": {"CodesetId": codeset_id, attr: bound}}}
            ],
        },
    }


def _cohort(*rules: dict, sets: list[tuple[int, str]]) -> dict:
    return {
        "ConceptSets": [
            {"id": i, "name": name, "expression": {"items": []}} for i, name in sets
        ],
        "PrimaryCriteria": {"CriteriaList": []},
        "InclusionRules": list(rules),
    }


def _pair(gold_key: str, gen_key: str):
    """One matched pair, built the way `pair_concept_sets` builds one."""
    gold = [ResolvedSet(key=gold_key, name="Alanine aminotransferase", concept_ids={1})]
    gen = [ResolvedSet(key=gen_key, name="Alanine aminotransferase", concept_ids={1})]
    return pair_concept_sets(gold, gen).pairs


class TestReadingABoundAtAll:
    def test_should_find_the_bound_a_rule_carries(self) -> None:
        cohort = _cohort(
            _measurement(7, "ValueAsNumber", "gte", 3), sets=[(7, "ALT")]
        )

        found = cohort_bounds(cohort)

        assert found["7"] == [("Measurement", "ValueAsNumber", "gte", 3.0, None)]

    def test_should_find_a_between_bound_with_its_extent(self) -> None:
        cohort = _cohort(
            _measurement(1, "ValueAsNumber", "bt", 6.5, 8.5), sets=[(1, "HbA1c")]
        )

        assert cohort_bounds(cohort)["1"] == [
            ("Measurement", "ValueAsNumber", "bt", 6.5, 8.5)
        ]

    def test_should_find_no_bound_in_a_cohort_that_carries_none(self) -> None:
        cohort = _cohort(sets=[(1, "HbA1c")])

        assert cohort_bounds(cohort) == {}


class TestClassifyingAPair:
    def _compare(self, gold_bound, gen_bound):
        gold = _cohort(_measurement(11, *gold_bound), sets=[(11, "ALT")])
        gen = _cohort(_measurement(22, *gen_bound), sets=[(22, "ALT")])
        return bound_agreement(_pair("11", "22"), gold, gen)

    def test_should_call_it_exact_when_operator_value_and_extent_agree(self) -> None:
        result = self._compare(("ValueAsNumber", "gte", 30, 59), ("ValueAsNumber", "gte", 30.0, 59.0))

        assert result["exact"] == 1
        assert result["operator_only"] == 0
        assert result["value"] == 0

    def test_should_call_gte_3_against_gt_3_an_operator_only_mismatch(self) -> None:
        """The off-by-one class. Measured on CAROLINA ALT, AST and alkaline phosphatase."""
        result = self._compare(("ValueAsNumber", "gte", 3), ("ValueAsNumber", "gt", 3.0))

        assert result["operator_only"] == 1
        assert result["exact"] == 0
        assert result["value"] == 0

    def test_should_call_a_different_number_a_value_mismatch(self) -> None:
        result = self._compare(("ValueAsNumber", "gte", 10), ("ValueAsNumber", "gte", 7.0))

        assert result["value"] == 1
        assert result["operator_only"] == 0

    def test_should_not_call_a_complementary_operator_a_mismatch(self) -> None:
        """gold `BMI gt 45` as an exclusion, ours `BMI lte 45` as an inclusion.

        Three real pairs in the 2026-09-13 export are this shape. Counting them as
        disagreements would make the measure report defects that are not there.
        """
        result = self._compare(("ValueAsNumber", "gt", 45), ("ValueAsNumber", "lte", 45.0))

        assert result["polarity_flip"] == 1
        assert result["operator_only"] == 0
        assert result["value"] == 0

    def test_should_treat_not_between_as_the_complement_of_between(self) -> None:
        result = self._compare(
            ("ValueAsNumber", "!bt", 6.5, 8.5), ("ValueAsNumber", "bt", 6.5, 8.5)
        )

        assert result["polarity_flip"] == 1

    def test_should_count_a_generated_bound_the_gold_pair_does_not_carry(self) -> None:
        gold = _cohort(sets=[(11, "ALT")])
        gen = _cohort(_measurement(22, "ValueAsNumber", "gt", 3.0), sets=[(22, "ALT")])

        result = bound_agreement(_pair("11", "22"), gold, gen)

        assert result["generated_only"] == 1
        assert result["gold_only"] == 0

    def test_should_count_a_gold_bound_the_generated_pair_does_not_carry(self) -> None:
        """The silent-loss direction: a threshold the protocol wrote and we dropped."""
        gold = _cohort(_measurement(11, "ValueAsNumber", "gt", 3), sets=[(11, "ALT")])
        gen = _cohort(sets=[(22, "ALT")])

        result = bound_agreement(_pair("11", "22"), gold, gen)

        assert result["gold_only"] == 1
        assert result["generated_only"] == 0


class TestRefusingToLookClean:
    def test_should_report_zero_pairs_compared_rather_than_perfect_agreement(self) -> None:
        """A run where neither side carries a bound must not read as 100% agreement.

        `pairs_compared` is the denominator. Without it, a comparison that silently read
        nothing on either side reports `exact=0, value=0` -- indistinguishable from a
        run where every bound matched, and from one where the extractor was never wired
        up at all.
        """
        gold = _cohort(sets=[(11, "ALT")])
        gen = _cohort(sets=[(22, "ALT")])

        result = bound_agreement(_pair("11", "22"), gold, gen)

        assert result["pairs_compared"] == 0
        assert result["gold_bounds_seen"] == 0
        assert result["generated_bounds_seen"] == 0

    def test_should_report_how_many_bounds_it_read_on_each_side(self) -> None:
        """The guard against a one-sided read reporting as agreement."""
        gold = _cohort(_measurement(11, "ValueAsNumber", "gt", 3), sets=[(11, "ALT")])
        gen = _cohort(_measurement(22, "ValueAsNumber", "gt", 3.0), sets=[(22, "ALT")])

        result = bound_agreement(_pair("11", "22"), gold, gen)

        assert result["gold_bounds_seen"] == 1
        assert result["generated_bounds_seen"] == 1
        assert result["pairs_compared"] == 1


class TestAgainstTheRealExport:
    """The real case that motivated the measure, not only synthetic rows."""

    def _load(self, label: str):
        gold_rel, gen_name = TRIALS[label]
        gen_path = GENERATED_DIR / gen_name
        if not gen_path.exists():
            pytest.skip(f"{gen_path} is not present")
        return json.loads((GOLD_DIR / gold_rel).read_text()), json.loads(gen_path.read_text())

    def test_should_surface_carolina_transaminase_operator_mismatches(self) -> None:
        """gold `RangeHighRatio gte 3`, ours `gt 3.0`, on ALT, AST and AP alike."""
        gold, gen = self._load("CAROLINA")
        gold_b, gen_b = cohort_bounds(gold), cohort_bounds(gen)

        assert ("Measurement", "RangeHighRatio", "gte", 3.0, None) in gold_b["172"]
        assert ("Measurement", "RangeHighRatio", "gt", 3.0, None) in gen_b["26"]

    def test_should_read_a_bound_on_every_trial_of_the_export(self) -> None:
        """If any trial reads zero bounds on either side, the extractor is not reading."""
        for label in TRIALS:
            gold, gen = self._load(label)
            assert cohort_bounds(gold), f"{label}: no gold bound read"
            assert cohort_bounds(gen), f"{label}: no generated bound read"
