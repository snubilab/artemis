"""A prior-use washout must not count the exposure that defines entry.

Under a drug-anchored entry every entrant necessarily has a class exposure on the
index day, because the index event IS an exposure to a drug in that class. So a
class-level washout whose concept set contains the entry drug and whose window ends
at ``index + 0`` empties the cohort -- it excludes people for the very event that
admitted them.

Measured on WebAPI 2.15.1, source SYNTHEA (schema ``synthea_cdm``), entry
``DrugEra(19069022)``, three separate definitions each with its own design hash:

    no inclusion rule                          10093 persons
    absence of the same drug, [-365, index]        0 persons
    absence of the same drug, [-365, index-1]  10093 persons

(``output/site_gap/2026-09-05/circe_index_window_experiment.py``.)

The correction is to end such a window the day before index, and ONLY where the
absence rule's concept set actually intersects the entry set. The alternative --
subtracting the study drug from its own class set -- is rejected: a patient who used
linagliptin six months before index is not a new user and must stay excluded, so
removing it would admit prior users of the study drug and break the new-user design.

The fix sits at the emission choke point (``_materialize_seeded_cohort_item``) rather
than at criterion->CIRCE time, because studies 1/8/9/10 all carry a prebuilt
``structuredExpression`` -- the per-arm export never calls
``_build_seeded_eligibility_rule`` at all -- and because the entry a rule collides
with is not final until the arm builder has repointed it (CAROLINA's comparator
enters on glimepiride, which the store's target entry is not).
"""
from __future__ import annotations

from typing import Any

import pytest

from src.services.tte_service import TTEService

LINAGLIPTIN = 40239216
SITAGLIPTIN = 1580747
INDEX_DAY_END = {"Days": 0, "Coeff": 1}
DAY_BEFORE_INDEX_END = {"Days": 1, "Coeff": -1}
PAST_INDEX_END = {"Days": 365, "Coeff": 1}


def _drug_set(set_id: int, name: str, concept_ids: list[int]) -> dict[str, Any]:
    return {
        "id": set_id,
        "name": name,
        "expression": {
            "items": [
                {
                    "concept": {
                        "CONCEPT_ID": cid,
                        "CONCEPT_NAME": name,
                        "DOMAIN_ID": "Drug",
                        "VOCABULARY_ID": "RxNorm",
                        "CONCEPT_CLASS_ID": "Ingredient",
                    },
                    "includeDescendants": True,
                    "isExcluded": False,
                }
                for cid in concept_ids
            ]
        },
    }


def _washout_rule(name: str, codeset_id: int, end: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "expression": {
            "Type": "ALL",
            "CriteriaList": [
                {
                    "Criteria": {"DrugExposure": {"CodesetId": codeset_id}},
                    "StartWindow": {
                        "Start": {"Days": 365, "Coeff": -1},
                        "End": dict(end),
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


def _circe(rules: list[dict[str, Any]]) -> dict[str, Any]:
    """CARMELINA's shape: a linagliptin DrugEra entry plus class washouts."""
    return {
        "ConceptSets": [
            _drug_set(1, "linagliptin", [LINAGLIPTIN]),
            _drug_set(2, "DPP-4 inhibitors", [LINAGLIPTIN, SITAGLIPTIN]),
            _drug_set(3, "GLP-1 receptor agonists", [42873638]),
        ],
        "PrimaryCriteria": {
            "CriteriaList": [{"DrugEra": {"CodesetId": 1}}],
            "ObservationWindow": {"PriorDays": 365, "PostDays": 0},
            "PrimaryCriteriaLimit": {"Type": "First"},
        },
        "InclusionRules": rules,
    }


def _end_of(expression: dict[str, Any], rule_name: str) -> dict[str, Any]:
    for rule in expression["InclusionRules"]:
        if rule["name"] == rule_name:
            return rule["expression"]["CriteriaList"][0]["StartWindow"]["End"]
    raise AssertionError("no rule named " + repr(rule_name))


class _CapturingClient:
    """Stands in for WebAPIClient, capturing what the service actually emits."""

    def __init__(self) -> None:
        self.expression: dict[str, Any] | None = None

    def create_cohort_definition(
        self, name: str, expression: dict[str, Any], description: str = ""
    ) -> dict[str, Any]:
        self.expression = expression
        return {"id": 4242, "name": name}


@pytest.fixture
def service() -> TTEService:
    return TTEService.__new__(TTEService)


def _emit(service: TTEService, expression: dict[str, Any]) -> dict[str, Any]:
    """Run one expression through the emission choke point every arm converges on."""
    client = _CapturingClient()
    item = service._materialize_seeded_cohort_item(
        client=client,
        study_id=9,
        study_name="CARMELINA",
        section="treatmentArms",
        item_key="arm_0",
        role="treatment",
        label="linagliptin",
        seed_text="linagliptin",
        existing_cohort_id=None,
        expression_builder=lambda: expression,
    )
    assert item.status == "created", item.model_dump()
    assert client.expression is not None
    return client.expression


class TestTheEmittedWashoutStopsBeforeIndex:
    def test_should_end_the_washout_the_day_before_index_when_it_contains_the_entry_drug(
        self, service
    ):
        """The blocking defect: the entry exposure falls inside its own washout."""
        emitted = _emit(
            service,
            _circe([_washout_rule("DPP-4 inhibitors use", 2, INDEX_DAY_END)]),
        )
        assert _end_of(emitted, "DPP-4 inhibitors use") == DAY_BEFORE_INDEX_END

    def test_should_leave_a_washout_alone_when_its_set_misses_the_entry_drug(self, service):
        """Scope is the collision, not washouts in general -- a study that is fine
        must not move."""
        emitted = _emit(
            service,
            _circe([_washout_rule("GLP-1 RA use", 3, INDEX_DAY_END)]),
        )
        assert _end_of(emitted, "GLP-1 RA use") == INDEX_DAY_END

    def test_should_leave_a_window_that_runs_past_index_alone(self, service):
        """A washout ending 365 days AFTER index is not a boundary-off-by-one; it
        excludes people for taking the drug after entry, which is a different rule.
        Moving it would silence the guard on the shape the guard exists for."""
        emitted = _emit(
            service,
            _circe([_washout_rule("No linagliptin", 2, PAST_INDEX_END)]),
        )
        assert _end_of(emitted, "No linagliptin") == PAST_INDEX_END

    def test_should_leave_a_presence_rule_alone(self, service):
        """Requiring the entry drug to be present is redundant, not contradictory."""
        rule = _washout_rule("On linagliptin", 2, INDEX_DAY_END)
        rule["expression"]["CriteriaList"][0]["Occurrence"] = {"Type": 2, "Count": 1}
        emitted = _emit(service, _circe([rule]))
        assert _end_of(emitted, "On linagliptin") == INDEX_DAY_END

    def test_should_correct_a_washout_nested_in_an_all_group(self, service):
        """CARMELINA's real shape: the class washouts sit one ALL group down."""
        inner = _washout_rule("inner", 2, INDEX_DAY_END)["expression"]
        rule = {
            "name": "GLP-1 receptor agonists use + DPP-4 inhibitors use",
            "expression": {
                "Type": "ALL",
                "CriteriaList": [],
                "DemographicCriteriaList": [],
                "Groups": [inner],
            },
        }
        emitted = _emit(service, _circe([rule]))
        group = emitted["InclusionRules"][0]["expression"]["Groups"][0]
        assert group["CriteriaList"][0]["StartWindow"]["End"] == DAY_BEFORE_INDEX_END
