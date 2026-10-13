"""The critic cache answers only the call it was filled by.

Real event, P2 NEW re-ingest (``output/site_gap/2026-10-12_p2_new/reingest.log``). The
CARMELINA criterion 'CABG' reached the critic twice with the same query, the same domain
(Procedure) and the same context ('Target domain: Procedure'), but different seeds:

* request at L23646, lineage L33732: seeds 4189169, 4336464, 4000733, 4168166 and the 46 KG
  candidates below -- a real critic call;
* lineage L53909 (and again L54027): seeds 4189169, 4336464, 4231998, 4168166 -- served by
  ``[CACHE HIT] Critic returning 14 cached concepts for 'CABG'`` (L53906). The critic never
  saw seed 4231998, and the replayed selection carried 4000733, which was not a seed of
  that call.

The cache key was ``query | domain | model | critic_signature``, so the second call
replayed the first one's answer. Call 2's own KG candidates were never rendered (the cache
answered before the prompt was built), so the real-event test holds the KG list fixed and
varies only what the log shows varied: the seeds.

The LLM is a recording stub that marks every id of both calls relevant, so a call's result
is exactly the candidates it was shown -- a replay is visible as the other call's ids.
No model, no Postgres.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import src.agents.agent2.critic as critic_mod
from src.agents.agent2.kg_expander import KGConcept

QUERY = "CABG"
DOMAIN = "Procedure"
CONTEXT = "Target domain: Procedure"
SEEDS_L33732 = [4189169, 4336464, 4000733, 4168166]
SEEDS_L53909 = [4189169, 4336464, 4231998, 4168166]
KG_L23646 = [
    4250892, 4158569, 4301351, 4029205, 4284104, 37111313, 3655761, 3655763, 4339629,
    4018579, 4020213, 3655764, 4337056, 4336466, 4336465, 3655762, 4337737, 4336467,
    4172226, 763535, 4049676, 4208093, 4286271, 4018012, 4159953, 4018934, 4134560,
    4018938, 4020466, 37017419, 4048543, 4046698, 4045839, 4176471, 4207060, 4045663,
    4263740, 4052252, 4295278, 4115340, 4146366, 4205489, 4296220, 4258433, 4303236,
    4132647,
]


class _RecordingChain:
    """Stands in for ``prompt | llm | parser``: records each call, marks ``ids`` relevant."""

    def __init__(self, ids: set[int]) -> None:
        self.ids = ids
        self.calls: list[dict[str, Any]] = []

    def invoke(self, inputs: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(inputs)
        return {
            "selected_concepts": [
                {"concept_id": cid, "relevant": True, "reasoning": "", "confidence": 1.0,
                 "potential_issue": "none", "assessment": "correct",
                 "recommended_action": "keep"}
                for cid in sorted(self.ids)
            ],
            "overall_reasoning": "",
        }


def _kg(ids: list[int]) -> list[KGConcept]:
    return [
        KGConcept(concept_id=cid, concept_name=f"c{cid}", domain_id=DOMAIN,
                  vocabulary_id="SNOMED", relationship="sibling")
        for cid in ids
    ]


@pytest.fixture
def critic(monkeypatch: pytest.MonkeyPatch) -> critic_mod.ConceptCritic:
    monkeypatch.setenv("AGENT2_CRITIC_MODEL_TIER", "follow")
    monkeypatch.setenv("AGENT2_CRITIC_SELF_REFLECT", "true")
    monkeypatch.setattr(critic_mod, "_concept_rows", lambda ids: {})
    with patch.object(critic_mod, "get_llm", return_value=MagicMock()):
        instance = critic_mod.ConceptCritic()
    every_id = set(SEEDS_L33732) | set(SEEDS_L53909) | set(KG_L23646) | {1, 2}
    instance._default_chain = _RecordingChain(every_id)
    return instance


def _evaluate(critic: critic_mod.ConceptCritic, seeds: list[int], kg: list[int],
              context: str | None = CONTEXT, query: str = QUERY) -> set[int]:
    return set(critic.evaluate(query, seeds, _kg(kg), context=context, domain_hint=DOMAIN))


def test_should_call_the_critic_again_when_the_same_query_and_domain_arrive_with_other_seeds(
    critic: critic_mod.ConceptCritic,
) -> None:
    first = _evaluate(critic, SEEDS_L33732, KG_L23646)
    second = _evaluate(critic, SEEDS_L53909, KG_L23646)

    assert len(critic._default_chain.calls) == 2, "the L53909 call was served from L33732's entry"
    assert 4231998 in second, "the L53909 seed never reached the critic"
    offered = set(SEEDS_L53909) | set(KG_L23646)
    assert second <= offered, f"returned ids the call never offered: {sorted(second - offered)}"
    assert 4000733 in first and 4000733 not in second


def test_should_call_the_critic_again_when_only_the_kg_candidates_differ(
    critic: critic_mod.ConceptCritic,
) -> None:
    _evaluate(critic, SEEDS_L33732, KG_L23646)
    second = _evaluate(critic, SEEDS_L33732, KG_L23646[:10])

    assert len(critic._default_chain.calls) == 2
    assert second == set(SEEDS_L33732) | set(KG_L23646[:10])


def test_should_call_the_critic_again_when_only_the_context_differs(
    critic: critic_mod.ConceptCritic,
) -> None:
    _evaluate(critic, SEEDS_L33732, KG_L23646, context=CONTEXT)
    _evaluate(critic, SEEDS_L33732, KG_L23646, context=None)

    queries = [call["query"] for call in critic._default_chain.calls]
    assert queries == [f"{CONTEXT}: {QUERY}", QUERY]


def test_should_serve_the_cache_when_the_call_is_identical(
    critic: critic_mod.ConceptCritic,
) -> None:
    first = _evaluate(critic, SEEDS_L33732, KG_L23646)
    second = _evaluate(critic, SEEDS_L33732, KG_L23646)

    assert len(critic._default_chain.calls) == 1
    assert second == first


def test_should_serve_the_cache_when_only_the_order_of_ids_differs(
    critic: critic_mod.ConceptCritic,
) -> None:
    _evaluate(critic, SEEDS_L33732, KG_L23646)
    _evaluate(critic, list(reversed(SEEDS_L33732)), list(reversed(KG_L23646)))

    assert len(critic._default_chain.calls) == 1


def test_should_not_share_a_key_when_kg_concept_ids_differ() -> None:
    """``kg_concept_ids`` decides which contradicted KG concepts survive the filter."""
    from src.agents.agent2.critic_cache import CriticCache

    def key(kg_concept_ids: set[int] | None) -> str:
        return CriticCache.make_key(
            QUERY, DOMAIN, context=CONTEXT, seed_concept_ids=[1],
            candidate_concept_ids=[2], kg_concept_ids=kg_concept_ids,
        )

    assert key(None) != key({2})
    assert key({2}) == key({2})
