"""Unit tests for dropping the ``Unit`` filter on allowlisted presence criteria.

DB-free on the ``PrefetchedVocabulary`` seam, so the real closure resolver runs.
Every concept id and bound below is copied from ``deliveries/2026-09-12/``.

The defect: a ``Unit`` filter compiles to ``AND unit_concept_id IN (...)``. At Ajou
every unit-bearing inclusion rule returned exactly 0 people (6 of 6) while Dong-A
passed the same rules, and a NULL unit matches no ``IN`` list, so widening the list
cannot fix it. The user decided to drop the filter on PRESENCE criteria for a named
set of analytes, and only where the residual risk is "can only miss patients".
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
from src.utils.circe_lint import unitless_value_bound_criteria  # noqa: E402

# HbA1c set, CAROLINA codeset 5 / CARMELINA codeset 8.
HBA1C = [3004410, 3007263, 3034639, 4197971, 44793001]
# EMPA-REG's HbA1c set adds 3005446 'Hemoglobin A1/Hemoglobin.total' -- HbA1, not HbA1c.
HBA1_TOTAL = 3005446
# BMI set, CAROLINA codeset 31.
BMI = [3038553, 36304833, 40762636]
# Glucose set, CAROLINA codeset 41 -- not allowlisted.
GLUCOSE = [3000483, 3004378, 3004676, 44816672]

PERCENT = [{"CONCEPT_ID": 8554, "CONCEPT_CODE": "%", "CONCEPT_NAME": "percent"}]
KG_M2 = [{"CONCEPT_ID": 9531, "CONCEPT_CODE": "kg/m2", "CONCEPT_NAME": "kilogram per square meter"}]
MG_DL = [{"CONCEPT_ID": 8840, "CONCEPT_CODE": "mg/dL", "CONCEPT_NAME": "milligram per deciliter"}]

PRESENCE = {"Type": 2, "Count": 1}
ABSENCE = {"Type": 0, "Count": 0}


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


def cohort(codeset_id: int, members: list[int], *, value: dict, unit: list | None,
           occurrence: dict = PRESENCE, group_type: str = "ALL") -> dict:
    measurement: dict = {"CodesetId": codeset_id, "ValueAsNumber": value}
    if unit is not None:
        measurement["Unit"] = deepcopy(unit)
    return {
        "ConceptSets": [
            concept_set(1, "linagliptin", [40239216]),
            concept_set(codeset_id, "analyte", members),
        ],
        "PrimaryCriteria": {"CriteriaList": [{"DrugExposure": {"CodesetId": 1}}]},
        "InclusionRules": [
            {
                "name": "rule",
                "expression": {
                    "Type": group_type,
                    "CriteriaList": [
                        {
                            "Criteria": {"Measurement": measurement},
                            "StartWindow": {
                                "Start": {"Days": 180, "Coeff": -1},
                                "End": {"Days": 0, "Coeff": 1},
                            },
                            "Occurrence": dict(occurrence),
                        }
                    ],
                    "DemographicCriteriaList": [],
                    "Groups": [],
                },
            }
        ],
    }


def measurement_of(base: dict) -> dict:
    return base["InclusionRules"][0]["expression"]["CriteriaList"][0]["Criteria"]["Measurement"]


# --------------------------------------------------------------------------
# the repair
# --------------------------------------------------------------------------

def test_should_remove_unit_when_presence_hba1c_criterion_bounds_a_range():
    """CAROLINA codeset 5: HbA1c bt 6.5..8.5 %. No IFCC (mmol/mol, >= 15), fraction
    (<= 0.25) or mass/volume (<= 4 g/dL) value can land in [6.5, 8.5], so an
    alternative-unit record can only be missed."""
    base = cohort(5, HBA1C, value={"Value": 6.5, "Op": "bt", "Extent": 8.5}, unit=PERCENT)
    applied = repair_presence_unit_filters(base, vocabulary(*HBA1C))
    assert "Unit" not in measurement_of(base)
    assert measurement_of(base)["ValueAsNumber"] == {"Value": 6.5, "Op": "bt", "Extent": 8.5}
    assert [r.analyte for r in applied] == ["HbA1c"]


def test_should_remove_unit_when_presence_bmi_criterion_bounds_at_most_45():
    """CAROLINA codeset 31: BMI lte 45 kg/m2 -- the rule that took Ajou 20,058 -> 0."""
    base = cohort(31, BMI, value={"Value": 45.0, "Op": "lte"}, unit=KG_M2)
    applied = repair_presence_unit_filters(base, vocabulary(*BMI))
    assert "Unit" not in measurement_of(base)
    assert [r.analyte for r in applied] == ["BMI"]


def test_should_keep_unit_when_criterion_is_an_exclusion():
    """A unit miss on an exclusion only lets a rule pass silently; it never zeroes a
    cohort, so the user kept those units."""
    base = cohort(5, HBA1C, value={"Value": 6.5, "Op": "bt", "Extent": 8.5},
                  unit=PERCENT, occurrence=ABSENCE)
    before = deepcopy(base)
    assert repair_presence_unit_filters(base, vocabulary(*HBA1C)) == []
    assert base == before


def test_should_keep_unit_when_analyte_is_not_allowlisted():
    base = cohort(41, GLUCOSE, value={"Value": 240.0, "Op": "gt"}, unit=MG_DL)
    before = deepcopy(base)
    assert repair_presence_unit_filters(base, vocabulary(*GLUCOSE)) == []
    assert base == before


def test_should_keep_unit_and_warn_when_concept_set_mixes_analytes(caplog):
    """HbA1c and BMI concepts in one set: no single scale table covers every member."""
    members = HBA1C + BMI
    base = cohort(5, members, value={"Value": 6.5, "Op": "bt", "Extent": 8.5}, unit=PERCENT)
    before = deepcopy(base)
    with caplog.at_level(logging.WARNING):
        assert repair_presence_unit_filters(base, vocabulary(*members)) == []
    assert base == before
    assert "mixed" in caplog.text


def test_should_keep_unit_and_warn_when_set_holds_an_unlisted_member(caplog):
    """EMPA-REG codeset 3 carries 3005446 HbA1 beside the HbA1c concepts."""
    members = HBA1C + [HBA1_TOTAL]
    base = cohort(3, members, value={"Value": 7.0, "Op": "bt", "Extent": 10.0}, unit=PERCENT)
    before = deepcopy(base)
    with caplog.at_level(logging.WARNING):
        assert repair_presence_unit_filters(base, vocabulary(*members)) == []
    assert base == before
    assert str(HBA1_TOTAL) in caplog.text


def test_should_keep_unit_when_bound_can_wrongly_include():
    """CARMELINA codeset 8: HbA1c gte 6.5 alone. Every IFCC value (>= 15 mmol/mol)
    passes a bare >= 6.5, including a patient at 20 mmol/mol (4.0 %)."""
    base = cohort(8, HBA1C, value={"Value": 6.5, "Op": "gte"}, unit=PERCENT, group_type="ANY")
    before = deepcopy(base)
    assert repair_presence_unit_filters(base, vocabulary(*HBA1C)) == []
    assert base == before


# --------------------------------------------------------------------------
# the lint reads the same table
# --------------------------------------------------------------------------

def test_should_not_flag_unitless_bound_when_presence_criterion_is_allowlisted():
    base = cohort(31, BMI, value={"Value": 45.0, "Op": "lte"}, unit=None)
    assert unitless_value_bound_criteria(base) == []


def test_should_flag_unitless_bound_when_allowlisted_analyte_is_an_exclusion():
    base = cohort(31, BMI, value={"Value": 45.0, "Op": "lte"}, unit=None, occurrence=ABSENCE)
    assert len(unitless_value_bound_criteria(base)) == 1


def test_should_flag_unitless_bound_when_presence_analyte_is_not_allowlisted():
    base = cohort(41, GLUCOSE, value={"Value": 240.0, "Op": "gt"}, unit=None)
    assert len(unitless_value_bound_criteria(base)) == 1


def test_should_flag_unitless_bound_when_allowlisted_bound_can_wrongly_include():
    base = cohort(8, HBA1C, value={"Value": 6.5, "Op": "gte"}, unit=None)
    assert len(unitless_value_bound_criteria(base)) == 1
