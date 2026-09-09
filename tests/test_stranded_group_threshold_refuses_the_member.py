"""A group threshold that cannot be handed down must refuse the member, not strand it.

``resolve_group_member_constraint`` refuses to copy an ABSOLUTE bound onto a member
whose analyte is measured in another unit, and that refusal is correct: "> 240 mg/dL"
on HbA1c -- reported in % or mmol/mol -- matches zero rows, and inside an ABSENCE
exclusion that turns a visible over-exclusion into a silent no-op. The two Plasma
Glucose members of the same group ARE measured in mg/dL, so the same bound reaches
them; the refusal is per member, not per group.

The defect was what happened next. ``_build_seeded_eligibility_rule`` read only
``.constraint`` off the resolution and dropped ``refusal_reason`` on the floor;
``build_measurement_value_filter(None)`` returns ``{}``, so the member emitted with
``criteria_attrs == {"CodesetId": N}`` -- an UNFILTERED ABSENCE, i.e. "exclude any
patient with any glucose measurement at all".

Measured on the delivered 2026-09-08 batch (``tmp/tte_cold6_20260908/studies.json``,
sha256 ``e751e225...f221b``), study 10 = CAROLINA: exclusion group label #44 'Glucose'
carries ``{gt 240.0 mg/dl absolute}``; members #45/#46/#47 (HbA1c, Fasting Plasma
Glucose, Random Plasma Glucose, conceptSetIds 66/67/68) all carry
``valueConstraint: null``. Each emitted ``{"Criteria": {"Measurement": {"CodesetId":
66}}, "Occurrence": {"Type": 0, "Count": 0}}``. Rule 36 then excluded any glucose
measurement in the last 180 days while inclusion rule 5 REQUIRED an HbA1c >= 6.5 in the
same window, over codesets overlapping on 4 of 6 presence concepts.

The stranding WAS recorded -- against the group label, which never emits -- so the three
members that actually shipped carried no record at all. Refusing a member is the same
choice ``refuse_domain_contradiction`` and ``refuse_unreadable_value_filter`` already
make: raise, let the caller record the criterion and drop it, and leave the rule
honestly absent instead of present and vacuous.

Refusing ALL THREE, though, was only ever half the repair. mg/dL measures #46 and #47
exactly as the protocol intended; only #45 is reported in another unit. So the bound is
distributed by analyte and #45 alone refuses -- the protocol's exclusion keeps two of
its three arms instead of leaving the cohort entirely.

The rows below are transcribed verbatim from that store.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.services.value_constraint import STRANDED_GROUP_CONSTRAINT_REASON
from src.utils.circe_lint import (
    refuse_domain_contradiction,
    refuse_unreadable_value_filter,
)
from src.utils.criterion_refusal import (
    REFUSAL_CODES,
    REFUSAL_DOMAIN_CONTRADICTION,
    REFUSAL_INTENT_UNPARSED,
    REFUSAL_NO_CONCEPT_MAPPING,
    REFUSAL_STRANDED_GROUP_THRESHOLD,
    REFUSAL_UNREADABLE_VALUE_FILTER,
    CriterionRefused,
)

# `tests/test_parser_paper_status.py` replaces `src.models.ir.Criteria` /
# `.ValueConstraint` with MagicMocks at import time and never restores them, so
# importing the real classes here would make this file pass or fail on collection
# order. The assembler reads the IR through plain attribute access, so these
# stand-ins are the contract it actually consumes -- the same choice, for the same
# reason, as `tests/test_group_label_value_constraint_propagation.py`, whose
# `TestStandInsMatchTheRealIR` pins the field names against the real model.


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

# --------------------------------------------------------------------------
# CAROLINA, store study 10, exclusion group a0c65a7e-0cb2-4498-99d4-f7de0a9779cd.
# --------------------------------------------------------------------------

CAROLINA_GLUCOSE_GROUP_ID = "a0c65a7e-0cb2-4498-99d4-f7de0a9779cd"
CAROLINA_GLUCOSE_LABEL_CONSTRAINT = {
    "op": "gt",
    "value": 240.0,
    "unitText": "mg/dl",
    "referenceBound": "absolute",
    "unitConceptId": None,
}
# The same shape with a unit-free bound. This one IS handed down, so it must NOT refuse
# -- a fix that refuses both directions has only traded a silent over-exclusion for a
# silently missing rule.
RATIO_LABEL_CONSTRAINT = {
    "op": "gt",
    "value": 3.0,
    "unitText": "x ULN",
    "referenceBound": "absolute",
    "unitConceptId": None,
}


def _row(
    criterion_id: int,
    text: str,
    *,
    is_label: bool,
    constraint: dict | None,
    group_id: str = CAROLINA_GLUCOSE_GROUP_ID,
) -> dict[str, Any]:
    return {
        "id": criterion_id,
        "description": text,
        "sourceText": text,
        "domain": "Measurement",
        "valueConstraint": constraint,
        "isGroupLabel": is_label,
        "groupId": group_id,
        "groupType": "ALL",
        "logicType": "ABSENCE",
        "window": {"start": -180, "end": 0},
    }


GLUCOSE_LABEL = _row(44, "Glucose", is_label=True, constraint=CAROLINA_GLUCOSE_LABEL_CONSTRAINT)
GLUCOSE_MEMBERS = [
    _row(45, "Hemoglobin A1c", is_label=False, constraint=None),
    _row(46, "Fasting Plasma Glucose", is_label=False, constraint=None),
    _row(47, "Random Plasma Glucose", is_label=False, constraint=None),
]


@pytest.fixture
def service():
    """A TTEService with only the vector-search / Agent2 hop stubbed out."""
    from src.services.tte_service import TTEService

    svc = TTEService.__new__(TTEService)
    svc._recommend_seeded_concept_set = MagicMock(
        side_effect=lambda name, expected_domain=None, workflow=None, **kw: {
            "name": name,
            "domain": "Measurement",
            # A real LOINC HbA1c concept, so the domain check upstream of the refusal
            # passes and the refusal under test is the one that fires.
            "expression": {
                "items": [{"concept": {"CONCEPT_ID": 3004410, "DOMAIN_ID": "Measurement"}}]
            },
        }
    )
    return svc


def _measurement_bodies(built: dict[str, Any]) -> list[dict[str, Any]]:
    bodies: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "Criteria" and isinstance(value, dict):
                    body = value.get("Measurement")
                    if isinstance(body, dict):
                        bodies.append(body)
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for rule in built.get("InclusionRules") or []:
        walk(rule)
    return bodies


class TestTheRealCarolinaGroupRefusesInsteadOfEmittingUnfiltered:
    def test_should_refuse_the_member_whose_analyte_is_not_measured_in_that_unit(
        self, service
    ):
        member, codeset_id = GLUCOSE_MEMBERS[0], 66

        with pytest.raises(CriterionRefused) as excinfo:
            service._build_seeded_eligibility_rule(
                criterion=member,
                codeset_id=codeset_id,
                exclusion=True,
                parent_value_constraint=CAROLINA_GLUCOSE_LABEL_CONSTRAINT,
            )

        assert excinfo.value.code == REFUSAL_STRANDED_GROUP_THRESHOLD, (
            f"criterion #{member['id']} {member['sourceText']!r} emitted "
            f'{{"CodesetId": {codeset_id}}} with no value filter -- an ABSENCE rule '
            f"over every HbA1c measurement on record"
        )
        assert excinfo.value.detail == STRANDED_GROUP_CONSTRAINT_REASON
        assert "% (percent)" in str(excinfo.value), (
            "a refusal that does not name the analyte, its unit and the label's unit "
            "leaves a human no way to tell a table gap from a protocol that really "
            "wrote an incompatible threshold"
        )

    @pytest.mark.parametrize(
        ("member", "codeset_id"),
        [(GLUCOSE_MEMBERS[1], 67), (GLUCOSE_MEMBERS[2], 68)],
        ids=["FastingPlasmaGlucose/67", "RandomPlasmaGlucose/68"],
    )
    def test_should_hand_the_bound_to_the_members_mg_dl_measures(
        self, service, member, codeset_id
    ):
        """Refusing these two was the over-correction: mg/dL is exactly the unit a
        plasma glucose is reported in, so '> 240' is the protocol's own threshold."""
        built = service._build_seeded_eligibility_rule(
            criterion=member,
            codeset_id=codeset_id,
            exclusion=True,
            parent_value_constraint=CAROLINA_GLUCOSE_LABEL_CONSTRAINT,
        )

        body = built["rule"]["expression"]["CriteriaList"][0]["Criteria"]["Measurement"]
        assert body["ValueAsNumber"] == {"Value": 240.0, "Op": "gt"}
        assert [unit["CONCEPT_ID"] for unit in body["Unit"]] == [8840]

    def test_should_not_refuse_a_member_of_a_reference_relative_group(self, service):
        """The propagating direction must survive: '> 3x ULN' IS handed down."""
        built = service._build_seeded_eligibility_rule(
            criterion=GLUCOSE_MEMBERS[0],
            codeset_id=66,
            exclusion=True,
            parent_value_constraint=RATIO_LABEL_CONSTRAINT,
        )

        body = built["rule"]["expression"]["CriteriaList"][0]["Criteria"]["Measurement"]
        assert body["RangeHighRatio"] == {"Value": 3.0, "Op": "gt"}

    def test_should_not_refuse_a_member_that_carries_its_own_threshold(self, service):
        """A member grounded per sub-criterion keeps its own answer and still emits."""
        member = dict(
            GLUCOSE_MEMBERS[0],
            valueConstraint={
                "op": "gt", "value": 6.5, "unitText": "%",
                "referenceBound": "absolute", "unitConceptId": None,
            },
        )

        built = service._build_seeded_eligibility_rule(
            criterion=member,
            codeset_id=66,
            exclusion=True,
            parent_value_constraint=CAROLINA_GLUCOSE_LABEL_CONSTRAINT,
        )

        body = built["rule"]["expression"]["CriteriaList"][0]["Criteria"]["Measurement"]
        assert body["ValueAsNumber"] == {"Value": 6.5, "Op": "gt"}

    def test_should_emit_only_the_two_members_the_bound_can_filter(self, service):
        """The whole group, built from the real store rows.

        An unfiltered ABSENCE over the whole concept set is worse than no rule -- it
        excludes every patient the inclusion criteria required -- so the member that
        cannot be filtered is absent. The two that can are filtered, not dropped:
        emitting nothing at all would surrender an exclusion the protocol wrote and
        mg/dL measures perfectly well.
        """
        built = service._build_seeded_target_circe(
            {
                "targetCohortName": "linagliptin",
                "inclusionCriteria": [],
                "exclusionCriteria": [GLUCOSE_LABEL, *GLUCOSE_MEMBERS],
            }
        )

        bodies = _measurement_bodies(built)
        assert len(bodies) == 2, (
            f"expected #46 Fasting Plasma Glucose and #47 Random Plasma Glucose to "
            f"emit and #45 Hemoglobin A1c to refuse; got {len(bodies)}: {bodies}"
        )
        for body in bodies:
            assert body["ValueAsNumber"] == {"Value": 240.0, "Op": "gt"}
            assert [unit["CONCEPT_ID"] for unit in body["Unit"]] == [8840]

    def test_should_record_the_refused_member_with_its_code(self, service):
        """The loss was recorded against the LABEL, which never emits. The members
        that actually shipped carried no record at all -- that is what this pins."""
        built = service._build_seeded_target_circe(
            {
                "targetCohortName": "linagliptin",
                "inclusionCriteria": [],
                "exclusionCriteria": [GLUCOSE_LABEL, *GLUCOSE_MEMBERS],
            }
        )

        unmapped = built["_unmappedCriteria"]
        stranded = [
            record
            for record in unmapped
            if record.get("refusalCode") == REFUSAL_STRANDED_GROUP_THRESHOLD
        ]
        assert {record["criterionId"] for record in stranded} == {"45"}
        for record in stranded:
            assert record["refusalDetail"] == STRANDED_GROUP_CONSTRAINT_REASON
            assert record["reason"].strip()


class TestTheCirceLintRefusalsCarryAMachineReadableCode:
    """Both raised a bare ``ValueError``, which records ``refusalCode: None`` -- and
    every consumer reads ``None`` as "nothing deliberately refused", i.e. a FAILURE."""

    def test_should_raise_domain_contradiction_when_the_set_is_from_another_domain(self):
        mapped = {
            "name": "Glimepiride",
            "domain": "Drug",
            "expression": {"items": [{"concept": {"CONCEPT_ID": 1597756, "DOMAIN_ID": "Drug"}}]},
        }

        with pytest.raises(CriterionRefused) as excinfo:
            refuse_domain_contradiction("ConditionOccurrence", mapped, "Glimepiride")

        assert excinfo.value.code == REFUSAL_DOMAIN_CONTRADICTION

    def test_should_raise_unreadable_value_filter_when_the_table_has_no_such_column(self):
        with pytest.raises(CriterionRefused) as excinfo:
            refuse_unreadable_value_filter(
                "DrugExposure", {"ValueAsNumber": {"Value": 165.0, "Op": "gt"}}, "aspirin"
            )

        assert excinfo.value.code == REFUSAL_UNREADABLE_VALUE_FILTER

    @pytest.mark.parametrize(
        ("call", "args"),
        [
            (
                refuse_domain_contradiction,
                (
                    "ConditionOccurrence",
                    {
                        "name": "Glimepiride",
                        "domain": "Drug",
                        "expression": {
                            "items": [{"concept": {"CONCEPT_ID": 1597756, "DOMAIN_ID": "Drug"}}]
                        },
                    },
                    "Glimepiride",
                ),
            ),
            (
                refuse_unreadable_value_filter,
                ("DrugExposure", {"ValueAsNumber": {"Value": 165.0, "Op": "gt"}}, "aspirin"),
            ),
        ],
        ids=["domain-contradiction", "unreadable-value-filter"],
    )
    def test_should_still_be_a_value_error_so_existing_handlers_keep_working(
        self, call, args
    ):
        with pytest.raises(ValueError):
            call(*args)

    def test_should_keep_circe_lint_pure(self):
        """`circe_lint` may import the vocabulary because it costs no I/O."""
        import src.utils.criterion_refusal as vocab

        assert not hasattr(vocab, "requests")
        assert vocab.__file__.endswith("criterion_refusal.py")


class TestTheVocabularyIsClosed:
    """A code raised but not registered fails at the GATE, far from the raise site."""

    @pytest.mark.parametrize(
        "code",
        [
            REFUSAL_STRANDED_GROUP_THRESHOLD,
            REFUSAL_DOMAIN_CONTRADICTION,
            REFUSAL_UNREADABLE_VALUE_FILTER,
        ],
    )
    def test_should_register_every_new_code(self, code):
        assert code in REFUSAL_CODES
        assert CriterionRefused("a reason", code=code).code == code

    def test_should_reject_an_unregistered_code_at_construction(self):
        with pytest.raises(ValueError, match="not in the vocabulary"):
            CriterionRefused("a reason", code="stranded_group_threshold")

    def test_should_reject_an_empty_reason(self):
        with pytest.raises(ValueError, match="needs a reason"):
            CriterionRefused("   ", code=REFUSAL_STRANDED_GROUP_THRESHOLD)


class TestTheAssemblerDropsTheMemberRatherThanEmittingItUnfiltered:
    """The `CohortAssembler` path read `refusal_reason` and only LOGGED it, then emitted
    the member unfiltered anyway. Its refusal channel is `continue` + the SKIP that
    `_validate_and_heal` records -- not a raise, because the store row must survive so
    the threshold can be re-grounded per sub-criterion at extraction."""

    def test_should_not_emit_a_member_whose_group_threshold_was_refused(self):
        from src.agents.agent3.assembler import CohortAssembler

        rule = CohortAssembler()._build_inclusion_rule(
            _Crit(
                name="Uncontrolled hyperglycaemia",
                domain="Measurement",
                entity_text="Glucose",
                logic_type="ABSENCE",
                value_constraint=_VC(op="gt", value=240.0, unit_text="mg/dL"),
                sub_criteria=[
                    _Crit(name=n, domain="Measurement", entity_text=n, logic_type="ABSENCE")
                    for n in (
                        "Elevated HbA1c",
                        "Elevated Fasting Glucose",
                        "Elevated Random Glucose",
                    )
                ],
            ),
            [],
            0,
            is_exclusion=True,
        )

        emitted = rule["expression"]["CriteriaList"]
        assert len(emitted) == 2, (
            f"each member emitted {{'CodesetId': N}} with no value filter, so the "
            f"ABSENCE rule matched every glucose measurement on record; expected the "
            f"two glucose members filtered and HbA1c dropped, got {len(emitted)}"
        )
        for entry in emitted:
            body = entry["Criteria"]["Measurement"]
            assert body["ValueAsNumber"] == {"Value": 240.0, "Op": "gt"}
            assert [unit["CONCEPT_ID"] for unit in body["Unit"]] == [8840]

    def test_should_still_emit_members_of_a_reference_relative_group(self):
        """The propagating direction must survive here too."""
        from src.agents.agent3.assembler import CohortAssembler

        rule = CohortAssembler()._build_inclusion_rule(
            _Crit(
                name="Impaired hepatic function",
                domain="Measurement",
                entity_text="Liver enzymes",
                logic_type="ABSENCE",
                value_constraint=_VC(op="gt", value=3.0, unit_text="x ULN"),
                sub_criteria=[
                    _Crit(name=n, domain="Measurement", entity_text=n, logic_type="ABSENCE")
                    for n in ("ALT", "AST", "ALP")
                ],
            ),
            [],
            0,
            is_exclusion=True,
        )

        bodies = [
            entry["Criteria"]["Measurement"]
            for entry in rule["expression"]["CriteriaList"]
        ]
        assert len(bodies) == 3
        for body in bodies:
            assert body["RangeHighRatio"] == {"Value": 3.0, "Op": "gt"}


class TestTheTemporalSeedIsAlreadyClassifiedAsIntentUnparsed:
    """A seed the intent router rejected for a TEMPORAL qualifier is `intent-unparsed`.

    The delivery gate reports these CARMELINA rows as::

        No concept mapping found for 'Cancer other than nonmelanoma skin cancer
        within 3 years': Temporal logic detected in: '...'

    which reads like `no-concept-mapping`. It is not: that sentence is only the
    human-readable `reason`, and the branch that builds it already carries
    `REFUSAL_INTENT_UNPARSED`. The store rows that motivated the report
    (`tmp/tte_cold6_20260908/studies.json`, study 9, criteria 13/10/11/13) carry NO
    `refusalCode` field at all because the whole record shape postdates that batch --
    the store was written 2026-09-08, `criterion_refusal.py` landed 2026-09-09.

    Pinned here so "the message says one thing, the code says another" cannot later be
    resolved in the wrong direction.
    """

    def test_should_classify_a_temporal_router_refusal_as_intent_unparsed(self, service):
        from src.services.tte_service import describe_mapping_failure

        seed = "Cancer other than nonmelanoma skin cancer within 3 years"

        class _EmptyWithTemporalFallback:
            include_recommendations: list = []
            fallback_reason = f"Temporal logic detected in: '{seed}'"

        service._get_seeded_concept_set_recommender = MagicMock(
            return_value=MagicMock(recommend=lambda *a, **kw: _EmptyWithTemporalFallback())
        )

        with pytest.raises(CriterionRefused) as excinfo:
            service._recommend_seeded_concept_set_rag_fallback(seed)

        record = describe_mapping_failure(excinfo.value)
        assert record["refusalCode"] == REFUSAL_INTENT_UNPARSED, (
            "the router refused a temporal qualifier that belongs in the criterion's "
            "`window`; classifying it as no-concept-mapping would blame the vocabulary"
        )
        assert record["refusalDetail"] == f"Temporal logic detected in: '{seed}'"

    def test_should_still_classify_a_genuine_vocabulary_miss_as_no_concept_mapping(
        self, service
    ):
        from src.services.tte_service import describe_mapping_failure

        class _EmptyWithNoFallback:
            include_recommendations: list = []
            fallback_reason = None

        service._get_seeded_concept_set_recommender = MagicMock(
            return_value=MagicMock(recommend=lambda *a, **kw: _EmptyWithNoFallback())
        )

        with pytest.raises(CriterionRefused) as excinfo:
            service._recommend_seeded_concept_set_rag_fallback("Contraindication to clopidogrel")

        assert describe_mapping_failure(excinfo.value)["refusalCode"] == (
            REFUSAL_NO_CONCEPT_MAPPING
        )


# --------------------------------------------------------------------------
# PLATO, store study 2, inclusion group 8e787307-e68e-49c6-9318-2203dc47dde2.
# --------------------------------------------------------------------------
# The counter-case to everything above. This label's "bound" is a COUNT of the group's
# own members -- "≥2 of the following:" -- and `parse_value_constraints` handed back
# `unitText: "of the following:"`, the tail of the English phrase, which is not a unit.
# None of the four members is measured in it, because none of them is measured at all,
# so all four left as `stranded-group-threshold` and PLATO's entire "≥2 risk factors"
# criterion was lost. On 2026-09-09, before the label carried an absolute bound,
# `Diabetes Mellitus` (concept set 8) emitted as a plain ConditionOccurrence.
#
# Rows transcribed verbatim from `output/site_gap/2026-09-10/store/studies.json`.

PLATO_RISK_FACTOR_GROUP_ID = "8e787307-e68e-49c6-9318-2203dc47dde2"
PLATO_COUNT_LABEL_CONSTRAINT = {
    "op": "gte",
    "value": 2.0,
    "unitText": "of the following:",
    "referenceBound": "absolute",
    "unitConceptId": None,
}


def _plato_row(
    criterion_id: int,
    description: str,
    source_text: str,
    domain: str,
    *,
    is_label: bool,
    constraint: dict | None,
) -> dict[str, Any]:
    return {
        "id": criterion_id,
        "description": description,
        "sourceText": source_text,
        "domain": domain,
        "valueConstraint": constraint,
        "isGroupLabel": is_label,
        "groupId": PLATO_RISK_FACTOR_GROUP_ID,
        "groupType": "ANY",
        "logicType": "PRESENCE",
        "window": None,
    }


PLATO_COUNT_LABEL = _plato_row(
    38,
    "At least 2 of the following risk factors",
    "Risk factor",
    "Observation",
    is_label=True,
    constraint=PLATO_COUNT_LABEL_CONSTRAINT,
)
PLATO_RISK_FACTORS = [
    _plato_row(39, "Hypertension", "Hypertension", "Condition", is_label=False, constraint=None),
    _plato_row(
        40, "Diabetes Mellitus", "Diabetes Mellitus", "Condition", is_label=False, constraint=None
    ),
    _plato_row(
        41, "Smoking Status", "Current smoker", "Observation", is_label=False, constraint=None
    ),
    _plato_row(42, "Obesity", "Obesity", "Condition", is_label=False, constraint=None),
]


@pytest.fixture
def domain_echoing_service():
    """As `service`, but the mapper answers in the domain the criterion asked for.

    PLATO's members are Conditions and an Observation, so a mapper hard-wired to
    Measurement would refuse them under `domain-contradiction` and the refusal under
    test would never be the one that fired.
    """
    from src.services.tte_service import TTEService

    svc = TTEService.__new__(TTEService)

    def _mapped(name, expected_domain=None, workflow=None, **_kw):
        domain = expected_domain or "Condition"
        return {
            "name": name,
            "domain": domain,
            "expression": {
                "items": [{"concept": {"CONCEPT_ID": 316866, "DOMAIN_ID": domain}}]
            },
        }

    svc._recommend_seeded_concept_set = MagicMock(side_effect=_mapped)
    return svc


class TestAGroupCardinalityStrandsNobody:
    def test_should_not_produce_the_count_at_all(self):
        """Root cause. The label never had a threshold to strand its members with."""
        from src.services.value_constraint import parse_value_constraints

        assert parse_value_constraints("≥2 of the following:") == []
        assert parse_value_constraints("At least 2 of the following risk factors") == []

    @pytest.mark.parametrize(
        "member",
        PLATO_RISK_FACTORS,
        ids=["Hypertension/39", "DiabetesMellitus/40", "CurrentSmoker/41", "Obesity/42"],
    )
    def test_should_emit_a_member_whose_label_carries_only_a_count(
        self, domain_echoing_service, member
    ):
        """Second line of defence, for the stores already written with the count in them.

        A count is not a bound, so there is nothing to hand down and nothing was lost --
        the member emits exactly as it would with no label constraint at all.
        """
        built = domain_echoing_service._build_seeded_eligibility_rule(
            criterion=member,
            codeset_id=member["id"],
            exclusion=False,
            parent_value_constraint=PLATO_COUNT_LABEL_CONSTRAINT,
        )

        body = built["rule"]["expression"]["CriteriaList"][0]["Criteria"]
        assert list(body) == [
            "ConditionOccurrence" if member["domain"] == "Condition" else "Observation"
        ]
        assert "ValueAsNumber" not in next(iter(body.values()))

    def test_should_build_all_four_risk_factors_from_the_real_store_rows(
        self, domain_echoing_service
    ):
        """The whole group, as delivered. Before: four `stranded-group-threshold` rows
        and no InclusionRule at all."""
        built = domain_echoing_service._build_seeded_target_circe(
            {
                "targetCohortName": "ticagrelor",
                "inclusionCriteria": [PLATO_COUNT_LABEL, *PLATO_RISK_FACTORS],
                "exclusionCriteria": [],
            }
        )

        stranded = [
            record
            for record in built.get("_unmappedCriteria") or []
            if record.get("refusalCode") == REFUSAL_STRANDED_GROUP_THRESHOLD
        ]
        assert stranded == [], (
            f"PLATO's '≥2 of the following' is a group cardinality, not a measurement "
            f"threshold; refusing its members loses the whole criterion: {stranded}"
        )
        assert len(built.get("InclusionRules") or []) == 1

    def test_should_not_skip_the_label_as_stranded(self, domain_echoing_service):
        """The census must stop reporting a loss that no longer happens."""
        built = domain_echoing_service._build_seeded_target_circe(
            {
                "targetCohortName": "ticagrelor",
                "inclusionCriteria": [PLATO_COUNT_LABEL, *PLATO_RISK_FACTORS],
                "exclusionCriteria": [],
            }
        )

        label_skips = [
            record
            for record in built.get("_skippedCriteria") or []
            if record.get("criterionId") == "38"
        ]
        assert [record["reason"] for record in label_skips] != [
            STRANDED_GROUP_CONSTRAINT_REASON
        ]
