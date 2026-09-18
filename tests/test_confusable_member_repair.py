"""Unit tests for the export-time removal of a confusable concept-set member.

THE REVERSED DECISION. ``src.utils.circe_lint.CONFUSABLE_ANALYTES`` used to argue that
nothing should remove the member, because doing so changes which patients the cohort
SELECTS. The user reversed that under one safety condition: the removal is applied only
where every criterion reading the set is a PRESENCE criterion, so a smaller set can only
select fewer patients. Where an absence criterion reads it, the direction flips and the
repair declines -- that is what ``should_decline_when_an_absence_criterion_reads_the_set``
gates, and it is the whole basis for the reversal.

THE MOTIVATING EVENT, not a fixture. EMPA-REG codeset 3 'Glycosylated haemoglobin
(HbA1c)' holds ``3005446 'Hemoglobin A1/Hemoglobin.total in Blood'``. That made
``presence_unit_repair`` classify the set as ``unlisted`` and keep the ``Unit [8554]``
filter on rule #4, and the hospital's Atlas inclusion report measured that rule at 0
people. The first test below is that set, that bound and that criterion shape, copied
from ``output/site_gap/2026-09-18_verify3/DELIVERY/empa-reg_treatment.circe.json``.

No vocabulary, no LLM, no database: every condition is readable from the expression.
"""
from __future__ import annotations

import logging
import sys
from copy import deepcopy
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.services.confusable_member_repair import (  # noqa: E402
    repair_confusable_members,
)
from src.utils.circe_lint import (  # noqa: E402
    confusable_concept_sets,
    iter_confusable_members,
)

# ---------------------------------------------------------------------------
# concept ids, copied from the delivered files
# ---------------------------------------------------------------------------

#: EMPA-REG codeset 3/4 'Glycosylated haemoglobin (HbA1c)', minus the confusable.
HBA1C = [3004410, 3007263, 3034639, 4197971, 44793001]
#: ``Hemoglobin A1/Hemoglobin.total in Blood`` -- HbA1, which includes A1a and A1b.
HBA1_TOTAL = 3005446

#: CAROLINA codeset 30 'LDL cholesterol' seeds, minus the confusable.
LDL = [3001308, 3009966, 3028288, 3028437, 3038988, 4041556]
#: ``Cholesterol in HDL [Mass/volume] in Serum or Plasma`` -- a different lipoprotein.
HDL = 3007070
#: ``Cholesterol in LDL [Units/volume] ... by Electrophoresis`` -- LDL, so NOT in the
#: confusable table, and deliberately still unlisted for the unit repair.
LDL_UNITS_PER_VOLUME = 3035009

#: CAROLINA codeset 28 'Systolic blood pressure' seeds, minus the confusable.
SYSTOLIC = [3004249, 3035856]
#: ``Blood pressure systolic and diastolic`` -- a panel over two quantities.
BP_PANEL = 40758413

PERCENT = [{"CONCEPT_ID": 8554, "CONCEPT_CODE": "%", "CONCEPT_NAME": "percent"}]
PRESENCE = {"Type": 2, "Count": 1}
ABSENCE = {"Type": 0, "Count": 0}


def concept_set(set_id: int, name: str, concept_ids: list[int], *,
                excluded: list[int] | None = None) -> dict:
    excluded = excluded or []
    return {
        "id": set_id,
        "name": name,
        "expression": {
            "items": [
                {
                    "concept": {"CONCEPT_ID": cid, "CONCEPT_NAME": f"concept {cid}"},
                    "includeDescendants": True,
                    "includeMapped": False,
                    "isExcluded": cid in excluded,
                }
                for cid in concept_ids
            ]
        },
    }


def empa_reg_rule_4(codeset_id: int, occurrence: dict) -> dict:
    """Rule #4 of EMPA-REG verbatim in shape: ANY over two ALL groups, each one
    Measurement with ``bt`` bounds and the ``percent`` Unit filter."""
    return {
        "name": (
            "HbA1c for patients on background therapy (>=7.0% and <=10%) + HbA1c for "
            "drug naive patients (>=7.0% and <=9.0%)"
        ),
        "expression": {
            "Type": "ANY",
            "CriteriaList": [],
            "DemographicCriteriaList": [],
            "Groups": [
                {
                    "Type": "ALL",
                    "CriteriaList": [
                        {
                            "Criteria": {
                                "Measurement": {
                                    "CodesetId": codeset_id,
                                    "ValueAsNumber": {
                                        "Value": 7.0, "Op": "bt", "Extent": 10.0,
                                    },
                                    "Unit": deepcopy(PERCENT),
                                }
                            },
                            "StartWindow": {
                                "Start": {"Days": 180, "Coeff": -1},
                                "End": {"Days": 0, "Coeff": 1},
                            },
                            "RestrictVisit": False,
                            "IgnoreObservationPeriod": False,
                            "Occurrence": dict(occurrence),
                        }
                    ],
                    "DemographicCriteriaList": [],
                    "Groups": [],
                }
            ],
        },
    }


def cohort(concept_sets: list[dict], rules: list[dict]) -> dict:
    return {
        "ConceptSets": [concept_set(1, "empagliflozin", [1594973])] + concept_sets,
        "PrimaryCriteria": {"CriteriaList": [{"DrugExposure": {"CodesetId": 1}}]},
        "InclusionRules": rules,
    }


def members_of(expression: dict, codeset_id: int) -> list[int]:
    return [
        item["concept"]["CONCEPT_ID"]
        for cs in expression["ConceptSets"] if cs["id"] == codeset_id
        for item in cs["expression"]["items"]
    ]


# ---------------------------------------------------------------------------
# 1. the real EMPA-REG case
# ---------------------------------------------------------------------------

def test_should_remove_hba1_total_when_the_hba1c_set_is_read_only_by_a_presence_criterion():
    """The motivating event: rule #4 of EMPA-REG, measured at 0 people at the site."""
    expression = cohort(
        [concept_set(3, "Glycosylated haemoglobin (HbA1c)", HBA1C + [HBA1_TOTAL])],
        [empa_reg_rule_4(3, PRESENCE)],
    )
    applied = repair_confusable_members(expression)

    assert len(applied) == 1
    assert applied[0].codeset_id == 3
    assert applied[0].analyte == "HbA1c"
    assert applied[0].removed_concept_ids == [HBA1_TOTAL]
    assert members_of(expression, 3) == HBA1C
    assert confusable_concept_sets(expression) == [], (
        "the lint must go quiet on the repaired expression"
    )


# ---------------------------------------------------------------------------
# 2. the safety condition
# ---------------------------------------------------------------------------

def test_should_decline_when_an_absence_criterion_reads_the_set(caplog):
    """Condition 4. A smaller set makes an ABSENCE easier to satisfy, so the direction
    flips from 'can only miss patients' to 'can wrongly include patients'."""
    expression = cohort(
        [concept_set(3, "Glycosylated haemoglobin (HbA1c)", HBA1C + [HBA1_TOTAL])],
        [empa_reg_rule_4(3, ABSENCE)],
    )
    before = deepcopy(expression)

    with caplog.at_level(logging.WARNING):
        applied = repair_confusable_members(expression)

    assert applied == []
    assert expression == before, "the member must stay"
    assert HBA1_TOTAL in members_of(expression, 3)
    text = caplog.text
    assert "confusable-member repair declines codeset 3" in text
    assert "not provably a presence criterion" in text
    assert "can wrongly include patients" in text
    assert "rule #1" in text


# ---------------------------------------------------------------------------
# 3-5. the remaining conditions
# ---------------------------------------------------------------------------

def test_should_leave_the_set_alone_when_the_name_states_both_analytes():
    """Condition 1, borrowed from the lint: 'systolic and diastolic' names the panel."""
    expression = cohort(
        [concept_set(28, "Systolic and diastolic blood pressure", SYSTOLIC + [BP_PANEL])],
        [empa_reg_rule_4(28, PRESENCE)],
    )
    before = deepcopy(expression)
    assert repair_confusable_members(expression) == []
    assert expression == before


def test_should_never_remove_ldl_units_per_volume_because_it_is_not_in_the_table():
    """Condition 2. 3035009 IS LDL -- deliberately unmodelled, never a confusable --
    so the repair removes HDL beside it and leaves 3035009 in place."""
    expression = cohort(
        [concept_set(30, "LDL cholesterol", LDL + [LDL_UNITS_PER_VOLUME, HDL])],
        [empa_reg_rule_4(30, PRESENCE)],
    )
    applied = repair_confusable_members(expression)

    assert [r.removed_concept_ids for r in applied] == [[HDL]]
    assert LDL_UNITS_PER_VOLUME in members_of(expression, 30)
    assert HDL not in members_of(expression, 30)


def test_should_decline_when_removing_the_member_would_empty_the_set(caplog):
    """Condition 3. A set whose ONLY included member is the confusable has nothing to
    fall back to, and an empty concept set matches every patient in Circe."""
    expression = cohort(
        [concept_set(3, "Glycosylated haemoglobin (HbA1c)", [HBA1_TOTAL])],
        [empa_reg_rule_4(3, PRESENCE)],
    )
    before = deepcopy(expression)

    with caplog.at_level(logging.WARNING):
        assert repair_confusable_members(expression) == []

    assert expression == before
    assert "no included member would remain" in caplog.text


def test_should_decline_when_the_set_carries_an_excluded_item(caplog):
    """Condition 5. An exclusion SUBTRACTS, so the direction inverts there too -- the
    same grounds ``entry_exclusion_repair`` declines an entry set holding one on."""
    expression = cohort(
        [concept_set(30, "LDL cholesterol", LDL + [HDL, LDL_UNITS_PER_VOLUME],
                     excluded=[LDL_UNITS_PER_VOLUME])],
        [empa_reg_rule_4(30, PRESENCE)],
    )
    before = deepcopy(expression)

    with caplog.at_level(logging.WARNING):
        assert repair_confusable_members(expression) == []

    assert expression == before
    assert HDL in members_of(expression, 30)
    assert "isExcluded" in caplog.text


# ---------------------------------------------------------------------------
# 6. the predicate really is shared
# ---------------------------------------------------------------------------

def test_should_agree_with_the_lint_on_which_sets_are_confusable():
    """Assert the agreement on one input rather than restating the table, so the gate
    and the repair cannot drift apart. Four sets: two confusable, two not."""
    expression = cohort(
        [
            concept_set(3, "Glycosylated haemoglobin (HbA1c)", HBA1C + [HBA1_TOTAL]),
            concept_set(5, "Glycosylated haemoglobin (HbA1c)", HBA1C),
            concept_set(28, "Systolic and diastolic blood pressure", SYSTOLIC + [BP_PANEL]),
            concept_set(30, "LDL cholesterol", LDL + [HDL]),
        ],
        [empa_reg_rule_4(3, PRESENCE)],
    )

    from_iterator = {
        int(cs["id"]) for cs, _entry, _held in iter_confusable_members(expression)
    }
    findings = confusable_concept_sets(expression)
    from_lint = {int(f.split()[1]) for f in findings}

    assert from_iterator == from_lint == {3, 30}
