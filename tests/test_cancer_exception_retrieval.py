"""Recorded cancer rows and candidate pools; no live vocabulary or LLM calls."""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.agents.agent2.retriever import ConceptRetriever
from src.services.entity_subtraction import resolve_entity_exception
from src.services.tte_service import TTEService


@pytest.fixture
def recorded():
    return json.loads(
        (Path(__file__).parent / "fixtures/cancer_exception_retrieval.json").read_text()
    )


def _retriever(pool, domain, *, fail=False):
    """Model Chroma's machine-domain filter, without inventing eligible candidates.

    The log contains class/vocabulary but no per-candidate domain or distance;
    domain and equal distances here are explicit test metadata, not measurements.
    """
    def query(**kwargs):
        if fail:
            raise RuntimeError("recorded pool unavailable")
        rows = pool if kwargs.get("where", {}).get("domain_id", domain) == domain else []
        return {
            "ids": [[str(r["concept_id"]) for r in rows]],
            "metadatas": [[{**r, "domain_id": domain} for r in rows]],
            "documents": [[r["concept_name"] for r in rows]],
            "distances": [[1.0] * len(rows)],
        }

    retriever = ConceptRetriever.__new__(ConceptRetriever)
    retriever.concept_weights = {}
    retriever.collection = MagicMock()
    retriever.collection.query.side_effect = query
    return retriever


def test_should_remove_device_pool_when_recorded_own_entity_requests_condition(recorded):
    row = recorded["rows"]["9"][1]
    retriever = _retriever(recorded["own_candidates"]["candidates"], "Device")
    assert retriever.search(row["sourceText"], domain_hint=row["domain"]) == []
    assert retriever.collection.query.call_args.kwargs["where"] == {"domain_id": "Condition"}


@pytest.mark.parametrize("study", ["9", "10"])
def test_should_filter_exception_search_when_recorded_member_requests_condition(recorded, study):
    row = recorded["rows"][study][1]
    exception = TTEService._stated_entity_exception(row, "cancer")
    retriever = _retriever(recorded["exception_candidates"]["candidates"], "Condition")
    candidates = retriever.search(exception.excepted[0], domain_hint=row["domain"])
    assert len(candidates) == 20  # Domain restriction cannot resolve this semantic mismatch.
    assert retriever.collection.query.call_args.kwargs["where"] == {"domain_id": "Condition"}


def test_should_keep_unhinted_search_when_no_machine_domain_is_supplied(recorded):
    retriever = _retriever(recorded["own_candidates"]["candidates"], "Device")
    assert len(retriever.search(recorded["own_candidates"]["query"])) == 20
    assert "where" not in retriever.collection.query.call_args.kwargs


def test_should_return_no_candidates_when_filtered_database_query_fails(recorded):
    retriever = _retriever(recorded["own_candidates"]["candidates"], "Device", fail=True)
    assert retriever.search(recorded["own_candidates"]["query"], domain_hint="Condition") == []
    assert retriever.collection.query.call_count == 1


@pytest.mark.parametrize("study", ["9", "10"])
def test_should_forward_member_domain_when_mapping_base_exception_and_own(recorded, study):
    row = recorded["rows"][study][1]
    calls = []

    class Service(TTEService):
        def _recommend_seeded_concept_set(self, seed_text, **kwargs):
            if kwargs.get("resolving_entity_exception"):
                calls.append((seed_text, kwargs["expected_domain"]))
                cid = 4031105 if seed_text == recorded["exception_candidates"]["query"] else 4194405
                return {"expression": {"items": [{"concept": {"CONCEPT_ID": cid}}]}}
            return super()._recommend_seeded_concept_set(seed_text, **kwargs)

    service = Service(store=MagicMock())
    service._closures_overlap = MagicMock(return_value=True)
    exception = service._stated_entity_exception(row, "cancer")
    service._recommend_seeded_concept_set(
        "cancer", expected_domain=row["domain"], entity_exception=exception,
    )
    assert calls == [
        ("cancer", "Condition"), (exception.excepted[0], "Condition"),
        (exception.own, "Condition"),
    ]
    # The group has planner exceptions; the member independently has annotation exceptions.
    assert "exceptedEntities" not in row
    assert exception.excepted == [recorded["exception_candidates"]["query"]]


def test_should_refuse_subtraction_when_recorded_exception_reranker_selects_none(recorded):
    row = recorded["rows"]["10"][1]
    exception = TTEService._stated_entity_exception(row, "cancer")
    base = {"expression": {"items": [{"concept": {"CONCEPT_ID": 4194405}}]}}
    # Recorded reranker outcome: all 20 offered melanoma candidates were rejected.
    result = resolve_entity_exception(
        exception,
        lambda phrase: base if phrase == exception.base else {"expression": {"items": []}},
    )
    assert result.mapping is None
    assert "mapped to no concepts" in result.fallback_reason


def test_should_refuse_subtraction_when_exception_covers_every_base_member(recorded):
    exception = TTEService._stated_entity_exception(recorded["rows"]["10"][1], "cancer")
    mapping = {"expression": {"items": [
        {"concept": {"CONCEPT_ID": r["concept_id"]}}
        for r in recorded["exception_candidates"]["candidates"]
    ]}}
    result = resolve_entity_exception(exception, lambda phrase: mapping)
    assert result.mapping is None
    assert result.covers_base


def test_should_ignore_exception_when_its_cited_span_is_absent(recorded):
    row = recorded["rows"]["10"][1]
    row["annotation"]["excepted_entities"][0]["span"] = "absent source span"
    assert TTEService._stated_entity_exception(row, "cancer") is None
