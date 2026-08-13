"""The recorded provenance of a mapped concept must not be fabricated.

Measured over output/circe_atc_fix: 6,950 of 6,961 recorded candidates carried
score exactly 0.0 and every single one carried source "rag". Neither was a
measurement. `_fetch_concept_candidates` re-hydrates candidates from the CDM by
id and constructed ConceptCandidate with 5 of its 7 fields, so `score` and
`source` fell to their Pydantic defaults -- 0.0 and "rag". One omission produced
both constants, and "rag" was positively false for every candidate that arrived
through KG or ATC expansion rather than through retrieval.

A relevance number does exist: the retriever computes `adjusted_score`
(retriever.py:295) and ranks by it. It was discarded at the agent2 boundary,
where MappingResult carries only a bare List[int].

These tests are DB-free and pin the recording rule, not the retrieval.
"""
from __future__ import annotations

import pytest

from src.agents.conceptset.rag_search import ConceptCandidate
from src.services.tte_service import build_mapping_candidate_items, mean_included_score


def cand(concept_id: int, name: str = "x") -> ConceptCandidate:
    return ConceptCandidate(
        concept_id=concept_id,
        concept_name=name,
        domain_id="Condition",
        vocabulary_id="SNOMED",
        concept_class_id="Clinical Finding",
    )


def test_should_flip_adjusted_score_so_a_closer_match_scores_higher():
    """adjusted_score is lower-is-better (retriever.py:295); the recorded field is not."""
    items = build_mapping_candidate_items(
        [cand(1, "near"), cand(2, "far")],
        {1: 0.60, 2: 0.90},
        selected_ids=[],
    )
    by_id = {i.conceptId: i.score for i in items}
    assert by_id[1] > by_id[2]


def test_should_record_none_when_the_candidate_never_reached_the_retriever():
    """KG/ATC-expanded concepts have no embedding distance. None, not 0.0 --
    0.0 is exactly the value the defect produced and must stay distinguishable."""
    items = build_mapping_candidate_items([cand(7)], {}, selected_ids=[])
    assert items[0].score is None


def test_should_not_claim_rag_for_a_candidate_that_did_not_come_from_rag():
    items = build_mapping_candidate_items(
        [cand(1), cand(2)], {1: 0.5}, selected_ids=[]
    )
    by_id = {i.conceptId: i.source for i in items}
    assert by_id[1] == "rag"
    assert by_id[2] == "expansion"


def test_should_mark_only_the_selected_candidates_as_included():
    items = build_mapping_candidate_items(
        [cand(1), cand(2)], {1: 0.5, 2: 0.5}, selected_ids=[2]
    )
    assert {i.conceptId: i.included for i in items} == {1: False, 2: True}


def test_should_report_no_confidence_when_no_included_candidate_was_scored():
    """The old code filtered `score > 0`, which was always empty, and then wrote
    0.0 from the else-branch -- a value indistinguishable from a real low score."""
    items = build_mapping_candidate_items([cand(1)], {}, selected_ids=[1])
    assert mean_included_score(items) is None


def test_should_average_only_the_included_scored_candidates():
    items = build_mapping_candidate_items(
        [cand(1), cand(2), cand(3)],
        {1: 0.0, 2: 1.0},
        selected_ids=[1, 2, 3],
    )
    # 1/(1+0.0) = 1.0 and 1/(1+1.0) = 0.5; concept 3 is unscored and excluded
    assert mean_included_score(items) == pytest.approx(0.75)


def test_should_keep_a_zero_adjusted_score_out_of_the_none_bucket():
    """A genuine adjusted_score of 0.0 is a perfect match, not a missing value.
    The old `score > 0` filter would have dropped it."""
    items = build_mapping_candidate_items([cand(1)], {1: 0.0}, selected_ids=[1])
    assert items[0].score == 1.0
    assert mean_included_score(items) == 1.0
