"""The mapper is asked for an entity as the protocol line spells it out, not as abbreviated.

Measured on the 2026-10-17 P6 SEG-OFF arm: with the curated abbreviation table gone
(266971e), the seed ``TIA`` retrieves 60 candidates none of which is 373503 Transient
cerebral ischemia, so CARMELINA, CAROLINA and EMPA-REG shipped 'Infarction of thyroid' and
'Ischemic stroke' as TIA; ``eGFR`` retrieves the Epidermal Growth Factor Receptor family, so
LEADER shipped six natriuretic-peptide tests as eGFR. ``transient ischemic attack`` and
``estimated glomerular filtration rate`` retrieve the intended concepts.

No table and no text test decides what an abbreviation stands for: one LLM call, shown the
protocol line and the entity, returns the entity in full. Code checks only that the answer
is a non-empty string.
"""

from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.agents.agent2 import entity_full_name as efn
from src.services.tte_service import TTEService

TIA_LINE = "16. Stroke or TIA ≤ 3 months prior to visit 1 (screening)"


class _Stub:
    def __init__(self, answer: str):
        self.answer = answer
        self.prompts: list[str] = []

    def invoke(self, messages):
        self.prompts.append(messages[-1].content)
        return SimpleNamespace(content=self.answer, response_metadata={})


@pytest.fixture(autouse=True)
def _private_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTEMIS_ENTITY_NAME_CACHE_PATH", str(tmp_path / "names.jsonl"))
    efn.reset_for_tests()
    yield
    efn.reset_for_tests()


def test_should_return_the_entity_unchanged_when_the_model_names_it_as_written():
    stub = _Stub(json.dumps({"abbreviations": []}))
    assert efn.full_entity_name("Body Mass Index", "BMI <= 45", llm=stub, model="m") == (
        "Body Mass Index"
    )


def test_should_return_the_full_name_when_the_model_spells_out_an_abbreviation():
    stub = _Stub(json.dumps({"abbreviations": [{"span": "TIA", "full_term": "Transient Ischemic Attack"}]}))
    assert efn.full_entity_name("TIA", TIA_LINE, llm=stub, model="m") == "Transient Ischemic Attack"
    assert TIA_LINE in stub.prompts[0] and "TIA" in stub.prompts[0]


def test_should_keep_the_entity_when_only_letter_case_differs():
    stub = _Stub(json.dumps({"abbreviations": [{"span": "CABG", "full_term": "cabg"}]}))
    assert efn.full_entity_name("CABG", "CABG", llm=stub, model="m") == "CABG"


def test_should_keep_the_entity_and_cache_nothing_when_the_answer_is_unreadable():
    stub = _Stub("not json")
    assert efn.full_entity_name("TIA", TIA_LINE, llm=stub, model="m") == "TIA"
    good = _Stub(json.dumps({"abbreviations": [{"span": "TIA", "full_term": "Transient Ischemic Attack"}]}))
    assert efn.full_entity_name("TIA", TIA_LINE, llm=good, model="m") == (
        "Transient Ischemic Attack"
    )


def test_should_not_ask_the_model_when_there_is_no_protocol_line():
    stub = _Stub(json.dumps({"abbreviations": []}))
    assert efn.full_entity_name("TIA", "", llm=stub, model="m") == "TIA"
    assert stub.prompts == []


def test_should_rename_only_an_entity_that_is_one_abbreviation():
    """A span inside a longer name, or one the entity does not hold, renames nothing."""
    stub = _Stub(json.dumps({"abbreviations": [{"span": "TIA", "full_term": "transient ischemic attack"}]}))
    assert efn.full_entity_name("Prior stroke or TIA", TIA_LINE, llm=stub, model="m") == "Prior stroke or TIA"
    stub = _Stub(json.dumps({"abbreviations": [{"span": "ESRD", "full_term": "end-stage renal disease"}]}))
    assert efn.full_entity_name("Chronic Kidney Disease", "CKD or ESRD", llm=stub, model="m") == (
        "Chronic Kidney Disease"
    )


def test_should_answer_from_the_cache_without_asking_again():
    stub = _Stub(json.dumps({"abbreviations": [{"span": "TIA", "full_term": "Transient Ischemic Attack"}]}))
    efn.full_entity_name("TIA", TIA_LINE, llm=stub, model="m")
    efn.full_entity_name("TIA", TIA_LINE, llm=stub, model="m")
    assert len(stub.prompts) == 1


# --------------------------------------------------------------------------- #
# Wiring: TTEService asks Agent 2 for the full name, keeps the set named by the seed.
# --------------------------------------------------------------------------- #

_EXPR = {"items": [{"concept": {"CONCEPT_ID": 373503, "CONCEPT_NAME": "Transient cerebral ischemia"}}]}


def _map(seed: str, source_line: str | None, full: str):
    from src.models.ir import MappingResult

    svc = TTEService(store=MagicMock())
    workflow = MagicMock()
    workflow.process_with_details.return_value = MappingResult(
        concept_ids=[373503], overbroad_concept_ids=[], route_path="slow"
    )
    recommendation = MagicMock()
    recommendation.name = None
    recommendation.expression.to_atlas_json.side_effect = lambda: deepcopy(_EXPR)
    builder = MagicMock()
    builder.build_expression.return_value = recommendation
    candidate = MagicMock(concept_id=373503, concept_name="Transient cerebral ischemia",
                          domain_id="Condition")
    prefetched = [MagicMock(concept_id=4043001, adjusted_score=0.9)]
    with (
        patch.object(TTEService, "_exact_ingredient_match_enabled", return_value=False),
        patch.object(TTEService, "_fetch_concept_candidates", return_value=[candidate]),
        patch("src.agents.conceptset.expression_builder.get_expression_builder",
              return_value=builder),
        patch("src.services.tte_service._criterion_cache_enabled", return_value=False),
        patch("src.agents.agent2.entity_full_name.full_entity_name",
              return_value=full) as named,
        patch("src.agents.agent2.retriever.ConceptRetriever") as retriever,
    ):
        retriever.return_value.search.return_value = [MagicMock(concept_id=373503, adjusted_score=0.5)]
        result = svc._recommend_seeded_concept_set(
            seed, expected_domain="Condition", workflow=workflow,
            pre_fetched_candidates=prefetched, source_line=source_line,
        )
    return result, workflow, builder, named


def test_should_query_agent2_with_the_full_name_and_its_own_prefetch():
    result, workflow, builder, named = _map("TIA", TIA_LINE, "Transient Ischemic Attack")
    named.assert_called_once()
    args, kwargs = workflow.process_with_details.call_args
    assert args[0] == "Transient Ischemic Attack"
    assert [c.concept_id for c in kwargs["pre_fetched_candidates"]] == [373503]
    assert result["name"] == "TIA"
    assert builder.build_expression.call_args.kwargs["criterion_name"] == "TIA"
    assert result["mapping_metadata"].queryUsed == "Transient Ischemic Attack"


def test_should_keep_the_seed_and_its_prefetch_when_the_full_name_is_the_seed():
    _result, workflow, _builder, _named = _map("Body Mass Index", "BMI", "Body Mass Index")
    args, kwargs = workflow.process_with_details.call_args
    assert args[0] == "Body Mass Index"
    assert [c.concept_id for c in kwargs["pre_fetched_candidates"]] == [4043001]


def test_should_pass_the_rows_protocol_line_to_the_mapper():
    svc = TTEService(store=MagicMock())
    row = {"id": 71, "description": "Transient Ischemic Attack (TIA)", "domain": "Condition",
           "sourceText": "TIA", "protocolLine": TIA_LINE, "logicType": "ABSENCE",
           "window": {"start": -90, "end": 0}, "valueConstraint": None}
    with patch.object(TTEService, "_recommend_seeded_concept_set",
                      side_effect=RuntimeError("stop")) as rec:
        with pytest.raises(RuntimeError):
            svc._build_seeded_eligibility_rule(criterion=row, codeset_id=0, exclusion=True)
    assert rec.call_args.kwargs["source_line"] == TIA_LINE
