"""The confusable-member repair on concept sets read by CONVERTED value-range absences.

THE MOTIVATING EVENT. b1e18e6 restates a lab-range inclusion ("HbA1c 7.0..10%") as the
absence of out-of-range results ("no HbA1c < 7.0, no HbA1c > 10.0"). On the 2026-10-08 dry
rebuild (``output/site_gap/2026-10-08_dryrun/DELIVERY/empa-reg_treatment.circe.json``)
EMPA-REG codesets 3 and 4 'Glycosylated haemoglobin (HbA1c)' kept ``3005446 Hemoglobin
A1/Hemoglobin.total in Blood`` -- HbA1, which reads higher than HbA1c -- because the only
readers left were absences and the repair accepted presence readers only. On "no HbA1c >
10", an HbA1 result over 10 excludes a patient whose HbA1c may be in range. The first test
is rule #6 and its ``_valueRangeConversions`` records as that file carries them.

THE CONTROLS. A plain absence -- one no conversion record covers -- still declines, as does
an absence whose bound or unit is not what the conversion emitted, and one reached through a
non-ALL group. No database: every condition is read off the expression, and what each
member measures is its LOINC ``Has component`` from the real synthea23m rows in
``tests/fixtures/p3_structural_rows.json`` (RFC-016 §4, A28).
"""
from __future__ import annotations

import json
import logging
import sys
from copy import deepcopy
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.services.confusable_member_repair import repair_confusable_members  # noqa: E402
from src.utils.circe_lint import (  # noqa: E402
    VALUE_RANGE_CONVERSIONS_KEY,
)
from src.utils.circe_lint import confusable_concept_sets as _confusable_concept_sets  # noqa: E402

#: LOINC concept id -> its 'Has component' concept ids (synthea23m).
COMPONENTS: dict[int, set[int]] = {}
for _cid, _component in json.loads(
    (REPO_ROOT / "tests" / "fixtures" / "p3_structural_rows.json").read_text()
)["vocabulary_loinc_components"]["rows"]:
    COMPONENTS.setdefault(_cid, set()).add(_component)


def confusable_concept_sets(expression: dict) -> list[str]:
    return _confusable_concept_sets(expression, COMPONENTS)
from src.utils.presence_unit_allowlist import iter_codeset_readers  # noqa: E402

#: EMPA-REG codesets 3/4 on the dry rebuild, after the conversion pruned 3034639, 4197971 and
#: 44793001 as not measured in '%'.
HBA1C_VERIFIED = [3004410, 3007263]
HBA1_TOTAL = 3005446
RULE_NAME = (
    "HbA1c for patients on background therapy (>=7.0% and <=10%) + HbA1c for drug naive "
    "patients (>=7.0% and <=9.0%)"
)
ABSENCE = {"Type": 0, "Count": 0}
PRESENCE = {"Type": 2, "Count": 1}


def concept_set(set_id: int, concept_ids: list[int]) -> dict:
    return {
        "id": set_id,
        "name": "Glycosylated haemoglobin (HbA1c)",
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


def measurement(codeset_id: int, value: dict, occurrence: dict, unit: list | None = None) -> dict:
    payload: dict = {"CodesetId": codeset_id, "ValueAsNumber": dict(value)}
    if unit is not None:
        payload["Unit"] = unit
    return {
        "Criteria": {"Measurement": payload},
        "StartWindow": {"Start": {"Days": 180, "Coeff": -1}, "End": {"Days": 0, "Coeff": 1}},
        "RestrictVisit": False,
        "IgnoreObservationPeriod": False,
        "Occurrence": dict(occurrence),
    }


def converted_group(codeset_id: int, occurrence: dict = ABSENCE) -> dict:
    return {
        "Type": "ALL",
        "CriteriaList": [
            measurement(codeset_id, {"Value": 7.0, "Op": "lt"}, occurrence),
            measurement(codeset_id, {"Value": 10.0, "Op": "gt"}, occurrence),
        ],
        "DemographicCriteriaList": [],
        "Groups": [],
    }


def conversion_record(codeset_id: int, presence: dict) -> dict:
    """The record b1e18e6 wrote for each branch, verbatim in shape."""
    return {
        "rule": RULE_NAME,
        "codesetId": codeset_id,
        "group": "ANY",
        "status": "converted",
        "reason": None,
        "statedUnit": {"CONCEPT_ID": 8554, "CONCEPT_CODE": "%"},
        "presence": presence,
        "property": "Mass fraction",
        "absences": [{"Value": 7.0, "Op": "lt"}, {"Value": 10.0, "Op": "gt"}],
        "removedMembers": [],
    }


def empa_reg_dry_rebuild() -> dict:
    """Rule #6 of the dry-rebuild EMPA-REG file: two ALL groups of two unitless absences."""
    return {
        "ConceptSets": [
            concept_set(3, HBA1C_VERIFIED + [HBA1_TOTAL]),
            concept_set(4, HBA1C_VERIFIED + [HBA1_TOTAL]),
        ],
        "PrimaryCriteria": {"CriteriaList": [{"DrugExposure": {"CodesetId": 1}}]},
        "InclusionRules": [
            {
                "name": RULE_NAME,
                "expression": {
                    "Type": "ALL",
                    "CriteriaList": [],
                    "DemographicCriteriaList": [],
                    "Groups": [converted_group(3), converted_group(4)],
                },
            }
        ],
        VALUE_RANGE_CONVERSIONS_KEY: [
            conversion_record(3, {"Value": 7.0, "Op": "bt", "Extent": 10.0}),
            conversion_record(4, {"Value": 7.0, "Op": "bt", "Extent": 9.0}),
        ],
    }


def members_of(expression: dict, codeset_id: int) -> list[int]:
    return [
        item["concept"]["CONCEPT_ID"]
        for cs in expression["ConceptSets"] if cs["id"] == codeset_id
        for item in cs["expression"]["items"]
    ]


# ---------------------------------------------------------------------------
# the motivating event
# ---------------------------------------------------------------------------

def test_should_remove_hba1_total_when_only_converted_value_range_absences_read_the_set():
    expression = empa_reg_dry_rebuild()

    applied = repair_confusable_members(expression, COMPONENTS)

    assert sorted(r.codeset_id for r in applied) == [3, 4]
    assert all(r.removed_concept_ids == [HBA1_TOTAL] for r in applied)
    assert members_of(expression, 3) == HBA1C_VERIFIED
    assert members_of(expression, 4) == HBA1C_VERIFIED
    assert confusable_concept_sets(expression) == [], "gate check 'confusable concept sets'"


def test_should_touch_nothing_but_the_member_when_it_repairs_a_converted_set():
    expression = empa_reg_dry_rebuild()
    expected = deepcopy(expression)
    for cs in expected["ConceptSets"]:
        cs["expression"]["items"] = [
            i for i in cs["expression"]["items"] if i["concept"]["CONCEPT_ID"] != HBA1_TOTAL
        ]

    repair_confusable_members(expression, COMPONENTS)

    assert expression == expected


def test_should_mark_a_converted_absence_reader_as_such_when_the_record_covers_it():
    readers = [r for r in iter_codeset_readers(empa_reg_dry_rebuild()) if r.codeset_id in (3, 4)]

    assert len(readers) == 4
    assert all(r.is_absence and not r.is_presence for r in readers)


# ---------------------------------------------------------------------------
# controls: absences the repair must still decline
# ---------------------------------------------------------------------------

def test_should_decline_when_a_plain_absence_that_no_conversion_record_covers_reads_the_set(caplog):
    """The chosen behaviour for a plain exclusion: decline, and leave the lint firing."""
    expression = empa_reg_dry_rebuild()
    del expression[VALUE_RANGE_CONVERSIONS_KEY]
    before = deepcopy(expression)

    with caplog.at_level(logging.WARNING):
        applied = repair_confusable_members(expression, COMPONENTS)

    assert applied == []
    assert expression == before
    assert "confusable-member repair declines codeset 3" in caplog.text
    assert "no value-range conversion record" in caplog.text
    assert len(confusable_concept_sets(expression)) == 2


def test_should_decline_when_the_conversion_was_declined_rather_than_applied():
    expression = empa_reg_dry_rebuild()
    for record in expression[VALUE_RANGE_CONVERSIONS_KEY]:
        record["status"] = "declined"
    before = deepcopy(expression)

    assert repair_confusable_members(expression, COMPONENTS) == []
    assert expression == before


def test_should_decline_when_the_absence_bound_is_not_one_the_conversion_emitted():
    expression = empa_reg_dry_rebuild()
    first = expression["InclusionRules"][0]["expression"]["Groups"][0]["CriteriaList"][0]
    first["Criteria"]["Measurement"]["ValueAsNumber"] = {"Value": 6.5, "Op": "lt"}
    before = deepcopy(expression)

    applied = repair_confusable_members(expression, COMPONENTS)

    assert [r.codeset_id for r in applied] == [4], "codeset 4's readers are still the record's"
    assert members_of(expression, 3) == members_of(before, 3)


def test_should_decline_when_the_absence_carries_a_unit_the_conversion_never_emits():
    expression = empa_reg_dry_rebuild()
    first = expression["InclusionRules"][0]["expression"]["Groups"][0]["CriteriaList"][0]
    first["Criteria"]["Measurement"]["Unit"] = [{"CONCEPT_ID": 8554, "CONCEPT_CODE": "%"}]

    applied = repair_confusable_members(expression, COMPONENTS)

    assert [r.codeset_id for r in applied] == [4]
    assert HBA1_TOTAL in members_of(expression, 3)


def test_should_decline_when_the_absence_is_reached_through_a_non_all_group():
    expression = empa_reg_dry_rebuild()
    expression["InclusionRules"][0]["expression"]["Groups"][0]["Type"] = "ANY"

    applied = repair_confusable_members(expression, COMPONENTS)

    assert [r.codeset_id for r in applied] == [4]
    assert HBA1_TOTAL in members_of(expression, 3)
