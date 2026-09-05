"""A placebo comparator must not enter on the drug its own rule excludes.

`_swap_primary_to_disease` early-returned under `TTE_DRUG_ANCHORED_ENTRY`, so the
derived (placebo) comparator kept the treatment `DrugEra` entry while its last rule
required zero occurrences of that same drug. No person can satisfy both, so the cohort
is empty by construction. `docs/wiki/content/drug-anchored-placebo-comparator-guard.md`
records the collision and names this fix as the outstanding work; the 2026-08-31
delivery sidestepped it by exporting placebo comparators with the flag off, which is the
composition these tests reproduce — a disease-anchored entry with the drug-absence rule
intact.

The active comparator is a different case and must not change: it enters on a genuinely
different drug (CAROLINA's glimepiride), never calls the swap, and is not contradictory.
"""
from __future__ import annotations

from typing import Any

import pytest

from src.services.tte_service import TTEService
from src.utils.circe_lint import contradictory_absence_rules, entry_concept_ids

EMPAGLIFLOZIN = 45774751
T2DM = 201826


def _drug_items(concept_ids: list[int], name: str) -> dict[str, Any]:
    return {
        "items": [
            {
                "concept": {
                    "CONCEPT_ID": cid,
                    "CONCEPT_NAME": name,
                    "CONCEPT_CODE": str(cid),
                    "DOMAIN_ID": "Drug",
                    "VOCABULARY_ID": "RxNorm",
                    "CONCEPT_CLASS_ID": "Ingredient",
                },
                "includeDescendants": True,
                "isExcluded": False,
            }
            for cid in concept_ids
        ]
    }


def _condition_items() -> dict[str, Any]:
    return {
        "items": [
            {
                "concept": {
                    "CONCEPT_ID": T2DM,
                    "CONCEPT_NAME": "Type 2 diabetes mellitus",
                    "CONCEPT_CODE": str(T2DM),
                    "DOMAIN_ID": "Condition",
                    "VOCABULARY_ID": "SNOMED",
                    "CONCEPT_CLASS_ID": "Clinical Finding",
                },
                "includeDescendants": True,
                "isExcluded": False,
            }
        ]
    }


def _eligibility() -> dict[str, Any]:
    """A store study entering on the study drug, with a Condition rule the fallback
    swap can anchor on — the shape studies 8 and 9 actually have."""
    return {
        "targetCohortName": "BI 10773",
        "inclusionCriteria": [],
        "exclusionCriteria": [],
        "structuredExpression": {
            "ConceptSets": [
                {
                    "id": 1,
                    "name": "BI 10773",
                    "expression": _drug_items([EMPAGLIFLOZIN], "empagliflozin"),
                },
                {"id": 2, "name": "Type 2 Diabetes Mellitus", "expression": _condition_items()},
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
                }
            ],
        },
    }


def _drug_rule_concept_ids(circe: dict[str, Any], arm_name: str) -> list[int]:
    sets_by_id = {cs["id"]: cs for cs in circe.get("ConceptSets") or []}
    for rule in circe.get("InclusionRules") or []:
        if arm_name not in rule.get("name", ""):
            continue
        for leaf in rule["expression"].get("CriteriaList") or []:
            body = leaf.get("Criteria", leaf)
            domain = next((k for k in body if isinstance(body[k], dict)), None)
            if domain is None:
                continue
            cs = sets_by_id.get(body[domain].get("CodesetId"))
            if cs is not None:
                return sorted(i["concept"]["CONCEPT_ID"] for i in cs["expression"]["items"])
    raise AssertionError("no drug rule naming " + repr(arm_name))


@pytest.fixture
def service(monkeypatch) -> TTEService:
    svc = TTEService.__new__(TTEService)
    monkeypatch.setenv("TTE_DRUG_ANCHORED_ENTRY", "1")

    def fake_recommend(seed_text: str, **kwargs: Any) -> dict[str, Any]:
        raise ValueError("No concept mapping found for " + repr(seed_text.strip()))

    monkeypatch.setattr(svc, "_recommend_seeded_concept_set", fake_recommend)
    monkeypatch.setattr(svc, "_repair_stale_drug_concept_sets", lambda base: None)
    return svc


class TestThePlaceboComparatorIsDiseaseAnchored:
    def test_should_enter_on_the_disease_when_drug_anchored_entry_is_on(self, service):
        """The regression. With the drug entry kept, the cohort excludes its own entry."""
        circe = service._build_disease_based_comparator_circe(_eligibility(), "BI 10773")
        domain, ids = entry_concept_ids(circe)
        assert domain == "ConditionOccurrence"
        assert ids == {T2DM}

    def test_should_keep_the_drug_absence_rule_after_the_swap(self, service):
        """The swap must move the entry, not drop the rule that defines the comparator."""
        circe = service._build_disease_based_comparator_circe(_eligibility(), "BI 10773")
        assert _drug_rule_concept_ids(circe, "BI 10773") == [EMPAGLIFLOZIN]

    def test_should_preserve_the_eligibility_rules_through_the_swap(self, service):
        circe = service._build_disease_based_comparator_circe(_eligibility(), "BI 10773")
        names = [r["name"] for r in circe["InclusionRules"]]
        assert "Type 2 Diabetes Mellitus" in names
        assert "No BI 10773" in names

    def test_should_produce_no_contradictory_absence_rule(self, service):
        circe = service._build_disease_based_comparator_circe(_eligibility(), "BI 10773")
        assert contradictory_absence_rules(circe) == []


class TestTheActiveComparatorKeepsItsDrugAnchor:
    def test_should_still_enter_on_the_comparator_drug(self, service, monkeypatch):
        """CAROLINA's shape: a genuinely different drug, correctly drug-anchored."""
        glimepiride = {
            "name": "glimepiride",
            "domain": "Drug",
            "expression": _drug_items([1597756], "glimepiride"),
            "mapping_metadata": None,
        }
        circe = service._build_drug_anchored_comparator_circe(
            _eligibility(), "glimepiride", prebuilt_concept_set=glimepiride
        )
        domain, ids = entry_concept_ids(circe)
        assert domain == "DrugEra"
        assert ids == {1597756}

    def test_should_produce_no_contradictory_absence_rule(self, service):
        glimepiride = {
            "name": "glimepiride",
            "domain": "Drug",
            "expression": _drug_items([1597756], "glimepiride"),
            "mapping_metadata": None,
        }
        circe = service._build_drug_anchored_comparator_circe(
            _eligibility(), "glimepiride", prebuilt_concept_set=glimepiride
        )
        assert contradictory_absence_rules(circe) == []
