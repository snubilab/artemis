"""An emission-time drop must be recorded in the file it changed.

``drop_unreadable_value_criteria`` removes a criterion whose value filter its own
CDM table cannot read, and the repair is correct: over the six-study export it took
the defective population from 10 to 0 and left all 108 legitimate filters standing.
What it did not do was say so anywhere the delivered artifact can be read from.
``TTEService._build_emittable_expression`` passed the returned list to
``logging.warning`` and nowhere else, so the change left no trace in the payload.

Measured on the two exports of the same six studies from the same store:

    deliver_20260908/aristotle_treatment.circe.json   rules=24  conceptsets=31
    deliver_fix_final/aristotle_treatment.circe.json  rules=23  conceptsets=30

    _generationCensus, _skippedCriteria and _unmappedCriteria are BYTE-IDENTICAL
    between the two, and no new key appears in either.

Two defects follow from that one omission.

**P1 — the accounting describes a file it no longer matches.**
``criterion_accounting`` printed the identical string for both files above --
"criterion accounting: 30 mapped, 2 unmapped, 5 skipped (all permitted)" -- for a
24-rule file and a 23-rule one. The mapper did map 30 criteria; one of them then
left the artifact, and nothing in the artifact says which. That is the same defect
class the delivery-gate work closed one stage upstream (`3a3581b`, finding 2):
records written into the payload that no reader can reconcile against the payload.

**P2 — the gate fails the batch the repair exists to produce.** Same store, same
gate binary::

    output/site_gap/2026-09-08/deliver_20260908/   rule-set mismatches: 0
    /tmp/deliver_fix_final/                        rule-set mismatches: 8 of 12

``_rule_multiset_check`` compares the file's ``InclusionRules`` names against the
store's ``structuredExpression``. The drop mutates the emitted deepcopy -- removing
a rule outright, or rewriting a grouped rule's name when one member leaves -- while
the store keeps the pre-drop text, so every touched file diverges from its own
store. Six of the eight were ``missing=1 extra=1`` (a rename) and one
``missing=1 extra=2`` (a rename plus the appended arm drug rule).

The repair for both is one record, ``_droppedCriteria``, written where the drop
happens and read at both boundaries:

* a reader of the delivered file can see which rule left, which criteria type
  carried the filter, and which attributes that type cannot read;
* the gate reconciles the store's rule multiset against the recorded
  transformations before comparing, so a *recorded* drop is explained and an
  *unrecorded* missing rule still fails.

The second half is the load-bearing one and is pinned below by its negative:
a file missing a rule with no record naming it must still FAIL.

Deliberately NOT changed: ``_generationCensus``. Its identity
``total == mapped + unmapped + demographicRules + skipped`` counts what the
generator did with the extracted criteria, and the mapper genuinely mapped the
criterion that was later dropped. The drop happens at a different stage, against a
different object -- an assembled CIRCE expression, often a deepcopy of a stored
``structuredExpression`` whose criterion ids the emitted rules no longer carry --
so it has no ``role``/``criterionId`` to file under and no place in that identity.
Folding it in would also make the delivered census disagree with the store's census
for the same generation. ``_droppedCriteria`` is a fourth channel because the event
is a fourth kind, and the identity above is asserted unchanged here and in
``tests/test_generation_census_accounts_for_every_criterion.py``.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest

from src.utils.circe_lint import (
    DROP_OUTCOME_RULE_REMOVED,
    DROP_OUTCOME_RULE_RENAMED,
    DROPPED_CRITERIA_KEY,
    drop_unreadable_value_criteria,
)

PERCENT_UNIT = [
    {
        "CONCEPT_CODE": "%",
        "CONCEPT_ID": 8554,
        "CONCEPT_NAME": "percent",
        "DOMAIN_ID": "Unit",
        "VOCABULARY_ID": "UCUM",
    }
]


def _member(criteria_type: str, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "Type": "ALL",
        "CriteriaList": [
            {
                "Criteria": {criteria_type: body},
                "StartWindow": {
                    "Start": {"Days": 365, "Coeff": -1},
                    "End": {"Days": 0, "Coeff": 1},
                },
                "RestrictVisit": False,
                "IgnoreObservationPeriod": False,
                "Occurrence": {"Type": 2, "Count": 1},
            }
        ],
        "DemographicCriteriaList": [],
        "Groups": [],
    }


def _rule(name: str, groups: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "name": name,
        "expression": {
            "Type": "ANY",
            "CriteriaList": [],
            "DemographicCriteriaList": [],
            "Groups": groups,
        },
    }


#: ARISTOTLE's aspirin exclusion, transcribed from
#: `output/site_gap/2026-09-08/deliver_20260908/aristotle_treatment.circe.json`.
#: DRUG_EXPOSURE has no value_as_number column, so Circe drops the attribute and the
#: rule excludes everyone on any aspirin at all. Its only criterion is unreadable, so
#: the whole rule leaves the file.
ASPIRIN_RULE = _rule(
    "aspirin",
    [_member("DrugExposure", {"CodesetId": 27, "ValueAsNumber": {"Value": 165.0, "Op": "gt"}})],
)

#: LEADER's cardiovascular-history rule: four readable members and one
#: ProcedureOccurrence carrying "> 50% stenosis" that PROCEDURE_OCCURRENCE cannot
#: read. The rule survives with its name rewritten -- the `missing=1 extra=1` shape.
LEADER_CV_HISTORY = _rule(
    "Chronic heart failure NYHA class II-III + Chronic renal failure + Prior MI"
    " + Prior revascularization >50% stenosis + Prior stroke or TIA",
    [
        _member("ConditionOccurrence", {"CodesetId": 9}),
        _member("ConditionOccurrence", {"CodesetId": 10}),
        _member("ConditionOccurrence", {"CodesetId": 11}),
        _member(
            "ProcedureOccurrence",
            {
                "CodesetId": 12,
                "ValueAsNumber": {"Value": 50.0, "Op": "gt"},
                "Unit": PERCENT_UNIT,
            },
        ),
        _member("ConditionOccurrence", {"CodesetId": 13}),
    ],
)

LEADER_NAME_AFTER = (
    "Chronic heart failure NYHA class II-III + Chronic renal failure + Prior MI"
    " + Prior stroke or TIA"
)

LEGITIMATE_HBA1C = _rule(
    "Elevated HbA1c",
    [
        _member(
            "Measurement",
            {"CodesetId": 5, "ValueAsNumber": {"Value": 7.0, "Op": "gte"}, "Unit": PERCENT_UNIT},
        )
    ],
)


def _shell(rules: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ConceptSets": [],
        "PrimaryCriteria": {
            "CriteriaList": [{"DrugEra": {"CodesetId": 1}}],
            "ObservationWindow": {"PriorDays": 365, "PostDays": 0},
            "PrimaryCriteriaLimit": {"Type": "First"},
        },
        "InclusionRules": rules,
        "CensoringCriteria": [],
    }


# ---------------------------------------------------------------------------
# Half one -- the record exists, and names what left
# ---------------------------------------------------------------------------


class TestTheDropRecordsWhatItRemoved:
    def test_should_name_the_rule_it_removed_when_its_only_criterion_is_unreadable(self):
        expression = _shell([deepcopy(ASPIRIN_RULE), deepcopy(LEGITIMATE_HBA1C)])

        (record,) = drop_unreadable_value_criteria(expression)

        assert record["rule"] == "aspirin"
        assert record["outcome"] == DROP_OUTCOME_RULE_REMOVED
        assert record["ruleAfter"] is None
        assert [r["name"] for r in expression["InclusionRules"]] == ["Elevated HbA1c"]

    def test_should_name_the_attributes_the_criteria_type_cannot_read(self):
        expression = _shell([deepcopy(ASPIRIN_RULE)])

        (record,) = drop_unreadable_value_criteria(expression)

        assert record["unreadable"] == [
            {
                "criteriaType": "DrugExposure",
                "attributes": ["ValueAsNumber"],
                "codesetId": 27,
            }
        ]

    def test_should_record_the_rewritten_name_when_the_rule_survived_the_drop(self):
        """The `missing=1 extra=1` shape: the rule stays, under a different name."""
        expression = _shell([deepcopy(LEADER_CV_HISTORY)])

        (record,) = drop_unreadable_value_criteria(expression)

        assert record["rule"] == LEADER_CV_HISTORY["name"]
        assert record["outcome"] == DROP_OUTCOME_RULE_RENAMED
        assert record["ruleAfter"] == LEADER_NAME_AFTER
        assert expression["InclusionRules"][0]["name"] == LEADER_NAME_AFTER

    def test_should_carry_a_human_readable_summary_naming_the_rule_and_the_filter(self):
        expression = _shell([deepcopy(ASPIRIN_RULE)])

        (record,) = drop_unreadable_value_criteria(expression)

        assert record["summary"] == "aspirin: DrugExposure carrying ValueAsNumber"

    def test_should_group_two_records_from_one_rule_under_one_rule_index(self):
        """Two unreadable members of one rule are one transformation, not two."""
        both_unreadable = _rule(
            "GLP-1 receptor agonists use + DPP-4 inhibitors use",
            [
                _member(
                    "DrugExposure",
                    {"CodesetId": 23, "ValueAsNumber": {"Value": 7.0, "Op": "gte"}},
                ),
                _member(
                    "DrugExposure",
                    {"CodesetId": 24, "ValueAsNumber": {"Value": 7.0, "Op": "gte"}},
                ),
            ],
        )
        expression = _shell([deepcopy(LEGITIMATE_HBA1C), both_unreadable])

        records = drop_unreadable_value_criteria(expression)

        assert len(records) == 2
        assert {r["ruleIndex"] for r in records} == {1}
        assert {r["outcome"] for r in records} == {DROP_OUTCOME_RULE_REMOVED}


class TestTheEmittedExpressionCarriesTheRecord:
    def test_should_write_the_record_into_the_expression_the_arm_builder_emits(self):
        from src.services.tte_service import TTEService

        stored = _shell([deepcopy(ASPIRIN_RULE), deepcopy(LEGITIMATE_HBA1C)])
        emitted = TTEService._build_emittable_expression(lambda: deepcopy(stored))

        assert [r["rule"] for r in emitted[DROPPED_CRITERIA_KEY]] == ["aspirin"]

    def test_should_write_an_empty_record_when_nothing_was_dropped(self):
        """Present-and-empty, matching `_unmappedCriteria` and `_skippedCriteria`:
        an absent key must mean "built before the record existed", never "clean"."""
        from src.services.tte_service import TTEService

        stored = _shell([deepcopy(LEGITIMATE_HBA1C)])
        emitted = TTEService._build_emittable_expression(lambda: deepcopy(stored))

        assert emitted[DROPPED_CRITERIA_KEY] == []

    def test_should_survive_the_concept_set_prune_the_exporter_runs(self):
        """The exporter writes what `prune_unused_concept_sets` returns, so a record
        the prune discarded would never reach the delivered file."""
        from src.pipeline.webapi_client import prune_unused_concept_sets
        from src.services.tte_service import TTEService

        stored = _shell([deepcopy(ASPIRIN_RULE), deepcopy(LEGITIMATE_HBA1C)])
        stored["ConceptSets"] = [
            {"id": 1, "name": "apixaban", "expression": {"items": []}},
            {"id": 5, "name": "HbA1c", "expression": {"items": []}},
            {"id": 27, "name": "aspirin", "expression": {"items": []}},
        ]
        emitted = TTEService._build_emittable_expression(lambda: deepcopy(stored))

        pruned = prune_unused_concept_sets(emitted)

        assert [r["rule"] for r in pruned[DROPPED_CRITERIA_KEY]] == ["aspirin"]
        assert [c["id"] for c in pruned["ConceptSets"]] == [1, 5], (
            "codesetId inside the drop record must not resurrect the pruned set"
        )


class TestTheGenerationCensusIdentityIsUnchanged:
    """The drop is a fourth kind of event, not a fifth term in the census identity."""

    def test_should_leave_the_census_untouched_when_a_criterion_is_dropped(self):
        from src.services.tte_service import TTEService

        census = {
            "total": 34,
            "mappable": 32,
            "mapped": 30,
            "unmapped": 2,
            "demographicRules": 2,
            "skipped": 0,
            "skippedByReason": {},
        }
        stored = _shell([deepcopy(ASPIRIN_RULE), deepcopy(LEGITIMATE_HBA1C)])
        stored["_generationCensus"] = deepcopy(census)

        emitted = TTEService._build_emittable_expression(lambda: deepcopy(stored))

        assert emitted["_generationCensus"] == census
        assert emitted["_generationCensus"]["total"] == (
            census["mapped"]
            + census["unmapped"]
            + census["demographicRules"]
            + census["skipped"]
        )


# ---------------------------------------------------------------------------
# Half two -- the gate reads the record, and still fails without one
# ---------------------------------------------------------------------------


def _store_study(rules: list[dict[str, Any]], study_id: int = 3) -> dict[str, Any]:
    """A two-arm store study whose `structuredExpression` carries `rules`."""
    core = _shell([deepcopy(r) for r in rules])
    core["ConceptSets"] = [
        {
            "id": 1,
            "name": "apixaban",
            "expression": {
                "items": [
                    {
                        "concept": {
                            "CONCEPT_ID": 43013024,
                            "CONCEPT_NAME": "apixaban",
                            "DOMAIN_ID": "Drug",
                            "VOCABULARY_ID": "RxNorm",
                            "CONCEPT_CLASS_ID": "Ingredient",
                            "CONCEPT_CODE": "1",
                        },
                        "includeDescendants": True,
                        "isExcluded": False,
                    }
                ]
            },
        }
    ]
    return {
        "id": study_id,
        "name": f"Study {study_id}",
        "comparisonMode": "target_minus_treatment",
        "treatmentArms": [{"name": "apixaban"}, {"name": "warfarin"}],
        "eligibility": {"structuredExpression": core},
    }


def _drop_record(
    *,
    rule: str,
    rule_after: str | None,
    outcome: str,
    criteria_type: str = "DrugExposure",
    attributes: tuple[str, ...] = ("ValueAsNumber",),
    codeset_id: int = 27,
    rule_index: int = 0,
) -> dict[str, Any]:
    return {
        "ruleIndex": rule_index,
        "rule": rule,
        "ruleAfter": rule_after,
        "outcome": outcome,
        "unreadable": [
            {
                "criteriaType": criteria_type,
                "attributes": list(attributes),
                "codesetId": codeset_id,
            }
        ],
        "summary": f"{rule}: {criteria_type} carrying {', '.join(attributes)}",
    }


@pytest.fixture
def gate(monkeypatch, tmp_path, capsys):
    """Run the delivery gate over one directory built from explicit file rules."""

    def _run(
        *,
        store_rules: list[dict[str, Any]],
        file_rules: list[dict[str, Any]],
        dropped: list[dict[str, Any]] | None,
    ) -> tuple[int, str]:
        monkeypatch.delenv("TTE_STORE_PATH", raising=False)
        study = _store_study(store_rules)
        core = study["eligibility"]["structuredExpression"]

        for role in ("treatment", "comparator"):
            payload = json.loads(json.dumps(core))
            payload["InclusionRules"] = json.loads(json.dumps(file_rules))
            if dropped is not None:
                payload[DROPPED_CRITERIA_KEY] = json.loads(json.dumps(dropped))
            (tmp_path / f"aristotle_{role}.circe.json").write_text(json.dumps(payload))

        store = tmp_path / "studies.json"
        store.write_text(json.dumps([study]))

        from scripts.verify_circe_delivery import main

        rc = main(["--dir", str(tmp_path), "--store", str(store), "--map", "aristotle=3"])
        return rc, capsys.readouterr().out

    return _run


class TestTheGateAcceptsARecordedDrop:
    def test_should_pass_when_the_file_records_the_rule_the_drop_removed(self, gate):
        rc, out = gate(
            store_rules=[ASPIRIN_RULE, LEGITIMATE_HBA1C],
            file_rules=[LEGITIMATE_HBA1C],
            dropped=[
                _drop_record(
                    rule="aspirin", rule_after=None, outcome=DROP_OUTCOME_RULE_REMOVED
                )
            ],
        )
        assert rc == 0, out
        assert "rule set mismatch" not in out

    def test_should_pass_when_the_file_records_a_rule_the_drop_renamed(self, gate):
        renamed = _rule(LEADER_NAME_AFTER, LEADER_CV_HISTORY["expression"]["Groups"][:3])
        rc, out = gate(
            store_rules=[LEADER_CV_HISTORY, LEGITIMATE_HBA1C],
            file_rules=[renamed, LEGITIMATE_HBA1C],
            dropped=[
                _drop_record(
                    rule=LEADER_CV_HISTORY["name"],
                    rule_after=LEADER_NAME_AFTER,
                    outcome=DROP_OUTCOME_RULE_RENAMED,
                    criteria_type="ProcedureOccurrence",
                    attributes=("Unit", "ValueAsNumber"),
                    codeset_id=12,
                )
            ],
        )
        assert rc == 0, out
        assert "rule set mismatch" not in out

    def test_should_still_allow_the_one_appended_arm_rule_beside_a_recorded_drop(self, gate):
        """`missing=1 extra=2` -- LEADER's comparator: a rename plus the arm rule."""
        renamed = _rule(LEADER_NAME_AFTER, LEADER_CV_HISTORY["expression"]["Groups"][:3])
        arm_rule = _rule("liraglutide exposure", [_member("DrugEra", {"CodesetId": 1})])
        rc, out = gate(
            store_rules=[LEADER_CV_HISTORY, LEGITIMATE_HBA1C],
            file_rules=[renamed, LEGITIMATE_HBA1C, arm_rule],
            dropped=[
                _drop_record(
                    rule=LEADER_CV_HISTORY["name"],
                    rule_after=LEADER_NAME_AFTER,
                    outcome=DROP_OUTCOME_RULE_RENAMED,
                    criteria_type="ProcedureOccurrence",
                    attributes=("Unit", "ValueAsNumber"),
                    codeset_id=12,
                )
            ],
        )
        assert rc == 0, out
        assert "rule set mismatch" not in out


class TestTheGateStillFailsAnUnexplainedMismatch:
    """The load-bearing half. A gate that accepts any mismatch has been turned off."""

    def test_should_fail_when_a_rule_is_missing_and_no_record_names_it(self, gate):
        rc, out = gate(
            store_rules=[ASPIRIN_RULE, LEGITIMATE_HBA1C],
            file_rules=[LEGITIMATE_HBA1C],
            dropped=[],
        )
        assert rc == 1, out
        assert "rule set mismatch" in out

    def test_should_fail_when_a_rule_is_missing_and_the_file_carries_no_record_key(self, gate):
        """An artifact built before the record existed is not thereby explained."""
        rc, out = gate(
            store_rules=[ASPIRIN_RULE, LEGITIMATE_HBA1C],
            file_rules=[LEGITIMATE_HBA1C],
            dropped=None,
        )
        assert rc == 1, out
        assert "rule set mismatch" in out

    def test_should_fail_when_the_record_explains_only_one_of_two_missing_rules(self, gate):
        other = _rule("Investigational drug use", [_member("DrugExposure", {"CodesetId": 30})])
        rc, out = gate(
            store_rules=[ASPIRIN_RULE, other, LEGITIMATE_HBA1C],
            file_rules=[LEGITIMATE_HBA1C],
            dropped=[
                _drop_record(
                    rule="aspirin", rule_after=None, outcome=DROP_OUTCOME_RULE_REMOVED
                )
            ],
        )
        assert rc == 1, out
        assert "rule set mismatch" in out

    def test_should_fail_when_a_record_names_a_rule_the_store_does_not_carry(self, gate):
        rc, out = gate(
            store_rules=[ASPIRIN_RULE, LEGITIMATE_HBA1C],
            file_rules=[LEGITIMATE_HBA1C],
            dropped=[
                _drop_record(
                    rule="a rule nobody generated",
                    rule_after=None,
                    outcome=DROP_OUTCOME_RULE_REMOVED,
                ),
                _drop_record(
                    rule="aspirin", rule_after=None, outcome=DROP_OUTCOME_RULE_REMOVED
                ),
            ],
        )
        assert rc == 1, out
        assert "a rule nobody generated" in out

    def test_should_fail_when_a_record_names_an_attribute_its_type_can_read(self, gate):
        """A record cannot launder an arbitrary removal: the (type, attribute) pair it
        claims must be one `unreadable_value_attributes` actually refuses. Measurement
        reads Unit, so this record describes no defect and explains no drop."""
        rc, out = gate(
            store_rules=[ASPIRIN_RULE, LEGITIMATE_HBA1C],
            file_rules=[LEGITIMATE_HBA1C],
            dropped=[
                _drop_record(
                    rule="aspirin",
                    rule_after=None,
                    outcome=DROP_OUTCOME_RULE_REMOVED,
                    criteria_type="Measurement",
                    attributes=("Unit",),
                )
            ],
        )
        assert rc == 1, out
        assert "Measurement" in out
        assert "Unit" in out


class TestTheAccountingLineNamesTheDrop:
    """P1: the same string printed for a 24-rule file and a 23-rule one."""

    def test_should_report_the_drop_count_on_the_row(self, gate):
        rc, out = gate(
            store_rules=[ASPIRIN_RULE, LEGITIMATE_HBA1C],
            file_rules=[LEGITIMATE_HBA1C],
            dropped=[
                _drop_record(
                    rule="aspirin", rule_after=None, outcome=DROP_OUTCOME_RULE_REMOVED
                )
            ],
        )
        assert rc == 0, out
        assert "1 dropped at emission" in out
        assert "aspirin" in out

    def test_should_distinguish_a_file_with_a_drop_from_one_without(self, gate):
        _rc_clean, clean = gate(
            store_rules=[LEGITIMATE_HBA1C],
            file_rules=[LEGITIMATE_HBA1C],
            dropped=[],
        )
        _rc_dropped, dropped = gate(
            store_rules=[ASPIRIN_RULE, LEGITIMATE_HBA1C],
            file_rules=[LEGITIMATE_HBA1C],
            dropped=[
                _drop_record(
                    rule="aspirin", rule_after=None, outcome=DROP_OUTCOME_RULE_REMOVED
                )
            ],
        )

        clean_line = [line for line in clean.splitlines() if "treatment" in line][0]
        dropped_line = [line for line in dropped.splitlines() if "treatment" in line][0]
        assert clean_line != dropped_line, (
            "the accounting line described both a 24-rule and a 23-rule file identically"
        )
        assert "0 dropped at emission" in clean_line

    def test_should_report_the_drop_on_a_failing_row_too(self, gate):
        """Every file of the real six-study batch fails on recorded criterion loss, so
        a summary printed only on a passing row would never once have said what the
        emission-time repair removed."""
        rc, out = gate(
            store_rules=[ASPIRIN_RULE, LEGITIMATE_HBA1C],
            file_rules=[LEGITIMATE_HBA1C],
            dropped=[
                _drop_record(
                    rule="aspirin",
                    rule_after=None,
                    outcome=DROP_OUTCOME_RULE_REMOVED,
                ),
                _drop_record(
                    rule="a rule nobody generated",
                    rule_after=None,
                    outcome=DROP_OUTCOME_RULE_REMOVED,
                ),
            ],
        )
        assert rc == 1, out
        assert "2 dropped at emission" in out
