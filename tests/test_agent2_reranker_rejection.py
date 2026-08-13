"""What the slow path does when the reranker rejects every candidate.

Before this, `_slow_path` inserted the retriever's #1 candidate unconditionally, so a
reranker that had just rejected all 20 candidates still produced a confident concept.
That is how the entry drug of two trials became the wrong molecule: the retriever
answered 'linagliptin' with sitagliptin (same DPP-4 class, adjacent in the embedding
space, and linagliptin itself absent from the top 20), the reranker correctly selected
nothing, and the force-include put sitagliptin back.

The measurement that motivated this is in
docs/experiments/2026-08-10_exact_vs_embedding_attribution.md.
"""
from __future__ import annotations

import pytest

from src.agents.agent2.retriever import CandidateConcept
from src.agents.agent2.workflow import _exact_name_concept, _seeds_after_rerank


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
LINAGLIPTIN = _c(40239216, "linagliptin")


class TestRerankerRejectedEverything:
    def test_should_return_no_seeds_when_reranker_rejects_all_and_no_exact_name_match(self):
        assert _seeds_after_rerank([SITAGLIPTIN, SAXAGLIPTIN], [], None) == []

    def test_should_not_force_include_top1_when_reranker_rejects_all(self):
        """The regression this file exists for: rejecting all must not yield candidates[0]."""
        seeds = _seeds_after_rerank([SITAGLIPTIN, SAXAGLIPTIN], [], None)
        assert SITAGLIPTIN.concept_id not in {c.concept_id for c in seeds}

    def test_should_use_the_exact_name_match_when_reranker_rejects_all(self):
        seeds = _seeds_after_rerank([SITAGLIPTIN, SAXAGLIPTIN], [], LINAGLIPTIN)
        assert [c.concept_id for c in seeds] == [40239216]


class TestRerankerSelectedSomething:
    """Unchanged behaviour: the force-include only ever protected a real selection."""

    def test_should_force_include_top1_when_reranker_selected_other_concepts(self):
        seeds = _seeds_after_rerank([SITAGLIPTIN, SAXAGLIPTIN], [SAXAGLIPTIN], None)
        assert [c.concept_id for c in seeds] == [1235494, 855999]

    def test_should_not_duplicate_top1_when_reranker_already_selected_it(self):
        seeds = _seeds_after_rerank([SITAGLIPTIN, SAXAGLIPTIN], [SITAGLIPTIN], None)
        assert [c.concept_id for c in seeds] == [1235494]

    def test_should_ignore_the_exact_name_match_when_reranker_selected_something(self):
        """The exact lookup is a fallback for rejection, not an override of a judgment."""
        seeds = _seeds_after_rerank([SITAGLIPTIN], [SITAGLIPTIN], LINAGLIPTIN)
        assert [c.concept_id for c in seeds] == [1235494]


@pytest.mark.integration
class TestExactNameLookup:
    def test_should_resolve_linagliptin_that_the_embedding_path_missed(self):
        got = _exact_name_concept("linagliptin", "Drug")
        assert got is not None and got.concept_id == 40239216

    def test_should_be_case_insensitive(self):
        got = _exact_name_concept("Linagliptin", "Drug")
        assert got is not None and got.concept_id == 40239216

    def test_should_return_nothing_for_a_development_code(self):
        """`BI 10773` is not in the vocabulary at all — that one needs the alias path."""
        assert _exact_name_concept("BI 10773", "Drug") is None

    def test_should_return_nothing_when_the_name_is_ambiguous_without_a_domain(self):
        """'ticagrelor' is both a LOINC answer and an RxNorm ingredient. Two standard
        concepts share the name, so with no domain to separate them the lookup declines
        rather than guessing — the same rule the MeSH alias path uses."""
        assert _exact_name_concept("ticagrelor", None) is None

    def test_should_resolve_an_ambiguous_name_once_the_domain_narrows_it(self):
        got = _exact_name_concept("ticagrelor", "Drug")
        assert got is not None and got.concept_id == 40241186
