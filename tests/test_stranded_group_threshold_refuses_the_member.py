"""A group threshold that cannot be handed down must refuse the member, not strand it.

``resolve_group_member_constraint`` refuses to copy an ABSOLUTE bound onto a group's
members, and that refusal is correct: "> 240 mg/dL" on HbA1c -- reported in % or
mmol/mol -- matches zero rows, and inside an ABSENCE exclusion that turns a visible
over-exclusion into a silent no-op.

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
members that actually shipped carried no record at all. Refusing them is the same choice
``refuse_domain_contradiction`` and ``refuse_unreadable_value_filter`` already make:
raise, let the caller record the criterion and drop it, and leave the rule honestly
absent instead of present and vacuous.

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
    @pytest.mark.parametrize(
        ("member", "codeset_id"),
        [(GLUCOSE_MEMBERS[0], 66), (GLUCOSE_MEMBERS[1], 67), (GLUCOSE_MEMBERS[2], 68)],
        ids=["HbA1c/66", "FastingPlasmaGlucose/67", "RandomPlasmaGlucose/68"],
    )
    def test_should_refuse_with_stranded_group_threshold_when_the_label_bound_is_absolute(
        self, service, member, codeset_id
    ):
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
            f"over every glucose measurement on record"
        )
        assert excinfo.value.detail == STRANDED_GROUP_CONSTRAINT_REASON

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

    def test_should_leave_no_rule_at_all_when_every_member_of_the_group_refuses(
        self, service
    ):
        """The deliberate consequence: the exclusion has genuinely left the cohort.

        Emitting *something* to keep the gate quiet is the defect, not the fix -- a
        delivery shipping without the protocol's exclusion should not pass.
        """
        built = service._build_seeded_target_circe(
            {
                "targetCohortName": "linagliptin",
                "inclusionCriteria": [],
                "exclusionCriteria": [GLUCOSE_LABEL, *GLUCOSE_MEMBERS],
            }
        )

        assert _measurement_bodies(built) == [], (
            "an unfiltered ABSENCE over the whole concept set is worse than no rule: "
            "it excludes every patient the inclusion criteria required"
        )

    def test_should_record_every_refused_member_with_its_code(self, service):
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
        assert {record["criterionId"] for record in stranded} == {"45", "46", "47"}
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

        assert rule["expression"]["CriteriaList"] == [], (
            "each member emitted {'CodesetId': N} with no value filter, so the ABSENCE "
            "rule matched every glucose measurement on record"
        )

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
            service._recommend_seeded_concept_set_rag_fallback("Risk factor 1")

        assert describe_mapping_failure(excinfo.value)["refusalCode"] == (
            REFUSAL_NO_CONCEPT_MAPPING
        )
