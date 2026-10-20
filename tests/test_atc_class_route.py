"""A drug class the vocabulary files under one route keeps that route through the ingredient rollup.

The ATC path maps a drug-class phrase to an ATC class and rolls it up to RxNorm Ingredients,
which are route-blind. Some classes are route-specific by definition -- H02 "CORTICOSTEROIDS FOR
SYSTEMIC USE" holds only oral, injectable, buccal and implant Clinical Drug Forms -- and the
rollup threw that away: P7 CAROLINA exclusion 19 shipped H02A's 20 ingredients with every cream,
eye drop and inhaler under them (closure 53,243 vs gold 14,986, P 0.28).

The route kept is the vocabulary's: the ``Has route of admin`` of the dose forms ATC files under
the chosen class. Neither the phrase nor the protocol line is read.

The guard is the selector's own evidence. 'corticosteroids' tied five classes at distance 0.000
(C05AA rectal/topical, S02B otic, S03B eye) -- an arbitrary pick says nothing about route, and
applying C05AA's routes took EMPA-REG exclusion 29 from R 0.789 to R 0.033 against gold 217 in
the offline replay. The rankings below are copied from the P7 arm_main driver.log.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.agents.agent2.drug_class_expander import AtcHit, class_route_is_decided
from src.services.overbroad_absence_repair import ConceptRecord
from src.services.route_subtraction import (
    AdministrationRoute,
    DrugForm,
    routes_for_concept_ids,
)
from src.services.tte_service import TTEService


def _hits(*ranked: tuple[str, float]) -> list[AtcHit]:
    return [AtcHit(i, code, code, dist) for i, (code, dist) in enumerate(ranked)]


class TestTheClassRouteIsDecidedOnlyWhenTheClassIs:
    def test_should_decide_when_no_unrelated_class_is_near_the_choice(self):
        hits = _hits(("H02", 0.134), ("H02B", 0.162), ("H02BX", 0.162), ("H02A", 0.168),
                     ("R01AD", 0.202))
        assert class_route_is_decided(hits, hits[3])

    def test_should_decide_on_the_singular_wording_too(self):
        hits = _hits(("H02", 0.275), ("H02A", 0.319), ("H02B", 0.328), ("H02BX", 0.328),
                     ("S02BA", 0.359))
        assert class_route_is_decided(hits, hits[1])

    def test_should_not_decide_when_unrelated_classes_tie_the_choice(self):
        hits = _hits(("C05AA", 0.0), ("S02B", 0.0), ("S02BA", 0.0), ("S03B", 0.0),
                     ("S03BA", 0.0))
        assert not class_route_is_decided(hits, hits[0])

    def test_should_decide_when_every_near_hit_is_the_same_subtree(self):
        hits = _hits(("A10A", 0.453), ("A10AE", 0.597), ("A10AC", 0.600), ("A10AB", 0.606))
        assert class_route_is_decided(hits, hits[0])


class TestRouteConceptsBecomeRouteValues:
    def test_should_return_the_routes_for_known_route_concepts(self):
        assert set(routes_for_concept_ids([4132161, 706184])) == {
            AdministrationRoute.ORAL, AdministrationRoute.INJECTABLE}

    def test_should_return_none_when_a_route_concept_is_not_one_of_the_thirteen(self):
        """An unlisted route would have its forms subtracted as if no route covered them."""
        assert routes_for_concept_ids([4132161, 999]) is None

    def test_should_return_none_for_no_routes(self):
        assert routes_for_concept_ids([]) is None


ORAL = DrugForm(11, "x Oral Tablet", "Oral Tablet", frozenset({4132161}))
INJ = DrugForm(12, "x Injectable Solution", "Injectable Solution", frozenset({706184}))
CREAM = DrugForm(13, "x Topical Cream", "Topical Cream", frozenset({4263689}))
EYE = DrugForm(14, "x Ophthalmic Suspension", "Ophthalmic Suspension", frozenset({4184451}))
FORMS = [ORAL, INJ, CREAM, EYE]


def _map(route_ids: list[int]) -> dict[str, Any]:
    from src.models.ir import MappingResult

    svc = TTEService(store=MagicMock())
    workflow = MagicMock()
    workflow.process_with_details.return_value = MappingResult(
        concept_ids=[1001], overbroad_concept_ids=[], route_path="atc", atc_expanded=True,
        atc_route_ids=route_ids,
    )
    expression = {"items": [{
        "concept": ConceptRecord(1001, "prednisolone", "Drug", "RxNorm", "Ingredient", "S", "1",
                                 None).as_circe_concept(),
        "isExcluded": False, "includeDescendants": True, "includeMapped": False}]}
    recommendation = MagicMock()
    recommendation.name = "Systemic corticosteroid"
    recommendation.expression.to_atlas_json.side_effect = lambda: deepcopy(expression)
    builder = MagicMock()
    builder.build_expression.return_value = recommendation
    candidate = MagicMock(concept_id=1001, concept_name="prednisolone", domain_id="Drug")
    records = {f.concept_id: ConceptRecord(f.concept_id, f.concept_name, "Drug", "RxNorm",
                                           "Clinical Drug Form", "S", "", None) for f in FORMS}
    with (
        patch.object(TTEService, "_exact_ingredient_match_enabled", return_value=False),
        patch.object(TTEService, "_fetch_concept_candidates", return_value=[candidate]),
        patch.object(TTEService, "_fetch_drug_forms", return_value=FORMS),
        patch.object(TTEService, "_fetch_concept_records", return_value=records),
        patch("src.agents.conceptset.expression_builder.get_expression_builder",
              return_value=builder),
        patch("src.services.tte_service._criterion_cache_enabled", return_value=False),
    ):
        return svc._recommend_seeded_concept_set(
            "Systemic corticosteroid", expected_domain="Drug", workflow=workflow)


def _excluded(result: dict[str, Any]) -> set[int]:
    items = result["expression"]["items"]
    return {i["concept"]["CONCEPT_ID"] for i in items if i.get("isExcluded")}


class TestTheMapperKeepsTheClassRoute:
    def test_should_exclude_forms_outside_the_class_routes_when_the_class_decides_them(self):
        result = _map([4132161, 706184])
        assert _excluded(result) == {13, 14}
        assert result["mapping_metadata"].selectedConceptIds == [
            i["concept"]["CONCEPT_ID"] for i in result["expression"]["items"]]

    def test_should_exclude_nothing_when_the_class_route_is_undecided(self):
        assert _excluded(_map([])) == set()


def test_should_carry_the_decided_class_route_out_of_the_workflow(monkeypatch):
    from src.agents.agent2 import workflow as workflow_mod
    from src.agents.agent2.drug_class_expander import AtcExpansion

    pool = MagicMock()
    pool.getconn.return_value = MagicMock()
    monkeypatch.setattr(workflow_mod, "_get_db_pool", lambda: pool)
    monkeypatch.setattr(workflow_mod, "expand_drug_class_via_vocab",
                        lambda text, conn, schema: AtcExpansion("H02A", [1, 2], [4132161]))
    monkeypatch.setattr(workflow_mod.logician, "roll_up_to_rxnorm_ingredients", list)
    flow = workflow_mod.Agent2Workflow.__new__(workflow_mod.Agent2Workflow)
    result = flow.process_with_details("Systemic corticosteroid", domain_hint="Drug")
    assert result.route_path == "atc"
    assert result.atc_route_ids == [4132161]


@pytest.mark.integration
def test_should_read_only_systemic_routes_under_h02a_from_the_vocabulary():
    psycopg2 = pytest.importorskip("psycopg2")
    from src.agents.agent2.drug_class_expander import class_route_ids
    from src.settings import settings

    try:
        conn = psycopg2.connect(settings.DATABASE_URL, connect_timeout=3)
    except psycopg2.OperationalError as e:
        pytest.skip(f"OMOP vocabulary unreachable: {e}")
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT concept_id FROM {settings.CDM_SCHEMA}.concept "
                    "WHERE vocabulary_id='ATC' AND concept_code='H02A'")
        class_id = cur.fetchone()[0]
        routes = routes_for_concept_ids(class_route_ids(cur, settings.CDM_SCHEMA, class_id))
    finally:
        conn.close()
    assert set(routes) == {AdministrationRoute.ORAL, AdministrationRoute.INJECTABLE,
                           AdministrationRoute.BUCCAL, AdministrationRoute.IMPLANT}
