"""The entry concept set of a drug-anchored cohort belongs to the store, not to the arm name.

Under `TTE_DRUG_ANCHORED_ENTRY`, a treatment cohort enters on the study drug. The store
already carries a resolved entry concept set for that drug, put there at generation time
by the target mapping -- which had the trial's MeSH intervention terms in hand. The
export path used to discard it and re-resolve the drug from the arm-name string alone,
without those aliases, and accept whatever came back.

For EMPA-REG the arm name is the development code "BI 10773", which appears nowhere in
the vocabulary, so exact-ingredient and alias lookup both refuse and the seed falls
through to embedding search. That produced `[702171, 859730, 1201447, 1201518, 1254065]`
-- bictegravir, a CHF-6366 metabolite, a Trikafta pack, vilobelimab -- while the store
held `[45774751 empagliflozin]`. Twelve CIRCE files went to two hospitals with that entry
set and returned 0 patients.

The signature is arm asymmetry: the comparator builder never repoints the entry, so the
two arms of one study disagreed about what the study drug was.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from src.services.tte_service import TTEService

EMPAGLIFLOZIN = 45774751
# The five concepts embedding search actually returned for "BI 10773".
EMBEDDING_FALLBACK_IDS = [702171, 859730, 1201447, 1201518, 1254065]


def _expression(concept_ids: list[int], name: str = "drug") -> dict[str, Any]:
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


def _entry_concept_ids(circe: dict[str, Any]) -> list[int]:
    """The concept ids the emitted PrimaryCriteria actually enters on."""
    sets_by_id = {cs["id"]: cs for cs in circe.get("ConceptSets") or []}
    out: list[int] = []
    for crit in (circe.get("PrimaryCriteria") or {}).get("CriteriaList") or []:
        for _domain, body in crit.items():
            if not isinstance(body, dict):
                continue
            cs = sets_by_id.get(body.get("CodesetId"))
            if cs is None:
                continue
            out.extend(
                item["concept"]["CONCEPT_ID"]
                for item in cs.get("expression", {}).get("items") or []
            )
    return sorted(out)


def _eligibility(entry_concept_ids: list[int]) -> dict[str, Any]:
    """A store study whose PrimaryCriteria enters on a DrugEra of the study drug."""
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


@pytest.fixture
def service(monkeypatch) -> TTEService:
    """Name resolution answers the way it really did for 'BI 10773'.

    The stub is the embedding fallback, not a failure: the defect is that a plausible
    wrong answer was accepted silently, so a stub that raised would test nothing.
    """
    svc = TTEService.__new__(TTEService)
    monkeypatch.setenv("TTE_DRUG_ANCHORED_ENTRY", "1")

    def fake_recommend(seed_text: str, **kwargs: Any) -> dict[str, Any]:
        return {
            "name": seed_text.strip(),
            "domain": "Drug",
            "expression": _expression(EMBEDDING_FALLBACK_IDS, "unrelated"),
            "mapping_metadata": None,
        }

    monkeypatch.setattr(svc, "_recommend_seeded_concept_set", fake_recommend)
    # The repair pass needs a live vocabulary database; it already fails open, and
    # stubbing it keeps this test about the entry choice rather than about psycopg2.
    monkeypatch.setattr(svc, "_repair_stale_drug_concept_sets", lambda base: None)
    return svc


class TestTheStoredEntryWins:
    def test_should_reuse_the_store_entry_concept_set_when_it_resolves(self, service):
        circe = service._build_disease_based_treatment_circe(
            _eligibility([EMPAGLIFLOZIN]), "BI 10773"
        )
        assert _entry_concept_ids(circe) == [EMPAGLIFLOZIN]

    def test_should_not_append_an_unreferenced_drug_concept_set_when_the_store_entry_is_reused(
        self, service
    ):
        """Reusing the stored entry and still appending the re-resolved set would leave
        the wrong concepts in the file, unreferenced but readable, for a site to find."""
        circe = service._build_disease_based_treatment_circe(
            _eligibility([EMPAGLIFLOZIN]), "BI 10773"
        )
        emitted = sorted(
            item["concept"]["CONCEPT_ID"]
            for cs in circe["ConceptSets"]
            for item in cs.get("expression", {}).get("items") or []
        )
        assert emitted == [EMPAGLIFLOZIN]

    def test_should_agree_on_the_entry_concept_set_between_both_arms_of_one_study(self, service):
        """The defect's signature. The comparator builder never repointed the entry, so
        the two arms of one study disagreed about what the study drug was."""
        eligibility = _eligibility([EMPAGLIFLOZIN])
        treatment = service._build_disease_based_treatment_circe(
            deepcopy(eligibility), "BI 10773"
        )
        comparator = service._build_disease_based_comparator_circe(
            deepcopy(eligibility), "BI 10773"
        )
        assert _entry_concept_ids(treatment) == _entry_concept_ids(comparator)


class TestNameResolutionStillServesAStoreWithNoEntrySet:
    def test_should_resolve_the_entry_from_the_arm_name_when_the_store_entry_is_empty(
        self, service
    ):
        """A store whose entry concept set resolved to nothing has no answer to reuse,
        so the arm name is still the fallback -- reuse is a preference, not a lock."""
        circe = service._build_disease_based_treatment_circe(_eligibility([]), "BI 10773")
        assert _entry_concept_ids(circe) == sorted(EMBEDDING_FALLBACK_IDS)
