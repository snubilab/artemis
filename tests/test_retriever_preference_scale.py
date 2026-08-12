"""Preference scoring must survive a change of embedding scale.

`_VOCAB_PREFERENCE`, `_PREFERRED_CLASSES` and `_PENALIZED_CLASSES` are absolute
constants in the +-0.03..0.50 range. They were tuned for distances on normalised
embeddings, which span roughly [0, 2]. The live collection is
`omop_concepts_medcpt`, whose L2 distances run ~47.6-56.1 — a spread of 8.5, so a
-0.30 vocabulary boost moves a candidate by 3.5% of the spread and the ranking is,
in practice, the raw vector order.

The fixture is the real 60-candidate ChromaDB result for "Platelet count" that
motivated this. `Measurement` prefers LOINC by -0.30 and penalises SNOMED by +0.20,
yet unscaled the gold LOINC Lab Tests rank 9th and 12th behind four SNOMED concepts,
and the generated ARISTOTLE concept set scored recall 0.000 against them.

Same root cause, worth knowing while reading this file: `standard_concept` is absent
from the ChromaDB metadata, so the standard-concept branch never executes at all.
That one is not a scale problem and is not fixed here.
"""
import json
from pathlib import Path

import pytest

from src.agents.agent2.retriever import ConceptRetriever

FIXTURE = Path(__file__).parent / "fixtures" / "retriever_platelet_candidates.json"


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def _retriever() -> ConceptRetriever:
    """A retriever with no ChromaDB and no DB — scoring is pure."""
    retriever = ConceptRetriever.__new__(ConceptRetriever)
    retriever.concept_weights = {}
    retriever.collection = None
    return retriever


def _raw(payload: dict, scale: float = 1.0, offset: float = 0.0):
    """Fixture rows as the (ids, metadatas, distances, documents) ChromaDB tuple."""
    rows = payload["candidates"]
    ids = [str(r["concept_id"]) for r in rows]
    metadatas = [
        {
            "domain_id": r["domain_id"],
            "vocabulary_id": r["vocabulary_id"],
            "concept_class_id": r["concept_class_id"],
        }
        for r in rows
    ]
    distances = [r["distance"] * scale + offset for r in rows]
    documents = [r["name"] for r in rows]
    return ids, metadatas, distances, documents


def _ranked_ids(retriever: ConceptRetriever, payload: dict, scale=1.0, offset=0.0, n=60):
    ids, metadatas, distances, documents = _raw(payload, scale, offset)
    scored = retriever._score_candidates(
        query_text=payload["query"],
        ids=ids,
        metadatas=metadatas,
        distances=distances,
        documents=documents,
        domain_hint=payload["domain_hint"],
        n_results=n,
    )
    return [c.concept_id for c in scored]


SNOMED_PROCEDURE_PLATELET_COUNT = 4267147
GOLD_LOINC_AUTOMATED_COUNT = 3024929


def test_should_rank_gold_loinc_above_the_snomed_procedure_it_lost_to():
    """The real case: a LOINC Lab Test must beat a SNOMED Procedure in Measurement.

    ARISTOTLE's "Platelet count" exclusion resolved to SNOMED `Platelet count`
    (4267147, a Procedure) plus an Observable Entity, and scored recall 0.000
    against gold's two LOINC Lab Tests. Unscaled, 4267147 ranked 8th and gold
    3024929 ranked 9th — the -0.30 LOINC boost and +0.20 SNOMED penalty could not
    close a 3.5-point distance gap.

    Scope note, so this test is not read as more than it is: it fixes the ordering
    between these two, not the whole criterion. The SNOMED Observable Entity and
    Clinical Finding sit at ranks 3 and 4 and do not move, so gold reaches rank 7,
    and whether the criterion is actually repaired depends on the reranker's pick.
    The measured value of this change is across the corpus, not here: gold@5 for
    Measurement went 11/31 -> 19/31 and gold@15 19/31 -> 25/31.
    """
    payload = _fixture()
    ranked = _ranked_ids(_retriever(), payload)

    gold_rank = ranked.index(GOLD_LOINC_AUTOMATED_COUNT) + 1
    snomed_rank = ranked.index(SNOMED_PROCEDURE_PLATELET_COUNT) + 1

    assert gold_rank < snomed_rank, (
        f"gold LOINC {GOLD_LOINC_AUTOMATED_COUNT} ranked {gold_rank}, still behind "
        f"SNOMED Procedure {SNOMED_PROCEDURE_PLATELET_COUNT} at {snomed_rank}; the "
        f"Measurement vocabulary preference is not reaching the ranking"
    )


@pytest.mark.parametrize("scale", [25.0, 0.04, 1000.0], ids=["25x", "0.04x", "1000x"])
def test_should_preserve_ranking_when_all_distances_are_multiplied(scale):
    """A change of embedding scale must not reorder candidates.

    Swapping the embedding model rescales every distance but does not change
    which concept is semantically closer, so the ranking must be invariant.
    Before dividing by the mean it was not: at 25x the constants vanish against
    the distances and the ranking collapses to raw vector order.

    Only multiplication is asserted. Dividing by the mean is deliberately *not*
    invariant to an additive offset: adding 100 to every distance really does
    mean every candidate is far away and none is meaningfully closer, and in that
    regime the vocabulary and class preferences should decide. No embedding model
    produces a pure offset anyway.
    """
    payload = _fixture()
    retriever = _retriever()

    baseline = _ranked_ids(retriever, payload)
    rescaled = _ranked_ids(retriever, payload, scale=scale)

    assert rescaled == baseline, (
        f"ranking changed when every distance was multiplied by {scale}; "
        f"preference constants are not scale-invariant"
    )


def test_should_use_one_scoring_implementation_for_search_and_batch_search():
    """`search` must not carry its own copy of the scoring block.

    The same duplication in `reranker.py` (`rerank_topn` vs `rerank_topn_batch`)
    already produced a green unit test over a prompt the pipeline never called.
    `search` feeds agent2's workflow; `batch_search` feeds tte_service.
    """
    payload = _fixture()
    ids, metadatas, distances, documents = _raw(payload)
    retriever = _retriever()

    class _StubCollection:
        def query(self, query_texts, n_results, include):
            return {
                "ids": [ids],
                "metadatas": [metadatas],
                "distances": [distances],
                "documents": [documents],
            }

    retriever.collection = _StubCollection()

    via_search = [
        c.concept_id
        for c in retriever.search(
            payload["query"], n_results=20, domain_hint=payload["domain_hint"]
        )
    ]
    via_scorer = _ranked_ids(retriever, payload, n=20)

    assert via_search == via_scorer
