"""An arm build emits a concept set's stored contents; it does not re-map a set by its name.

`_repair_stale_drug_concept_sets` ran at all three arm-build exits (treatment on the stored
entry, treatment on a freshly mapped drug, active comparator). It looked every concept-set
NAME up as an RxNorm Ingredient (`LOWER(concept_name) = ANY(names)`) and, where one
matched, replaced the set's contents with that ingredient. That reads a name as text to
choose concepts, which AGENTS.md § PROMPTS AND TEXT RULES forbids, and it never acted on
a measured run: 0 rewrites / 6 declines on the delivery candidate, 0 / 8 on P3 arm A
(output/site_gap/2026-10-12_p3_dry/analysis_a/textrule_removal/classC_evidence/
d2_export_d3.txt). Every set it could select was chosen by its name, so nothing of it
survives on ids alone and it is deleted.

The set below is the stale shape the repair was written for: named after one ingredient,
holding another. The build must emit it as stored, and must not ask the vocabulary
anything to decide that -- `psycopg2.connect` raises if anything tries.
"""
from __future__ import annotations

from typing import Any

import pytest

from src.services.tte_service import TTEService

SITAGLIPTIN = 1580747
#: A concept-set name that is exactly one RxNorm Ingredient's name, for a set that holds
#: a different ingredient.
INGREDIENT_NAME = "linagliptin"


def _expression(concept_ids: list[int]) -> dict[str, Any]:
    return {
        "items": [
            {
                "concept": {
                    "CONCEPT_ID": cid,
                    "CONCEPT_NAME": "sitagliptin",
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
        "targetCohortName": INGREDIENT_NAME,
        "inclusionCriteria": [],
        "exclusionCriteria": [],
        "structuredExpression": {
            "ConceptSets": [
                {"id": 1, "name": INGREDIENT_NAME, "expression": _expression(entry_concept_ids)}
            ],
            "PrimaryCriteria": {
                "CriteriaList": [{"DrugEra": {"CodesetId": 1}}],
                "ObservationWindow": {"PriorDays": 365, "PostDays": 0},
                "PrimaryCriteriaLimit": {"Type": "First"},
            },
            "InclusionRules": [],
        },
    }


def _mapped_drug() -> dict[str, Any]:
    return {
        "name": INGREDIENT_NAME,
        "domain": "Drug",
        "expression": _expression([SITAGLIPTIN]),
        "mapping_metadata": None,
    }


def _entry_set_ids(circe: dict[str, Any]) -> list[int]:
    """The concept ids of the set the emitted PrimaryCriteria enters on."""
    sets_by_id = {cs["id"]: cs for cs in circe.get("ConceptSets") or []}
    ids: list[int] = []
    for crit in (circe.get("PrimaryCriteria") or {}).get("CriteriaList") or []:
        for body in crit.values():
            cs = sets_by_id.get(body.get("CodesetId")) if isinstance(body, dict) else None
            if cs is not None:
                ids.extend(i["concept"]["CONCEPT_ID"] for i in cs["expression"]["items"])
    return sorted(ids)


@pytest.fixture
def service(monkeypatch) -> TTEService:
    svc = TTEService.__new__(TTEService)
    monkeypatch.setenv("TTE_DRUG_ANCHORED_ENTRY", "1")
    monkeypatch.setattr(svc, "_recommend_seeded_concept_set", lambda seed, **kw: _mapped_drug())

    def _no_vocabulary(*_args, **_kwargs):
        raise AssertionError("the arm build asked the vocabulary database")

    monkeypatch.setattr("psycopg2.connect", _no_vocabulary)
    return svc


def test_should_emit_the_stored_entry_set_when_its_name_is_another_ingredients_name(service):
    circe = service._build_disease_based_treatment_circe(
        _eligibility([SITAGLIPTIN]), INGREDIENT_NAME
    )
    assert _entry_set_ids(circe) == [SITAGLIPTIN]


def test_should_emit_the_freshly_mapped_entry_set_when_its_name_is_another_ingredients_name(
    service,
):
    """No stored entry: the arm name is mapped, and the set it maps to is emitted as is."""
    circe = service._build_disease_based_treatment_circe(_eligibility([]), INGREDIENT_NAME)
    assert _entry_set_ids(circe) == [SITAGLIPTIN]


def test_should_emit_the_comparator_set_when_its_name_is_another_ingredients_name(service):
    circe = service._build_drug_anchored_comparator_circe(
        _eligibility([SITAGLIPTIN]), INGREDIENT_NAME, prebuilt_concept_set=_mapped_drug()
    )
    assert _entry_set_ids(circe) == [SITAGLIPTIN]
