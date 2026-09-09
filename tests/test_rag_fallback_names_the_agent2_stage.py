"""When both mapping stages fail, the record must name both.

`_recommend_seeded_concept_set` runs Agent 2 first and, on any exception, logs a
structlog warning and falls through to the RAG fallback. If the fallback then fails too,
the exception the caller sees is the fallback's alone -- and the Agent 2 failure that
sent it there survives only in a log line.

That is exactly what produced the six empty-reason rows of the 2026-09-08 batch: Agent 2
returned no seeds and the fallback's ontology search timed out, and the artifact recorded
`""`. Chaining the fallback failure onto the Agent 2 one makes `describe_mapping_failure`
name both stages in a single sentence.

The empty-Agent-2 case is separate and needs saying in the message rather than in a
`__cause__`, because Agent 2 did not raise -- it returned nothing, which is not an
exception to chain.

`expected_domain="Condition"` keeps the exact-ingredient and MeSH-alias tiers out of the
call entirely (both are gated on `expected_domain in ("Drug", None)`), so no database is
touched. The criterion cache is turned off through its own env flag.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.services.tte_service import TTEService
from src.utils.criterion_refusal import REFUSAL_NO_CONCEPT_MAPPING, CriterionRefused


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> TTEService:
    monkeypatch.setenv("CRITERION_CACHE_ENABLED", "false")
    return TTEService(store=MagicMock())


def _agent2_raising(monkeypatch: pytest.MonkeyPatch, exc: BaseException) -> None:
    from src.agents.agent2 import workflow as agent2_workflow

    def _boom(self, *args, **kwargs):
        raise exc

    monkeypatch.setattr(agent2_workflow.Agent2Workflow, "process_with_details", _boom)


def _agent2_returning_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.agents.agent2 import workflow as agent2_workflow

    monkeypatch.setattr(
        agent2_workflow.Agent2Workflow,
        "process_with_details",
        lambda self, *a, **k: SimpleNamespace(
            concept_ids=[], overbroad_concept_ids=[], route_path="rag_only"
        ),
    )


def test_should_chain_the_fallback_failure_onto_the_agent2_failure(service, monkeypatch):
    """Agent 2 raised, then the fallback timed out. One record, both stages."""
    _agent2_raising(monkeypatch, RuntimeError("agent2 died"))

    recommender = MagicMock()
    recommender.recommend.side_effect = TimeoutError()
    monkeypatch.setattr(service, "_get_seeded_concept_set_recommender", lambda: recommender)

    with pytest.raises(TimeoutError) as caught:
        service._recommend_seeded_concept_set(
            "Contraindication to clopidogrel", expected_domain="Condition"
        )
    cause = caught.value.__cause__
    assert isinstance(cause, RuntimeError), "the Agent 2 failure was dropped on the floor"
    assert "agent2 died" in str(cause)


def test_should_say_agent2_returned_nothing_when_it_did_not_raise(service, monkeypatch):
    """No exception to chain, so the fact goes in the message instead."""
    _agent2_returning_nothing(monkeypatch)

    recommender = MagicMock()
    recommender.recommend.return_value = SimpleNamespace(
        include_recommendations=[], fallback_reason=None
    )
    monkeypatch.setattr(service, "_get_seeded_concept_set_recommender", lambda: recommender)

    with pytest.raises(CriterionRefused) as caught:
        service._recommend_seeded_concept_set(
            "Investigational drug use", expected_domain="Condition"
        )
    assert caught.value.code == REFUSAL_NO_CONCEPT_MAPPING
    assert "Agent 2 returned no concepts" in str(caught.value)
    assert "No concept mapping found" in str(caught.value)


def test_should_leave_a_lone_fallback_refusal_unwrapped(service, monkeypatch):
    """Agent 2 succeeded-and-was-skipped is not a stage to name; do not invent one."""
    _agent2_raising(monkeypatch, RuntimeError("agent2 died"))

    recommender = MagicMock()
    recommender.recommend.return_value = SimpleNamespace(
        include_recommendations=[], fallback_reason="intent router could not parse"
    )
    monkeypatch.setattr(service, "_get_seeded_concept_set_recommender", lambda: recommender)

    with pytest.raises(CriterionRefused) as caught:
        service._recommend_seeded_concept_set("Table II criteria", expected_domain="Condition")
    assert caught.value.code == "intent-unparsed"
    assert caught.value.detail == "intent router could not parse"
    assert isinstance(caught.value.__cause__, RuntimeError)
