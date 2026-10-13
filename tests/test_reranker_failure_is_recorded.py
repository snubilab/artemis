"""A reranker answer that cannot be used selects nothing, and says so on the mapping.

The Agent 2 reranker parsed with LangChain's ``JsonOutputParser``, whose partial-JSON
repair closes a reply cut off mid-item and returns what it completed. Measured on
1835b17 with the P3 dry-run's answer for "chronic kidney disease" (driver log:
``reranker -> 3 selected: [(198185, ...), (46271022, ...), (36716947, ...)]``) cut inside
its second id: ``{"query_has_match": true, "selected_ids": [198185, 4627`` came back as
``[198185, 4627]`` -- a shorter selection with a truncated id in it. A failed top-N call
fell back to a second, single-select prompt and used its pick, and anything that failed
there became "no candidate fits". None of it reached the mapping: the criterion was
mapped from whatever came back, or recorded as a gap like a genuine no-match.

Now the reply is parsed strictly, a reply carrying no ``selected_ids`` list is broken
rather than empty, and any failure raises ``RerankerFailed``: the workflow keeps no seed,
records the reason on ``MappingResult.reranker_failure`` (``mapping_failures()`` stage
``reranker``), and the seeded-mapping step carries it onto whatever the RAG fallback
returns, so the store's ``_mappingFailureCriteria`` and gate (ab) see it.

No LLM is called: the reranker's model is a stub returning the text a model returned.
"""

import json
import logging
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from src.agents.agent2.retriever import CandidateConcept
from src.models.ir import MappingResult

FAILURE_MARKER = "[Reranker] Top-N reranking failed"
#: The P3 dry-run's answer for "chronic kidney disease".
ANSWER = json.dumps({"query_has_match": True, "selected_ids": [198185, 46271022, 36716947]})
CUT = ANSWER[: ANSWER.index("46271022") + 4]


def _candidate(cid: int) -> CandidateConcept:
    return CandidateConcept(concept_id=cid, concept_name=f"c{cid}", domain_id="Condition",
                            vocabulary_id="SNOMED", concept_class_id="Clinical Finding",
                            distance=0.1)


CANDIDATES = [_candidate(c) for c in (198185, 46271022, 36716947, 4627)]


class _Model:
    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    def runnable(self, *_a, **_k):
        return RunnableLambda(self._invoke)

    def _invoke(self, _payload):
        self.calls += 1
        if isinstance(self.reply, Exception):
            raise self.reply
        return AIMessage(content=self.reply)


def _reranker(reply):
    from src.agents.agent2 import reranker as reranker_mod

    model = _Model(reply)
    with patch.object(reranker_mod, "get_llm", model.runnable):
        return reranker_mod.ConceptReranker(), model


#: Each one a reply the reranker cannot use, and what the recorded reason must name.
BROKEN = {
    "cut mid-item": (CUT, "Invalid json output"),
    "call raised": (TimeoutError("read timeout"), "TimeoutError: read timeout"),
    "not json": ("the model wrote prose", "Invalid json output"),
    "no selected_ids": ('{"query_has_match": true}', "selected_ids"),
    "selected_ids not a list": ('{"query_has_match": true, "selected_ids": "198185"}', "selected_ids"),
}


# ── the reranker ─────────────────────────────────────────────


@pytest.mark.parametrize("case", sorted(BROKEN))
def test_should_raise_with_the_reason_and_ask_no_second_prompt_when_the_answer_is_unusable(
    caplog, case
):
    from src.agents.agent2.reranker import RerankerFailed

    reply, reason = BROKEN[case]
    reranker, model = _reranker(reply)
    caplog.set_level(logging.WARNING)

    with pytest.raises(RerankerFailed) as raised:
        reranker.rerank_topn("chronic kidney disease", CANDIDATES)

    assert reason in str(raised.value), raised.value
    assert model.calls == 1, "a second prompt was asked after the top-N call failed"
    lines = [r.getMessage() for r in caplog.records if FAILURE_MARKER in r.getMessage()]
    assert len(lines) == 1 and "\n" not in lines[0], lines


def test_should_select_the_whole_answer():
    reranker, _model = _reranker(ANSWER)

    selected = reranker.rerank_topn("chronic kidney disease", CANDIDATES)

    assert [c.concept_id for c in selected] == [198185, 46271022, 36716947]


def test_should_select_nothing_when_the_model_says_no_candidate_fits():
    reranker, _model = _reranker('{"query_has_match": false, "selected_ids": []}')

    assert reranker.rerank_topn("qqzzxx", CANDIDATES) == []


# ── the workflow records it on the mapping ───────────────────


def _process(reranker):
    from src.agents.agent2 import workflow as wf

    workflow = wf.Agent2Workflow()
    workflow._reranker = reranker
    with patch.object(wf, "expand_abbreviation", return_value=("q", False)), \
            patch.object(wf, "expand_in_context", side_effect=lambda q: q), \
            patch.object(wf.logician, "decompose_combination", side_effect=lambda cid: [cid]), \
            patch.object(wf.logician, "prune_empty_concepts", side_effect=lambda ids: ids), \
            patch.object(wf.logician, "drop_wrong_entity_class_for_condition",
                         side_effect=lambda ids: ids), \
            patch.object(wf.Agent2Workflow, "_kg_expand_and_critique",
                         side_effect=lambda ids, *a, **k: (ids, [], True)), \
            patch.object(wf, "get_kg_expander"):
        return workflow.process_with_details(
            "chronic kidney disease", domain_hint="Condition",
            pre_fetched_candidates=list(CANDIDATES),
        )


def test_should_record_the_failure_and_map_nothing_when_the_reranker_answer_is_cut():
    reranker, _model = _reranker(CUT)

    result = _process(reranker)

    assert result.concept_ids == [] and result.seed_concept_ids == []
    assert "Invalid json output" in (result.reranker_failure or ""), result.reranker_failure
    assert result.mapping_failures() == [
        {"stage": "reranker", "reason": result.reranker_failure, "seedsOnly": False}
    ]
    assert "Reranker failed" in result.gap_report.unmapped_items[0].reason


def test_should_leave_the_failure_unset_when_the_reranker_answers():
    reranker, _model = _reranker(ANSWER)

    result = _process(reranker)

    assert result.concept_ids == [198185, 46271022, 36716947]
    assert result.reranker_failure is None and result.mapping_failures() == []


# ── the seeded mapping carries it past the RAG fallback ──────


REASON = "OutputParserException: Invalid json output: " + CUT


def _recommend(rag):
    """``_recommend_seeded_concept_set`` with Agent 2 returning a failed reranker."""
    from src.services import tte_service

    failed = MappingResult(concept_ids=[], route_path="slow", reranker_failure=REASON)
    with patch("src.agents.agent2.workflow.Agent2Workflow.process_with_details",
               return_value=failed), \
            patch.object(tte_service.TTEService, "_recommend_seeded_concept_set_rag_fallback",
                         side_effect=rag), \
            patch.dict("os.environ", {"CRITERION_CACHE_ENABLED": "false"}):
        return tte_service.TTEService(store=MagicMock())._recommend_seeded_concept_set(
            "Chronic kidney disease", expected_domain="Condition"
        )


def test_should_carry_the_reranker_failure_onto_the_rag_fallback_mapping():
    from src.api.models.tte import CriterionMappingMetadata

    def rag(seed, expected_domain=None):
        return {"name": seed, "domain": "Condition", "expression": {"items": [{"concept": {
            "CONCEPT_ID": 46271022}}]},
            "mapping_metadata": CriterionMappingMetadata(queryUsed=seed,
                                                         rerankMethod="rag_fallback")}

    out = _recommend(rag)

    assert out["mapping_metadata"].mappingFailures == [
        {"stage": "reranker", "reason": REASON, "seedsOnly": False,
         "query": "Chronic kidney disease"}
    ]


def test_should_name_the_reranker_failure_when_the_rag_fallback_refuses_too():
    from src.services.tte_service import CriterionRefused

    def rag(seed, expected_domain=None):
        raise CriterionRefused(f"No concept mapping found for '{seed}'", code="no-concept-mapping")

    with pytest.raises(CriterionRefused) as raised:
        _recommend(rag)

    assert "reranker: " + REASON in str(raised.value), raised.value
