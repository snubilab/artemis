"""RFC-016 step 4, A16: a criterion naming no clinical entity is refused on its annotation.

``unmappable-placeholder`` is the one refusal code the delivery gate permits. It used to be
earned on the seed's own words -- ``_seed_is_unmappable_placeholder``, a set of English word
lists ("investigational drug", "risk factor N", "table II" ...). Now the annotation step's
``no_entity`` field decides (``refers_elsewhere`` / ``investigator_judgement``), with the
fragment of ``protocolLine`` that shows it; the refusal carries that fragment as its
``detail``, and the gate permits it only when the fragment is in the store row's line.

Rows are real (``tests/fixtures/rfc016_step4_rows.json``, 2026-10-12 prompt_f2 store):
ARISTOTLE exclusion 32 and CAROLINA exclusion 47 are the two refusals the candidate run
permitted through the word list. The mapper is a stub; nothing reaches an LLM or database.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.services.criterion_annotation import ANNOTATION_KEY, validate_annotation
from src.services.tte_service import TTEService
from src.utils.criterion_refusal import (
    REFUSAL_DOMAIN_CONTRADICTION,
    REFUSAL_NO_CONCEPT_MAPPING,
    REFUSAL_UNMAPPABLE_PLACEHOLDER,
    CriterionRefused,
)

ROWS = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "rfc016_step4_rows.json").read_text()
)
ARISTOTLE_32 = ROWS["aristotle_exclusion_32"]
CAROLINA_47 = ROWS["carolina_exclusion_47"]
BASE = {"record_requirement": "forbidden", "conditional_span": None, "excepted_entities": []}


def _annotated(row: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    row = deepcopy(row)
    fields, rejected = validate_annotation({**BASE, **payload}, row["protocolLine"])
    row[ANNOTATION_KEY] = {"promptVersion": "test", "model": "stub", **fields}
    if rejected:
        row["_annotationRejected"] = rejected
    return row


def _mapping(domains: list[str]) -> dict[str, Any]:
    return {
        "name": "answer",
        "domain": domains[0],
        "expression": {
            "items": [
                {
                    "concept": {
                        "CONCEPT_ID": 100 + n,
                        "CONCEPT_NAME": f"concept {n}",
                        "CONCEPT_CODE": str(n),
                        "DOMAIN_ID": domain,
                        "VOCABULARY_ID": "SNOMED",
                        "CONCEPT_CLASS_ID": "Clinical Finding",
                    },
                    "includeDescendants": True,
                    "isExcluded": False,
                }
                for n, domain in enumerate(domains)
            ]
        },
        "mapping_metadata": None,
    }


def _service(monkeypatch, mapping: dict[str, Any]) -> tuple[TTEService, MagicMock]:
    svc = TTEService.__new__(TTEService)
    mapper = MagicMock(return_value=mapping)
    monkeypatch.setattr(svc, "_recommend_seeded_concept_set", mapper)
    return svc, mapper


class TestTheAnnotationDecides:
    def test_should_refuse_as_irreducible_with_the_span_when_the_line_refers_elsewhere(
        self, monkeypatch
    ):
        row = _annotated(
            ARISTOTLE_32,
            {"no_entity": "refers_elsewhere", "no_entity_span": "investigational drug"},
        )
        svc, mapper = _service(monkeypatch, _mapping(["Drug"]))
        with pytest.raises(CriterionRefused) as caught:
            svc._build_seeded_eligibility_rule(criterion=row, codeset_id=5, exclusion=True)
        assert caught.value.code == REFUSAL_UNMAPPABLE_PLACEHOLDER
        assert caught.value.detail == "investigational drug"
        mapper.assert_not_called()

    def test_should_keep_the_permit_on_a_row_whose_entity_text_is_empty(self, monkeypatch):
        """ARISTOTLE 32 carries no ``sourceText``; the missing-entity re-code must not take the
        one permitted code away."""
        assert ARISTOTLE_32["sourceText"] == ""
        row = _annotated(
            ARISTOTLE_32,
            {"no_entity": "refers_elsewhere", "no_entity_span": "investigational drug"},
        )
        svc, _mapper = _service(monkeypatch, _mapping(["Measurement", "Procedure"]))
        with pytest.raises(CriterionRefused) as caught:
            svc._build_seeded_eligibility_rule(criterion=row, codeset_id=5, exclusion=True)
        assert caught.value.code == REFUSAL_UNMAPPABLE_PLACEHOLDER

    def test_should_map_the_row_when_the_annotation_says_the_line_names_an_entity(
        self, monkeypatch
    ):
        row = _annotated(CAROLINA_47, {"no_entity": "none", "no_entity_span": None})
        svc, mapper = _service(monkeypatch, _mapping(["Drug"]))
        rule = svc._build_seeded_eligibility_rule(criterion=row, codeset_id=5, exclusion=True)
        mapper.assert_called_once()
        assert "DrugExposure" in rule["rule"]["expression"]["CriteriaList"][0]["Criteria"]

    def test_should_map_the_row_when_the_no_entity_span_is_not_in_the_line(self, monkeypatch):
        row = _annotated(
            CAROLINA_47,
            {"no_entity": "refers_elsewhere", "no_entity_span": "investigational product"},
        )
        assert row["_annotationRejected"][0]["field"] == "no_entity"
        svc, mapper = _service(monkeypatch, _mapping(["Drug"]))
        svc._build_seeded_eligibility_rule(criterion=row, codeset_id=5, exclusion=True)
        mapper.assert_called_once()


class TestTheSeedIsNotRead:
    def test_should_keep_the_contradiction_code_when_a_category_seed_maps_to_another_domain(
        self, monkeypatch
    ):
        """CAROLINA 47 is seeded "Investigational drug" and the vocabulary answered from Meas
        Value / Measurement / Observation / Procedure. Without an annotation that is a
        contradiction like any other, and is not permitted."""
        row = deepcopy(CAROLINA_47)
        svc, _mapper = _service(
            monkeypatch, _mapping(["Meas Value", "Measurement", "Observation", "Procedure"])
        )
        with pytest.raises(CriterionRefused) as caught:
            svc._build_seeded_eligibility_rule(criterion=row, codeset_id=5, exclusion=True)
        assert caught.value.code == REFUSAL_DOMAIN_CONTRADICTION

    def test_should_build_the_rule_when_a_category_seed_maps_in_its_own_domain(self, monkeypatch):
        row = deepcopy(CAROLINA_47)
        svc, _mapper = _service(monkeypatch, _mapping(["Drug"]))
        rule = svc._build_seeded_eligibility_rule(criterion=row, codeset_id=5, exclusion=True)
        assert "DrugExposure" in rule["rule"]["expression"]["CriteriaList"][0]["Criteria"]

    @pytest.mark.parametrize("seed", ["Table II criteria", "Investigational drug", "Risk factor 1"])
    def test_should_refuse_as_no_concept_mapping_when_the_fallback_finds_nothing(
        self, monkeypatch, seed
    ):
        monkeypatch.setenv("CRITERION_CACHE_ENABLED", "false")
        svc = TTEService(store=MagicMock())
        recommender = MagicMock()
        recommender.recommend.return_value = SimpleNamespace(
            include_recommendations=[], fallback_reason=None
        )
        monkeypatch.setattr(svc, "_get_seeded_concept_set_recommender", lambda: recommender)
        with pytest.raises(CriterionRefused) as caught:
            svc._recommend_seeded_concept_set_rag_fallback(seed, expected_domain="Condition")
        assert caught.value.code == REFUSAL_NO_CONCEPT_MAPPING


def test_should_keep_the_fallback_code_through_the_agent2_wrapper(monkeypatch):
    """``_recommend_seeded_concept_set`` re-wraps the fallback refusal to name the Agent 2
    stage; the code must survive the re-wrap, or the record loses what the gate reads."""
    from src.agents.agent2 import workflow as agent2_workflow

    monkeypatch.setenv("CRITERION_CACHE_ENABLED", "false")
    svc = TTEService(store=MagicMock())
    monkeypatch.setattr(
        agent2_workflow.Agent2Workflow,
        "process_with_details",
        lambda self, *a, **k: SimpleNamespace(
            concept_ids=[], overbroad_concept_ids=[], route_path="rag_only"
        ),
    )
    recommender = MagicMock()
    recommender.recommend.return_value = SimpleNamespace(
        include_recommendations=[], fallback_reason=None
    )
    monkeypatch.setattr(svc, "_get_seeded_concept_set_recommender", lambda: recommender)
    with pytest.raises(CriterionRefused) as caught:
        svc._recommend_seeded_concept_set("Risk factor 1", expected_domain="Condition")
    assert caught.value.code == REFUSAL_NO_CONCEPT_MAPPING
    assert "Agent 2 returned no concepts" in str(caught.value)
