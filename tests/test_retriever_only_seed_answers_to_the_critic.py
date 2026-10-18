"""A seed only the retriever chose is kept only if the critic keeps it.

When the reranker selects concepts but not the retriever's #1, `_seeds_after_rerank` still
adds that #1 as a seed. Since a5cdf79 the retriever's order is the embedding distance alone,
so its #1 is the nearest vector, not a judgement: A2 (2026-10-14_a2_dry) seeded "alanine
aminotransferase" with the AST serum concept 3013721, "TIA" with "Infarction of thyroid",
"LDL cholesterol" with HDL cholesterol. The critic, shown that seed beside the others,
rejected it in 24 of the 48 such calls where it ran — and the seed stayed anyway, because the
refiner keeps every seed. The ALT concept set of EMPA-REG carried AST.

The critic is the only model that judged such a seed, so its rejection now stands. A seed the
reranker chose is untouched, and so is a retriever-only seed when no critic judged it (critic
skipped or failed): nothing then contradicts it.
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


def _process(critic_selects, n_kg=12):
    from src.agents.agent2 import workflow as wf

    expander = MagicMock()
    expander.expand.side_effect = lambda sid, *a, **k: [_kg(900 + i) for i in range(n_kg)] if sid == ALT else []
    critic = MagicMock()
    critic.evaluate_with_outcome.return_value = CriticOutcome(list(critic_selects))
    workflow = wf.Agent2Workflow()
    workflow._reranker = _PicksALT()
    with patch.dict("os.environ", {"KG_EXPAND_MODE": "clinical_anchor", "ENABLE_REFINER": "1"}), \
            patch.object(wf, "expand_abbreviation", return_value=(QUERY, False)), \
            patch.object(wf, "expand_in_context", side_effect=lambda q: q), \
            patch.object(wf.logician, "decompose_combination", side_effect=lambda cid: [cid]), \
            patch.object(wf.logician, "prune_empty_concepts", side_effect=lambda ids: ids), \
            patch.object(wf.logician, "drop_wrong_entity_class_for_condition",
                         side_effect=lambda ids: ids), \
            patch.object(wf, "admit_within_seed_closure", side_effect=lambda gen, seeds: [c for _, c in gen]), \
            patch.object(wf, "get_kg_expander", return_value=expander), \
            patch.object(wf, "get_critic", return_value=critic), \
            patch.object(wf, "_refine", side_effect=_refine_keeps_every_seed):
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
