"""The delivery gate counts a member that emitted a demographic criterion as emitted.

``_group_label_violations`` (``scripts/verify_circe_delivery.py``) re-judges a ``group-label``
permit member by member, and read which members emitted only from ``_criterionConceptSetRefs``.
A member that emits an Age builds a ``DemographicCriteriaList`` rule, which mints no concept set,
so after the age hand-down (2c0392f) CARMELINA inclusion 29 -- which emits ``Age >= 18`` from its
label 28 -- was re-judged as stranded: "its absolute threshold ... does not reach 1 of its 2
member(s)". The build writes no per-criterion record of a demographic rule; what it does write
is the census partition, under which such a member is the one booked as ``demographicRules``.

Real rows (``tests/fixtures/p3_age_label_rows.json``): arm B CARMELINA inclusion 28-30, and the
expression the build made of them at 620d1a0, before the hand-down, frozen in the same file.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from src.utils.circe_lint import CRITERION_CONCEPT_SET_REFS_KEY

FIXTURE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "p3_age_label_rows.json").read_text()
)
ROWS: list[dict[str, Any]] = FIXTURE["carmelina_age_label_arm_b"]["rows"]
BEFORE_HAND_DOWN: dict[str, Any] = FIXTURE["carmelina_age_label_arm_b_build_620d1a0"]["expression"]


def _stub_recommend(seed_text: str, **_: Any) -> dict[str, Any]:
    """The stub the frozen expression was built with -- no ChromaDB, no LLM."""
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
def built() -> dict[str, Any]:
    from src.services.tte_service import TTEService

    svc = TTEService.__new__(TTEService)
    svc._recommend_seeded_concept_set = _stub_recommend
    return svc._build_seeded_target_circe(
        {
            "targetCohortName": "AF cohort",
            "inclusionCriteria": deepcopy(ROWS),
            "exclusionCriteria": [],
        }
    )


def _permit_violations(expression: dict[str, Any]) -> list[str]:
    from scripts.verify_circe_delivery import criteria_index, skipped_criteria_violations

    index = criteria_index({"eligibility": {"inclusionCriteria": ROWS, "exclusionCriteria": []}})
    return skipped_criteria_violations(expression["_skippedCriteria"], index, expression)


def _without_refs(expression: dict[str, Any]) -> dict[str, Any]:
    # The exported CIRCE files carry no refs map; the gate reads such a file too.
    stripped = deepcopy(expression)
    stripped.pop(CRITERION_CONCEPT_SET_REFS_KEY)
    return stripped


@pytest.mark.parametrize("refs", ["with-refs", "without-refs"])
def test_should_pass_the_label_check_when_its_member_emitted_the_label_bound_as_an_age(built, refs):
    expression = built if refs == "with-refs" else _without_refs(built)

    assert _permit_violations(expression) == []


@pytest.mark.parametrize("refs", ["with-refs", "without-refs"])
def test_should_still_fail_the_label_when_no_member_emitted(refs):
    expression = BEFORE_HAND_DOWN if refs == "with-refs" else _without_refs(BEFORE_HAND_DOWN)

    violations = _permit_violations(expression)

    assert len(violations) == 1, violations
    assert "inclusion #28 " in violations[0]
    assert "is a group label skipped while none of its 2 member(s) emitted" in violations[0]


def test_should_not_count_a_member_as_emitted_when_the_census_books_no_demographic_rule_for_it():
    # A producer that dropped member 29 without recording it: its skip record struck, the census
    # still booking no demographic rule. Nothing says 29 emitted, so it is not credited.
    expression = deepcopy(BEFORE_HAND_DOWN)
    expression["_skippedCriteria"] = [
        r for r in expression["_skippedCriteria"] if r["criterionId"] != "29"
    ]
    assert expression["_generationCensus"]["demographicRules"] == 0

    violations = _permit_violations(expression)

    assert len(violations) == 1, violations
    assert "inclusion #28 " in violations[0]
    assert "does not reach 1 of its 2 member(s)" in violations[0]
