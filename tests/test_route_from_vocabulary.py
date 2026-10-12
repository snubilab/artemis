"""RFC-016 step 4, A12 + C2: which drug forms a route restriction keeps comes from the vocabulary.

The route a criterion asks for is the annotation's ``route`` field, quoted from its protocol
line (``criterion_annotation.stated_route``). Which forms satisfy it is OMOP's
``Has route of admin`` edge from each Clinical Drug Form's dose form to a SNOMED / OMOP
Extension route concept, with ``concept_ancestor`` above it -- the vocabulary files
Transdermal under Topical and Nasal under Respiratory tract. No dose-form name and no
criterion text is read.

Dose forms, routes and ancestors are the real ones, from
``tests/fixtures/rxnorm_dose_form_routes.json`` (synthea23m capture). The Clinical Drug Form
ids are stand-ins: the decision reads only the form's route. Criterion rows are real, from
``tests/fixtures/rfc016_step4_rows.json``.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.services.criterion_annotation import ANNOTATION_KEY, validate_annotation
from src.services.overbroad_absence_repair import ConceptRecord
from src.services.route_subtraction import (
    AdministrationRoute,
    DrugForm,
    compute_route_subtraction,
)
from src.services.tte_service import TTEService

FIXTURES = Path(__file__).resolve().parent / "fixtures"
VOCAB = json.loads((FIXTURES / "rxnorm_dose_form_routes.json").read_text())
ROWS = json.loads((FIXTURES / "rfc016_step4_rows.json").read_text())

_ANCESTORS = {route["routeId"]: frozenset(route["ancestorIds"]) for route in VOCAB["routes"]}
_DOSE_FORMS = {form["doseFormId"]: form for form in VOCAB["doseForms"]}


def _form(cdf_id: int, dose_form_id: int) -> DrugForm:
    """A Clinical Drug Form under a real dose form, carrying that form's route closure."""
    dose_form = _DOSE_FORMS[dose_form_id]
    route = dose_form["routeId"]
    return DrugForm(
        concept_id=cdf_id,
        concept_name=f"stand-in {dose_form['name']}",
        dose_form=dose_form["name"],
        route_ids=_ANCESTORS[route] if route is not None else frozenset(),
    )


ORAL_TABLET = _form(1, 19082573)
TOPICAL_CREAM = _form(2, 19082224)
TRANSDERMAL_SYSTEM = _form(3, 19082229)
NASAL_SPRAY = _form(4, 19011167)
METERED_DOSE_INHALER = _form(5, 19126918)
ORAL_LOZENGE = _form(6, 19082253)  # the vocabulary files it under Buccal, not Oral
RECTAL_SUPPOSITORY = _form(7, 19082200)
INJECTABLE_SOLUTION = _form(8, 19082103)
PACK = _form(9, 19127776)  # no route in the vocabulary
FORMS = [
    ORAL_TABLET,
    TOPICAL_CREAM,
    TRANSDERMAL_SYSTEM,
    NASAL_SPRAY,
    METERED_DOSE_INHALER,
    ORAL_LOZENGE,
    RECTAL_SUPPOSITORY,
    INJECTABLE_SOLUTION,
    PACK,
]


def _ids(forms: list[DrugForm]) -> set[int]:
    return {form.concept_id for form in forms}


class TestTheVocabularyDecides:
    def test_should_keep_only_oral_forms_when_the_route_is_oral(self):
        result = compute_route_subtraction(FORMS, [AdministrationRoute.ORAL])
        assert _ids(result.excluded) == _ids(FORMS) - {1, 9}
        assert _ids(result.undecidable) == {9}

    def test_should_keep_transdermal_forms_when_the_route_is_topical(self):
        result = compute_route_subtraction(FORMS, [AdministrationRoute.TOPICAL])
        assert {2, 3}.isdisjoint(_ids(result.excluded))

    def test_should_drop_topical_forms_when_the_route_is_transdermal(self):
        result = compute_route_subtraction(FORMS, [AdministrationRoute.TRANSDERMAL])
        assert 2 in _ids(result.excluded)
        assert 3 not in _ids(result.excluded)

    def test_should_keep_nasal_forms_when_the_route_is_the_respiratory_tract(self):
        result = compute_route_subtraction(FORMS, [AdministrationRoute.RESPIRATORY_TRACT])
        assert {4, 5}.isdisjoint(_ids(result.excluded))

    def test_should_keep_every_listed_route_when_several_are_stated(self):
        keep = [
            AdministrationRoute.ORAL,
            AdministrationRoute.INJECTABLE,
            AdministrationRoute.RECTAL,
        ]
        result = compute_route_subtraction(FORMS, keep)
        assert _ids(result.excluded) == {2, 3, 4, 5, 6}

    def test_should_never_subtract_a_form_whose_dose_form_has_no_route(self):
        result = compute_route_subtraction([PACK], [AdministrationRoute.ORAL])
        assert result.excluded == []
        assert result.undecidable == [PACK]

    @pytest.mark.parametrize("keep", [None, []])
    def test_should_subtract_nothing_when_no_route_is_stated(self, keep):
        assert compute_route_subtraction(FORMS, keep).excluded == []


# --------------------------------------------------------------------------- #
# The build step reads the annotation, never the seed
# --------------------------------------------------------------------------- #

INGREDIENT_ID = 1001
BASE = {"record_requirement": "forbidden", "conditional_span": None, "excepted_entities": []}


def _annotated(row: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    row = deepcopy(row)
    fields, rejected = validate_annotation({**BASE, **payload}, row["protocolLine"])
    assert not rejected, rejected
    row[ANNOTATION_KEY] = {"promptVersion": "test", "model": "stub", **fields}
    return row


def _ingredient_mapping(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "domain": "Drug",
        "expression": {
            "items": [
                {
                    "concept": ConceptRecord(
                        INGREDIENT_ID, name, "Drug", "RxNorm", "Ingredient", "S", "1", None
                    ).as_circe_concept(),
                    "isExcluded": False,
                    "includeDescendants": True,
                    "includeMapped": False,
                }
            ]
        },
        "mapping_metadata": None,
    }


def _records(forms: list[DrugForm]) -> dict[int, ConceptRecord]:
    return {
        f.concept_id: ConceptRecord(
            f.concept_id, f.concept_name, "Drug", "RxNorm", "Clinical Drug Form", "S", "", None
        )
        for f in forms
    }


def _build(criterion: dict[str, Any], mapping: dict[str, Any]) -> tuple[dict[str, Any], MagicMock]:
    service = TTEService.__new__(TTEService)
    fetch = MagicMock(return_value=FORMS)
    with (
        patch.object(TTEService, "_recommend_seeded_concept_set", return_value=mapping),
        patch.object(TTEService, "_fetch_drug_forms", fetch),
        patch.object(TTEService, "_fetch_concept_records", return_value=_records(FORMS)),
    ):
        result = service._build_seeded_eligibility_rule(
            criterion=criterion, codeset_id=70, exclusion=True
        )
    return result, fetch


def _excluded(result: dict[str, Any]) -> set[int]:
    items = result["conceptSet"]["expression"]["items"]
    return {i["concept"]["CONCEPT_ID"] for i in items if i.get("isExcluded")}


class TestTheBuildStep:
    def test_should_exclude_non_oral_forms_when_the_line_states_oral(self):
        row = _annotated(
            ROWS["carolina_exclusion_57"],
            {"route": ["oral"], "route_span": "oral, implantable or injectable contraceptives"},
        )
        mapping = _ingredient_mapping("oral contraceptives")
        result, _fetch = _build(row, mapping)
        assert _excluded(result) == _ids(FORMS) - {1, 9}
        assert mapping["expression"]["items"][1:] == [], "the mapper's expression is not mutated"

    def test_should_subtract_nothing_when_the_annotation_states_any_route(self):
        """CAROLINA exclusion 57's seed is "oral contraceptives": the route word is in the seed,
        and the seed is not read for one."""
        row = _annotated(ROWS["carolina_exclusion_57"], {"route": ["any"], "route_span": None})
        result, fetch = _build(row, _ingredient_mapping("oral contraceptives"))
        assert _excluded(result) == set()
        fetch.assert_not_called()

    def test_should_subtract_nothing_when_the_row_carries_no_annotation(self):
        result, fetch = _build(
            deepcopy(ROWS["leader_variant_inclusion_16"]), _ingredient_mapping("OADs")
        )
        assert _excluded(result) == set()
        fetch.assert_not_called()

    def test_should_keep_the_systemic_routes_the_annotation_lists(self):
        row = _annotated(
            ROWS["carolina_exclusion_18"],
            {
                "route": ["oral", "injectable", "rectal", "transdermal"],
                "route_span": "systemic corticosteroids",
            },
        )
        result, _fetch = _build(row, _ingredient_mapping("Systemic corticosteroid"))
        assert _excluded(result) == {2, 4, 5, 6}

    def test_should_list_the_emitted_members_as_selected_when_forms_are_excluded(self):
        """The invariant the mapper used to keep: the review UI's selected ids are the
        concept set's ids, exclusions included."""
        from src.api.models.tte import CriterionMappingMetadata

        row = _annotated(
            ROWS["plato_exclusion_22"],
            {"route": ["oral"], "route_span": "Oral anticoagulation therapy"},
        )
        mapping = _ingredient_mapping("Oral anticoagulant therapy")
        mapping["mapping_metadata"] = CriterionMappingMetadata(
            allCandidates=[],
            rerankConfidence=None,
            rerankMethod="agent2",
            queryUsed="Oral anticoagulant therapy",
            selectedConceptIds=[INGREDIENT_ID],
        )
        result, _fetch = _build(row, mapping)
        emitted = [i["concept"]["CONCEPT_ID"] for i in result["conceptSet"]["expression"]["items"]]
        assert result["_mapping_metadata"].selectedConceptIds == emitted
        assert mapping["mapping_metadata"].selectedConceptIds == [INGREDIENT_ID]


class TestTheMapperDoesNotReadARoute:
    def test_should_return_no_route_exclusion_from_the_mapper_whatever_the_seed_says(self):
        """The cached mapping is route-free: a route is the row's, not the seed's."""
        from src.models.ir import MappingResult

        svc = TTEService(store=MagicMock())
        workflow = MagicMock()
        workflow.process_with_details.return_value = MappingResult(
            concept_ids=[INGREDIENT_ID], overbroad_concept_ids=[], route_path="slow"
        )
        recommendation = MagicMock()
        recommendation.name = "Systemic corticosteroid"
        recommendation.expression.to_atlas_json.side_effect = lambda: deepcopy(
            _ingredient_mapping("prednisolone")["expression"]
        )
        builder = MagicMock()
        builder.build_expression.return_value = recommendation
        candidate = MagicMock(
            concept_id=INGREDIENT_ID, concept_name="prednisolone", domain_id="Drug"
        )
        fetch = MagicMock(return_value=FORMS)
        with (
            patch.object(TTEService, "_exact_ingredient_match_enabled", return_value=False),
            patch.object(TTEService, "_fetch_concept_candidates", return_value=[candidate]),
            patch.object(TTEService, "_fetch_drug_forms", fetch),
            patch(
                "src.agents.conceptset.expression_builder.get_expression_builder",
                return_value=builder,
            ),
            patch("src.services.tte_service._criterion_cache_enabled", return_value=False),
        ):
            result = svc._recommend_seeded_concept_set(
                "Systemic corticosteroid", expected_domain="Drug", workflow=workflow
            )
        workflow.process_with_details.assert_called_once()
        assert result["mapping_metadata"].rerankMethod == "agent2"
        assert not [i for i in result["expression"]["items"] if i.get("isExcluded")]
        fetch.assert_not_called()


def test_should_not_serve_a_cached_mapping_of_the_shape_that_carried_seed_routes(monkeypatch):
    """Entries written while the mapper read routes off the seed hold those exclusions;
    the entry-shape part of the key keeps them from being served as route-free."""
    from src.agents.agent2 import criterion_cache as cc

    cache = cc.CriterionResultCache(max_entries=10, ttl_hours=1)
    entry = cc.CriterionCacheEntry(
        concept_ids=[INGREDIENT_ID],
        expression=_ingredient_mapping("prednisolone")["expression"],
        name="Systemic corticosteroid",
        domain="Drug",
        created_at="2026-10-12T00:00:00+00:00",
    )
    monkeypatch.setattr(cc, "ENTRY_SHAPE", "seed-routes")
    cache.put("Systemic corticosteroid", "Drug", entry)
    assert cache.get("Systemic corticosteroid", "Drug") is not None

    monkeypatch.setattr(cc, "ENTRY_SHAPE", "route-free-v1")
    assert cache.get("Systemic corticosteroid", "Drug") is None
