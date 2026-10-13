"""A group label emits no rule of its own, whatever its domain.

``TTEService._build_seeded_target_circe`` checked the Demographics domain before
``isGroupLabel``, so a Demographics-domain group LABEL took the demographic branch and
``_build_demographic_rule`` built an Age rule from the label's own ``valueConstraint``.

Real rows, copied verbatim into ``tests/fixtures/p3_structural_rows.json``:

* ARISTOTLE inclusion 16 'AF/Risk Factor Check' (``2026-10-12_p2_new`` store) is the label
  of the "≥ 18 yrs with AF and one or more risk factors" group and carries ``gte 18``.
  Its member 17 'Age >= 18 years' carries the same bound, so the label added a second
  Age criterion to the group.
* CARMELINA inclusion 11 'Age >= 18 years' (2026-10-12 candidate store) is a label with
  no bound; it was recorded as ``demographic-no-rule`` instead of ``group-label``.

The other side of the same move. When the label is the ONLY row carrying the bound, a
label that emits nothing must hand the bound to its Demographics members, or the age
leaves the cohort. Real rows, copied verbatim into ``tests/fixtures/p3_age_label_rows.json``:

* CARMELINA inclusion 28 'Age at screening' (``2026-10-12_p2_new`` store and the P3 dry
  arm B store) is the label and carries ``gte 18 years``; its members 29 'Age at Visit 1
  (General)' and 30 'Age at Visit 1 (Japan Specific)' carry no bound. The protocol
  requires age >= 18 of everyone; after d77d544 no Age rule was built (28 ``group-label``,
  29 ``demographic-no-rule``, 30 a restated duplicate of 29).
* EMPA-REG inclusion 9 'Age >= 18 years' (arm B) carries its own bound and an annotation
  calling the number ``other``. Its Age is emitted, yet the build listed the threshold under
  ``_unrepresentableThresholds`` as one no CIRCE value filter represents.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

FIXTURE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "p3_structural_rows.json").read_text()
)
AGE_FIXTURE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "p3_age_label_rows.json").read_text()
)


def _stub_recommend(seed_text: str, **_: Any) -> dict[str, Any]:
    """A Condition concept set for any seed -- no ChromaDB, no LLM."""
    return {
        "name": seed_text,
        "domain": "Condition",
        "expression": {
            "items": [
                {
                    "concept": {
                        "CONCEPT_ID": 313217,
                        "CONCEPT_NAME": "Atrial fibrillation",
                        "DOMAIN_ID": "Condition",
                        "VOCABULARY_ID": "SNOMED",
                        "CONCEPT_CLASS_ID": "Clinical Finding",
                    },
                    "includeDescendants": True,
                    "isExcluded": False,
                }
            ]
        },
    }


@pytest.fixture
def service():
    from src.services.tte_service import TTEService

    svc = TTEService.__new__(TTEService)
    svc._recommend_seeded_concept_set = _stub_recommend
    return svc


def _build(service, inclusion: list[dict[str, Any]]) -> dict[str, Any]:
    eligibility = {
        "targetCohortName": "AF cohort",
        "inclusionCriteria": inclusion,
        "exclusionCriteria": [],
    }
    return service._build_seeded_target_circe(eligibility)


def _age_criteria(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "Age":
                found.append(value)
            else:
                found.extend(_age_criteria(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_age_criteria(value))
    return found


def _skip_reason(circe: dict[str, Any], criterion_id: int) -> str | None:
    return next(
        (r["reason"] for r in circe["_skippedCriteria"] if r["criterionId"] == str(criterion_id)),
        None,
    )


def test_should_emit_one_age_criterion_when_the_label_and_its_member_both_state_the_bound(service):
    rows = FIXTURE["m1_aristotle_af_group"]["rows"]
    circe = _build(service, rows)

    ages = _age_criteria(circe["InclusionRules"])
    assert ages == [{"Value": 18.0, "Op": "gte"}], ages


def test_should_skip_the_label_as_a_group_label_when_it_carries_a_demographic_bound(service):
    rows = FIXTURE["m1_aristotle_af_group"]["rows"]
    circe = _build(service, rows)

    # Which group-label reason (plain, or stranded threshold) is the resolver's question,
    # not this branch's; what this branch decides is that the label emits nothing.
    reason = _skip_reason(circe, 16)
    assert reason is not None and reason.startswith("group-label"), reason


def test_should_record_the_label_as_group_label_when_it_carries_no_bound(service):
    rows = FIXTURE["m1_carmelina_age_group"]["rows"]
    circe = _build(service, rows)

    assert _skip_reason(circe, 11) == "group-label"
    assert sorted(a["Value"] for a in _age_criteria(circe["InclusionRules"])) == [18.0, 20.0]


def _label_of(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return next(r for r in rows if r.get("isGroupLabel"))


@pytest.mark.parametrize("section", ["carmelina_age_label_p2_new", "carmelina_age_label_arm_b"])
def test_should_emit_the_label_bound_when_only_the_demographic_label_carries_it(service, section):
    rows = AGE_FIXTURE[section]["rows"]
    circe = _build(service, rows)

    assert _age_criteria(circe["InclusionRules"]) == [{"Value": 18.0, "Op": "gte"}]
    # The label still emits nothing of its own; the member carries its bound.
    assert _skip_reason(circe, 28) == "group-label"
    assert _skip_reason(circe, 29) is None


def test_should_emit_the_label_bound_when_the_label_threshold_is_annotated_other(service):
    # Arm B's annotation called the label's number a lab value. Arm A annotated the label of
    # the same protocol line (CARMELINA inclusion 11) `other`; that one field is varied here.
    rows = deepcopy(AGE_FIXTURE["carmelina_age_label_arm_b"]["rows"])
    label = _label_of(rows)
    assert label["annotation"]["quantity_kind"] == "lab_value"
    label["annotation"]["quantity_kind"] = "other"

    circe = _build(service, rows)

    assert _age_criteria(circe["InclusionRules"]) == [{"Value": 18.0, "Op": "gte"}]


@pytest.mark.parametrize(
    ("section", "emitting_id"),
    [("empareg_age_arm_b", "9"), ("carmelina_age_label_arm_b", "29")],
)
def test_should_write_no_unrepresentable_threshold_record_when_the_age_is_emitted(
    service, section, emitting_id
):
    rows = AGE_FIXTURE[section]["rows"]
    circe = _build(service, rows)

    assert _age_criteria(circe["InclusionRules"]) == [{"Value": 18.0, "Op": "gte"}]
    assert _skip_reason(circe, int(emitting_id)) is None
    recorded = {r["criterionId"] for r in circe["_unrepresentableThresholds"]}
    assert emitting_id not in recorded, circe["_unrepresentableThresholds"]


def test_should_emit_the_inverted_label_bound_when_the_demographic_group_is_an_exclusion(service):
    # The same real rows placed in the exclusion role, which no protocol states: this pins
    # only that the exclusion loop hands the label's bound down as the inclusion loop does.
    rows = AGE_FIXTURE["carmelina_age_label_p2_new"]["rows"]
    circe = service._build_seeded_target_circe(
        {"targetCohortName": "AF cohort", "inclusionCriteria": [], "exclusionCriteria": rows}
    )

    assert _age_criteria(circe["InclusionRules"]) == [{"Value": 18.0, "Op": "lt"}]
    assert _skip_reason(circe, 28) == "group-label"
