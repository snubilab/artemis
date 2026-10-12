"""Candidate ranking does not read concept names (RFC-016 §4, C4).

``ConceptRetriever._score_candidates`` added a boost when a concept NAME equalled,
contained or shared a word prefix with the query, and lifted the class penalty when the
name contained the query. That is a text rule over OMOP concept names; ranking is the
embedding distance plus the machine-field preferences (vocabulary, class, domain).

The candidates are the real 60-row ChromaDB result for "Platelet count"
(``tests/fixtures/retriever_platelet_candidates.json``). Each test changes only the names
-- the distances and metadata are the real rows -- and requires the order not to move.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.agents.agent2.retriever import ConceptRetriever

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "retriever_platelet_candidates.json").read_text()
)


def _ranked_ids(documents: list[str]) -> list[int]:
    retriever = ConceptRetriever.__new__(ConceptRetriever)
    retriever.concept_weights = {}
    retriever.collection = None
    rows = FIXTURE["candidates"]
    scored = retriever._score_candidates(
        query_text=FIXTURE["query"],
        ids=[str(r["concept_id"]) for r in rows],
        metadatas=[
            {
                "domain_id": r["domain_id"],
                "vocabulary_id": r["vocabulary_id"],
                "concept_class_id": r["concept_class_id"],
            }
            for r in rows
        ],
        distances=[r["distance"] for r in rows],
        documents=documents,
        domain_hint=FIXTURE["domain_hint"],
        n_results=len(rows),
    )
    return [c.concept_id for c in scored]


def test_should_rank_identically_when_every_name_is_replaced_by_its_concept_id():
    real_names = [r["name"] for r in FIXTURE["candidates"]]
    opaque_names = [str(r["concept_id"]) for r in FIXTURE["candidates"]]

    assert _ranked_ids(real_names) == _ranked_ids(opaque_names)


def test_should_not_lift_a_candidate_when_its_name_equals_the_query():
    rows = FIXTURE["candidates"]
    names = [r["name"] for r in rows]
    before = _ranked_ids(names)
    last = before[-1]
    renamed = [FIXTURE["query"] if r["concept_id"] == last else r["name"] for r in rows]

    assert _ranked_ids(renamed) == before
