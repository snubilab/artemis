"""A seed only the retriever chose is kept only if the critic keeps it.

When the reranker selects concepts but not the retriever's #1, `_seeds_after_rerank` still
adds that #1 as a seed. Since a5cdf79 the retriever's order is the embedding distance alone,
so its #1 is the nearest vector, not a judgement: A2 (2026-10-14_a2_dry) seeded "alanine
aminotransferase" with the AST serum concept 3013721, "TIA" with "Infarction of thyroid",
"LDL cholesterol" with HDL cholesterol. The critic, shown that seed beside the others,
rejected it in 24 of the 48 such calls where it ran — and the seed stayed anyway, because the
refiner keeps every seed. The ALT concept set of EMPA-REG carried AST.

The critic is the only model that judged such a seed, so its rejection now stands.
Reranker seeds need two further negative tiebreak verdicts; a skipped or failed critic
leaves every seed unchanged.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.agents.agent2.critic import CriticOutcome
from src.agents.agent2.kg_expander import KGConcept
from src.agents.agent2.retriever import CandidateConcept

QUERY = "alanine aminotransferase"
AST, ALT, ALT_BLOOD = 3013721, 3006923, 46236949


def _cand(cid: int) -> CandidateConcept:
    return CandidateConcept(concept_id=cid, concept_name=f"c{cid}", domain_id="Condition",
                            vocabulary_id="SNOMED", concept_class_id="Clinical Finding",
                            distance=50.0)


def _kg(cid: int) -> KGConcept:
    return KGConcept(concept_id=cid, concept_name=f"k{cid}", domain_id="Condition",
                     vocabulary_id="SNOMED", relationship="sibling (parent: c1)", via_concept_id=1)


class _PicksALT:
    def rerank_topn(self, *_args, **_kwargs):
        return [_cand(ALT), _cand(ALT_BLOOD)]


def _refine_keeps_every_seed(seed_ids, kg_concepts, *_args, **_kwargs):
    """ConceptSetRefiner's contract: seeds are never pruned (concept_set_refiner.refine)."""
    return SimpleNamespace(kept_ids=list(seed_ids) + [c.concept_id for c in kg_concepts], overbroad_ids=[])


def _process(critic_selects, n_kg=12, judge=None, failure=None, refiner=None, enabled="1",
             name_rows=None, lookup_error=None):
    from src.agents.agent2 import workflow as wf

    expander = MagicMock()
    expander.expand.side_effect = lambda sid, *a, **k: [_kg(900 + i) for i in range(n_kg)] if sid == ALT else []
    critic = MagicMock()
    critic.evaluate_with_outcome.return_value = CriticOutcome(list(critic_selects), failure=failure)
    workflow = wf.Agent2Workflow()
    workflow._reranker = _PicksALT()
    with patch.dict("os.environ", KG_EXPAND_MODE="clinical_anchor", ENABLE_REFINER=enabled), \
            patch.object(wf, "expand_abbreviation", return_value=(QUERY, False)), \
            patch.object(wf, "expand_in_context", side_effect=lambda q: q), \
            patch.object(wf.logician, "decompose_combination", side_effect=lambda cid: [cid]), \
            patch.object(wf.logician, "prune_empty_concepts", side_effect=lambda ids: ids), \
            patch.object(wf.logician, "drop_wrong_entity_class_for_condition",
                         side_effect=lambda ids: ids), \
            patch.object(wf, "admit_within_seed_closure", side_effect=lambda gen, seeds: [c for _, c in gen]), \
            patch.object(wf, "get_kg_expander", return_value=expander), \
            patch.object(wf, "get_critic", return_value=critic), \
            patch.object(wf, "_concept_rows", side_effect=lookup_error,
                         return_value=name_rows if name_rows is not None else {
                             cid: (f"c{cid}", "Condition", "SNOMED")
                             for cid in (AST, ALT, ALT_BLOOD)}), \
            patch.object(wf, "judge_seed", new=judge or MagicMock(
                return_value={"drop": False, "first": {}, "second": {}})), \
            patch.object(wf, "_refine", side_effect=refiner or _refine_keeps_every_seed):
        return workflow.process_with_details(
            QUERY, domain_hint="Condition",
            pre_fetched_candidates=[_cand(AST), _cand(ALT), _cand(ALT_BLOOD)],
        )


def test_should_drop_retriever_only_seed_when_critic_rejects_it():
    result = _process(critic_selects=[ALT, ALT_BLOOD, 900])

    assert AST not in result.concept_ids
    assert AST not in result.seed_concept_ids
    assert {ALT, ALT_BLOOD, 900}.issubset(result.concept_ids)


def test_should_keep_retriever_only_seed_when_critic_selects_it():
    result = _process(critic_selects=[AST, ALT, 900])

    assert AST in result.concept_ids and AST in result.seed_concept_ids


def test_should_keep_reranker_seed_even_when_critic_rejects_it():
    result = _process(critic_selects=[ALT, 900])

    assert ALT_BLOOD in result.concept_ids


def test_should_keep_retriever_only_seed_when_no_critic_judged_it():
    result = _process(critic_selects=[], n_kg=3)  # <= 10 candidates: critic skipped

    assert AST in result.concept_ids and AST in result.seed_concept_ids


def _verdict(drop):
    return {"drop": drop, "first": {"answer": "no" if drop else "yes"},
            "second": {"answer": "no" if drop else "not_called"}}


def test_should_drop_disputed_reranker_seed_before_refiner_when_both_judges_reject():
    judge = MagicMock(return_value=_verdict(True))
    refiner = MagicMock(side_effect=_refine_keeps_every_seed)
    result = _process([ALT, 900], judge=judge, refiner=refiner)
    assert ALT_BLOOD not in result.concept_ids
    assert ALT_BLOOD not in result.seed_concept_ids
    assert refiner.call_args.args[0] == [ALT]
    judge.assert_called_once_with(QUERY, f"c{ALT_BLOOD}")


def test_should_keep_all_reranker_seeds_when_every_reranker_seed_would_drop(caplog):
    import logging
    judge = MagicMock(return_value=_verdict(True))
    with caplog.at_level(logging.INFO):
        result = _process([900], judge=judge)
    assert {ALT, ALT_BLOOD}.issubset(result.concept_ids)
    assert {ALT, ALT_BLOOD}.issubset(result.seed_concept_ids)
    assert AST not in result.concept_ids
    assert judge.call_count == 2
    assert "all_reranker_seeds_preserved" in caplog.text


def test_should_log_query_seed_and_judgement_when_seed_is_dropped(caplog):
    import logging
    with caplog.at_level(logging.INFO):
        _process([ALT, 900], judge=MagicMock(return_value=_verdict(True)))
    assert QUERY in caplog.text
    assert str(ALT_BLOOD) in caplog.text
    assert "seed_tiebreak" in caplog.text and "dropped" in caplog.text


def test_should_not_judge_retriever_only_seed_when_critic_rejects_it():
    judge = MagicMock()
    result = _process([ALT, ALT_BLOOD, 900], judge=judge)
    assert AST not in result.concept_ids
    judge.assert_not_called()


def test_should_not_call_judge_when_critic_is_skipped_or_failed():
    for n_kg, failure in [(3, None), (12, "unreadable critic")]:
        judge = MagicMock()
        result = _process([], n_kg=n_kg, failure=failure, judge=judge)
        assert {AST, ALT, ALT_BLOOD}.issubset(result.concept_ids)
        judge.assert_not_called()


def test_should_apply_tiebreak_when_refiner_is_disabled():
    result = _process([ALT, 900], judge=MagicMock(return_value=_verdict(True)), enabled="0")
    assert ALT_BLOOD not in result.concept_ids and ALT_BLOOD not in result.seed_concept_ids


def test_should_preserve_disputed_seed_when_judge_keeps_it_without_refiner():
    result = _process([ALT, 900], judge=MagicMock(return_value=_verdict(False)), enabled="0")
    assert ALT_BLOOD in result.concept_ids and ALT_BLOOD in result.seed_concept_ids


def test_should_keep_seed_when_concept_name_is_missing_or_lookup_fails():
    for error in (None, RuntimeError("vocabulary unavailable")):
        judge = MagicMock()
        result = _process([ALT, 900], judge=judge, name_rows={}, lookup_error=error)
        assert ALT_BLOOD in result.concept_ids and ALT_BLOOD in result.seed_concept_ids
        judge.assert_not_called()


def test_should_drop_recorded_carolina_seed_when_real_judge_path_returns_two_no(monkeypatch):
    import sys

    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableLambda

    from src.agents.agent2 import seed_tiebreak
    from src.agents.agent2.critic_cache import CriticCache

    # The recorded gatefix3 disagreement, with a separate critic-selected seed so
    # the preserve-all guard is not the reason for the result.
    monkeypatch.setattr(sys.modules[__name__], "QUERY",
                        "Hypersensitivity to glimepiride or SU class")
    monkeypatch.setattr(sys.modules[__name__], "ALT_BLOOD", 443732)
    calls = []

    def answer(prompt):
        calls.append(prompt.to_messages())
        return AIMessage(content='{"answer":"no"}')

    monkeypatch.setattr(seed_tiebreak, "_cache", CriticCache())
    monkeypatch.setattr(seed_tiebreak, "get_llm", lambda **kw: RunnableLambda(answer))
    result = _process([ALT, 900], judge=seed_tiebreak.judge_seed,
                      name_rows={443732: ("Disorder due to type 2 diabetes mellitus",
                                          "Condition", "SNOMED")})
    assert 443732 not in result.concept_ids and 443732 not in result.seed_concept_ids
    assert len(calls) == 2
    assert all(QUERY in messages[1].content and
               "Disorder due to type 2 diabetes mellitus" in messages[1].content
               for messages in calls)
