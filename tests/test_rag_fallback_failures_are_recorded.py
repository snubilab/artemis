"""The RAG fallback's two model stages record an unusable answer on the mapping.

When Agent 2 maps nothing, ``_recommend_seeded_concept_set`` asks the ConceptSet
recommender, whose NLU router splits the seed into include/exclude intents and whose
clinical reranker picks the best candidate. Both parsed with LangChain's
``JsonOutputParser``, whose partial-JSON repair closes a reply cut off mid-item. Measured
on 1835b17 with the P3 dry-run's answers (driver log: ``Intent separated include=['solid
organ transplant'] exclude=[]`` and ``[Reranker] LLM: selected=2721126, conf=0.950``):

- the router's reply cut inside its include came back as ``include=['solid organ
  transpl']``, an intent nobody wrote;
- the clinical reranker's reply cut inside its id came back as ``selected=27211``, which
  is no candidate, and was used as an ``llm`` ranking with the default confidence.

And a failed call was invisible: the router kept the whole seed as one include, the
reranker fell back to score order, and the mapping metadata said ``rag_fallback`` either
way. Now each reply is parsed strictly; a failure keeps that same fallback answer and
records itself (``FailedIntentResult.failure``, ``RerankerResult.failure``) on the
recommender's ``mapping_failures``, which the RAG fallback writes to
``CriterionMappingMetadata.mappingFailures`` -- so ``_mappingFailureCriteria`` and gate
(ab) see it -- and the recommender's cache does not store the response.

No LLM is called: each stage's model is a stub returning the text a model returned.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from src.agents.conceptset.rag_search import ConceptCandidate

INTENT = json.dumps({"include": ["solid organ transplant"], "exclude": [],
                     "fallback_to": None, "fallback_reason": None})
INTENT_CUT = INTENT[: INTENT.index("transplant") + 6]
PICK = json.dumps({"selected_id": 2721126, "confidence": 0.95})
PICK_CUT = PICK[: PICK.index("2721126") + 5]
CANDIDATES = [
    ConceptCandidate(concept_id=cid, concept_name=f"c{cid}", domain_id="Procedure",
                     vocabulary_id="SNOMED", concept_class_id="Procedure", score=score)
    for cid, score in ((4322471, 0.9), (2721126, 0.8), (27211, 0.1))
]


def _replying(reply):
    def _invoke(*_a, **_k):
        if isinstance(reply, Exception):
            raise reply
        return AIMessage(content=reply)

    return lambda *_a, **_k: RunnableLambda(_invoke)


def _separator(reply):
    from src.agents.conceptset import nlu_router

    with patch.object(nlu_router, "get_llm", _replying(reply)):
        return nlu_router.IntentSeparator()


def _clinical(reply):
    import src.utils.llm as llm_mod
    from src.agents.conceptset.clinical_reranker import ClinicalReranker

    reranker = ClinicalReranker(use_cross_encoder=False)
    with patch.object(llm_mod, "get_llm", _replying(reply)):
        reranker._init_llm()
    return reranker


# ── NLU router ───────────────────────────────────────────────


@pytest.mark.parametrize("reply, reason", [
    (INTENT_CUT, "Invalid json output"),
    (TimeoutError("read timeout"), "TimeoutError: read timeout"),
], ids=["cut mid-item", "call raised"])
def test_should_keep_the_seed_whole_and_record_why_when_the_intent_reply_is_unusable(reply, reason):
    result = _separator(reply).separate("solid organ transplant")

    assert result.include == ["solid organ transplant"] and result.exclude == []
    assert reason in (result.failure or ""), result.failure
    assert "\n" not in result.failure


def test_should_separate_the_whole_intent_reply():
    result = _separator(INTENT).separate("solid organ transplant")

    assert result.include == ["solid organ transplant"]
    assert getattr(result, "failure", None) is None


# ── clinical reranker ────────────────────────────────────────


def test_should_rank_by_score_and_record_why_when_the_pick_reply_is_cut():
    result = _clinical(PICK_CUT).rerank("solid organ transplant", CANDIDATES, 3)

    assert result.method == "score"
    assert [c.concept_id for c in result.candidates] == [4322471, 2721126, 27211]
    assert "Invalid json output" in (result.failure or ""), result.failure


def test_should_rank_the_whole_pick_first():
    result = _clinical(PICK).rerank("solid organ transplant", CANDIDATES, 3)

    assert result.method == "llm" and result.failure is None
    assert result.candidates[0].concept_id == 2721126


# ── the recommender and the mapping it hands back ────────────


def _recommender(intent_reply, pick_reply):
    from src.agents.conceptset import nlu_router
    from src.agents.conceptset.recommender import ConceptSetRecommender

    router = nlu_router.NLURouter.__new__(nlu_router.NLURouter)
    router.intent_separator = _separator(intent_reply)
    stage2 = MagicMock()
    stage2.search.return_value = list(CANDIDATES)
    from src.agents.conceptset.expression_builder import ConceptSetExpression, RecommendationItem

    builder = MagicMock()
    builder.build_expression.side_effect = lambda candidates, **k: RecommendationItem(
        name=k.get("criterion_name") or "set", expression=ConceptSetExpression())
    cache = MagicMock()
    cache.get.return_value = None
    return ConceptSetRecommender(
        nlu_router=router, stage2=stage2, reranker=_clinical(pick_reply),
        expression_builder=builder, cache=cache,
    ), cache


@pytest.mark.parametrize("intent_reply, pick_reply, stages", [
    (INTENT_CUT, PICK, ["nlu_router"]),
    (INTENT, PICK_CUT, ["clinical_reranker"]),
], ids=["intent cut", "pick cut"])
def test_should_list_the_stage_that_failed_and_cache_nothing(intent_reply, pick_reply, stages):
    recommender, cache = _recommender(intent_reply, pick_reply)

    response = recommender.recommend("solid organ transplant", top_k=3)

    assert [f["stage"] for f in response.mapping_failures] == stages
    assert all(f["seedsOnly"] is False and f["reason"] for f in response.mapping_failures)
    cache.set.assert_not_called()


def test_should_list_nothing_and_cache_a_clean_recommendation():
    recommender, cache = _recommender(INTENT, PICK)

    response = recommender.recommend("solid organ transplant", top_k=3)

    assert response.mapping_failures == []
    cache.set.assert_called_once()


def test_should_write_the_recommender_failures_to_the_rag_mapping_metadata():
    from src.services.tte_service import TTEService

    failure = {"stage": "clinical_reranker", "reason": "OutputParserException: Invalid json output: "
               + PICK_CUT, "seedsOnly": False}
    recommendation = MagicMock()
    recommendation.name = "solid organ transplant"
    recommendation.expression.to_atlas_json.return_value = {"items": [{"concept": {
        "CONCEPT_ID": 4322471, "CONCEPT_NAME": "c", "DOMAIN_ID": "Procedure"}}]}
    response = MagicMock(include_recommendations=[recommendation], fallback_reason=None,
                         mapping_failures=[failure])
    svc = TTEService(store=MagicMock())
    with patch.object(svc, "_get_seeded_concept_set_recommender",
                      return_value=MagicMock(recommend=MagicMock(return_value=response))), \
            patch.object(svc, "_resolve_seeded_domain", return_value="Procedure"):
        out = svc._recommend_seeded_concept_set_rag_fallback("solid organ transplant")

    assert out["mapping_metadata"].mappingFailures == [
        {**failure, "query": "solid organ transplant"}
    ]
