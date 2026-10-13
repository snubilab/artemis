"""What the slow path does when the reranker rejects every candidate.

Before this, `_slow_path` inserted the retriever's #1 candidate unconditionally, so a
reranker that had just rejected all 20 candidates still produced a confident concept.
That is how the entry drug of two trials became the wrong molecule: the retriever
answered 'linagliptin' with sitagliptin (same DPP-4 class, adjacent in the embedding
space, and linagliptin itself absent from the top 20), the reranker correctly selected
nothing, and the force-include put sitagliptin back.

The measurement that motivated this is in
docs/experiments/2026-08-10_exact_vs_embedding_attribution.md.

A rejection is now final. The exact concept-name lookup that used to stand in for it
(`_exact_name_concept`, LOWER(concept_name) = LOWER(query)) read a concept name as text
to choose a concept, which AGENTS.md § PROMPTS AND TEXT RULES forbids; it was deleted
after it fired 0 times in 14 consults on the delivery candidate and 0 in 11 on P3 arm A
(output/site_gap/2026-10-12_p3_dry/analysis_a/textrule_removal/classC_evidence/d1.txt).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.agents.agent2.retriever import CandidateConcept
from src.agents.agent2.workflow import _seeds_after_rerank


def _c(concept_id: int, name: str, domain: str = "Drug") -> CandidateConcept:
    return CandidateConcept(
        concept_id=concept_id,
        concept_name=name,
        domain_id=domain,
        vocabulary_id="RxNorm",
        concept_class_id="Ingredient",
        distance=80.0,
    )


SITAGLIPTIN = _c(1235494, "sitagliptin 32.1 MG")
SAXAGLIPTIN = _c(855999, "saxagliptin 2.5 MG Oral Tablet by Sandoz")


class TestRerankerRejectedEverything:
    def test_should_return_no_seeds_when_reranker_rejects_all(self):
        assert _seeds_after_rerank([SITAGLIPTIN, SAXAGLIPTIN], []) == []

    def test_should_not_force_include_top1_when_reranker_rejects_all(self):
        """The regression this file exists for: rejecting all must not yield candidates[0]."""
        seeds = _seeds_after_rerank([SITAGLIPTIN, SAXAGLIPTIN], [])
        assert SITAGLIPTIN.concept_id not in {c.concept_id for c in seeds}


class TestRerankerSelectedSomething:
    """Unchanged behaviour: the force-include only ever protected a real selection."""

    def test_should_force_include_top1_when_reranker_selected_other_concepts(self):
        seeds = _seeds_after_rerank([SITAGLIPTIN, SAXAGLIPTIN], [SAXAGLIPTIN])
        assert [c.concept_id for c in seeds] == [1235494, 855999]

    def test_should_not_duplicate_top1_when_reranker_already_selected_it(self):
        seeds = _seeds_after_rerank([SITAGLIPTIN, SAXAGLIPTIN], [SITAGLIPTIN])
        assert [c.concept_id for c in seeds] == [1235494]


# ── the whole slow path, reranker answering "none" ───────────


QUERY = "chronic kidney disease"
#: A standard concept whose name is the query, as the vocabulary would hand it back.
NAMED_AS_THE_QUERY = (46271022, "Chronic kidney disease", "Condition", "SNOMED", "Clinical Finding")
CANDIDATES = [
    CandidateConcept(concept_id=cid, concept_name=f"c{cid}", domain_id="Condition",
                     vocabulary_id="SNOMED", concept_class_id="Clinical Finding", distance=0.4)
    for cid in (198185, 36716947)
]


class _SelectsNothing:
    """A reranker whose usable answer is that no candidate denotes the term."""

    def rerank_topn(self, *_args, **_kwargs):
        return []


def _vocabulary_answering_by_name():
    """A pool whose connection answers any query with one concept named as the query."""
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.__exit__.return_value = False
    cursor.fetchall.return_value = [NAMED_AS_THE_QUERY]
    conn = MagicMock()
    conn.cursor.return_value = cursor
    pool = MagicMock()
    pool.getconn.return_value = conn
    return pool


def _process(pool):
    from src.agents.agent2 import workflow as wf

    workflow = wf.Agent2Workflow()
    workflow._reranker = _SelectsNothing()
    with patch.object(wf, "expand_abbreviation", return_value=(QUERY, False)), \
            patch.object(wf, "expand_in_context", side_effect=lambda q: q), \
            patch.object(wf, "_get_db_pool", return_value=pool), \
            patch.object(wf.logician, "decompose_combination", side_effect=lambda cid: [cid]), \
            patch.object(wf.logician, "prune_empty_concepts", side_effect=lambda ids: ids), \
            patch.object(wf.logician, "drop_wrong_entity_class_for_condition",
                         side_effect=lambda ids: ids), \
            patch.object(wf.Agent2Workflow, "_kg_expand_and_critique",
                         side_effect=lambda ids, *a, **k: (ids, [], True)), \
            patch.object(wf, "get_kg_expander"):
        return workflow.process_with_details(
            QUERY, domain_hint="Condition", pre_fetched_candidates=list(CANDIDATES),
        )


def test_should_map_nothing_and_record_a_gap_when_the_reranker_selects_nothing():
    """Even when a standard concept carries the query as its name: the reranker's "none"
    stands, and the empty mapping is recorded on the result rather than replaced."""
    pool = _vocabulary_answering_by_name()

    result = _process(pool)

    assert result.concept_ids == [] and result.seed_concept_ids == []
    assert result.gap_report.mapped_count == 0
    assert [gap.reason for gap in result.gap_report.unmapped_items] == ["No OMOP mapping found"]
    assert [gap.original_text for gap in result.gap_report.unmapped_items] == [QUERY]
    # A judgment, not a failure: nothing is booked as a reranker failure.
    assert result.reranker_failure is None and result.mapping_failures() == []
    pool.getconn.assert_not_called()
