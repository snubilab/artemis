"""RFC-016 step 3 in the build: the annotation decides how a threshold is emitted.

Real rows throughout (``tests/fixtures/rfc016_quantity_rows.json``, with the SHA-256 of
each source). The mapper is a stub answering in the domain the criterion asks for, its
concepts are SNOMED so the LOINC specimen step is not reached, and the member LOINC
properties are stubbed where a test needs them; nothing reaches an LLM or a database.

What is pinned:

* ``reference_bound`` comes from the annotation, never from ``unitText`` (A21 deleted):
  "x ULN" in a unit slot is an unresolvable unit without an annotation, and a
  ``RangeHighRatio`` with one;
* a threshold whose verified ``quantity_kind`` is not a lab value is never a value filter,
  instead of an English word list rejecting it (A5b). By kind (coordinator, 2026-10-12): a
  ``dose`` or ``statistical`` threshold skips the WHOLE criterion, recorded under
  ``_skippedCriteria`` with reason, kind and span (and a group label takes its members);
  a ``duration``, ``count`` or non-Measurement ``other`` threshold keeps the criterion and
  is recorded under ``_unrepresentableThresholds``;
* a group label whose threshold is not a lab value hands nothing down and strands nobody
  (``is_item_count`` deleted);
* a unit whose trailing exponent the PDF text lost resolves when exactly one unit differing
  from it by that digit is the LOINC property of the member concepts.
"""

from __future__ import annotations

import json
import zlib
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from src.services.criterion_annotation import (
    ANNOTATION_KEY,
    UNREPRESENTABLE_THRESHOLDS_KEY,
    validate_annotation,
)
from src.services.tte_service import TTEService
from src.services.value_constraint import RESTORED_UNIT_CRITERIA_KEY
from src.utils.criterion_refusal import (
    REFUSAL_STRANDED_GROUP_THRESHOLD,
    REFUSAL_UNREADABLE_VALUE_FILTER,
    REFUSAL_UNSTATED_UNIT_BOUND,
)

FIXTURE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "rfc016_quantity_rows.json").read_text()
)
PLATO = {row["id"]: row for row in FIXTURE["plato_inclusion"]}
ARISTOTLE = {row["id"]: row for row in FIXTURE["aristotle_exclusion"]}
CARMELINA = {row["id"]: row for row in FIXTURE["carmelina_exclusion"]}
CAROLINA = {row["id"]: row for row in FIXTURE["carolina_inclusion"]}
SEGMENTED = FIXTURE["segmentation"]
ASPIRIN = FIXTURE["aristotle_exclusion_26"]  # "Required treatment with aspirin > 165 mg/day"
LIFE_EXPECTANCY = FIXTURE["carolina_exclusion_67"]  # "... a life expectancy less than 5 years ..."


def _payload(span: Any, kind: Any, bound: Any) -> dict[str, Any]:
    return {
        "record_requirement": "required",
        "excepted_entities": [],
        "threshold_span": span,
        "quantity_kind": kind,
        "reference_bound": bound,
    }


def _annotated(row: dict[str, Any], span: Any, kind: Any, bound: Any) -> dict[str, Any]:
    row = deepcopy(row)
    fields, rejected = validate_annotation(_payload(span, kind, bound), row["protocolLine"])
    assert rejected == [], rejected
    row[ANNOTATION_KEY] = {"promptVersion": "test", "model": "stub", **fields}
    return row


def _concept_set(seed: str, domain: str) -> dict[str, Any]:
    concept_id = zlib.crc32(seed.encode()) % 10**8
    return {
        "name": seed,
        "domain": domain,
        "expression": {
            "items": [
                {
                    "concept": {
                        "CONCEPT_ID": concept_id,
                        "CONCEPT_NAME": seed,
                        "CONCEPT_CODE": str(concept_id),
                        "DOMAIN_ID": domain,
                        "VOCABULARY_ID": "SNOMED",
                        "CONCEPT_CLASS_ID": "Clinical Finding",
                    },
                    "includeDescendants": True,
                    "isExcluded": False,
                }
            ]
        },
        "mapping_metadata": None,
    }


class _Agent2IsStubbed:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Agent 2 is stubbed out in this test")


@pytest.fixture
def service(monkeypatch) -> TTEService:
    monkeypatch.setattr("src.agents.agent2.workflow.Agent2Workflow", _Agent2IsStubbed)
    monkeypatch.setattr("src.agents.agent2.query_expander.QueryExpander", _Agent2IsStubbed)
    monkeypatch.setattr("src.agents.agent2.retriever.ConceptRetriever", _Agent2IsStubbed)
    svc = TTEService.__new__(TTEService)

    def fake_recommend(seed_text: str, **kwargs: Any) -> dict[str, Any]:
        return _concept_set(seed_text.strip(), kwargs.get("expected_domain") or "Measurement")

    monkeypatch.setattr(svc, "_recommend_seeded_concept_set", fake_recommend)
    # No member's LOINC property is known unless a test says so.
    monkeypatch.setattr(svc, "_concept_set_lab_properties", lambda expression: {})
    return svc


def _members_measured_in(service: TTEService, monkeypatch, prop: str) -> None:
    """Every mapped member's concepts carry LOINC property ``prop``."""

    def properties(expression: dict[str, Any]) -> dict[int, str | None]:
        return {int(item["concept"]["CONCEPT_ID"]): prop for item in expression["items"]}

    monkeypatch.setattr(service, "_concept_set_lab_properties", properties)


def _build(service: TTEService, inclusion=(), exclusion=()) -> dict[str, Any]:
    return service._build_seeded_target_circe(
        {
            "targetCohortName": "target",
            "inclusionCriteria": deepcopy(list(inclusion)),
            "exclusionCriteria": deepcopy(list(exclusion)),
        }
    )


def _criteria(circe: dict[str, Any]) -> list[dict[str, Any]]:
    """Every emitted criteria body, flattened."""
    found: list[dict[str, Any]] = []

    def walk(group: dict[str, Any]) -> None:
        for entry in group.get("CriteriaList") or []:
            found.extend(entry["Criteria"].values())
        for child in group.get("Groups") or []:
            walk(child)

    for rule in circe["InclusionRules"]:
        walk(rule["expression"])
    return found


def _refusals(circe: dict[str, Any]) -> dict[str, str]:
    return {r["criterionId"]: r.get("refusalCode") for r in circe["_unmappedCriteria"]}


# --------------------------------------------------------------------------- #
# reference_bound (A21)
# --------------------------------------------------------------------------- #


class TestTheReferenceBoundComesFromTheAnnotation:
    """ARISTOTLE exclusion 2 stores "x ULN" in ``unitText`` with ``referenceBound: absolute``."""

    def test_should_emit_a_range_high_ratio_when_the_annotation_says_uln(self, service):
        row = _annotated(ARISTOTLE[2], "> 2X ULN", "lab_value", "uln")
        circe = _build(service, exclusion=[row])
        [criteria] = _criteria(circe)
        assert criteria["RangeHighRatio"] == {"Value": 2.0, "Op": "gt"}
        assert "ValueAsNumber" not in criteria

    def test_should_not_read_uln_out_of_the_unit_slot_without_an_annotation(self, service):
        circe = _build(service, exclusion=[ARISTOTLE[2]])
        assert _criteria(circe) == []
        assert _refusals(circe) == {"2": REFUSAL_UNSTATED_UNIT_BOUND}

    def test_should_take_uln_from_the_annotation_for_plato_troponin_too(self, service):
        row = _annotated(
            PLATO[29], "greater than the upper limit of normal", "lab_value", "uln"
        )
        circe = _build(service, inclusion=[row])
        [criteria] = _criteria(circe)
        assert criteria["RangeHighRatio"] == {"Value": 1.0, "Op": "gt"}

    def test_should_hand_the_labels_ratio_bound_to_a_member_that_carries_none(self, service):
        """CARMELINA's liver label, and member 11 as ``_criteria_from_ir`` now writes it:
        no bound copied onto the store row, because nothing reads ULN out of ``unitText``
        at ingest any more. The label's annotation is what reaches it."""
        label = _annotated(CARMELINA[10], "≥ 3 x upper limit of normal (ULN)", "lab_value", "uln")
        member = dict(deepcopy(CARMELINA[11]), valueConstraint=None)
        circe = _build(service, exclusion=[label, member])
        [criteria] = _criteria(circe)
        assert criteria["RangeHighRatio"] == {"Value": 3.0, "Op": "gte"}


# --------------------------------------------------------------------------- #
# quantity_kind (A5b)
# --------------------------------------------------------------------------- #


class TestAThresholdThatIsNotALabValue:
    """PLATO inclusion 26: "carotid stenosis (≥50%)" on a Condition row."""

    def test_should_be_refused_as_unreadable_without_an_annotation(self, service):
        circe = _build(service, inclusion=[PLATO[26]])
        assert _refusals(circe) == {"26": REFUSAL_UNREADABLE_VALUE_FILTER}

    def test_should_emit_the_criterion_without_it_and_record_it(self, service):
        row = _annotated(PLATO[26], "(≥50%)", "other", "none")
        circe = _build(service, inclusion=[row])
        [criteria] = _criteria(circe)
        assert "ValueAsNumber" not in criteria
        assert circe[UNREPRESENTABLE_THRESHOLDS_KEY] == [
            {
                "criterionId": "26",
                "role": "inclusion",
                "label": row["sourceText"],
                "isGroupLabel": False,
                "reason": "threshold-not-representable",
                "quantityKind": "other",
                "thresholdSpan": "(≥50%)",
                "valueConstraint": row["valueConstraint"],
            }
        ]

    def test_should_still_apply_a_lab_value_on_the_same_kind_of_row(self, service):
        """The decision is the kind, not the row: the same row read as a lab value keeps
        its number (and the Condition table then refuses it, as before)."""
        row = _annotated(PLATO[26], "(≥50%)", "lab_value", "none")
        circe = _build(service, inclusion=[row])
        assert _refusals(circe) == {"26": REFUSAL_UNREADABLE_VALUE_FILTER}
        assert circe[UNREPRESENTABLE_THRESHOLDS_KEY] == []

    def test_should_carry_an_empty_record_when_nothing_was_left_out(self, service):
        circe = _build(service, exclusion=[ARISTOTLE[23]])
        assert circe[UNREPRESENTABLE_THRESHOLDS_KEY] == []


class TestCarolinaTreatmentCompliance:
    """CAROLINA inclusion 31-33 (P2 NEW store): the label carries ``gte 80 %`` on an
    Observation row, the two members carry no ``valueConstraint`` at all, and the band
    "between 80% and 120%" survives only in the line."""

    def test_should_strand_the_members_under_the_absolute_label_without_an_annotation(
        self, service
    ):
        circe = _build(service, inclusion=[CAROLINA[31], CAROLINA[32], CAROLINA[33]])
        assert set(_refusals(circe).values()) == {REFUSAL_STRANDED_GROUP_THRESHOLD}

    def test_should_hand_nothing_down_from_a_label_whose_threshold_is_not_a_lab_value(
        self, service
    ):
        span = "between 80% and 120%"
        rows = [
            _annotated(CAROLINA[31], span, "other", "none"),
            _annotated(CAROLINA[32], span, "other", "none"),
            _annotated(CAROLINA[33], span, "other", "none"),
        ]
        circe = _build(service, inclusion=rows)
        assert REFUSAL_STRANDED_GROUP_THRESHOLD not in _refusals(circe).values()
        recorded = {r["criterionId"] for r in circe[UNREPRESENTABLE_THRESHOLDS_KEY]}
        # The label (Observation) is recorded; the members are Measurement rows, so an
        # `other` threshold on them is the Measurement-domain case and is not recorded --
        # they carry no number to apply, which is what gate (j) reads.
        assert recorded == {"31"}

    def test_should_still_collapse_the_two_identical_members(self, service):
        """E6 compares structured fields; the annotation states the same span for both,
        so it gives them nothing to tell apart. One survives, carrying the span."""
        span = "between 80% and 120%"
        rows = [_annotated(CAROLINA[i], span, "other", "none") for i in (31, 32, 33)]
        circe = _build(service, inclusion=rows)
        collapsed = {r["criterionId"] for r in circe["_skippedCriteria"]}
        assert collapsed & {"32", "33"} and not {"32", "33"} <= collapsed


# --------------------------------------------------------------------------- #
# A group cardinality strands nobody
# --------------------------------------------------------------------------- #

#: PLATO's "≥2 of the following" label as the 2026-09-10 store carried it
#: (`tests/test_stranded_group_threshold_refuses_the_member.py`), on the line the candidate
#: store's own label row for that list carries (inclusion 32).
COUNT_LABEL = {
    **deepcopy(PLATO[32]),
    "domain": "Observation",
    "groupId": "plato-count",
    "valueConstraint": {
        "op": "gte",
        "value": 2.0,
        "unitText": "of the following:",
        "referenceBound": "absolute",
        "unitConceptId": None,
    },
}
SMOKER = {
    "id": 41,
    "description": "Smoking Status",
    "sourceText": "Current smoker",
    "domain": "Observation",
    "valueConstraint": None,
    "isGroupLabel": False,
    "groupId": "plato-count",
    "groupType": "ANY",
    "logicType": "PRESENCE",
    "window": None,
    "protocolLine": "≥2 of the following:",
}


class TestAGroupCardinalityStrandsNobody:
    def test_should_strand_an_observation_member_when_nothing_says_the_number_is_a_count(
        self, service
    ):
        circe = _build(service, inclusion=[COUNT_LABEL, SMOKER])
        assert _refusals(circe) == {"41": REFUSAL_STRANDED_GROUP_THRESHOLD}

    def test_should_emit_the_member_when_the_label_says_its_number_is_a_count(self, service):
        label = _annotated(COUNT_LABEL, "≥2", "count", "none")
        circe = _build(service, inclusion=[label, SMOKER])
        [criteria] = _criteria(circe)
        assert "ValueAsNumber" not in criteria
        assert _refusals(circe) == {}


# --------------------------------------------------------------------------- #
# A unit whose exponent the PDF text lost
# --------------------------------------------------------------------------- #


def _segmented_row(
    line: str, op: str, value: float, unit_text: str, logic_type: str
) -> dict[str, Any]:
    """A Measurement criterion as Agent 1 extracts it from a segmented line: the unit
    copied as written, which is what the extraction prompt asks for."""
    return {
        "id": 99,
        "description": line,
        "sourceText": line,
        "protocolLine": line,
        "domain": "Measurement",
        "logicType": logic_type,
        "window": {"start": -180, "end": 0},
        "valueConstraint": {
            "op": op,
            "value": value,
            "valueHigh": None,
            "unitText": unit_text,
            "referenceBound": "absolute",
            "unitConceptId": None,
        },
        "isGroupLabel": False,
        "groupId": None,
    }


class TestADroppedUnitExponent:
    def test_should_refuse_the_platelet_bound_when_the_members_are_unknown(self, service):
        circe = _build(service, exclusion=[ARISTOTLE[23]])
        assert _refusals(circe) == {"23": REFUSAL_UNSTATED_UNIT_BOUND}

    def test_should_restore_mm3_when_the_members_are_number_concentrations(
        self, service, monkeypatch
    ):
        _members_measured_in(service, monkeypatch, "Number Concentration")
        circe = _build(service, exclusion=[ARISTOTLE[23]])
        [criteria] = _criteria(circe)
        assert criteria["ValueAsNumber"] == {"Value": 100000.0, "Op": "lte"}
        assert criteria["Unit"][0]["CONCEPT_ID"] == 8785
        [record] = circe[RESTORED_UNIT_CRITERIA_KEY]
        assert (record["criterionId"], record["statedUnit"], record["unitConceptId"]) == (
            "23", "/ mm", 8785,
        )
        assert record["property"] == "Number Concentration"

    def test_should_not_restore_into_a_property_the_members_do_not_carry(
        self, service, monkeypatch
    ):
        _members_measured_in(service, monkeypatch, "Mass Concentration")
        circe = _build(service, exclusion=[ARISTOTLE[23]])
        assert _refusals(circe) == {"23": REFUSAL_UNSTATED_UNIT_BOUND}
        assert circe[RESTORED_UNIT_CRITERIA_KEY] == []

    def test_should_restore_kg_m2_on_carmelinas_bmi_line(self, service, monkeypatch):
        line = SEGMENTED["CARMELINA.supplement"]["inclusion_6"]
        assert "kg/m " in line
        _members_measured_in(service, monkeypatch, "Ratio")
        circe = _build(service, inclusion=[_segmented_row(line, "lte", 45.0, "kg/m", "PRESENCE")])
        [criteria] = _criteria(circe)
        assert criteria["Unit"][0]["CONCEPT_ID"] == 9531

    def test_should_restore_the_body_surface_unit_on_carmelinas_egfr_line(
        self, service, monkeypatch
    ):
        line = SEGMENTED["CARMELINA.supplement"]["exclusion_4"]
        assert "1.73 m " in line
        _members_measured_in(service, monkeypatch, "Volume Rate/Area")
        circe = _build(
            service, exclusion=[_segmented_row(line, "lt", 15.0, "ml/min/1.73 m", "ABSENCE")]
        )
        [criteria] = _criteria(circe)
        assert criteria["Unit"][0]["CONCEPT_ID"] == 720870


# --------------------------------------------------------------------------- #
# dose / statistical: the whole criterion is skipped
# --------------------------------------------------------------------------- #


class TestADoseOrStatisticalThresholdSkipsTheCriterion:
    """ARISTOTLE exclusion 26: "Required treatment with aspirin > 165 mg/day" on a Drug row
    with no ``valueConstraint``. Emitted without its number it excludes every aspirin user."""

    def test_should_emit_the_plain_drug_without_an_annotation(self, service):
        circe = _build(service, exclusion=[ASPIRIN])
        assert len(_criteria(circe)) == 1
        assert circe["_skippedCriteria"] == []

    @pytest.mark.parametrize("kind", ["dose", "statistical"])
    def test_should_skip_the_whole_criterion_and_record_why(self, service, kind):
        row = _annotated(ASPIRIN, "> 165 mg/day", kind, "none")
        circe = _build(service, exclusion=[row])
        assert circe["InclusionRules"] == []
        [skip] = circe["_skippedCriteria"]
        assert (skip["criterionId"], skip["reason"], skip["quantityKind"], skip["thresholdSpan"]) == (
            "26", "threshold-not-representable", kind, "> 165 mg/day",
        )
        assert skip["thresholdDecidedBy"] == "26"
        # Skipped, so not also listed as a threshold the file carries without a filter.
        assert circe[UNREPRESENTABLE_THRESHOLDS_KEY] == []
        assert circe["_generationCensus"]["skippedByReason"] == {"threshold-not-representable": 1}

    def test_should_take_a_labels_members_with_it(self, service):
        """The decision is the label's when the label states the threshold (as a
        conditional label takes its members). CAROLINA inclusion 31-33, with the label's
        kind answered ``statistical`` to drive this branch."""
        label = _annotated(CAROLINA[31], "between 80% and 120%", "statistical", "none")
        circe = _build(service, inclusion=[label, CAROLINA[32], CAROLINA[33]])
        skips = {r["criterionId"]: r for r in circe["_skippedCriteria"]}
        # 33 is E6's duplicate of 32 and is collapsed first, as it was before; the label
        # and the surviving member go under the label's threshold decision.
        assert {cid: r["reason"] for cid, r in skips.items()} == {
            "31": "threshold-not-representable",
            "32": "threshold-not-representable",
            "33": "restated-distinctness-duplicate",
        }
        assert skips["32"]["thresholdDecidedBy"] == "31"
        assert circe["InclusionRules"] == []


# --------------------------------------------------------------------------- #
# duration / count: the criterion is kept, the threshold recorded
# --------------------------------------------------------------------------- #


class TestADurationOrCountThresholdKeepsTheCriterion:
    def test_should_keep_the_life_expectancy_criterion_and_record_its_threshold(self, service):
        """CAROLINA exclusion 67, ``lt 5 years`` on an Observation row."""
        span = "life expectancy less than 5 years"
        row = _annotated(LIFE_EXPECTANCY, span, "duration", "none")
        circe = _build(service, exclusion=[row])
        [criteria] = _criteria(circe)
        assert "ValueAsNumber" not in criteria
        [record] = circe[UNREPRESENTABLE_THRESHOLDS_KEY]
        assert (record["criterionId"], record["quantityKind"], record["thresholdSpan"]) == (
            "67", "duration", span,
        )
        assert circe["_skippedCriteria"] == []

    def test_should_keep_a_count_labels_members(self, service):
        label = _annotated(COUNT_LABEL, "≥2", "count", "none")
        circe = _build(service, inclusion=[label, SMOKER])
        assert len(_criteria(circe)) == 1
        assert [r["quantityKind"] for r in circe[UNREPRESENTABLE_THRESHOLDS_KEY]] == ["count"]
