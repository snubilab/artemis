"""Restated duplicates are decided by structured fields, never by a description stem (RFC-016 E6).

Two rows collapse when ``(domain, sourceText, window, valueConstraint, logicType)`` are equal
AND they sit in the same place in the rule tree: both top-level, or in groups of one type whose
non-label members carry the same keys (one group, or a group and its restatement). Group
labels, rows with no ``sourceText`` and restatable demographics never collapse here.

Real rows come from two verbatim store extracts:

* ``tests/fixtures/p5_candidate_rows.json`` -- the 2026-10-12_prompt_f2 candidate, where the
  description-stem test produced 16 ``restated-distinctness-duplicate`` skips per arm;
* ``tests/fixtures/infra_004_store_criteria.json`` -- the SPEC-INFRA-004 reference store.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from src.services.restated_distinctness import (
    COLLAPSE_REASON,
    SURVIVOR_RULE,
    WITHHELD_CONTEXT_DISTINCT,
    collapse_all_restated_criteria,
    collapse_restated_criteria,
    distinctness_key,
)

FIXTURES = Path(__file__).parent / "fixtures"
CANDIDATE = {
    s["id"]: s for s in json.loads((FIXTURES / "p5_candidate_rows.json").read_text())["studies"]
}
REFERENCE = {
    s.get("nctId"): s
    for s in json.loads((FIXTURES / "infra_004_store_criteria.json").read_text())["studies"]
    if s.get("nctId")
}
NAMES = {1: "LEADER", 2: "PLATO", 3: "ARISTOTLE", 8: "EMPA-REG", 9: "CARMELINA", 10: "CAROLINA"}


def _candidate_drops() -> set[tuple[str, str, int]]:
    drops: set[tuple[str, str, int]] = set()
    for sid, study in CANDIDATE.items():
        keys, _, _ = collapse_all_restated_criteria(
            inclusion_criteria=study["eligibility"]["inclusionCriteria"],
            exclusion_criteria=study["eligibility"]["exclusionCriteria"],
        )
        drops |= {(NAMES[sid], role, int(cid)) for role, cid in keys}
    return drops


#: Dropped by the description-stem test on the candidate (16 skips per arm, both arms alike).
STEM_DROPS = {
    ("LEADER", "inclusion", 18), ("LEADER", "inclusion", 19), ("LEADER", "inclusion", 36),
    ("LEADER", "inclusion", 37), ("LEADER", "inclusion", 40), ("LEADER", "exclusion", 29),
    ("ARISTOTLE", "exclusion", 19), ("ARISTOTLE", "exclusion", 20),
    ("EMPA-REG", "exclusion", 44), ("EMPA-REG", "exclusion", 45),
    ("CARMELINA", "exclusion", 9), ("CARMELINA", "exclusion", 19),
    ("CARMELINA", "exclusion", 20), ("CARMELINA", "exclusion", 21),
    ("CARMELINA", "exclusion", 29), ("CAROLINA", "exclusion", 20),
}

#: The structured test's drops on the same rows.
STRUCTURED_DROPS = {
    # LEADER group 9a021f8e restates group 4a712697 member for member (#13-#15); the stem
    # test missed #17 ("naïve" against "naive").
    ("LEADER", "inclusion", 17), ("LEADER", "inclusion", 18), ("LEADER", "inclusion", 19),
    # Two members of one ANY group, both mapped from "CHD".
    ("LEADER", "inclusion", 28),
    # Moderate and Severe Mitral Stenosis share one group, entity and window.
    ("ARISTOTLE", "exclusion", 10),
    ("ARISTOTLE", "exclusion", 19), ("ARISTOTLE", "exclusion", 20),
    ("EMPA-REG", "exclusion", 44), ("EMPA-REG", "exclusion", 45),
    ("CARMELINA", "exclusion", 19), ("CARMELINA", "exclusion", 20),
    ("CARMELINA", "exclusion", 21),
    # Same group, same entity ("Hypersensitivity" / "Allergy") and window.
    ("CARMELINA", "exclusion", 31), ("CARMELINA", "exclusion", 32),
    # CAROLINA's HbA1c subgroup rows: in each of two groups every member carries the same
    # entity, window and value constraint.
    ("CAROLINA", "inclusion", 7), ("CAROLINA", "inclusion", 8),
    *{("CAROLINA", "inclusion", i) for i in range(11, 20)},
}


class TestTheCandidateRows:
    def test_should_drop_exactly_the_structured_duplicates_on_the_candidate(self) -> None:
        assert _candidate_drops() == STRUCTURED_DROPS
        assert len(STRUCTURED_DROPS) == 25

    def test_should_keep_nine_of_the_sixteen_stem_drops(self) -> None:
        assert STEM_DROPS & STRUCTURED_DROPS == {
            ("LEADER", "inclusion", 18), ("LEADER", "inclusion", 19),
            ("ARISTOTLE", "exclusion", 19), ("ARISTOTLE", "exclusion", 20),
            ("EMPA-REG", "exclusion", 44), ("EMPA-REG", "exclusion", 45),
            ("CARMELINA", "exclusion", 19), ("CARMELINA", "exclusion", 20),
            ("CARMELINA", "exclusion", 21),
        }

    @pytest.mark.parametrize(
        "name,role,cid,survivor",
        [("LEADER", "exclusion", 29, 28), ("CARMELINA", "exclusion", 29, 28),
         ("CAROLINA", "exclusion", 20, 19)],
    )
    def test_should_not_fold_a_member_onto_its_group_label(self, name, role, cid, survivor) -> None:
        """The stem test folded these onto their own label, which mints no concept set."""
        sid = next(k for k, v in NAMES.items() if v == name)
        label = next(
            c for c in CANDIDATE[sid]["eligibility"][f"{role}Criteria"] if c["id"] == survivor
        )
        assert label["isGroupLabel"] is True
        assert (name, role, cid) not in _candidate_drops()

    @pytest.mark.parametrize(
        "name,role,cid",
        [("LEADER", "inclusion", 36), ("LEADER", "inclusion", 37), ("LEADER", "inclusion", 40),
         ("CARMELINA", "exclusion", 9)],
    )
    def test_should_not_move_a_member_into_a_different_group(self, name, role, cid) -> None:
        """The stem test dropped each onto a row in a group with different members."""
        assert (name, role, cid) not in _candidate_drops()
        sid = next(k for k, v in NAMES.items() if v == name)
        _, _, intact = collapse_restated_criteria(
            CANDIDATE[sid]["eligibility"][f"{role}Criteria"], role=role
        )
        reported = {i for g in intact for i in g["criterionIds"]}
        assert cid in reported
        assert all(g["reason"] == WITHHELD_CONTEXT_DISTINCT for g in intact)


# --------------------------------------------------------------------------- #
# Properties, on constructed rows
# --------------------------------------------------------------------------- #


def _row(cid: Any, source: str = "Heart failure", **fields: Any) -> dict[str, Any]:
    row = {
        "id": cid, "domain": "Condition", "description": f"row {cid}", "sourceText": source,
        "valueConstraint": None, "window": {"start": -9999, "end": 0}, "logicType": "ABSENCE",
        "groupId": None, "groupType": "ALL", "parentGroupId": None, "isGroupLabel": False,
    }
    row.update(fields)
    return row


def _dropped(rows: list[dict[str, Any]], role: str = "exclusion") -> set[str]:
    drops, _, _ = collapse_restated_criteria(rows, role=role)
    return {cid for _, cid in drops}


class TestTheKey:
    @pytest.mark.parametrize(
        "field,value",
        [("domain", "Measurement"), ("sourceText", "Hypertension"),
         ("window", {"start": -180, "end": 0}), ("valueConstraint", {"op": "gt", "value": 3.0}),
         ("logicType", "PRESENCE")],
    )
    def test_should_keep_two_rows_apart_when_one_key_field_differs(self, field, value) -> None:
        assert _dropped([_row(1), _row(2, **{field: value})]) == set()

    def test_should_collapse_two_top_level_rows_when_every_key_field_is_equal(self) -> None:
        assert _dropped([_row(1, description="A"), _row(2, description="unrelated words")]) == {"2"}

    def test_should_ignore_key_order_inside_a_value_constraint(self) -> None:
        a = _row(1, valueConstraint={"op": "gt", "value": 3.0})
        b = _row(2, valueConstraint={"value": 3.0, "op": "gt"})
        assert distinctness_key(a) == distinctness_key(b)


class TestWhatNeverCollapses:
    def test_should_not_collapse_rows_without_source_text(self) -> None:
        assert _dropped([_row(1, source=""), _row(2, source="")]) == set()

    def test_should_not_collapse_a_group_label(self) -> None:
        rows = [_row(1, groupId="g", isGroupLabel=True), _row(2, groupId="g")]
        assert _dropped(rows) == set()

    def test_should_leave_restatable_demographics_to_their_own_path(self) -> None:
        rows = [_row(1, domain="Demographics"), _row(2, domain="Demographics")]
        assert _dropped(rows) == set()

    def test_should_collapse_demographics_that_carry_a_value_constraint(self) -> None:
        bound = {"op": "gte", "value": 70.0}
        rows = [_row(1, domain="Demographics", valueConstraint=bound),
                _row(2, domain="Demographics", valueConstraint=bound)]
        assert _dropped(rows) == {"2"}

    def test_should_never_collapse_across_roles(self) -> None:
        drops, _, _ = collapse_all_restated_criteria(
            inclusion_criteria=[_row(1)], exclusion_criteria=[_row(1)]
        )
        assert drops == set()


class TestThePlaceInTheRuleTree:
    def test_should_not_move_a_member_onto_a_top_level_row(self) -> None:
        rows = [_row(1), _row(2, groupId="g", groupType="ANY"), _row(3, "Stroke", groupId="g",
                                                                      groupType="ANY")]
        drops, _, intact = collapse_restated_criteria(rows, role="exclusion")
        assert drops == set()
        assert [g["reason"] for g in intact] == [WITHHELD_CONTEXT_DISTINCT]

    def test_should_not_move_a_member_into_a_group_with_other_members(self) -> None:
        rows = [_row(1, groupId="a"), _row(2, "Stroke", groupId="a"), _row(3, groupId="b")]
        assert _dropped(rows) == set()

    def test_should_collapse_a_restated_group_member_for_member(self) -> None:
        rows = [_row(1, groupId="a"), _row(2, "Stroke", groupId="a"),
                _row(3, groupId="b"), _row(4, "Stroke", groupId="b")]
        assert _dropped(rows) == {"3", "4"}

    def test_should_not_treat_groups_of_different_type_as_restatements(self) -> None:
        rows = [_row(1, groupId="a", groupType="ALL"), _row(2, groupId="b", groupType="ANY")]
        assert _dropped(rows) == set()

    def test_should_collapse_identical_members_of_one_group(self) -> None:
        rows = [_row(1, groupId="a", groupType="ANY"), _row(2, groupId="a", groupType="ANY")]
        assert _dropped(rows) == {"2"}


class TestTheRecord:
    def test_should_keep_the_first_member_in_document_order(self) -> None:
        _, (record,), _ = collapse_restated_criteria([_row(9), _row(3)], role="exclusion")
        assert (record["survivorId"], record["droppedIds"]) == (9, [3])
        assert record["survivorRule"] == SURVIVOR_RULE
        assert record["reason"] == COLLAPSE_REASON
        assert record["distinctnessKey"]["sourceText"] == "Heart failure"


# --------------------------------------------------------------------------- #
# The SPEC-INFRA-004 reference store
# --------------------------------------------------------------------------- #


def _reference(nct: str, role: str, ids: list[int]) -> list[dict[str, Any]]:
    rows = [c for c in REFERENCE[nct][f"{role}Criteria"] if c["id"] in ids]
    assert sorted(c["id"] for c in rows) == sorted(ids)
    return copy.deepcopy(rows)


class TestTheReferenceStore:
    @pytest.mark.parametrize("ids", [[13, 14, 15], [23, 24, 25, 26]])
    def test_should_never_collapse_distinct_entities_under_one_category_label(self, ids) -> None:
        """EMPA-REG "Cardiovascular Disease" and the thyroid / adrenal pairs, grouped or not."""
        rows = _reference("NCT01131676", "exclusion", ids)
        assert _dropped(rows) == set()
        for row in rows:
            row["groupId"] = None
        assert _dropped(rows) == set()

    def test_should_leave_one_survivor_per_analyte_in_the_liver_group(self) -> None:
        rows = _reference("NCT01131676", "exclusion", [44, 45, 46, 47, 48, 49])
        assert _dropped(rows) == {"47", "48", "49"}

    def test_should_collapse_the_restated_alcohol_rows(self) -> None:
        drops, _, _ = collapse_restated_criteria(
            REFERENCE["NCT01243424"]["exclusionCriteria"], role="exclusion"
        )
        assert ("exclusion", "49") in drops
