"""A cohort that excludes what it enters on is empty, and nothing looked for it.

`No <drug>` requires zero occurrences of a concept set; when that set intersects the
PrimaryCriteria entry set, no person can satisfy the definition. CARMELINA shipped that
shape and passed every gate check, because each check reads one property of a file and
none of them compares the entry against what the rules exclude.

The fixtures are the real contradictory artifacts on disk, read (never modified), so the
check is shown the case that motivated it rather than only a synthetic one.

Under the disease-anchored placebo fix this check will not fire on a placebo comparator,
because the entry becomes a Condition and the excluded set is a Drug. That is what a
working guard looks like: it is kept as the regression guard for the collision itself,
so if the swap is ever skipped again — by a flag, a new anchor branch, or a study whose
NCT enters the anchor table — the emptiness is caught at the gate instead of at a
hospital. A check is worth having for the failure it makes impossible to ship, not for
how often it fires.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from src.utils.circe_lint import contradictory_absence_rules

SITE_GAP = pathlib.Path(__file__).resolve().parents[1] / "output" / "site_gap" / "2026-09-05"
CONTRADICTORY = [
    SITE_GAP / "reexport_wiring_fix" / "carmelina_comparator.circe.json",
    SITE_GAP / "reexport_probe_flag1" / "carmelina_comparator.circe.json",
]


def _entry_set_id(circe):
    crit = circe["PrimaryCriteria"]["CriteriaList"][0]
    domain = next(k for k in crit if isinstance(crit[k], dict))
    return crit[domain]["CodesetId"]


class TestTheCheckFiresOnTheRealBrokenArtifacts:
    @pytest.mark.parametrize("path", CONTRADICTORY, ids=lambda p: p.parent.name)
    def test_should_flag_the_drug_absence_rule_that_excludes_its_own_entry(self, path):
        if not path.exists():
            pytest.skip("artifact not present: " + str(path))
        circe = json.loads(path.read_text())
        assert "No linagliptin" in contradictory_absence_rules(circe)

    @pytest.mark.parametrize("path", CONTRADICTORY, ids=lambda p: p.parent.name)
    def test_should_also_flag_the_class_washout_that_contains_the_entry_drug(self, path):
        """A second instance of the same collision, found by writing the check rather
        than by reading the files: CARMELINA excludes prior DPP-4 inhibitor use, and
        linagliptin -- the drug this cohort enters on -- is a DPP-4 inhibitor. The
        window ends at index rather than after it, so this is a prior-use washout
        rather than the placebo collision, but the entry exposure falls inside it
        either way. Pinned so the finding cannot be lost.
        """
        if not path.exists():
            pytest.skip("artifact not present: " + str(path))
        circe = json.loads(path.read_text())
        assert "GLP-1 receptor agonists use + DPP-4 inhibitors use" in (
            contradictory_absence_rules(circe)
        )


class TestTheCheckDoesNotFireOnSoundDefinitions:
    def test_should_not_flag_a_disease_anchored_comparator(self):
        """The shape the fix produces: Condition entry, Drug exclusion, disjoint."""
        circe = {
            "ConceptSets": [
                {
                    "id": 1,
                    "name": "T2DM",
                    "expression": {"items": [{"concept": {"CONCEPT_ID": 201826}}]},
                },
                {
                    "id": 2,
                    "name": "drug",
                    "expression": {"items": [{"concept": {"CONCEPT_ID": 45774751}}]},
                },
            ],
            "PrimaryCriteria": {"CriteriaList": [{"ConditionOccurrence": {"CodesetId": 1}}]},
            "InclusionRules": [
                {
                    "name": "No drug",
                    "expression": {
                        "Type": "ALL",
                        "CriteriaList": [
                            {
                                "Criteria": {"DrugExposure": {"CodesetId": 2}},
                                "Occurrence": {"Type": 0, "Count": 0},
                            }
                        ],
                        "Groups": [],
                    },
                }
            ],
        }
        assert contradictory_absence_rules(circe) == []

    def test_should_not_flag_a_presence_rule_on_the_entry_set(self):
        """Requiring the entry drug to be PRESENT is redundant, not contradictory."""
        circe = {
            "ConceptSets": [
                {
                    "id": 1,
                    "name": "drug",
                    "expression": {"items": [{"concept": {"CONCEPT_ID": 45774751}}]},
                },
            ],
            "PrimaryCriteria": {"CriteriaList": [{"DrugEra": {"CodesetId": 1}}]},
            "InclusionRules": [
                {
                    "name": "On drug",
                    "expression": {
                        "Type": "ALL",
                        "CriteriaList": [
                            {
                                "Criteria": {"DrugExposure": {"CodesetId": 1}},
                                "Occurrence": {"Type": 2, "Count": 1},
                            }
                        ],
                        "Groups": [],
                    },
                }
            ],
        }
        assert contradictory_absence_rules(circe) == []

    def test_should_not_flag_an_absence_set_that_subtracts_the_entry_concept(self):
        """An ``isExcluded`` item is SUBTRACTED from the set, so it can never be the
        reason an absence rule collides with the entry -- it is the repair for that
        collision. This shape is what the export-time repair writes (see
        ``src.services.entry_exclusion_repair``): the absence set keeps its own
        members and carries the entry concepts as exclusions. Reading the literal id
        list without honouring ``isExcluded`` flagged the repaired file and would have
        rejected the export for the defect it had just fixed."""
        circe = {
            "ConceptSets": [
                {
                    "id": 1,
                    "name": "Type 2 Diabetes Mellitus",
                    "expression": {"items": [
                        {"concept": {"CONCEPT_ID": 201826}, "includeDescendants": True},
                    ]},
                },
                {
                    "id": 2,
                    "name": "Endocrine disorder",
                    "expression": {"items": [
                        {"concept": {"CONCEPT_ID": 201820}, "includeDescendants": True},
                        {"concept": {"CONCEPT_ID": 201826}, "includeDescendants": True,
                         "isExcluded": True},
                    ]},
                },
            ],
            "PrimaryCriteria": {"CriteriaList": [{"ConditionOccurrence": {"CodesetId": 1}}]},
            "InclusionRules": [
                {
                    "name": "Endocrine disorder (excluding T2DM)",
                    "expression": {
                        "Type": "ALL",
                        "CriteriaList": [
                            {
                                "Criteria": {"ConditionOccurrence": {"CodesetId": 2}},
                                "StartWindow": {"Start": {"Days": 9999, "Coeff": -1},
                                                "End": {"Days": 0, "Coeff": 1}},
                                "Occurrence": {"Type": 0, "Count": 0},
                            }
                        ],
                        "Groups": [],
                    },
                }
            ],
        }
        assert contradictory_absence_rules(circe) == []

        # The same shape WITHOUT the exclusion is still flagged -- the guard is
        # narrowed to what `isExcluded` means, not switched off.
        circe["ConceptSets"][1]["expression"]["items"][1]["isExcluded"] = False
        assert contradictory_absence_rules(circe) == ["Endocrine disorder (excluding T2DM)"]

    def test_should_not_flag_an_absence_leaf_under_an_any_group(self):
        """`ANY` means at least one alternative holds, so one unsatisfiable alternative
        does not empty the rule. Flagging it would be a false positive on a delivery
        gate, which is the expensive direction to be wrong in."""
        circe = {
            "ConceptSets": [
                {
                    "id": 1,
                    "name": "drug",
                    "expression": {"items": [{"concept": {"CONCEPT_ID": 45774751}}]},
                },
                {
                    "id": 2,
                    "name": "other",
                    "expression": {"items": [{"concept": {"CONCEPT_ID": 999}}]},
                },
            ],
            "PrimaryCriteria": {"CriteriaList": [{"DrugEra": {"CodesetId": 1}}]},
            "InclusionRules": [
                {
                    "name": "Either",
                    "expression": {
                        "Type": "ANY",
                        "CriteriaList": [
                            {
                                "Criteria": {"DrugExposure": {"CodesetId": 1}},
                                "Occurrence": {"Type": 0, "Count": 0},
                            },
                            {
                                "Criteria": {"DrugExposure": {"CodesetId": 2}},
                                "Occurrence": {"Type": 2, "Count": 1},
                            },
                        ],
                        "Groups": [],
                    },
                }
            ],
        }
        assert contradictory_absence_rules(circe) == []

    def test_should_flag_an_absence_leaf_nested_in_an_all_group(self):
        """Nested `ALL` is still conjunctive, so the emptiness survives one level down."""
        circe = {
            "ConceptSets": [
                {
                    "id": 1,
                    "name": "drug",
                    "expression": {"items": [{"concept": {"CONCEPT_ID": 45774751}}]},
                },
            ],
            "PrimaryCriteria": {"CriteriaList": [{"DrugEra": {"CodesetId": 1}}]},
            "InclusionRules": [
                {
                    "name": "No drug nested",
                    "expression": {
                        "Type": "ALL",
                        "CriteriaList": [],
                        "Groups": [
                            {
                                "Type": "ALL",
                                "CriteriaList": [
                                    {
                                        "Criteria": {"DrugExposure": {"CodesetId": 1}},
                                        "Occurrence": {"Type": 0, "Count": 0},
                                    }
                                ],
                                "Groups": [],
                            }
                        ],
                    },
                }
            ],
        }
        assert contradictory_absence_rules(circe) == ["No drug nested"]


class TestTheCheckReadsTheWindowBoundary:
    """The check is concept-set overlap AND the index day falling inside the window.

    A washout that stops the day BEFORE index does not count the entry exposure, and
    that is not an intuition -- it is arm 3 of the WebAPI experiment recorded in
    `contradictory_absence_rules`' docstring: `[-365, index-1]` returns the full
    10,093-person population where `[-365, index]` returns 0. Everything else stays
    flagged, including a window that runs PAST index, one that stops exactly ON it,
    and an absence rule carrying no window at all.
    """

    @staticmethod
    def _circe(end):
        criterion = {
            "Criteria": {"DrugExposure": {"CodesetId": 1}},
            "Occurrence": {"Type": 0, "Count": 0},
        }
        if end is not None:
            criterion["StartWindow"] = {"Start": {"Days": 365, "Coeff": -1}, "End": end}
        return {
            "ConceptSets": [
                {
                    "id": 1,
                    "name": "DPP-4 inhibitors",
                    "expression": {"items": [{"concept": {"CONCEPT_ID": 40239216}}]},
                },
            ],
            "PrimaryCriteria": {"CriteriaList": [{"DrugEra": {"CodesetId": 1}}]},
            "InclusionRules": [
                {
                    "name": "Prior DPP-4 use",
                    "expression": {
                        "Type": "ALL",
                        "CriteriaList": [criterion],
                        "Groups": [],
                    },
                }
            ],
        }

    def test_should_not_flag_a_washout_that_ends_the_day_before_index(self):
        circe = self._circe({"Days": 1, "Coeff": -1})
        assert contradictory_absence_rules(circe) == []

    def test_should_still_flag_a_washout_that_ends_on_the_index_day(self):
        circe = self._circe({"Days": 0, "Coeff": 1})
        assert contradictory_absence_rules(circe) == ["Prior DPP-4 use"]

    def test_should_still_flag_a_window_that_runs_past_the_index_day(self):
        circe = self._circe({"Days": 365, "Coeff": 1})
        assert contradictory_absence_rules(circe) == ["Prior DPP-4 use"]

    def test_should_still_flag_an_absence_rule_carrying_no_window(self):
        """No StartWindow means unbounded, which contains the index day."""
        assert contradictory_absence_rules(self._circe(None)) == ["Prior DPP-4 use"]

    def test_should_still_flag_an_unbounded_end_with_no_day_count(self):
        """`End: {Coeff: 1}` with no Days is +infinity, not the index day."""
        circe = self._circe({"Coeff": 1})
        assert contradictory_absence_rules(circe) == ["Prior DPP-4 use"]

    def test_should_still_flag_a_day_before_index_end_rebased_on_the_index_end_date(self):
        """`UseIndexEnd` compares against the end of the index era, so `index-1` there
        is not provably before the index start day. Only the provable case is exempt."""
        circe = self._circe({"Days": 1, "Coeff": -1})
        window = circe["InclusionRules"][0]["expression"]["CriteriaList"][0]["StartWindow"]
        window["UseIndexEnd"] = True
        assert contradictory_absence_rules(circe) == ["Prior DPP-4 use"]
