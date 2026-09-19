"""A restated-absence removal is reconciled, not forgiven.

`restated_absence_repair` removes a whole inclusion rule, so the delivered file
legitimately carries one fewer rule than the store study. Check (b) of the delivery
gate compares those two multisets and fails on `missing=1` unless something accounts
for the difference, and `_droppedCriteria` cannot: `dropped_criteria_violations`
re-judges every record there against `unreadable_value_attributes`, and a removal
made because one rule forbade another's whole range names no unreadable attribute.
So the repair records under its own key and the gate reads that key here.

The standard is the one `tests/test_delivery_gate_reconciles_skip_records.py` sets:
the record is a permit the gate re-judges, not a word it takes. The record is written
by the artifact being checked, so a producer that emitted a removal record for a rule
it simply lost would launder real loss past the gate. Three things are therefore
re-derived from the delivered file itself, and each has a test below in which IT is
the gate that fires:

  * the removed rule is really gone from the file,
  * the surviving partner the record names is really still in the file,
  * and that partner really carries the `bt low..high` the record claims it states —
    which is the whole justification for the removal.

Names and bounds are the real 2026-09-12 CARMELINA pair, the delivery that went to a
hospital and returned 0 people because rules #12 and #13 were complements.
"""
from __future__ import annotations

from typing import Any

# The producer's own spellings, imported and never retyped: a guessed key or outcome
# reconciles nothing and the test would pass while the gate stayed blind.
from scripts.verify_circe_delivery import (
    reconcile_dropped_rules,
    restated_absence_removal_violations,
)
from src.services.restated_absence_repair import RESTATED_ABSENCE_REMOVALS_KEY
from src.utils.circe_lint import DROP_OUTCOME_RULE_REMOVED

#: The rule the repair removes -- 2026-09-12 CARMELINA, rule #13.
REMOVED_RULE = "HbA1c below lower limit + HbA1c above upper limit"
#: The rule that survives and states the protocol range -- rule #12, after the range
#: collapse turned its `ANY(gte 6.5, lte 10)` into one `bt`.
PARTNER_RULE = "HbA1c at least 6.5% + HbA1c at most 10.0%"
LOW, HIGH = 6.5, 10.0


def _presence_rule(name: str, low: float, high: float) -> dict[str, Any]:
    """The surviving partner: one `bt` Measurement criterion under a top-level ALL."""
    return {
        "name": name,
        "expression": {
            "Type": "ALL",
            "CriteriaList": [
                {
                    "Criteria": {
                        "Measurement": {
                            "CodesetId": 8,
                            "ValueAsNumber": {"Value": low, "Extent": high, "Op": "bt"},
                        }
                    },
                    "Occurrence": {"Type": 2, "Count": 1},
                    "StartWindow": {
                        "Start": {"Days": 180, "Coeff": -1},
                        "End": {"Days": 0, "Coeff": 1},
                    },
                }
            ],
            "Groups": [],
        },
    }


def _removal_record(**overrides: Any) -> dict[str, Any]:
    record = {
        "ruleIndex": 12,
        "rule": REMOVED_RULE,
        "ruleAfter": None,
        "outcome": DROP_OUTCOME_RULE_REMOVED,
        "partnerRuleIndex": 11,
        "partnerRule": PARTNER_RULE,
        "low": LOW,
        "high": HIGH,
        "codesetIds": [8, 9, 10, 11],
        "nConcepts": 5,
        "summary": "removed because it forbade every value the partner requires",
    }
    record.update(overrides)
    return record


def _expression(records: list[dict[str, Any]], partner: dict[str, Any] | None = None) -> dict:
    """A delivered expression carrying the survivor and the removal records."""
    rules = [{"name": "Type 2 Diabetes Mellitus", "expression": {"Type": "ALL"}}]
    if partner is not None:
        rules.append(partner)
    return {"InclusionRules": rules, RESTATED_ABSENCE_REMOVALS_KEY: records}


#: What the store study still carries: both rules, because the repair leaves the store
#: alone and mutates only the expression being delivered.
STORE_NAMES = ["Type 2 Diabetes Mellitus", PARTNER_RULE, REMOVED_RULE]


class TestTheStoreSideMovesForward:
    def test_should_drop_the_removed_rule_from_the_store_side_when_a_record_accounts_for_it(self):
        expression = _expression([_removal_record()], _presence_rule(PARTNER_RULE, LOW, HIGH))

        adjusted, violations = reconcile_dropped_rules(expression, STORE_NAMES)

        assert violations == []
        assert sorted(adjusted) == sorted(["Type 2 Diabetes Mellitus", PARTNER_RULE])

    def test_should_leave_the_store_side_alone_when_the_file_records_no_removal(self):
        expression = _expression([], _presence_rule(PARTNER_RULE, LOW, HIGH))

        adjusted, violations = reconcile_dropped_rules(expression, STORE_NAMES)

        assert violations == []
        assert sorted(adjusted) == sorted(STORE_NAMES)

    def test_should_report_a_violation_when_the_record_names_a_rule_the_store_lacks(self):
        expression = _expression(
            [_removal_record(rule="A rule no store study carries")],
            _presence_rule(PARTNER_RULE, LOW, HIGH),
        )

        _adjusted, violations = reconcile_dropped_rules(expression, STORE_NAMES)

        assert violations, "a record naming a rule the store lacks explains nothing"


class TestThePermitIsReJudged:
    def test_should_report_nothing_when_the_file_bears_out_the_record(self):
        expression = _expression([_removal_record()], _presence_rule(PARTNER_RULE, LOW, HIGH))

        assert restated_absence_removal_violations(expression) == []

    def test_should_report_a_violation_when_the_removed_rule_is_still_in_the_file(self):
        expression = _expression([_removal_record()], _presence_rule(PARTNER_RULE, LOW, HIGH))
        expression["InclusionRules"].append({"name": REMOVED_RULE, "expression": {"Type": "ALL"}})

        violations = restated_absence_removal_violations(expression)

        assert any(REMOVED_RULE in v and "still" in v for v in violations), violations

    def test_should_report_a_violation_when_the_surviving_partner_is_not_in_the_file(self):
        expression = _expression([_removal_record()], partner=None)

        violations = restated_absence_removal_violations(expression)

        assert any(PARTNER_RULE in v for v in violations), violations

    def test_should_report_a_violation_when_the_partner_does_not_state_the_recorded_range(self):
        # The partner survives and is named, but carries a different range -- so nothing
        # in the file justifies removing a rule that forbade 6.5..10.
        expression = _expression(
            [_removal_record()], _presence_rule(PARTNER_RULE, 7.0, 9.0)
        )

        violations = restated_absence_removal_violations(expression)

        assert any("bt" in v for v in violations), violations

    def test_should_report_a_violation_when_the_outcome_is_not_a_rule_removal(self):
        expression = _expression(
            [_removal_record(outcome="rule-renamed")], _presence_rule(PARTNER_RULE, LOW, HIGH)
        )

        violations = restated_absence_removal_violations(expression)

        assert violations, "only a rule-removal outcome is replayable here"
