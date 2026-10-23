"""The critic's reply carries only what the selection reads.

Critic replies dominate mapping decode time (median ~1300 completion tokens per call at
~15 tok/s). Each candidate's free-text ``reasoning`` and the ``overall_reasoning`` were
read by log lines alone, so the contract asks for neither per-candidate narration nor an
unbounded summary. These tests pin the contract to the fields the selection path reads and
check that a reply without narration still yields the same selection.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from src.agents.agent2 import critic as critic_mod
from src.agents.agent2.critic import ConceptCritic, CriticSelection

CONSUMED = {
    "concept_id", "relevant", "confidence", "potential_issue", "assessment", "recommended_action",
}


class _Recording(dict):
    """A selection dict that records every key the critic reads from it."""

    seen: set = set()

    def get(self, key, default=None):
        _Recording.seen.add(key)
        return super().get(key, default)

    def __getitem__(self, key):
        _Recording.seen.add(key)
        return super().__getitem__(key)


def _kg(cid):
    c = MagicMock()
    c.concept_id, c.concept_name, c.domain_id = cid, "X", "Condition"
    c.vocabulary_id, c.relationship = "SNOMED", "child"
    return c


@pytest.fixture
def critic():
    with patch.dict(os.environ, {"AGENT2_CRITIC_SELF_REFLECT": "true"}), \
         patch("src.agents.agent2.critic.get_llm", return_value=MagicMock()):
        return ConceptCritic()


def _evaluate(critic, reply):
    chain = MagicMock()
    chain.invoke.return_value = reply
    critic._default_chain = chain
    with patch.object(critic, "_cache") as cache, \
         patch("src.agents.agent2.critic.select_critic_model", return_value=None):
        cache.get.return_value = None
        return critic.evaluate_with_outcome("q", [1], [_kg(2), _kg(3), _kg(4)], kg_concept_ids={2})


def _compact(cid, relevant, assessment="correct", action="keep", confidence=0.9):
    return {"concept_id": cid, "relevant": relevant, "confidence": confidence,
            "potential_issue": "none", "assessment": assessment, "recommended_action": action}


def test_should_name_only_consumed_fields_when_defining_a_candidate_entry():
    assert set(CriticSelection.model_fields) == CONSUMED


def test_should_read_no_field_outside_the_contract_when_selecting(critic):
    _Recording.seen = set()
    reply = {"selected_concepts": [
        _Recording(_compact(1, True)),
        _Recording(_compact(2, True, "contradicted", "drop", 0.8)),   # KG, confident: preserved
        _Recording(_compact(3, True, "contradicted", "drop", 0.8)),   # not KG: dropped
        _Recording(_compact(4, False)),
    ]}
    _evaluate(critic, reply)
    assert _Recording.seen <= set(CriticSelection.model_fields)


def test_should_select_the_same_concepts_when_the_reply_carries_no_narration(critic):
    reply = {"selected_concepts": [
        _compact(1, True),
        _compact(2, True, "contradicted", "drop", 0.8),
        _compact(3, True, "contradicted", "drop", 0.8),
        _compact(4, False),
    ]}
    outcome = _evaluate(critic, reply)
    assert outcome.failure is None
    assert outcome.concept_ids == [1, 2]


def test_should_not_ask_for_per_candidate_reasoning_when_rendering_the_contract():
    assert "- reasoning:" not in critic_mod._OUTPUT_CONTRACT
    for field in CONSUMED:
        assert f"- {field}:" in critic_mod._OUTPUT_CONTRACT

