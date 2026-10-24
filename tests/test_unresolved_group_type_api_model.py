"""A group the IR declared no ``group_type`` for survives the API model as ``groupType: None``.

Measured on P12 (``output/site_gap/2026-10-24_p12_final``, both arms, studies 1/3/8):
``run_generate_from_nct`` died at ``TTEStudy.model_validate`` with "groupType: Input should be a
valid string" on every row of such a group. ec28632 made None the producer's deliberate
"unresolved" state (``_criteria_from_ir``), which ``unresolved_group_relations`` reads, but
``Criterion.groupType`` still accepted only ``str``. Writing ALL instead would rebuild the P11
defect (LEADER's "≥1 of the following" AND-ed), so the API model is what changes.

The group below is verbatim from the P12 MAIN study-1 cached Agent 1 IR
(``arm_main/trials/s1/agent1_ir/NCT01179048_vllm_google_gemma-4-E4B-it_bf91f12afcd74635.json``,
sha256 9b0da286b5dceac7f5d7eeb82a12d420a9a2d13ec152dc394fb69ea42a2aa93a,
``target.inclusion_rules[4]``; fields not used by the parser omitted).
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from src.agents.agent1.parser import LogicDecomposer
from src.api.models.tte import TTEStudy
from src.services.criterion_annotation import unresolved_group_relations
from src.services.tte_service import TTEService

_LEADER_INCLUSION_5 = {
    "name": "No prior cardiovascular disease cohort criteria",
    "domain": "Demographics",
    "source_text": (
        "5. No Prior cardiovascular disease group: Age ≥60 y and ≥1 of the following criteria:"
    ),
    "group_type": None,
    "logic_type": "PRESENCE",
    "sub_criteria": [
        {"name": "Microalbuminuria or proteinuria", "domain": "Condition",
         "source_text": "5.1 Microalbuminuria or proteinuria", "group_type": None},
        {"name": "Hypertension and LVH", "domain": "Condition",
         "source_text": "5.2 Hypertension and left ventricular hypertrophy by ECG or imaging",
         "group_type": None},
        {"name": "LV dysfunction", "domain": "Condition",
         "source_text": "5.3 Left ventricular systolic or diastolic dysfunction by imaging",
         "group_type": None},
        {"name": "Ankle-brachial index", "domain": "Measurement",
         "source_text": "5.4 Ankle-brachial index <0.9", "group_type": None},
    ],
}


def _rows(rule: dict) -> list[dict]:
    parser = LogicDecomposer.__new__(LogicDecomposer)
    service = TTEService.__new__(TTEService)
    return service._criteria_from_ir([parser._build_criteria(deepcopy(rule))])


def _through_api_model(rows: list[dict]) -> list[dict]:
    study = {"eligibility": {"inclusionCriteria": rows}}
    return TTEStudy.model_validate(study).model_dump()["eligibility"]["inclusionCriteria"]


def test_should_keep_group_type_none_when_the_ir_declared_none():
    rows = _rows(_LEADER_INCLUSION_5)
    assert [r["groupType"] for r in rows] == [None] * 5

    dumped = _through_api_model(rows)

    assert [r["groupType"] for r in dumped] == [None] * 5
    # The build still sees the group as unresolved after the round trip.
    assert set(unresolved_group_relations(dumped)) == {str(r["id"]) for r in rows}


@pytest.mark.parametrize("declared", ["ALL", "ANY"])
def test_should_keep_a_declared_group_type_when_validated(declared):
    rule = {**deepcopy(_LEADER_INCLUSION_5), "group_type": declared}
    dumped = _through_api_model(_rows(rule))
    assert [r["groupType"] for r in dumped] == [declared] * 5
    assert unresolved_group_relations(dumped) == {}


def test_should_default_to_all_when_a_row_carries_no_group_type_key():
    """A store row written before the key was kept still reads as declared ALL."""
    dumped = _through_api_model([{"id": 1, "description": "x"}])
    assert dumped[0]["groupType"] == "ALL"


def test_should_keep_parent_group_id_of_a_nested_unresolved_group():
    outer = {
        "name": "outer", "domain": "Condition", "group_type": "ANY",
        "sub_criteria": [{"name": "leaf", "domain": "Condition"}, deepcopy(_LEADER_INCLUSION_5)],
    }
    rows = _rows(outer)
    dumped = _through_api_model(rows)

    outer_id = rows[0]["groupId"]
    inner = [r for r in dumped if r["groupId"] != outer_id]
    assert len(inner) == 5
    assert {r["groupType"] for r in inner} == {None}
    assert {r["parentGroupId"] for r in inner} == {outer_id}
    assert [r["groupType"] for r in dumped if r["groupId"] == outer_id] == ["ANY", "ANY"]
