"""RFC-016 step 4: the ``route``, ``specimen`` and ``no_entity`` annotation fields.

Every row is real, copied verbatim into ``tests/fixtures/rfc016_step4_rows.json`` from the
2026-10-12 prompt_f2 candidate store (path and SHA-256 recorded there). The route values are
the OMOP route concepts RxNorm dose forms reach through ``Has route of admin``, captured in
``tests/fixtures/rxnorm_dose_form_routes.json``. The model is a stub; nothing here reaches an
LLM or a database.

What is pinned: a field is kept only when its value is one the schema defines and its
fragment is a substring of ``protocolLine``; otherwise it is absent and the rejection is
recorded. The readers re-check the fragment against the row's own line.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from src.services import criterion_annotation as annotation_mod
from src.services.criterion_annotation import (
    ANNOTATION_KEY,
    ANNOTATION_REJECTED_KEY,
    NoEntity,
    Specimen,
    annotate_row,
    render_prompt,
    stated_no_entity,
    stated_route,
    stated_specimen,
    validate_annotation,
)
from src.services.route_subtraction import AdministrationRoute

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ROWS = json.loads((FIXTURES / "rfc016_step4_rows.json").read_text())
VOCAB = json.loads((FIXTURES / "rxnorm_dose_form_routes.json").read_text())

LEADER_13 = ROWS["leader_inclusion_13"]
LEADER_VARIANT_16 = ROWS["leader_variant_inclusion_16"]
CAROLINA_17 = ROWS["carolina_exclusion_17"]
CAROLINA_UACR = ROWS["carolina_inclusion_28"]
ARISTOTLE_32 = ROWS["aristotle_exclusion_32"]


#: The step-1 fields, valid on every line, so only the field under test can be rejected.
BASE = {"record_requirement": "required", "conditional_span": None, "excepted_entities": []}


def _annotated(row: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    row = deepcopy(row)
    fields, rejected = validate_annotation({**BASE, **payload}, row.get("protocolLine"))
    row[ANNOTATION_KEY] = {"promptVersion": "test", "model": "stub", **fields}
    if rejected:
        row[ANNOTATION_REJECTED_KEY] = rejected
    return row


def _rejected_fields(payload: dict[str, Any], line: str) -> list[str]:
    return [r["field"] for r in validate_annotation({**BASE, **payload}, line)[1]]


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTEMIS_ANNOTATION_CACHE_PATH", str(tmp_path / "annotations.jsonl"))
    annotation_mod.reset_for_tests()
    yield
    annotation_mod.reset_for_tests()


class TestTheRouteValuesComeFromTheVocabulary:
    def test_should_offer_exactly_the_routes_rxnorm_dose_forms_reach(self):
        reached = {form["routeId"] for form in VOCAB["doseForms"] if form["routeId"] is not None}
        assert {route.concept_id for route in AdministrationRoute} == reached

    def test_should_ask_the_model_for_every_route_value_and_the_three_fields(self):
        prompt = render_prompt(LEADER_13, [], "inclusion")
        for token in [route.value for route in AdministrationRoute] + ["route", "route_span"]:
            assert f"`{token}`" in prompt
        for token in ["specimen", "specimen_span", "no_entity", "no_entity_span"]:
            assert f"`{token}`" in prompt
        for value in [s.value for s in Specimen] + [n.value for n in NoEntity]:
            assert f"`{value}`" in prompt


class TestRoute:
    def test_should_keep_a_route_when_its_span_is_in_the_protocol_line(self):
        row = _annotated(LEADER_13, {"route": ["oral"], "route_span": "oral anti-diabetic drugs"})
        assert row[ANNOTATION_KEY]["route"] == ["oral"]
        statement = stated_route(row)
        assert statement is not None
        assert statement.routes == (AdministrationRoute.ORAL,)
        assert statement.span == "oral anti-diabetic drugs"

    def test_should_keep_several_routes_when_the_line_restricts_to_more_than_one(self):
        row = _annotated(
            CAROLINA_17,
            {"route": ["oral", "injectable", "rectal"], "route_span": "systemic corticosteroids"},
        )
        statement = stated_route(row)
        assert statement is not None
        assert set(statement.routes) == {
            AdministrationRoute.ORAL,
            AdministrationRoute.INJECTABLE,
            AdministrationRoute.RECTAL,
        }

    def test_should_drop_the_route_when_its_span_is_not_in_the_protocol_line(self):
        payload = {"route": ["oral"], "route_span": "orally administered"}
        assert _rejected_fields(payload, LEADER_13["protocolLine"]) == ["route"]
        assert stated_route(_annotated(LEADER_13, payload)) is None

    def test_should_drop_a_route_the_vocabulary_does_not_carry(self):
        payload = {"route": ["systemic"], "route_span": "systemic corticosteroids"}
        assert _rejected_fields(payload, CAROLINA_17["protocolLine"]) == ["route"]
        assert stated_route(_annotated(CAROLINA_17, payload)) is None

    def test_should_drop_any_when_it_is_listed_beside_a_route(self):
        payload = {"route": ["any", "oral"], "route_span": "oral anti-diabetic drugs"}
        assert _rejected_fields(payload, LEADER_13["protocolLine"]) == ["route"]

    def test_should_accept_any_without_a_span_and_state_no_route(self):
        row = _annotated(LEADER_13, {"route": ["any"], "route_span": None})
        assert row[ANNOTATION_KEY]["route"] == ["any"]
        assert ANNOTATION_REJECTED_KEY not in row
        assert stated_route(row) is None

    def test_should_state_no_route_when_the_stored_span_no_longer_matches_the_line(self):
        row = _annotated(LEADER_13, {"route": ["oral"], "route_span": "oral anti-diabetic drugs"})
        row["protocolLine"] = "Anti-diabetic drug naive"
        assert stated_route(row) is None

    def test_should_state_no_route_on_a_row_without_a_protocol_line(self):
        row = deepcopy(LEADER_VARIANT_16)
        outcome = annotate_row(row, [], "inclusion", model="stub", llm=None)
        assert outcome == "no-line"
        assert stated_route(row) is None


class TestSpecimen:
    def test_should_keep_a_specimen_when_its_span_is_in_the_protocol_line(self):
        row = _annotated(
            CAROLINA_UACR,
            {"specimen": "urine", "specimen_span": "urinary albumin creatinine ratio"},
        )
        statement = stated_specimen(row)
        assert statement is not None
        assert statement.specimen is Specimen.URINE
        assert statement.span == "urinary albumin creatinine ratio"

    def test_should_drop_a_specimen_when_its_span_is_not_in_the_protocol_line(self):
        payload = {"specimen": "blood", "specimen_span": "serum albumin"}
        assert _rejected_fields(payload, CAROLINA_UACR["protocolLine"]) == ["specimen"]
        assert stated_specimen(_annotated(CAROLINA_UACR, payload)) is None

    def test_should_drop_a_specimen_outside_the_four_values(self):
        payload = {"specimen": "serum", "specimen_span": "urinary"}
        assert _rejected_fields(payload, CAROLINA_UACR["protocolLine"]) == ["specimen"]

    def test_should_state_any_without_a_span(self):
        row = _annotated(CAROLINA_UACR, {"specimen": "any", "specimen_span": None})
        statement = stated_specimen(row)
        assert statement is not None
        assert statement.specimen is Specimen.ANY
        assert statement.span is None


class TestNoEntity:
    def test_should_keep_refers_elsewhere_when_its_span_is_in_the_protocol_line(self):
        row = _annotated(
            ARISTOTLE_32,
            {"no_entity": "refers_elsewhere", "no_entity_span": "investigational drug"},
        )
        statement = stated_no_entity(row)
        assert statement is not None
        assert statement.kind is NoEntity.REFERS_ELSEWHERE
        assert statement.span == "investigational drug"

    def test_should_drop_no_entity_when_its_span_is_not_in_the_protocol_line(self):
        payload = {"no_entity": "refers_elsewhere", "no_entity_span": "Investigational drug use"}
        assert _rejected_fields(payload, ARISTOTLE_32["protocolLine"]) == ["no_entity"]
        assert stated_no_entity(_annotated(ARISTOTLE_32, payload)) is None

    def test_should_drop_no_entity_when_it_carries_no_span(self):
        payload = {"no_entity": "investigator_judgement", "no_entity_span": None}
        assert _rejected_fields(payload, ARISTOTLE_32["protocolLine"]) == ["no_entity"]

    def test_should_state_nothing_when_the_line_names_an_entity(self):
        row = _annotated(ARISTOTLE_32, {"no_entity": "none", "no_entity_span": None})
        assert ANNOTATION_REJECTED_KEY not in row
        assert stated_no_entity(row) is None
