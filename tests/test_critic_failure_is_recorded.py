"""A failed critic keeps the seeds, and says so on the mapping; it is never cached.

When the critic's call failed or its JSON could not be read, ``ConceptCritic.evaluate``
logged ``[Critic] Evaluation failed`` and returned the seeds, and the workflow could not
tell that answer from a critic that chose the seeds: the mapping carried no record, and
the criterion cache stored it like any other. Two malformed responses did not even reach
that handler: a truncated reply was repaired by LangChain's partial-JSON parser into the
selections it happened to complete, and a reply without ``selected_concepts`` read as "no
concept selected" -- both were returned and written to the critic cache as answers.

No LLM is called: the critic's chain is replaced by the text a model returned, fed
through the critic's own parser.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from src.agents.agent2.kg_expander import KGConcept
from src.models.ir import MappingResult

FAILURE_MARKER = "[Critic] Evaluation failed"
SEED = 10
#: Twelve anchors: clinical_anchor mode runs the critic only above ten.
ANCHORS = list(range(20, 32))


def _selection(ids):
    return (
        '{"selected_concepts": ['
        + ", ".join(
            f'{{"concept_id": {cid}, "relevant": true, "reasoning": "", "confidence": 1.0, '
            f'"potential_issue": "none", "assessment": "correct", "recommended_action": "keep"}}'
            for cid in ids
        )
        + '], "overall_reasoning": ""}'
    )


class _Replies:
    """The model's raw text, one reply per call, fed through the critic's own parser."""

    def __init__(self, parser, reply):
        self.calls = 0
        self.reply = reply
        self.chain = RunnableLambda(self._invoke) | parser

    def _invoke(self, _payload):
        self.calls += 1
        if isinstance(self.reply, Exception):
            raise self.reply
        return AIMessage(content=self.reply)


@pytest.fixture
def critic(monkeypatch):
    from src.agents.agent2 import critic as critic_mod

    monkeypatch.setenv("AGENT2_CRITIC_MODEL_TIER", "follow")
    monkeypatch.setenv("AGENT2_CRITIC_SELF_REFLECT", "true")
    monkeypatch.setattr(critic_mod, "_concept_rows", lambda ids: {})
    with patch.object(critic_mod, "get_llm", return_value=MagicMock()):
        instance = critic_mod.ConceptCritic()

    def _answer(reply):
        replies = _Replies(instance.parser, reply)
        instance._default_chain = replies.chain
        return replies

    instance.answer = _answer
    return instance


def _kg(ids):
    return [KGConcept(concept_id=cid, concept_name=f"c{cid}", domain_id="Condition",
                      vocabulary_id="SNOMED", relationship="sibling") for cid in ids]


def _process(monkeypatch, critic):
    from src.agents.agent2 import workflow as wf

    class _Expander:
        def expand(self, *_a, **_k):
            return _kg(ANCHORS)

        def save_cache(self):
            pass

    monkeypatch.setenv("KG_EXPAND_MODE", "clinical_anchor")
    monkeypatch.setenv("ENABLE_REFINER", "0")
    monkeypatch.setattr(wf, "get_kg_expander", lambda: _Expander())
    monkeypatch.setattr(wf, "get_critic", lambda: critic)
    workflow = wf.Agent2Workflow()
    with patch("src.agents.agent2.workflow.expand_abbreviation", return_value=("q", False)), \
         patch("src.agents.agent2.workflow.expand_in_context", return_value="q"), \
         patch.object(wf.Agent2Workflow, "_slow_path", return_value=[SEED]), \
         patch("src.agents.agent2.workflow.logician.drop_wrong_entity_class_for_condition",
               side_effect=lambda ids: ids):
        return workflow.process_with_details("q", domain_hint="Condition")


def _failure_lines(caplog):
    return [r.getMessage() for r in caplog.records if FAILURE_MARKER in r.getMessage()]


#: Each one a reply the critic cannot use, and what the recorded reason must name.
BROKEN_REPLIES = {
    "call raised": (TimeoutError("read timeout"), "TimeoutError: read timeout"),
    "not json": ("the model wrote prose", "Invalid json output"),
    "truncated json": (_selection([SEED, 20, 21])[:-40], "Invalid json output"),
    "no selected_concepts": ('{"overall_reasoning": "none fit"}', "selected_concepts"),
    "selected_concepts not a list": ('{"selected_concepts": "20, 21"}', "selected_concepts"),
}


# ── workflow: the failure is recorded on the mapping, seeds alone ─────


@pytest.mark.parametrize("case", sorted(BROKEN_REPLIES))
def test_should_record_the_failure_and_keep_the_seeds_alone_when_the_critic_answer_is_unusable(
    monkeypatch, caplog, critic, case
):
    reply, reason = BROKEN_REPLIES[case]
    critic.answer(reply)
    caplog.set_level(logging.WARNING)

    result = _process(monkeypatch, critic)

    assert result.concept_ids == [SEED], "a partial or empty critic answer was used"
    assert reason in (result.critic_failure or ""), result.critic_failure
    assert result.mapping_failures() == [
        {"stage": "critic", "reason": result.critic_failure, "seedsOnly": True}
    ]
    lines = _failure_lines(caplog)
    assert len(lines) == 1, lines
    assert "\n" not in lines[0]


def test_should_leave_the_failure_unset_when_the_critic_answers(monkeypatch, critic):
    critic.answer(_selection([SEED, 20, 21]))

    result = _process(monkeypatch, critic)

    assert result.concept_ids == [SEED, 20, 21]
    assert result.critic_failure is None
    assert result.mapping_failures() == []


# ── critic cache: an unusable answer is never stored ─────────


@pytest.mark.parametrize("case", sorted(BROKEN_REPLIES))
def test_should_ask_again_rather_than_replay_when_the_critic_answer_was_unusable(critic, case):
    replies = critic.answer(BROKEN_REPLIES[case][0])

    critic.evaluate("q", [SEED], _kg(ANCHORS), domain_hint="Condition")
    critic.evaluate("q", [SEED], _kg(ANCHORS), domain_hint="Condition")

    assert replies.calls == 2, "an unusable answer was served from the critic cache"
    assert critic._cache.size == 0


def test_should_replay_a_usable_answer_from_the_critic_cache(critic):
    replies = critic.answer(_selection([SEED, 20]))

    first = critic.evaluate("q", [SEED], _kg(ANCHORS), domain_hint="Condition")
    second = critic.evaluate("q", [SEED], _kg(ANCHORS), domain_hint="Condition")

    assert first == second == [SEED, 20]
    assert replies.calls == 1


# ── criterion cache: a mapping with a failed critic is not stored ──


def test_should_not_store_a_mapping_in_the_criterion_cache_when_its_critic_failed():
    from tests.test_kg_specificity_lookup_failure import _recommend

    out, cache = _recommend(MappingResult(
        concept_ids=[SEED], route_path="slow", critic_failure="TimeoutError: read timeout",
    ))

    assert out["name"] == "set"
    assert cache.stats()["current_size"] == 0
