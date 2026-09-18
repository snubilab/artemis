"""Regression tests: a KG-expanded ancestor must not displace the reranker's seed.

Measured defect (hospital delivery): a concept set named 'Type 1 diabetes
mellitus' shipped holding a single member ``4130526 'Disorder of glucose
metabolism'`` instead of the seed ``201254 'Type 1 diabetes mellitus'``.
``4130526`` has 180 descendants — including type 2 diabetes — so the absence
rule built on it covered 100% of the cohort's own T2DM entry event and the
cohort was 0 people on any CDM.

Mechanism, verified end to end against the live vocabulary (read-only):

1. the reranker selects ``201254`` — it is the seed;
2. ``KGExpander.get_ancestors(..., max_sep=2)`` adds ``4130526`` to the
   candidate list during ``_kg_expand_and_critique``;
3. ``ExpressionBuilder._filter_overbroad`` keeps ``4130526`` because 180
   descendants is under ``AGENT2_ROLLUP_MAX_DESCENDANTS`` (default 500);
4. ``ExpressionBuilder._roll_up`` then deletes ``201254`` because it is a
   descendant of another candidate.

The rule these tests pin: **a candidate that was not a seed may not displace a
seed** — when a non-seed candidate is a proper ancestor of a seed candidate,
the non-seed ancestor is dropped. Keeping both is not sufficient, because the
ancestor still pulls T2DM in through its descendants.

No live database and no LLM: ``get_db_session`` is patched throughout with a
fake vocabulary.
"""

from __future__ import annotations

from typing import Any, Iterable
from unittest.mock import patch

import pytest

from src.agents.conceptset.expression_builder import ExpressionBuilder
from src.agents.conceptset.rag_search import ConceptCandidate

# --- The real concepts from the shipped defect -----------------------------

T1DM = 201254            # 'Type 1 diabetes mellitus'  — the seed
GLUCOSE_DISORDER = 4130526  # 'Disorder of glucose metabolism' — the KG ancestor
ASTHMA = 317009          # an unrelated candidate, ancestor of nothing here

_NAMES = {
    T1DM: "Type 1 diabetes mellitus",
    GLUCOSE_DISORDER: "Disorder of glucose metabolism",
    ASTHMA: "Asthma",
}


def _candidate(concept_id: int) -> ConceptCandidate:
    return ConceptCandidate(
        concept_id=concept_id,
        concept_name=_NAMES[concept_id],
        domain_id="Condition",
        vocabulary_id="SNOMED",
        concept_class_id="Clinical Finding",
    )


class _Row:
    """A row object exposing the columns the builder reads by attribute."""

    def __init__(self, **columns: Any) -> None:
        for key, value in columns.items():
            setattr(self, key, value)


class _Result:
    def __init__(self, rows: Iterable[_Row]) -> None:
        self._rows = list(rows)

    def fetchall(self) -> list[_Row]:
        return self._rows


class _FakeDB:
    """Answers the builder's three/four queries from an in-memory vocabulary.

    ``ancestry`` is a set of (ancestor_concept_id, descendant_concept_id) pairs
    with min_levels_of_separation > 0. ``descendant_counts`` maps a concept to
    its total descendant count in the full vocabulary (not just among the
    candidates), which is what ``_filter_overbroad`` thresholds on.
    """

    def __init__(
        self,
        ancestry: set[tuple[int, int]],
        descendant_counts: dict[int, int],
        standard_ids: set[int],
    ) -> None:
        self.ancestry = ancestry
        self.descendant_counts = descendant_counts
        self.standard_ids = standard_ids

    def execute(self, statement: Any, params: dict[str, Any]) -> _Result:
        sql = str(statement)

        # _validate_standard_concepts
        if "standard_concept" in sql:
            return _Result(
                _Row(concept_id=cid)
                for cid in params["ids"]
                if cid in self.standard_ids
            )

        # _filter_overbroad
        if "HAVING" in sql:
            threshold = params["threshold"]
            return _Result(
                _Row(ancestor_concept_id=cid, desc_count=self.descendant_counts.get(cid, 0))
                for cid in params["ids"]
                if self.descendant_counts.get(cid, 0) > threshold
            )

        # the non-seed-ancestor guard
        if "ancestor_ids" in params:
            ancestors = {
                a
                for (a, d) in self.ancestry
                if a in set(params["ancestor_ids"]) and d in set(params["descendant_ids"])
            }
            return _Result(_Row(ancestor_concept_id=a) for a in sorted(ancestors))

        # _roll_up
        ids = set(params["ids"])
        return _Result(
            _Row(descendant_concept_id=d, ancestor_concept_id=a)
            for (a, d) in sorted(self.ancestry)
            if a in ids and d in ids
        )

    def close(self) -> None:  # pragma: no cover - contextmanager parity
        pass


def _patched_session(db: _FakeDB):
    """Patch the builder's session factory to yield ``db``."""
    from contextlib import contextmanager

    @contextmanager
    def _factory():
        yield db

    return patch(
        "src.agents.conceptset.expression_builder.get_db_session",
        _factory,
    )


@pytest.fixture
def diabetes_db() -> _FakeDB:
    """The real shape: 4130526 is an ancestor of 201254 and has 180 descendants."""
    return _FakeDB(
        ancestry={(GLUCOSE_DISORDER, T1DM)},
        descendant_counts={GLUCOSE_DISORDER: 180, T1DM: 12, ASTHMA: 40},
        standard_ids={T1DM, GLUCOSE_DISORDER, ASTHMA},
    )


def _concept_ids(recommendation) -> list[int]:
    return [item.concept_id for item in recommendation.expression.items]


def test_should_keep_the_seed_when_a_kg_ancestor_would_absorb_it(diabetes_db: _FakeDB) -> None:
    """The measured defect: 4130526 arrived via KG expansion and is not a seed."""
    builder = ExpressionBuilder(schema="cdm")
    candidates = [_candidate(T1DM), _candidate(GLUCOSE_DISORDER)]

    with _patched_session(diabetes_db):
        recommendation = builder.build_expression(
            candidates,
            roll_up=True,
            criterion_name="Type 1 diabetes mellitus",
            seed_concept_ids=[T1DM],
        )

    ids = _concept_ids(recommendation)
    assert T1DM in ids, "the reranker's seed must survive"
    assert GLUCOSE_DISORDER not in ids, (
        "a non-seed ancestor must not ride along — its 180 descendants include T2DM"
    )


def test_should_roll_up_normally_when_both_concepts_are_seeds(diabetes_db: _FakeDB) -> None:
    """A legitimate roll-up among seeds is unchanged: the ancestor absorbs the descendant."""
    builder = ExpressionBuilder(schema="cdm")
    candidates = [_candidate(T1DM), _candidate(GLUCOSE_DISORDER)]

    with _patched_session(diabetes_db):
        recommendation = builder.build_expression(
            candidates,
            roll_up=True,
            seed_concept_ids=[T1DM, GLUCOSE_DISORDER],
        )

    assert _concept_ids(recommendation) == [GLUCOSE_DISORDER]


def test_should_preserve_legacy_behaviour_when_no_seed_ids_are_supplied(
    diabetes_db: _FakeDB,
) -> None:
    """``seed_concept_ids=None`` must mean 'behave exactly as before the fix'."""
    builder = ExpressionBuilder(schema="cdm")
    candidates = [_candidate(T1DM), _candidate(GLUCOSE_DISORDER)]

    with _patched_session(diabetes_db):
        default_call = builder.build_expression(candidates, roll_up=True)
        explicit_none = builder.build_expression(
            candidates, roll_up=True, seed_concept_ids=None
        )

    assert _concept_ids(default_call) == [GLUCOSE_DISORDER]
    assert _concept_ids(explicit_none) == [GLUCOSE_DISORDER]


def test_should_leave_a_non_seed_alone_when_it_is_not_an_ancestor_of_any_seed() -> None:
    """A non-seed candidate unrelated to the seeds is untouched."""
    db = _FakeDB(
        ancestry=set(),
        descendant_counts={T1DM: 12, ASTHMA: 40},
        standard_ids={T1DM, ASTHMA},
    )
    builder = ExpressionBuilder(schema="cdm")
    candidates = [_candidate(T1DM), _candidate(ASTHMA)]

    with _patched_session(db):
        recommendation = builder.build_expression(
            candidates, roll_up=True, seed_concept_ids=[T1DM]
        )

    assert sorted(_concept_ids(recommendation)) == sorted([T1DM, ASTHMA])
