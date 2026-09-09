"""A value filter must be merged only onto a criteria type whose CDM table reads it.

``build_measurement_value_filter`` returns a flat Circe fragment and all three
callers merged it unconditionally::

    criteria_attrs.update(build_measurement_value_filter(criterion["valueConstraint"]))

Nothing asked whether the criteria type the fragment lands on can read it. Measured
over the twelve files of ``output/site_gap/2026-09-08/deliver_20260908/``:

    DEFECTIVE  10 criteria across 8 files
      DrugExposure        + ValueAsNumber          x6   aristotle x1/arm, carmelina x2/arm
      ConditionOccurrence + Unit + ValueAsNumber   x2   carolina
      ProcedureOccurrence + Unit + ValueAsNumber   x2   leader
    LEGITIMATE 108 criteria in the SAME files
      Measurement  + Unit + ValueAsNumber          x54
      Measurement  + RangeHighRatio                x30
      Measurement  + ValueAsNumber                 x20
      Observation  + Unit + ValueAsNumber          x4

So a blanket ban is wrong: it would break 108 working filters to remove 10 broken
ones. Which attribute each type can read is a fact about Circe, and it was measured
rather than assumed -- every entry in ``CRITERIA_TYPE_VALUE_ATTRIBUTES`` comes from
POSTing a probe expression to the live ``WebAPI /cohortdefinition/sql`` twice, once
with the attribute and once without, and keeping the attribute only when the
rendered SQL differed. The four rows this suite depends on::

    Measurement          reads Abnormal, RangeHigh, RangeHighRatio, RangeLow,
                               RangeLowRatio, Unit, ValueAsConcept, ValueAsNumber
    Observation          reads Qualifier, Unit, ValueAsConcept, ValueAsNumber
                               -- and NOT RangeHighRatio/RangeLowRatio, because
                               OBSERVATION has no range_low/range_high columns
    DrugExposure         reads Quantity only
    ConditionOccurrence  reads nothing
    ProcedureOccurrence  reads Quantity only

The independent corroboration is the gold corpus: across the 18 TROY v1.1 CIRCE
files under ``data/gold/`` a value attribute appears on ``Measurement`` and on no
other criteria type.

Two refusal surfaces, because the defect has two lifetimes:

* generation -- the three merge sites refuse the criterion before it is built, the
  way ``refuse_domain_contradiction`` does, so the shape is never created;
* emission -- ``drop_unreadable_value_criteria`` repairs an already-stored
  ``structuredExpression``. Studies 1/8/9/10 all carry a prebuilt
  ``structuredExpression`` that the arm builders deepcopy verbatim, so a
  generation-only fix would need an LLM re-extraction to reach a delivered file.

Stripping the attribute and keeping the criterion is NOT the repair. Circe already
ignores the attribute, so stripping changes nothing about who the cohort selects --
it only stops the file from *saying* it filters. The rule would keep matching every
aspirin exposure while reading as "aspirin > 165 mg". Refusing the criterion is what
leaves the claim honestly absent instead of present and wrong.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

import pytest

from src.utils.circe_lint import (
    CRITERIA_TYPE_VALUE_ATTRIBUTES,
    drop_unreadable_value_criteria,
    refuse_unreadable_value_filter,
    unreadable_value_attributes,
    unreadable_value_filter_criteria,
)

NUMBER = {"Value": 5.0, "Op": "gt"}
PERCENT_UNIT = [
    {
        "CONCEPT_CODE": "%",
        "CONCEPT_ID": 8554,
        "CONCEPT_NAME": "percent",
        "DOMAIN_ID": "Unit",
        "VOCABULARY_ID": "UCUM",
    }
]


# ---------------------------------------------------------------------------
# The predicate
# ---------------------------------------------------------------------------


class TestUnreadableValueAttributes:
    def test_should_name_the_attribute_when_drug_exposure_carries_value_as_number(self):
        assert unreadable_value_attributes(
            "DrugExposure", {"CodesetId": 27, "ValueAsNumber": NUMBER}
        ) == ["ValueAsNumber"]

    def test_should_name_both_attributes_when_condition_occurrence_carries_a_unit_filter(
        self,
    ):
        assert unreadable_value_attributes(
            "ConditionOccurrence",
            {"CodesetId": 3, "ValueAsNumber": NUMBER, "Unit": PERCENT_UNIT},
        ) == ["Unit", "ValueAsNumber"]

    def test_should_name_nothing_when_measurement_carries_a_unit_filter(self):
        assert (
            unreadable_value_attributes(
                "Measurement",
                {"CodesetId": 3, "ValueAsNumber": NUMBER, "Unit": PERCENT_UNIT},
            )
            == []
        )

    def test_should_name_nothing_when_measurement_carries_a_reference_ratio(self):
        assert (
            unreadable_value_attributes("Measurement", {"RangeHighRatio": NUMBER}) == []
        )

    def test_should_name_nothing_when_observation_carries_a_unit_filter(self):
        assert (
            unreadable_value_attributes(
                "Observation",
                {"CodesetId": 4, "ValueAsNumber": NUMBER, "Unit": PERCENT_UNIT},
            )
            == []
        )

    def test_should_name_the_ratio_when_observation_carries_one(self):
        """OBSERVATION has no range_low/range_high, and the rendered SQL is identical."""
        assert unreadable_value_attributes(
            "Observation", {"RangeHighRatio": NUMBER}
        ) == ["RangeHighRatio"]

    def test_should_stay_silent_when_the_criteria_type_is_not_modelled(self):
        assert (
            unreadable_value_attributes("PayerPlanPeriod", {"ValueAsNumber": NUMBER})
            == []
        )

    def test_should_stay_silent_on_a_key_outside_the_value_vocabulary(self):
        """A non-value key such as ``First`` is not a guess this gate makes."""
        assert unreadable_value_attributes("DrugExposure", {"First": True}) == []

    def test_should_cover_every_criteria_type_the_domain_table_models(self):
        from src.utils.circe_lint import CRITERIA_TYPE_DOMAINS

        assert set(CRITERIA_TYPE_DOMAINS) <= set(CRITERIA_TYPE_VALUE_ATTRIBUTES), (
            "a criteria type the domain gate models but this table does not is a hole: "
            "the value gate would silently pass it"
        )


class TestRefuseUnreadableValueFilter:
    def test_should_raise_when_the_type_cannot_read_the_fragment(self):
        with pytest.raises(ValueError) as excinfo:
            refuse_unreadable_value_filter(
                "DrugExposure", {"ValueAsNumber": NUMBER}, "aspirin"
            )
        message = str(excinfo.value)
        assert "DrugExposure" in message
        assert "ValueAsNumber" in message
        assert "aspirin" in message

    def test_should_not_raise_when_the_type_can_read_the_fragment(self):
        refuse_unreadable_value_filter(
            "Measurement", {"ValueAsNumber": NUMBER, "Unit": PERCENT_UNIT}, "HbA1c"
        )

    def test_should_not_raise_on_an_empty_fragment(self):
        refuse_unreadable_value_filter("DrugExposure", {}, "aspirin")


# ---------------------------------------------------------------------------
# Delivery-gate locators
# ---------------------------------------------------------------------------


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


# The four real defects, transcribed from
# `output/site_gap/2026-09-08/deliver_20260908/*_treatment.circe.json`.
ARISTOTLE_ASPIRIN = {
    "name": "aspirin",
    "expression": {
        "Type": "ALL",
        "CriteriaList": [
            {
                "Criteria": {
                    "DrugExposure": {
                        "CodesetId": 27,
                        "ValueAsNumber": {"Value": 165.0, "Op": "gt"},
                    }
                },
                "StartWindow": {
                    "Start": {"Days": 365, "Coeff": -1},
                    "End": {"Days": 0, "Coeff": 1},
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

CARMELINA_INCRETINS = _rule(
    "GLP-1 receptor agonists use + DPP-4 inhibitors use",
    [
        _member("DrugExposure", {"CodesetId": 23, "ValueAsNumber": {"Value": 7.0, "Op": "gte"}}),
        _member("DrugExposure", {"CodesetId": 24, "ValueAsNumber": {"Value": 7.0, "Op": "gte"}}),
    ],
)

CAROLINA_T2D = _rule(
    "Type 2 diabetes + Type 2 diabetes duration > 10 years",
    [
        _member("ConditionOccurrence", {"CodesetId": 2}),
        _member(
            "ConditionOccurrence",
            {
                "CodesetId": 3,
                "ValueAsNumber": {"Value": 10.0, "Op": "gt"},
                "Unit": [{"CONCEPT_ID": 9448, "CONCEPT_NAME": "year"}],
            },
        ),
    ],
)

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

LEGITIMATE_HBA1C = _rule(
    "Elevated HbA1c",
    [
        _member(
            "Measurement",
            {"CodesetId": 5, "ValueAsNumber": {"Value": 7.0, "Op": "gte"}, "Unit": PERCENT_UNIT},
        )
    ],
)


class TestUnreadableValueFilterCriteria:
    def test_should_locate_every_real_defect_by_rule_name(self):
        findings = unreadable_value_filter_criteria(
            _shell([deepcopy(r) for r in (ARISTOTLE_ASPIRIN, CARMELINA_INCRETINS,
                                          CAROLINA_T2D, LEADER_CV_HISTORY)])
        )
        assert len(findings) == 5
        joined = "\n".join(findings)
        assert "aspirin" in joined
        assert "DrugExposure" in joined
        assert "ProcedureOccurrence" in joined
        assert "ValueAsNumber" in joined

    def test_should_find_nothing_in_a_legitimate_measurement_filter(self):
        assert unreadable_value_filter_criteria(_shell([deepcopy(LEGITIMATE_HBA1C)])) == []


# ---------------------------------------------------------------------------
# Emission-time repair
# ---------------------------------------------------------------------------


class TestDropUnreadableValueCriteria:
    def test_should_drop_the_whole_rule_when_its_only_criterion_is_unreadable(self):
        expression = _shell([deepcopy(ARISTOTLE_ASPIRIN)])
        dropped = drop_unreadable_value_criteria(expression)

        assert expression["InclusionRules"] == []
        assert len(dropped) == 1
        assert "aspirin" in dropped[0]["summary"]

    def test_should_drop_the_whole_rule_when_every_member_is_unreadable(self):
        expression = _shell([deepcopy(CARMELINA_INCRETINS)])
        drop_unreadable_value_criteria(expression)

        assert expression["InclusionRules"] == []

    def test_should_keep_the_readable_member_and_drop_only_the_unreadable_one(self):
        expression = _shell([deepcopy(LEADER_CV_HISTORY)])
        drop_unreadable_value_criteria(expression)

        groups = expression["InclusionRules"][0]["expression"]["Groups"]
        assert [g["CriteriaList"][0]["Criteria"] for g in groups] == [
            {"ConditionOccurrence": {"CodesetId": 9}},
            {"ConditionOccurrence": {"CodesetId": 10}},
            {"ConditionOccurrence": {"CodesetId": 11}},
            {"ConditionOccurrence": {"CodesetId": 13}},
        ]

    def test_should_drop_the_members_description_from_the_rule_name(self):
        expression = _shell([deepcopy(LEADER_CV_HISTORY)])
        drop_unreadable_value_criteria(expression)

        assert expression["InclusionRules"][0]["name"] == (
            "Chronic heart failure NYHA class II-III + Chronic renal failure"
            " + Prior MI + Prior stroke or TIA"
        ), (
            "the rule still advertised '>50% stenosis' while carrying no such filter, "
            "which is the same false claim the dropped criterion made"
        )

    def test_should_drop_the_duration_clause_from_the_carolina_rule_name(self):
        expression = _shell([deepcopy(CAROLINA_T2D)])
        drop_unreadable_value_criteria(expression)

        rule = expression["InclusionRules"][0]
        assert rule["name"] == "Type 2 diabetes"
        assert len(rule["expression"]["Groups"]) == 1

    def test_should_leave_the_rule_name_alone_when_the_correspondence_is_not_provable(
        self,
    ):
        """A name that does not split into one segment per member is not rewritten."""
        rule = deepcopy(LEADER_CV_HISTORY)
        rule["name"] = "Prior cardiovascular disease"
        expression = _shell([rule])
        drop_unreadable_value_criteria(expression)

        assert expression["InclusionRules"][0]["name"] == "Prior cardiovascular disease"

    def test_should_leave_a_truncated_rule_name_alone(self):
        rule = deepcopy(CAROLINA_T2D)
        rule["name"] = "Type 2 diabetes + Type 2 diabetes duratio..."
        expression = _shell([rule])
        drop_unreadable_value_criteria(expression)

        assert expression["InclusionRules"][0]["name"].endswith("...")

    def test_should_leave_a_legitimate_measurement_filter_untouched(self):
        expression = _shell([deepcopy(LEGITIMATE_HBA1C)])
        before = deepcopy(expression)

        assert drop_unreadable_value_criteria(expression) == []
        assert expression == before

    def test_should_report_only_what_it_actually_removed(self):
        """A CorrelatedCriteria is out of the repair's reach, so it is not claimed."""
        rule = deepcopy(LEGITIMATE_HBA1C)
        entry = rule["expression"]["Groups"][0]["CriteriaList"][0]
        entry["Criteria"]["Measurement"]["CorrelatedCriteria"] = {
            "Type": "ALL",
            "CriteriaList": [
                {"Criteria": {"DrugExposure": {"CodesetId": 9, "ValueAsNumber": NUMBER}}}
            ],
            "DemographicCriteriaList": [],
            "Groups": [],
        }
        expression = _shell([rule])

        assert drop_unreadable_value_criteria(expression) == [], (
            "claiming a drop the pruner never performed is worse than not repairing it"
        )
        assert unreadable_value_filter_criteria(expression) != [], (
            "what the repair cannot reach must still reach the delivery gate"
        )

    def test_should_leave_primary_criteria_untouched(self):
        """Dropping the entry criterion would empty the cohort; report it, never repair it."""
        expression = _shell([])
        expression["PrimaryCriteria"]["CriteriaList"] = [
            {"DrugEra": {"CodesetId": 1, "ValueAsNumber": NUMBER}}
        ]
        before = deepcopy(expression)

        assert drop_unreadable_value_criteria(expression) == []
        assert expression == before
        assert unreadable_value_filter_criteria(expression) != []

    def test_should_leave_the_whole_delivered_batch_of_legitimate_filters_intact(self):
        """The 108 legitimate filters must survive; only the 10 defective ones go."""
        rules = [deepcopy(LEGITIMATE_HBA1C) for _ in range(10)]
        rules.append(deepcopy(ARISTOTLE_ASPIRIN))
        expression = _shell(rules)

        drop_unreadable_value_criteria(expression)

        assert len(expression["InclusionRules"]) == 10
        assert all(
            r["expression"]["Groups"][0]["CriteriaList"][0]["Criteria"]["Measurement"][
                "Unit"
            ]
            for r in expression["InclusionRules"]
        )


# ---------------------------------------------------------------------------
# Wiring -- the three generation merge sites and the one emission site
# ---------------------------------------------------------------------------


class TestSeededBuilderRefusesAtGeneration:
    def test_should_refuse_the_criterion_when_its_type_cannot_read_the_constraint(self):
        from src.services.tte_service import TTEService

        service = TTEService.__new__(TTEService)
        service._recommend_seeded_concept_set = lambda label, **kw: {
            "name": label,
            "domain": "Drug",
            "expression": {"items": [{"concept": {"CONCEPT_ID": 1, "DOMAIN_ID": "Drug"}}]},
        }

        with pytest.raises(ValueError) as excinfo:
            service._build_seeded_eligibility_rule(
                criterion={
                    "id": 1,
                    "sourceText": "aspirin > 165 mg/day",
                    "domain": "Drug",
                    "valueConstraint": {"op": "gt", "value": 165.0, "unitText": "mg"},
                },
                codeset_id=27,
                exclusion=True,
            )
        assert "DrugExposure" in str(excinfo.value)

    def test_should_build_the_rule_when_its_type_can_read_the_constraint(self):
        from src.services.tte_service import TTEService

        service = TTEService.__new__(TTEService)
        service._recommend_seeded_concept_set = lambda label, **kw: {
            "name": label,
            "domain": "Measurement",
            "expression": {
                "items": [{"concept": {"CONCEPT_ID": 1, "DOMAIN_ID": "Measurement"}}]
            },
        }

        built = service._build_seeded_eligibility_rule(
            criterion={
                "id": 1,
                "sourceText": "HbA1c >= 7%",
                "domain": "Measurement",
                "valueConstraint": {"op": "gte", "value": 7.0, "unitText": "%"},
            },
            codeset_id=5,
            exclusion=False,
        )
        body = built["rule"]["expression"]["CriteriaList"][0]["Criteria"]["Measurement"]
        assert body["ValueAsNumber"] == {"Value": 7.0, "Op": "gte"}


class TestEmittableExpressionRepairsAStoredExpression:
    def test_should_drop_the_unreadable_criterion_the_arm_builder_deepcopied(self):
        from src.services.tte_service import TTEService

        stored = _shell([deepcopy(ARISTOTLE_ASPIRIN), deepcopy(LEGITIMATE_HBA1C)])
        emitted = TTEService._build_emittable_expression(lambda: deepcopy(stored))

        assert [r["name"] for r in emitted["InclusionRules"]] == ["Elevated HbA1c"]
        assert unreadable_value_filter_criteria(emitted) == []


# ---------------------------------------------------------------------------
# Builder B -- src/agents/agent3/assembler.py, both of its merge sites.
#
# `docs/reviews/2026-07-30_fallback_audit.md` MISC-01 records that the
# domain -> criteria-type decision lives in four places. A gate applied to one
# merge site and not the others is this tree's most repeated defect, so both of
# the assembler's sites are pinned here alongside the service's.
#
# The IR stand-ins below are deliberately plain dataclasses.
# `tests/test_parser_paper_status.py` replaces `src.models.ir.Criteria` and
# `.ValueConstraint` with MagicMocks at import time and never restores them, so
# importing the real classes would make this file pass or fail on collection
# order. Both builders reach the IR through plain attribute access.
# ---------------------------------------------------------------------------


@dataclass
class _VC:
    op: str
    value: float
    reference_bound: str = "absolute"
    unit_text: str | None = None
    unit_concept_id: int | None = None


@dataclass
class _Crit:
    name: str
    domain: str
    entity_text: str | None = None
    source_text: str | None = None
    concept_set_id: int | None = None
    logic_type: str = "PRESENCE"
    window: Any = None
    value_constraint: _VC | None = None
    sub_criteria: list["_Crit"] = field(default_factory=list)
    group_type: str = "ALL"
    conditional: bool = False


@pytest.fixture
def assembler():
    from src.agents.agent3.assembler import CohortAssembler

    built = CohortAssembler.__new__(CohortAssembler)
    built._find_concept_set_id = lambda entity_text, concept_sets: 7
    return built


def _emitted_criteria(rule: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        next(iter(entry["Criteria"].values()))
        for entry in rule["expression"]["CriteriaList"]
    ]


class TestAssemblerAtomicBranchRefuses:
    def test_should_skip_the_rule_when_a_drug_criterion_carries_a_value_constraint(
        self, assembler
    ):
        rule = assembler._build_inclusion_rule(
            _Crit(
                name="aspirin > 165 mg/day",
                domain="Drug",
                entity_text="aspirin",
                value_constraint=_VC(op="gt", value=165.0, unit_text="mg"),
            ),
            [],
            0,
            is_exclusion=True,
        )

        assert rule["expression"]["CriteriaList"] == [], (
            "a DrugExposure ignores ValueAsNumber, so this rule excluded everyone on "
            "any aspirin at all while reading as '> 165 mg/day'"
        )
        assert (
            assembler._validate_and_heal(rule, rule["name"], "aspirin").action == "SKIP"
        )

    def test_should_build_the_rule_when_a_measurement_carries_the_same_constraint(
        self, assembler
    ):
        rule = assembler._build_inclusion_rule(
            _Crit(
                name="HbA1c >= 7%",
                domain="Measurement",
                entity_text="HbA1c",
                value_constraint=_VC(op="gte", value=7.0, unit_text="%"),
            ),
            [],
            0,
        )

        assert _emitted_criteria(rule)[0]["ValueAsNumber"] == {"Value": 7.0, "Op": "gte"}


class TestAssemblerCompositeBranchRefuses:
    def test_should_emit_only_the_member_whose_type_can_read_the_constraint(
        self, assembler
    ):
        group = _Crit(
            name="Type 2 diabetes + Type 2 diabetes duration > 10 years",
            domain="Condition",
            entity_text="Type 2 diabetes",
            group_type="ANY",
            sub_criteria=[
                _Crit(name="Type 2 diabetes", domain="Condition", entity_text="T2D"),
                _Crit(
                    name="Type 2 diabetes duration > 10 years",
                    domain="Condition",
                    entity_text="T2D duration",
                    value_constraint=_VC(op="gt", value=10.0, unit_text="years"),
                ),
            ],
        )

        rule = assembler._build_inclusion_rule(group, [], 0)

        emitted = _emitted_criteria(rule)
        assert len(emitted) == 1
        assert "ValueAsNumber" not in emitted[0]

    def test_should_keep_every_member_when_the_group_is_measurement_domain(
        self, assembler
    ):
        group = _Crit(
            name="Elevated liver enzymes",
            domain="Measurement",
            entity_text="liver enzymes",
            value_constraint=_VC(op="gt", value=3.0, unit_text="x ULN"),
            sub_criteria=[
                _Crit(name=name, domain="Measurement", entity_text=name)
                for name in ("ALT", "AST", "ALP")
            ],
        )

        rule = assembler._build_inclusion_rule(group, [], 0, is_exclusion=True)

        emitted = _emitted_criteria(rule)
        assert len(emitted) == 3
        assert all(c["RangeHighRatio"] == {"Value": 3.0, "Op": "gt"} for c in emitted)


class TestEveryMergeSiteIsGated:
    """No `build_measurement_value_filter` result reaches a criteria dict ungated."""

    def test_should_gate_every_call_site_of_the_value_filter_builder(self):
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        sites = []
        for path in (
            root / "src" / "services" / "tte_service.py",
            root / "src" / "agents" / "agent3" / "assembler.py",
        ):
            text = path.read_text()
            for match in re.finditer(r"build_measurement_value_filter\(", text):
                line_no = text.count("\n", 0, match.start()) + 1
                window = "\n".join(
                    text.splitlines()[max(0, line_no - 1) : line_no + 25]
                )
                if "unreadable_value_attributes" not in window and (
                    "refuse_unreadable_value_filter" not in window
                ):
                    sites.append(f"{path.name}:{line_no}")
        assert sites == [], (
            "these merge sites drop a value filter onto a criteria dict without "
            f"asking whether the type reads it: {sites}"
        )
