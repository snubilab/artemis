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
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "p3_structural_rows.json").read_text()
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
