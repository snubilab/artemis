"""A ``_restatedRuleCollapse`` record must receive every export-time rewrite its survivor receives.

The collapse runs at BUILD time (``_build_seeded_target_circe`` ->
``collapse_redundant_inclusion_rules``) and carries the removed rule's expression verbatim, so
the delivery gate can re-derive "this rule was redundant" from the file
(``scripts/verify_circe_delivery.py`` ``restated_rule_collapse_violations``). The export then
rewrites the surviving rules -- the entry-colliding washout shift, the unreadable-value drop, the
six arm repairs -- and until this fix never touched the carried copy.

Measured on the 2026-10-08 dry rebuild at 907ab84 (``output/site_gap/2026-10-08_dryrun``):
CARMELINA treatment enters on linagliptin, the shift moved the survivor's DPP-4 window End
0 -> -1, the carried twin kept End 0, and the gate failed both records with "the removal lost a
criterion". The comparator, whose entry is not a DPP-4 drug, received no shift and passed.

The fix applies the SAME rewrite function to the carried rule. It never copies the survivor
into the record: a record that does not restate its survivor must still fail the gate, which
``TestTheGateStillRejects`` pins.
"""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts.verify_circe_delivery import restated_rule_collapse_violations
from src.services.restated_rules import (
    IDENTICAL_REASON,
    RESTATED_RULE_COLLAPSE_KEY,
    collapse_redundant_inclusion_rules,
)
from src.services.tte_service import TTEService

REPO = Path(__file__).resolve().parents[1]
CARMELINA_0923 = REPO / "deliveries" / "2026-09-23" / "carmelina_treatment.circe.json"

INDEX_DAY_END = {"Days": 0, "Coeff": 1}
DAY_BEFORE_INDEX_END = {"Days": 1, "Coeff": -1}


def _walk_windows(node: Any):
    if isinstance(node, dict):
        if isinstance(node.get("StartWindow"), dict):
            yield node["StartWindow"]
        for value in node.values():
            yield from _walk_windows(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_windows(value)


def _carmelina_as_stored() -> dict[str, Any]:
    """The real 09-23 CARMELINA treatment file, put back into its pre-emission state.

    The delivered file is post-emission: the washout shift already moved every DPP-4 leaf to
    End -1. The store holds End 0 for them (the dry-rebuild record carries End 0), so undoing
    the shift recreates what the export receives. Then the build-time collapse runs, exactly as
    ``_build_seeded_target_circe`` does since 5d9bf6c.
    """
    expression = json.loads(CARMELINA_0923.read_text())
    for window in _walk_windows(expression["InclusionRules"]):
        if window.get("End") == DAY_BEFORE_INDEX_END:
            window["End"] = dict(INDEX_DAY_END)
    collapse_redundant_inclusion_rules(expression)
    return expression


def _emit(expression: dict[str, Any]) -> dict[str, Any]:
    return TTEService._build_emittable_expression(lambda: expression)


class TestTheRealCarmelinaCase:
    def test_should_collapse_two_rules_when_the_stored_carmelina_is_built(self):
        """Precondition, so the test below is about the export and not about the collapse."""
        expression = _carmelina_as_stored()
        reasons = [r["reason"] for r in expression[RESTATED_RULE_COLLAPSE_KEY]]
        assert reasons == ["restated-rule-identical", "restated-rule-implied"]
        assert restated_rule_collapse_violations(expression) == []

    def test_should_keep_both_collapse_records_redundant_when_the_washout_shift_moves_the_survivor(
        self,
    ):
        emitted = _emit(_carmelina_as_stored())

        survivor = next(
            r for r in emitted["InclusionRules"]
            if r["name"].startswith("Exclusion of GLP-1 receptor agonists if recent")
        )
        assert DAY_BEFORE_INDEX_END in [w["End"] for w in _walk_windows(survivor)], (
            "precondition: the shift must have moved the survivor"
        )
        assert restated_rule_collapse_violations(emitted) == []

    def test_should_move_the_carried_dpp4_window_when_the_survivor_moves(self):
        emitted = _emit(_carmelina_as_stored())

        for record in emitted[RESTATED_RULE_COLLAPSE_KEY]:
            ends = [w["End"] for w in _walk_windows(record["expression"])]
            assert DAY_BEFORE_INDEX_END in ends, (record["rule"], ends)


# --- a small synthetic file, for the properties the real case does not exercise ------------


def _cs(set_id: int, name: str, concept_ids: list[int]) -> dict[str, Any]:
    return {
        "id": set_id,
        "name": name,
        "expression": {
            "items": [
                {
                    "concept": {"CONCEPT_ID": cid, "CONCEPT_NAME": name},
                    "includeDescendants": True,
                    "isExcluded": False,
                    "includeMapped": False,
                }
                for cid in concept_ids
            ]
        },
    }


def _absence_rule(name: str, codeset_id: int, start_days: int = 7) -> dict[str, Any]:
    return {
        "name": name,
        "expression": {
            "Type": "ALL",
            "CriteriaList": [
                {
                    "Criteria": {"DrugExposure": {"CodesetId": codeset_id}},
                    "StartWindow": {
                        "Start": {"Days": start_days, "Coeff": -1},
                        "End": dict(INDEX_DAY_END),
                    },
                    "RestrictVisit": False,
                    "IgnoreObservationPeriod": False,
                    "Occurrence": {"Type": 0, "Count": 0},
                }
            ],
            "DemographicCriteriaList": [],
            "Groups": [],
        },
    }


ENTRY_DRUG = 40239216


def _collapsed_pair() -> dict[str, Any]:
    """Survivor over codeset 2, its identical twin over codeset 3 (same content), collapsed."""
    expression = {
        "ConceptSets": [
            _cs(1, "entry drug", [ENTRY_DRUG]),
            _cs(2, "class", [ENTRY_DRUG, 1580747]),
            _cs(3, "class again", [ENTRY_DRUG, 1580747]),
        ],
        "PrimaryCriteria": {
            "CriteriaList": [{"DrugEra": {"CodesetId": 1}}],
            "ObservationWindow": {"PriorDays": 365, "PostDays": 0},
            "PrimaryCriteriaLimit": {"Type": "First"},
        },
        "InclusionRules": [_absence_rule("survivor", 2), _absence_rule("twin", 3)],
    }
    (record,) = collapse_redundant_inclusion_rules(expression)
    assert record["reason"] == IDENTICAL_REASON and record["survivorRule"] == "survivor"
    return expression


class TestTheGateStillRejects:
    def test_should_still_fail_the_gate_when_the_carried_rule_does_not_restate_its_survivor(
        self,
    ):
        """The replay must not launder a bad record: a carried rule with a different window
        is not made identical by being rewritten alongside its survivor."""
        expression = _collapsed_pair()
        criterion = expression[RESTATED_RULE_COLLAPSE_KEY][0]["expression"]["CriteriaList"][0]
        criterion["StartWindow"]["Start"]["Days"] = 30

        violations = restated_rule_collapse_violations(_emit(expression))

        assert len(violations) == 1, violations
        assert "the removal lost a criterion" in violations[0]


class TestTheReplayHelper:
    @staticmethod
    def _rename_every_member(expression: dict[str, Any]) -> list[str]:
        """A stand-in rewrite: touches every rule's window and every set a rule reads."""
        read: set[Any] = set()
        changed: list[str] = []
        for rule in expression.get("InclusionRules") or []:
            for window in _walk_windows(rule["expression"]):
                window["Start"]["Days"] += 1
            for criterion in rule["expression"]["CriteriaList"]:
                read.add(criterion["Criteria"]["DrugExposure"]["CodesetId"])
            changed.append(rule["name"])
        for concept_set in expression.get("ConceptSets") or []:
            if concept_set["id"] in read:
                for item in concept_set["expression"]["items"]:
                    item["concept"]["CONCEPT_NAME"] += "*"
        return changed

    def test_should_apply_the_rewrite_to_the_carried_rule_and_the_sets_only_it_reads(self):
        from src.services.tte_service import _rewrite_with_collapsed_rules

        expression = _collapsed_pair()
        returned = _rewrite_with_collapsed_rules(expression, self._rename_every_member)

        assert returned == ["survivor"], "the caller sees the rewrite's result on the file"
        sets = {cs["id"]: cs for cs in expression["ConceptSets"]}
        names = lambda i: [it["concept"]["CONCEPT_NAME"] for it in sets[i]["expression"]["items"]]  # noqa: E731
        assert names(2) == ["class*", "class*"], "the survivor's set is rewritten once, not twice"
        assert names(3) == ["class again*", "class again*"], "the set only the record reads"
        assert names(1) == ["entry drug"]
        record = expression[RESTATED_RULE_COLLAPSE_KEY][0]["expression"]
        assert [w["Start"]["Days"] for w in _walk_windows(record)] == [8]
        survivor = expression["InclusionRules"][0]["expression"]
        assert [w["Start"]["Days"] for w in _walk_windows(survivor)] == [8]
        assert restated_rule_collapse_violations(expression) == []

    def test_should_leave_the_record_unchanged_and_warn_when_the_rewrite_removes_the_carried_rule(
        self, caplog
    ):
        from src.services.tte_service import _rewrite_with_collapsed_rules

        expression = _collapsed_pair()
        before = deepcopy(expression[RESTATED_RULE_COLLAPSE_KEY])

        def drop_twin(e: dict[str, Any]) -> None:
            e["InclusionRules"] = [r for r in e["InclusionRules"] if r["name"] != "twin"]

        with caplog.at_level(logging.WARNING):
            _rewrite_with_collapsed_rules(expression, drop_twin)

        assert expression[RESTATED_RULE_COLLAPSE_KEY] == before
        assert any("twin" in m and "removed" in m for m in caplog.messages), caplog.messages

    def test_should_change_nothing_when_the_file_carries_no_collapse_record(self):
        from src.services.tte_service import _rewrite_with_collapsed_rules

        expression = _collapsed_pair()
        expression[RESTATED_RULE_COLLAPSE_KEY] = []
        expected = deepcopy(expression)
        self._rename_every_member(expected)

        _rewrite_with_collapsed_rules(expression, self._rename_every_member)

        assert expression == expected


class TestTheArmRepairsReachTheRecord:
    def test_should_keep_the_record_redundant_when_an_arm_repair_rewrites_the_survivor(self):
        """The six arm repairs run through one method; one of them stands in for all six."""
        expression = _collapsed_pair()
        service = TTEService.__new__(TTEService)

        def restrict_to_visit(e: dict[str, Any]) -> None:
            for rule in e.get("InclusionRules") or []:
                for criterion in rule["expression"]["CriteriaList"]:
                    criterion["RestrictVisit"] = True

        noop = lambda e, *_stated: None  # noqa: E731
        for name in (
            "_repair_overbroad_absence_sets",
            "_repair_entry_excluded_by_own_rule",
            "_repair_range_disjunctions",
            "_repair_restated_absences",
            "_repair_confusable_concept_set_members",
        ):
            setattr(service, name, noop)
        service._repair_presence_unit_filters = restrict_to_visit

        service._apply_export_repairs(expression)

        assert expression["InclusionRules"][0]["expression"]["CriteriaList"][0]["RestrictVisit"]
        assert restated_rule_collapse_violations(expression) == []
