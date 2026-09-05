"""The comparator must not re-derive the study drug by name, and a build failure must be reported.

Two defects, one incident. EMPA-REG's derived comparator excludes users of the study
drug, and it resolved that drug from the arm-name string "BI 10773" with no alias
context — the same shape as the treatment-path defect already fixed by preferring the
store's resolved entry concept set. Here it does not silently return the wrong drug; it
raises `ValueError: No concept mapping found for BI 10773`.

That raise was then caught by a bare `except Exception: pass` in
`_materialize_seeded_cohort_item`'s already-attached branch, so the arm produced no
file, the exporter wrote a manifest listing five files, and the delivery gate exited 0.
A swallow on a delivery path turns a loud failure into a missing deliverable.
"""
from __future__ import annotations

from typing import Any

import pytest

from src.services.tte_service import TTEService

EMPAGLIFLOZIN = 45774751
EMBEDDING_FALLBACK_IDS = [702171, 859730, 1201447, 1201518, 1254065]


def _expression(concept_ids: list[int], name: str) -> dict[str, Any]:
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


def _eligibility(entry_concept_ids: list[int]) -> dict[str, Any]:
    return {
        "targetCohortName": "BI 10773",
        "inclusionCriteria": [],
        "exclusionCriteria": [],
        "structuredExpression": {
            "ConceptSets": [
                {
                    "id": 1,
                    "name": "BI 10773",
                    "expression": _expression(entry_concept_ids, "empagliflozin"),
                }
            ],
            "PrimaryCriteria": {
                "CriteriaList": [{"DrugEra": {"CodesetId": 1}}],
                "ObservationWindow": {"PriorDays": 365, "PostDays": 0},
                "PrimaryCriteriaLimit": {"Type": "First"},
            },
            "InclusionRules": [],
        },
    }


def _absence_rule_concept_ids(circe: dict[str, Any], arm_name: str) -> list[int]:
    """The concept ids the emitted drug-ABSENCE rule actually excludes on."""
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
            if cs is None:
                continue
            return sorted(i["concept"]["CONCEPT_ID"] for i in cs["expression"]["items"])
    raise AssertionError("no drug rule naming " + repr(arm_name) + " in " + repr(
        [r.get("name") for r in circe.get("InclusionRules") or []]))


@pytest.fixture
def service(monkeypatch) -> TTEService:
    """Name resolution raises, the way it really does for a development code."""
    svc = TTEService.__new__(TTEService)
    monkeypatch.setenv("TTE_DRUG_ANCHORED_ENTRY", "1")

    def fake_recommend(seed_text: str, **kwargs: Any) -> dict[str, Any]:
        raise ValueError("No concept mapping found for " + repr(seed_text.strip()))

    monkeypatch.setattr(svc, "_recommend_seeded_concept_set", fake_recommend)
    monkeypatch.setattr(svc, "_repair_stale_drug_concept_sets", lambda base: None)
    return svc


class TestTheComparatorReusesTheStoreDrugSet:
    def test_should_use_the_store_entry_concept_set_when_name_resolution_would_fail(
        self, service
    ):
        """The regression: the arm name is a development code, and the store already
        holds the resolved drug. Re-deriving it raises and loses the whole arm."""
        circe = service._build_disease_based_comparator_circe(
            _eligibility([EMPAGLIFLOZIN]), "BI 10773"
        )
        assert _absence_rule_concept_ids(circe, "BI 10773") == [EMPAGLIFLOZIN]

    def test_should_still_emit_the_absence_rule_rather_than_raising(self, service):
        circe = service._build_disease_based_comparator_circe(
            _eligibility([EMPAGLIFLOZIN]), "BI 10773"
        )
        assert any("BI 10773" in r.get("name", "") for r in circe["InclusionRules"])

    def test_should_propagate_the_resolution_failure_when_the_store_has_no_entry_set(
        self, service
    ):
        """Reuse is a preference, not a mask. With nothing stored to reuse there is no
        answer, and inventing one is what produced the wrong drug in the first place."""
        with pytest.raises(ValueError):
            service._build_disease_based_comparator_circe(_eligibility([]), "BI 10773")


class TestABuildFailureIsReportedRatherThanSwallowed:
    def test_should_report_failed_when_the_expression_builder_raises_for_an_attached_arm(
        self, service
    ):
        """`existing_cohort_id` is set for every arm of every study in the store, so this
        branch is the one every real export takes."""
        def _boom() -> dict[str, Any]:
            raise ValueError("No concept mapping found for 'BI 10773'")

        item = service._materialize_seeded_cohort_item(
            client=None,
            study_id=8,
            study_name="EMPA-REG",
            section="treatmentArms",
            item_key="arm_1",
            role="comparator",
            label="No BI 10773",
            seed_text="Placebo",
            existing_cohort_id=3380,
            expression_builder=_boom,
        )
        assert item.status == "failed"
        assert item.error is not None
        assert "No concept mapping found" in item.error

    def test_should_still_report_already_attached_when_the_builder_succeeds(self, service):
        """The non-failing shape of the same branch must keep its existing meaning."""
        class _Client:
            def create_cohort_definition(self, name, expression, description=""):
                return {"id": 3380, "name": name}

        item = service._materialize_seeded_cohort_item(
            client=_Client(),
            study_id=8,
            study_name="EMPA-REG",
            section="treatmentArms",
            item_key="arm_1",
            role="comparator",
            label="No BI 10773",
            seed_text="Placebo",
            existing_cohort_id=3380,
            expression_builder=lambda: {"InclusionRules": []},
        )
        assert item.status == "skipped"
        assert item.reason == "already_attached"
