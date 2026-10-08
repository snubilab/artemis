"""Route subtraction must reach the expression `_recommend_seeded_concept_set` returns.

`_apply_route_subtraction` appends isExcluded Clinical Drug Form items. Until this
fix it appended them to a COPY of the built expression's item list, so the returned
expression -- and the criterion-cache entry stored from it -- never carried them:
the verify5 store's "Systemic corticosteroid" set held 0 excluded items while the
log reported 779 computed. These tests drive the real method with the mapper's
collaborators stubbed, and the route decision itself left real.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agents.agent2.criterion_cache import CriterionResultCache
from src.models.ir import MappingResult
from src.services.route_subtraction import DrugForm

INGREDIENT_ID = 1001
ORAL_FORM_ID = 2001
TOPICAL_FORM_ID = 2002
SEED = "Systemic corticosteroid"


def _ingredient_expression() -> dict:
    return {
        "items": [
            {
                "concept": {
                    "CONCEPT_ID": INGREDIENT_ID,
                    "CONCEPT_NAME": "prednisolone",
                    "DOMAIN_ID": "Drug",
                    "CONCEPT_CLASS_ID": "Ingredient",
                    "STANDARD_CONCEPT": "S",
                    "VOCABULARY_ID": "RxNorm",
                    "CONCEPT_CODE": "8638",
                    "INVALID_REASON": None,
                },
                "isExcluded": False,
                "includeDescendants": True,
                "includeMapped": False,
            }
        ]
    }


def _candidate() -> MagicMock:
    cand = MagicMock()
    cand.concept_id = INGREDIENT_ID
    cand.concept_name = "prednisolone"
    cand.domain_id = "Drug"
    return cand


def _run(forms: list[DrugForm], cache: CriterionResultCache | None = None) -> dict:
    """Call the real mapper once with Agent 2, the builder and the vocabulary stubbed."""
    from src.services.tte_service import TTEService

    svc = TTEService(store=MagicMock())
    workflow = MagicMock()
    workflow.process_with_details.return_value = MappingResult(
        concept_ids=[INGREDIENT_ID], overbroad_concept_ids=[], route_path="slow",
    )
    recommendation = MagicMock()
    recommendation.name = SEED
    # A fresh dict per build, as the real to_atlas_json produces.
    recommendation.expression.to_atlas_json.side_effect = lambda: _ingredient_expression()
    builder = MagicMock()
    builder.build_expression.return_value = recommendation

    with patch.object(TTEService, "_exact_ingredient_match_enabled", return_value=False), \
         patch.object(TTEService, "_fetch_concept_candidates", return_value=[_candidate()]), \
         patch.object(TTEService, "_fetch_drug_forms", return_value=forms), \
         patch("src.agents.conceptset.expression_builder.get_expression_builder",
               return_value=builder), \
         patch("src.services.tte_service._criterion_cache_enabled",
               return_value=cache is not None), \
         patch("src.services.tte_service.get_criterion_cache", return_value=cache):
        return svc._recommend_seeded_concept_set(
            SEED, expected_domain="Drug", workflow=workflow,
        )


def _excluded_ids(expression: dict) -> list[int]:
    return [i["concept"]["CONCEPT_ID"] for i in expression["items"] if i.get("isExcluded")]


ORAL = DrugForm(ORAL_FORM_ID, "prednisolone Oral Tablet", "Oral Tablet")
TOPICAL = DrugForm(TOPICAL_FORM_ID, "prednisolone Topical Cream", "Topical Cream")


def test_should_return_route_exclusions_when_route_subtraction_excludes_a_form():
    result = _run([ORAL, TOPICAL])

    assert _excluded_ids(result["expression"]) == [TOPICAL_FORM_ID]
    excluded = next(i for i in result["expression"]["items"] if i.get("isExcluded"))
    assert excluded["includeDescendants"] is True
    assert excluded["concept"]["CONCEPT_CLASS_ID"] == "Clinical Drug Form"


def test_should_leave_expression_unchanged_when_route_subtraction_excludes_nothing():
    result = _run([ORAL])

    assert result["expression"] == _ingredient_expression()


def test_should_cache_the_returned_expression_when_route_subtraction_excludes_a_form():
    cache = CriterionResultCache(max_entries=10, ttl_hours=1)

    result = _run([ORAL, TOPICAL], cache=cache)
    cached = cache.get(" ".join(SEED.split()), "Drug")

    assert cached is not None
    assert cached.expression == result["expression"]
    assert _excluded_ids(cached.expression) == [TOPICAL_FORM_ID]


def test_should_serve_route_exclusions_when_a_second_call_hits_the_cache():
    cache = CriterionResultCache(max_entries=10, ttl_hours=1)
    _run([ORAL, TOPICAL], cache=cache)

    # Forms empty on the second call: only the cache can supply the exclusion.
    second = _run([], cache=cache)

    assert _excluded_ids(second["expression"]) == [TOPICAL_FORM_ID]


@pytest.mark.parametrize("forms", [[ORAL, TOPICAL], [ORAL]])
def test_should_report_selected_ids_matching_the_expression_when_mapping(forms):
    result = _run(forms)

    expression_ids = [i["concept"]["CONCEPT_ID"] for i in result["expression"]["items"]]
    assert result["mapping_metadata"].selectedConceptIds == expression_ids
