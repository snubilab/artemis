"""A group label's threshold must reach its members from the STORE, not only from IR.

``resolve_group_member_constraint`` is the one place that decides whether a label's
threshold is handed down, and two builders called it: the IR -> store import
(``TTEService._criteria_from_ir``) and the assembler. The third path never did.

``_build_seeded_target_circe`` reads criteria as the store holds them and calls
``_build_seeded_eligibility_rule``, which read ``criterion["valueConstraint"]``
directly. For a member row whose ``valueConstraint`` is ``None`` -- which is every
member of a labelled group in every store written before the import-time fix --
``build_measurement_value_filter`` returned ``{}`` and the number was gone.

Measured on ``tmp/tte_cold6_32k_20260907/studies.json``, study 10, exclusion group
``5bb178d2``: the label carries ``{gt 3.0 "x ULN"}``; the members ALT, AST and ALP
carry ``None``; the emitted rule is a Measurement occurrence with count 0 and no
``RangeHighRatio`` at all. So the exclusion reads "liver enzymes above 3x ULN" and
excludes anyone with any ALT/AST/ALP result on record.

Fixing this at the import boundary alone would not reach a delivered file: the
stores that exist today were already imported, and ``tte_service.py`` deepcopies a
prebuilt ``structuredExpression`` to avoid re-running Agent2. Fixing it where the
store row becomes CIRCE reaches them on the next build.

The census guard asks the resolver itself, once per member, rather than re-deriving
the answer from the store rows: a member's ``valueConstraint`` being null stopped
being evidence of loss once an absolute bound could reach some members and not
others. A label is flagged only when a member actually ended up refused.
``TestTheCensusStillDistinguishesTheTwoRefusals`` pins all three directions --
reference-relative, absolute-and-lossy, absolute-and-complete.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.services.value_constraint import STRANDED_GROUP_CONSTRAINT_REASON

# Transcribed from tmp/tte_cold6_32k_20260907/studies.json, study 10, group 5bb178d2.
LIVER_GROUP_ID = "5bb178d2"
LIVER_LABEL_CONSTRAINT = {
    "op": "gt",
    "value": 3.0,
    "unitText": "x ULN",
    "referenceBound": "absolute",
    "unitConceptId": None,
}
# study 8's group, same shape but an absolute bound: mg/dL fits a plasma glucose and
# is meaningless for HbA1c, and both are members -- so this one is handed down to one
# member and refused for the other.
GLUCOSE_GROUP_ID = "a1b2c3d4"
GLUCOSE_LABEL_CONSTRAINT = {
    "op": "gt",
    "value": 240.0,
    "unitText": "mg/dL",
    "referenceBound": "absolute",
    "unitConceptId": None,
}


def _label(criterion_id: int, group_id: str, text: str, constraint: dict) -> dict:
    return {
        "id": criterion_id,
        "description": text,
        "sourceText": text,
        "domain": "Measurement",
        "valueConstraint": constraint,
        "isGroupLabel": True,
        "groupId": group_id,
        "groupType": "ALL",
        "logicType": "ABSENCE",
        "window": None,
    }


def _member(criterion_id: int, group_id: str, text: str) -> dict:
    return {
        "id": criterion_id,
        "description": text,
        "sourceText": text,
        "domain": "Measurement",
        "valueConstraint": None,
        "isGroupLabel": False,
        "groupId": group_id,
        "groupType": "ALL",
        "logicType": "ABSENCE",
        "window": None,
    }


LIVER_ROWS = [
    _label(20, LIVER_GROUP_ID, "Active liver disease or impaired hepatic function",
           LIVER_LABEL_CONSTRAINT),
    _member(21, LIVER_GROUP_ID, "Alanine aminotransferase level"),
    _member(22, LIVER_GROUP_ID, "Aspartate aminotransferase level"),
    _member(23, LIVER_GROUP_ID, "Alkaline phosphatase level"),
]

GLUCOSE_ROWS = [
    _label(30, GLUCOSE_GROUP_ID, "Uncontrolled hyperglycaemia", GLUCOSE_LABEL_CONSTRAINT),
    _member(31, GLUCOSE_GROUP_ID, "Elevated HbA1c"),
    _member(32, GLUCOSE_GROUP_ID, "Elevated Fasting Glucose"),
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
            "expression": {
                "items": [{"concept": {"CONCEPT_ID": 3006923, "DOMAIN_ID": "Measurement"}}]
            },
        }
    )
    return svc


def _eligibility(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "targetCohortName": "T2DM cohort",
        "inclusionCriteria": [],
        "exclusionCriteria": rows,
    }


def _measurement_bodies(expression: dict[str, Any]) -> list[dict[str, Any]]:
    bodies: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "Criteria" and isinstance(value, dict):
                    for criteria_type, body in value.items():
                        if criteria_type == "Measurement" and isinstance(body, dict):
                            bodies.append(body)
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for rule in expression.get("InclusionRules") or []:
        walk(rule)
    return bodies


class TestStoreRowsInheritTheLabelThresholdAtBuildTime:
    def test_should_emit_range_high_ratio_for_every_member_of_a_ratio_labelled_group(
        self, service
    ):
        built = service._build_seeded_target_circe(_eligibility(list(LIVER_ROWS)))

        bodies = _measurement_bodies(built)
        assert len(bodies) == 3, "ALT / AST / ALP should each emit one criterion"
        for body in bodies:
            assert body.get("RangeHighRatio") == {"Value": 3.0, "Op": "gt"}, (
                "the member rows carry valueConstraint=None and the label row is "
                "refused as isGroupLabel, so '> 3x ULN' reached nothing and the "
                "exclusion dropped anyone with any liver enzyme result on record"
            )

    def test_should_hand_an_absolute_bound_to_the_member_measured_in_that_unit(
        self, service
    ):
        """One member of this group takes '> 240 mg/dL'; the other cannot.

        The count is asserted before the bodies are read. The previous version of this
        test looped over `_measurement_bodies(built)` asserting an absence, and once
        every member started refusing the loop iterated zero times -- it passed while
        proving nothing. An emptiness assertion inside a loop is only a real assertion
        when the loop's length is pinned outside it.
        """
        built = service._build_seeded_target_circe(_eligibility(list(GLUCOSE_ROWS)))

        bodies = _measurement_bodies(built)
        assert len(bodies) == 1, (
            f"expected 'Elevated Fasting Glucose' to emit and 'Elevated HbA1c' to "
            f"refuse; got {len(bodies)} bodies: {bodies}"
        )
        assert bodies[0]["ValueAsNumber"] == {"Value": 240.0, "Op": "gt"}
        assert [u["CONCEPT_ID"] for u in bodies[0]["Unit"]] == [8840]

    def test_should_refuse_the_member_the_absolute_bound_does_not_fit(self, service):
        """'> 240 mg/dL' on HbA1c matches zero rows; inside an ABSENCE exclusion that
        silently stops excluding anybody, so the member is refused rather than emitted."""
        built = service._build_seeded_target_circe(_eligibility(list(GLUCOSE_ROWS)))

        refused = [
            record
            for record in built["_unmappedCriteria"]
            if record.get("refusalCode") == "stranded-group-threshold"
        ]
        assert [record["label"] for record in refused] == ["Elevated HbA1c"]
        assert "% (percent)" in refused[0]["reason"]
        assert "mg/dL" in refused[0]["reason"]

    def test_should_not_overwrite_a_member_that_carries_its_own_threshold(self, service):
        rows = [dict(row) for row in LIVER_ROWS]
        rows[1] = dict(rows[1], valueConstraint={
            "op": "gt", "value": 5.0, "unitText": "x ULN",
            "referenceBound": "absolute", "unitConceptId": None,
        })

        built = service._build_seeded_target_circe(_eligibility(rows))

        values = sorted(
            body["RangeHighRatio"]["Value"] for body in _measurement_bodies(built)
        )
        assert values == [3.0, 3.0, 5.0], (
            "the decomposer grounds a sub-item's own threshold in its own source text "
            "(REQ-004/REQ-005); propagation must never overwrite that answer"
        )

    def test_should_not_mutate_the_criteria_rows_it_was_handed(self, service):
        rows = [dict(row) for row in LIVER_ROWS]
        service._build_seeded_target_circe(_eligibility(rows))

        assert [row["valueConstraint"] for row in rows[1:]] == [None, None, None], (
            "the eligibility dict reaching this builder is the study's own; writing "
            "the resolved constraint back into it would persist a derived value"
        )

    def test_should_leave_an_ungrouped_criterion_alone(self, service):
        row = _member(40, "", "Serum creatinine")
        row["groupId"] = None
        row["valueConstraint"] = {
            "op": "gt", "value": 2.0, "unitText": "mg/dL",
            "referenceBound": "absolute", "unitConceptId": None,
        }

        built = service._build_seeded_target_circe(_eligibility([row]))

        assert _measurement_bodies(built)[0]["ValueAsNumber"] == {
            "Value": 2.0, "Op": "gt"
        }


class TestTheCensusStillDistinguishesTheTwoRefusals:
    """`unfiltered` alone is NOT the right discriminator once the build propagates."""

    def test_should_not_flag_a_ratio_label_whose_threshold_now_reaches_its_members(
        self, service
    ):
        built = service._build_seeded_target_circe(_eligibility(list(LIVER_ROWS)))

        reasons = [
            record["reason"]
            for record in built["_skippedCriteria"]
            if record["isGroupLabel"]
        ]
        assert reasons == ["group-label"], (
            "the members do carry valueConstraint=None in the store, so a census keyed "
            "on that alone would call this label stranded -- but the build handed its "
            "ratio bound down, so nothing was lost"
        )

    def test_should_flag_an_absolute_label_that_lost_a_member(self, service):
        """Losing ONE member is loss. 'Elevated Fasting Glucose' takes the bound and
        'Elevated HbA1c' cannot, so the group's threshold did not survive intact."""
        built = service._build_seeded_target_circe(_eligibility(list(GLUCOSE_ROWS)))

        reasons = [
            record["reason"]
            for record in built["_skippedCriteria"]
            if record["isGroupLabel"]
        ]
        assert reasons == [STRANDED_GROUP_CONSTRAINT_REASON]

    def test_should_not_flag_an_absolute_label_whose_bound_fits_every_member(
        self, service
    ):
        """Every member here is a glucose, so mg/dL reaches all of them and nothing
        was lost. Flagging this would report a loss the build did not incur -- and the
        delivery gate treats the stranded reason as loss, so it would block for nothing."""
        rows = [
            _label(30, GLUCOSE_GROUP_ID, "Uncontrolled hyperglycaemia",
                   GLUCOSE_LABEL_CONSTRAINT),
            _member(31, GLUCOSE_GROUP_ID, "Fasting Plasma Glucose"),
            _member(32, GLUCOSE_GROUP_ID, "Random Plasma Glucose"),
        ]

        built = service._build_seeded_target_circe(_eligibility(rows))

        bodies = _measurement_bodies(built)
        assert len(bodies) == 2
        reasons = [
            record["reason"]
            for record in built["_skippedCriteria"]
            if record["isGroupLabel"]
        ]
        assert reasons == ["group-label"]
