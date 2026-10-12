"""A group label's bound is not handed to, and does not strand, a member that cannot hold it.

``resolve_group_member_constraint`` asked "is this absolute bound in the member's unit?"
of every bare member, whatever its criteria type. A ConditionOccurrence reads no value
attribute at all (``circe_lint.CRITERIA_TYPE_VALUE_ATTRIBUTES``), so the answer was always
"no", the member was refused as stranded, and a real criterion left the cohort because
its group label carried somebody else's number.

Real rows (``tests/fixtures/p3_structural_rows.json``):

* ``m1_aristotle_af_group`` -- ARISTOTLE inclusion 16 'AF/Risk Factor Check'
  (Demographics, ``gte 18 yrs``) over 17 'Age >= 18 years' (its own bound),
  18 'atrial fibrillation (AF)' and 19 'Risk factors for stroke' (Conditions). The age
  bound refused AF and the stroke risk factors.
* ``m10b_carmelina_renal_group`` -- CARMELINA exclusion 22 'Severe renal impairment or
  ESRD' (Measurement, ``lt 15 ml/min/1.73 m2``) over 23 (eGFR, its own bound) and
  24 'need for maintenance dialysis' (Condition). The eGFR bound refused the dialysis arm.
* ``m10b_carolina_compliance_group`` -- the guard: CAROLINA inclusion 31 (Observation,
  ``gte 80 %``) over two bare MEASUREMENT members. A Measurement can hold the bound, so
  the unit check still decides and an unfiltered member is still never emitted.

The mapper and the LOINC vocabulary are stubbed: one Condition concept stands in for every
Condition seed and one LOINC eGFR test for every Measurement seed; the vocabulary knows no
LOINC property for either, so a member that reaches the unit check strands.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.services.value_constraint import STRANDED_GROUP_CONSTRAINT_REASON
from src.utils.criterion_refusal import REFUSAL_STRANDED_GROUP_THRESHOLD

FIXTURE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "p3_structural_rows.json").read_text()
)


def _stub_recommend(seed_text: str, *, expected_domain: str | None = None, **_: Any) -> dict:
    measurement = expected_domain == "Measurement"
    return {
        "name": seed_text,
        "domain": "Measurement" if measurement else "Condition",
        "expression": {
            "items": [
                {
                    "concept": {
                        "CONCEPT_ID": 3049187 if measurement else 313217,
                        "DOMAIN_ID": "Measurement" if measurement else "Condition",
                    },
                    "includeDescendants": True,
                    "isExcluded": False,
                }
            ]
        },
    }


class _NoLoincProperties:
    def properties(self, _ids):
        return {}

    def close(self):
        pass


@pytest.fixture
def service():
    from src.services.tte_service import TTEService

    svc = TTEService.__new__(TTEService)
    svc._recommend_seeded_concept_set = _stub_recommend
    svc._lab_test_vocabulary = _NoLoincProperties
    return svc


def _build(service, *, inclusion=(), exclusion=()) -> dict[str, Any]:
    return service._build_seeded_target_circe(
        {
            "targetCohortName": "cohort",
            "inclusionCriteria": list(inclusion),
            "exclusionCriteria": list(exclusion),
        }
    )


def _refused(circe: dict[str, Any]) -> set[str]:
    return {
        r["criterionId"]
        for r in circe["_unmappedCriteria"]
        if r.get("refusalCode") == REFUSAL_STRANDED_GROUP_THRESHOLD
    }


def _skip_reason(circe: dict[str, Any], criterion_id: int) -> str | None:
    return next(
        (r["reason"] for r in circe["_skippedCriteria"] if r["criterionId"] == str(criterion_id)),
        None,
    )


def _condition_entries(
    circe: dict[str, Any], criteria_type: str = "ConditionOccurrence"
) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            body = (node.get("Criteria") or {}).get(criteria_type)
            if isinstance(body, dict):
                found.append(body)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(circe["InclusionRules"])
    return found


def test_should_emit_the_condition_members_of_a_group_whose_label_carries_an_age_bound(service):
    circe = _build(service, inclusion=FIXTURE["m1_aristotle_af_group"]["rows"])

    assert _refused(circe) == set()
    assert len(_condition_entries(circe)) == 2
    assert all(set(body) == {"CodesetId"} for body in _condition_entries(circe))
    assert _skip_reason(circe, 16) == "group-label"


def test_should_emit_the_dialysis_arm_of_a_renal_group_whose_label_carries_an_egfr_bound(service):
    circe = _build(service, exclusion=FIXTURE["m10b_carmelina_renal_group"]["rows"])

    assert _refused(circe) == set()
    assert len(_condition_entries(circe)) == 1
    assert _skip_reason(circe, 22) == "group-label"


def test_should_still_strand_a_measurement_member_whose_unit_cannot_be_verified(service):
    """The guard: a Measurement CAN hold the bound, so the unit check still decides, and
    a member it cannot verify is refused rather than emitted unfiltered.

    Members 32 and 33 carry identical structured fields -- their 80 % / 120 % bounds live
    only in the descriptions -- so the restated-distinctness collapse (RFC-016 E6) keeps
    32 and drops 33 before the unit check. Either way no member emits, and the one that
    reaches the check is refused."""
    circe = _build(service, inclusion=FIXTURE["m10b_carolina_compliance_group"]["rows"])

    assert "32" in _refused(circe)
    assert _refused(circe) <= {"32", "33"}
    assert _condition_entries(circe, "Measurement") == []
    assert _skip_reason(circe, 31) == STRANDED_GROUP_CONSTRAINT_REASON
