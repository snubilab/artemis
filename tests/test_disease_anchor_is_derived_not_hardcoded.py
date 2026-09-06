"""The disease entry anchor must come from the study, never from a table keyed on NCT id.

`DISEASE_ANCHOR_CONCEPTS` mapped three benchmark NCT ids to a hardcoded condition
concept. A study whose id was in that table took a different branch: its entry was
replaced by the tabled concept AND its `InclusionRules` were emptied, on the stated
grounds that "eligibility criteria are too restrictive for the small benchmark CDMs".
A study not in the table kept every rule and derived its anchor from its own Condition
criteria. Two studies with identical clinical content therefore produced structurally
different cohorts purely because someone had listed one id.

A comparator carrying none of its trial's eligibility criteria is not an emulation of
that trial, so the table is removed and every study takes the derivation path.
"""
from __future__ import annotations

from typing import Any

import pytest

from src.services.tte_service import TTEService

T2DM = 201826
EMPAGLIFLOZIN = 45774751
LEADER_NCT = "NCT01179048"
NOT_TABLED_NCT = "NCT99999999"


def _base() -> dict[str, Any]:
    """A drug-anchored base carrying one Condition rule the derivation can anchor on."""
    return {
        "ConceptSets": [
            {
                "id": 1,
                "name": "study drug",
                "expression": {
                    "items": [
                        {
                            "concept": {
                                "CONCEPT_ID": EMPAGLIFLOZIN,
                                "CONCEPT_NAME": "empagliflozin",
                                "DOMAIN_ID": "Drug",
                                "VOCABULARY_ID": "RxNorm",
                                "CONCEPT_CLASS_ID": "Ingredient",
                            },
                            "includeDescendants": True,
                            "isExcluded": False,
                        }
                    ]
                },
            },
            {
                "id": 2,
                "name": "Type 2 Diabetes Mellitus",
                "expression": {
                    "items": [
                        {
                            "concept": {
                                "CONCEPT_ID": T2DM,
                                "CONCEPT_NAME": "Type 2 diabetes mellitus",
                                "DOMAIN_ID": "Condition",
                                "VOCABULARY_ID": "SNOMED",
                                "CONCEPT_CLASS_ID": "Clinical Finding",
                            },
                            "includeDescendants": True,
                            "isExcluded": False,
                        }
                    ]
                },
            },
        ],
        "PrimaryCriteria": {
            "CriteriaList": [{"DrugEra": {"CodesetId": 1}}],
            "ObservationWindow": {"PriorDays": 365, "PostDays": 0},
            "PrimaryCriteriaLimit": {"Type": "First"},
        },
        "InclusionRules": [
            {
                "name": "Type 2 Diabetes Mellitus",
                "expression": {
                    "Type": "ALL",
                    "CriteriaList": [
                        {
                            "Criteria": {"ConditionOccurrence": {"CodesetId": 2}},
                            "Occurrence": {"Type": 2, "Count": 1},
                        }
                    ],
                    "DemographicCriteriaList": [],
                    "Groups": [],
                },
            },
            {
                "name": "Age >= 50",
                "expression": {
                    "Type": "ALL",
                    "CriteriaList": [],
                    "DemographicCriteriaList": [{"Age": {"Value": 50, "Op": "gte"}}],
                    "Groups": [],
                },
            },
        ],
    }


def _study(nct_id: str) -> dict[str, Any]:
    return {"trialMetadata": {"nctId": nct_id}}


@pytest.fixture
def service(monkeypatch) -> TTEService:
    svc = TTEService.__new__(TTEService)
    monkeypatch.delenv("TTE_DRUG_ANCHORED_ENTRY", raising=False)
    return svc


class TestTheAnchorIsDerivedFromTheStudy:
    def test_should_keep_the_eligibility_rules_when_the_nct_is_a_benchmark_id(self, service):
        """The defect. A tabled NCT emitted a rule-free skeleton; the rules must survive."""
        swapped = service._swap_primary_to_disease(_base(), {}, study=_study(LEADER_NCT))
        assert [r["name"] for r in swapped["InclusionRules"]] == [
            "Type 2 Diabetes Mellitus",
            "Age >= 50",
        ]

    def test_should_build_the_same_cohort_when_only_the_nct_id_differs(self, service):
        """Identical clinical content must not produce a different cohort by identity."""
        tabled = service._swap_primary_to_disease(_base(), {}, study=_study(LEADER_NCT))
        untabled = service._swap_primary_to_disease(_base(), {}, study=_study(NOT_TABLED_NCT))
        assert tabled == untabled
