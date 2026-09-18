"""Unit tests for collapsing an ``ANY`` two-sided bound back into one ``bt`` range.

DB-free on the ``PrefetchedVocabulary`` seam, so the real closure resolver runs. Every
concept id, bound and rule name below is copied from
``deliveries/2026-09-12/carmelina_treatment.circe.json`` rule #12.

The defect: the protocol asks for ``6.5 <= HbA1c <= 10.0`` and the rule was emitted as
``Type: ANY`` over ``gte 6.5`` and ``lte 10.0`` -- a disjunction nearly everyone with an
HbA1c satisfies. The collapse also unblocks the presence-unit repair, which declines a
one-sided bound because an IFCC value (>= 15 mmol/mol) passes a bare ``>= 6.5``.
"""
from __future__ import annotations

import logging
import sys
from copy import deepcopy
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.services.conceptset_closure import PrefetchedVocabulary  # noqa: E402
from src.services.presence_unit_repair import repair_presence_unit_filters  # noqa: E402
from src.services.range_disjunction_repair import (  # noqa: E402
    iter_range_disjunctions,
    repair_range_disjunctions,
)

# CARMELINA codesets 8 and 9 -- byte-identical item lists.
HBA1C = [3004410, 3007263, 3034639, 4197971, 44793001]
# EMPA-REG's HbA1c set adds 3005446 'Hemoglobin A1/Hemoglobin.total' -- HbA1, not HbA1c.
HBA1_TOTAL = 3005446

PERCENT = [
    {
        "CONCEPT_CODE": "%",
        "CONCEPT_ID": 8554,
        "CONCEPT_NAME": "percent",
        "DOMAIN_ID": "Unit",
        "VOCABULARY_ID": "UCUM",
    }
]

PRESENCE = {"Type": 2, "Count": 1}
WINDOW_180 = {"Start": {"Days": 180, "Coeff": -1}, "End": {"Days": 0, "Coeff": 1}}

CARMELINA_RULE_12 = "HbA1c at least 6.5% + HbA1c at most 10.0%"


def vocabulary(*concept_ids: int) -> PrefetchedVocabulary:
    """Seed-only closures: what the live vocabulary returned for these sets."""
    return PrefetchedVocabulary(
        concept_invalid_reason={cid: None for cid in concept_ids},
        ancestor_edges={cid: {cid} for cid in concept_ids},
    )


def concept_set(set_id: int, name: str, concept_ids: list[int]) -> dict:
    return {
        "id": set_id,
        "name": name,
        "expression": {
            "items": [
                {
                    "concept": {"CONCEPT_ID": cid, "CONCEPT_NAME": f"concept {cid}"},
                    "includeDescendants": True,
                    "includeMapped": False,
                    "isExcluded": False,
                }
                for cid in concept_ids
            ]
        },
    }


def criterion(codeset_id: int, value: dict, *, occurrence: dict = PRESENCE,
              window: dict = WINDOW_180, unit: list | None = PERCENT) -> dict:
    measurement: dict = {"CodesetId": codeset_id, "ValueAsNumber": dict(value)}
    if unit is not None:
        measurement["Unit"] = deepcopy(unit)
    return {
        "Criteria": {"Measurement": measurement},
        "StartWindow": deepcopy(window),
        "RestrictVisit": False,
        "IgnoreObservationPeriod": False,
        "Occurrence": dict(occurrence),
    }


def cohort(low: dict, high: dict, *, name: str = CARMELINA_RULE_12,
           low_members: list[int] = HBA1C, high_members: list[int] = HBA1C,
           rule_type: str = "ANY") -> dict:
    """CARMELINA rule #12's shape: ANY over two single-criterion ALL groups."""
    return {
        "ConceptSets": [
            concept_set(1, "linagliptin", [40239216]),
            concept_set(8, "HbA1c", low_members),
            concept_set(9, "HbA1c", high_members),
        ],
        "PrimaryCriteria": {"CriteriaList": [{"DrugExposure": {"CodesetId": 1}}]},
        "InclusionRules": [
            {
                "name": name,
                "expression": {
                    "Type": rule_type,
                    "CriteriaList": [],
                    "DemographicCriteriaList": [],
                    "Groups": [
                        {
                            "Type": "ALL",
                            "CriteriaList": [low],
                            "DemographicCriteriaList": [],
                            "Groups": [],
                        },
                        {
                            "Type": "ALL",
                            "CriteriaList": [high],
                            "DemographicCriteriaList": [],
                            "Groups": [],
                        },
                    ],
                },
            }
        ],
    }


def sole_measurement(base: dict) -> dict:
    expression = base["InclusionRules"][0]["expression"]
    return expression["CriteriaList"][0]["Criteria"]["Measurement"]


# --------------------------------------------------------------------------
# it fires on the measured shape
# --------------------------------------------------------------------------

def test_should_collapse_to_one_between_criterion_when_any_rule_brackets_one_analyte():
    """CARMELINA rule #12 verbatim: codeset 8 gte 6.5 OR codeset 9 lte 10.0, the two sets
    resolving to the same closure."""
    base = cohort(
        criterion(8, {"Value": 6.5, "Op": "gte"}),
        criterion(9, {"Value": 10.0, "Op": "lte"}),
    )
    applied = repair_range_disjunctions(base, vocabulary(*HBA1C))

    assert [(r.rule_index, r.low, r.high) for r in applied] == [(0, 6.5, 10.0)]
    expression = base["InclusionRules"][0]["expression"]
    assert expression["Type"] == "ALL"
    assert expression["Groups"] == []
    assert len(expression["CriteriaList"]) == 1
    assert sole_measurement(base)["ValueAsNumber"] == {
        "Value": 6.5, "Extent": 10.0, "Op": "bt",
    }
    # The surviving criterion keeps everything but the bound: window, occurrence and
    # the unit filter the presence-unit repair then judges.
    assert sole_measurement(base)["CodesetId"] == 8
    assert sole_measurement(base)["Unit"] == PERCENT
    assert base["InclusionRules"][0]["expression"]["CriteriaList"][0]["StartWindow"] == WINDOW_180


def test_should_leave_the_concept_sets_untouched_when_it_collapses():
    """Only the rule expression is rewritten; the now-unreferenced set 9 stays as data."""
    base = cohort(
        criterion(8, {"Value": 6.5, "Op": "gte"}),
        criterion(9, {"Value": 10.0, "Op": "lte"}),
    )
    before = deepcopy(base["ConceptSets"])
    repair_range_disjunctions(base, vocabulary(*HBA1C))
    assert base["ConceptSets"] == before


# --------------------------------------------------------------------------
# it declines
# --------------------------------------------------------------------------

def test_should_decline_and_warn_when_the_two_closures_differ(caplog):
    """Merging two different analytes is a different and wrong repair. EMPA-REG's HbA1c
    set carries 3005446 HbA1 beside the HbA1c concepts."""
    base = cohort(
        criterion(8, {"Value": 6.5, "Op": "gte"}),
        criterion(9, {"Value": 10.0, "Op": "lte"}),
        high_members=HBA1C + [HBA1_TOTAL],
    )
    before = deepcopy(base)
    with caplog.at_level(logging.WARNING):
        assert repair_range_disjunctions(base, vocabulary(*HBA1C, HBA1_TOTAL)) == []
    assert base == before
    assert str(HBA1_TOTAL) in caplog.text


def test_should_decline_when_occurrences_differ():
    """An absence on one side is not a bracketed range; it is a different rule."""
    base = cohort(
        criterion(8, {"Value": 6.5, "Op": "gte"}),
        criterion(9, {"Value": 10.0, "Op": "lte"}, occurrence={"Type": 0, "Count": 0}),
    )
    before = deepcopy(base)
    assert repair_range_disjunctions(base, vocabulary(*HBA1C)) == []
    assert base == before


def test_should_decline_when_windows_differ():
    """Two bounds read over different lookbacks are two observations, not one range."""
    base = cohort(
        criterion(8, {"Value": 6.5, "Op": "gte"}),
        criterion(9, {"Value": 10.0, "Op": "lte"},
                  window={"Start": {"Days": 365, "Coeff": -1}, "End": {"Days": 0, "Coeff": 1}}),
    )
    before = deepcopy(base)
    assert repair_range_disjunctions(base, vocabulary(*HBA1C)) == []
    assert base == before


def test_should_decline_when_both_bounds_point_the_same_way():
    base = cohort(
        criterion(8, {"Value": 6.5, "Op": "gte"}),
        criterion(9, {"Value": 10.0, "Op": "gte"}),
    )
    before = deepcopy(base)
    assert repair_range_disjunctions(base, vocabulary(*HBA1C)) == []
    assert base == before


def test_should_decline_when_the_low_bound_is_not_below_the_high_bound():
    base = cohort(
        criterion(8, {"Value": 10.0, "Op": "gte"}),
        criterion(9, {"Value": 6.5, "Op": "lte"}),
        name="HbA1c at least 10.0% + HbA1c at most 6.5%",
    )
    before = deepcopy(base)
    assert repair_range_disjunctions(base, vocabulary(*HBA1C)) == []
    assert base == before


def test_should_decline_and_warn_when_either_bound_is_strict(caplog):
    """``bt`` is inclusive, so collapsing a strict bound would admit the endpoint. That
    widening is a second semantic change nobody asked for, so the repair declines."""
    base = cohort(
        criterion(8, {"Value": 6.5, "Op": "gt"}),
        criterion(9, {"Value": 10.0, "Op": "lte"}),
    )
    before = deepcopy(base)
    with caplog.at_level(logging.WARNING):
        assert repair_range_disjunctions(base, vocabulary(*HBA1C)) == []
    assert base == before
    assert "inclusive" in caplog.text


def test_should_decline_and_warn_when_the_rule_name_brackets_two_populations(caplog):
    """EMPA-REG rule #4's shape: two genuinely different populations, each with its own
    range. The name is the only thing that separates it from a bracketed range."""
    base = cohort(
        criterion(8, {"Value": 7.0, "Op": "gte"}),
        criterion(9, {"Value": 10.0, "Op": "lte"}),
        name="HbA1c for patients on background therapy (>=7.0%) "
             "+ HbA1c for drug naive patients (<=10.0%)",
    )
    before = deepcopy(base)
    with caplog.at_level(logging.WARNING):
        assert repair_range_disjunctions(base, vocabulary(*HBA1C)) == []
    assert base == before
    assert "name" in caplog.text


def test_should_decline_when_the_rule_name_does_not_state_the_delivered_bounds():
    """A name naming other numbers describes another rule; collapsing on it would be a
    guess."""
    base = cohort(
        criterion(8, {"Value": 6.5, "Op": "gte"}),
        criterion(9, {"Value": 10.0, "Op": "lte"}),
        name="HbA1c at least 7.0% + HbA1c at most 9.0%",
    )
    assert repair_range_disjunctions(base, vocabulary(*HBA1C)) == []


def test_should_decline_when_the_rule_is_a_conjunction():
    """``Type: ALL`` over the same two bounds already means the range."""
    base = cohort(
        criterion(8, {"Value": 6.5, "Op": "gte"}),
        criterion(9, {"Value": 10.0, "Op": "lte"}),
        rule_type="ALL",
    )
    before = deepcopy(base)
    assert repair_range_disjunctions(base, vocabulary(*HBA1C)) == []
    assert base == before


def test_should_decline_when_a_group_holds_more_than_its_own_criterion():
    """CARMELINA rule #14's shape: one branch carries a second criterion, so the ANY is
    not a two-bound bracket."""
    base = cohort(
        criterion(8, {"Value": 6.5, "Op": "gte"}),
        criterion(9, {"Value": 10.0, "Op": "lte"}),
    )
    groups = base["InclusionRules"][0]["expression"]["Groups"]
    groups[0]["CriteriaList"].append(
        {"Criteria": {"ConditionOccurrence": {"CodesetId": 1}}, "Occurrence": dict(PRESENCE)}
    )
    before = deepcopy(base)
    assert repair_range_disjunctions(base, vocabulary(*HBA1C)) == []
    assert base == before


def test_should_find_no_candidate_without_a_vocabulary_when_nothing_qualifies():
    """The DB-free pre-gate the wiring uses to skip the database entirely."""
    base = cohort(
        criterion(8, {"Value": 6.5, "Op": "gte"}),
        criterion(9, {"Value": 10.0, "Op": "lte"}),
        rule_type="ALL",
    )
    assert list(iter_range_disjunctions(base)) == []


# --------------------------------------------------------------------------
# composition: the collapse is what makes the unit filter droppable
# --------------------------------------------------------------------------

def test_should_keep_the_unit_when_the_one_sided_bound_is_not_collapsed_first():
    """The before half of the composition. ``gte 6.5`` alone: every IFCC value
    (>= 15 mmol/mol) passes it, so the presence-unit repair must decline."""
    base = cohort(
        criterion(8, {"Value": 6.5, "Op": "gte"}),
        criterion(9, {"Value": 10.0, "Op": "lte"}),
    )
    assert repair_presence_unit_filters(base, vocabulary(*HBA1C)) == []
    groups = base["InclusionRules"][0]["expression"]["Groups"]
    assert groups[0]["CriteriaList"][0]["Criteria"]["Measurement"]["Unit"] == PERCENT


def test_should_drop_the_unit_when_the_collapse_runs_first():
    """The wired order. ``bt 6.5..10.0`` can be reached by no alternative unit, so the
    unit filter that zeroed the rule at Ajou comes off."""
    base = cohort(
        criterion(8, {"Value": 6.5, "Op": "gte"}),
        criterion(9, {"Value": 10.0, "Op": "lte"}),
    )
    assert len(repair_range_disjunctions(base, vocabulary(*HBA1C))) == 1
    applied = repair_presence_unit_filters(base, vocabulary(*HBA1C))
    assert [r.analyte for r in applied] == ["HbA1c"]
    assert "Unit" not in sole_measurement(base)
    assert sole_measurement(base)["ValueAsNumber"] == {"Value": 6.5, "Extent": 10.0, "Op": "bt"}
