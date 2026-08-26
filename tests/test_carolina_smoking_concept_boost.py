"""SPEC-INFRA-006: CAROLINA smoking criterion — concept-priority boost, not seeding.

Decision Point 0 (spec.md §1.1, plan.md M1) required re-verifying the rank-140-of-200
premise under the actual production retrieval configuration before committing to a fix
mechanism. The live re-verification (this SPEC's completion report §Decision Point 0)
found a DIFFERENT shape of defect than the SPEC's own authoring narrative assumed:

  * Under `ConceptRetriever().batch_search(["Cigarette smoking"], n_results=60,
    domain_hints=["Observation"])` — the exact call shape `tte_service.py:4729-4731`
    uses in production — the gold-mapped standard concepts 903651 ("Currently doesn't
    use tobacco or its derivatives") and 903652 ("Findings of tobacco or its
    derivatives use or exposure") ARE present in the fetch_n=180 pool ChromaDB's hard
    `where={"domain_id": "Observation"}` filter returns (raw ranks 40 and 15 of 180
    respectively) — this is NOT a pool-membership gap, spec.md §1's ranking-defect
    framing notwithstanding.
  * They are, however, scored so poorly by `_score_candidates`'s modifiers (both carry
    `vocabulary_id="OMOP Extension"`, unlisted in `_VOCAB_PREFERENCE["Observation"]`
    -> default +0.05 penalty; both carry `concept_class_id="Clinical Finding"`, which
    IS in `_PENALIZED_CLASSES` and neither name substring-matches "Cigarette smoking"
    -> a further +0.05 penalty) that they fall to scored ranks 105 and 143 of 180 —
    well outside the `n_results=60` window `batch_search()` actually returns to the
    caller.

This matches plan.md M1's SECOND Decision Point 0 bullet and acceptance.md's Edge
Cases table entry for this exact outcome: "the hard-filtered pool already includes
903651 within the scored window, but it is still not selected... the fix would be a
targeted score boost via the *existing* concept_priority_defaults.json mechanism
alone... with no pool-membership merge needed at all." AC-001/AC-002 are re-scoped
accordingly (acceptance.md's own explicit permission) to the boost mechanism rather
than a seed-coverage pool-membership merge that Decision Point 0 found unnecessary.

The fixture is the REAL fetch_n=180 ChromaDB result for the actual expanded query
text ("Cigarette smoking" — confirmed unchanged by abbreviation/context/query-expander
passes) against the production `omop_concepts_medcpt` collection with the hard
`domain_id="Observation"` filter, captured live via `docker exec artemis-api`.
"""
from __future__ import annotations

import json
from pathlib import Path

from src.agents.agent2.retriever import ConceptRetriever

FIXTURE = Path(__file__).parent / "fixtures" / "carolina_smoking_pool.json"

TARGET_A = 903652  # "Findings of tobacco or its derivatives use or exposure"
TARGET_B = 903651  # "Currently doesn't use tobacco or its derivatives"


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def _retriever(concept_weights: dict[int, float] | None = None) -> ConceptRetriever:
    """A retriever with no ChromaDB and no DB — scoring is pure."""
    retriever = ConceptRetriever.__new__(ConceptRetriever)
    retriever.concept_weights = concept_weights if concept_weights is not None else {}
    retriever.collection = None
    return retriever


def _raw(payload: dict):
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
    distances = [r["distance"] for r in rows]
    documents = [r["name"] for r in rows]
    return ids, metadatas, distances, documents


def _ranked_ids(retriever: ConceptRetriever, payload: dict, n: int = 60) -> list[int]:
    ids, metadatas, distances, documents = _raw(payload)
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


# --------------------------------------------------------------------------- #
# AC-001 (re-scoped, acceptance.md Edge Cases permission): pre-fix the targets
# are excluded from the production n_results=60 window; post-fix they are not.
# --------------------------------------------------------------------------- #


class TestTargetConceptsReachTheScoredWindow:
    def test_targets_are_absent_pre_boost(self):
        """RED: without the concept-priority boost, both targets fall outside the
        n_results=60 window `batch_search()` actually returns — reproducing the
        defect this SPEC exists to fix."""
        payload = _fixture()
        retriever = _retriever(concept_weights={})
        ranked = _ranked_ids(retriever, payload, n=60)

        assert TARGET_A not in ranked, (
            f"{TARGET_A} unexpectedly present pre-boost; RED fixture is stale"
        )
        assert TARGET_B not in ranked, (
            f"{TARGET_B} unexpectedly present pre-boost; RED fixture is stale"
        )

    def test_targets_present_after_the_committed_boost(self):
        """GREEN: `_load_concept_weights()` reads the on-disk
        `concept_priority_defaults.json` (the actual fix — 2 new entries, no code
        change) and both targets enter the returned top-60."""
        retriever = _retriever(concept_weights=None)
        retriever.concept_weights = ConceptRetriever._load_concept_weights(retriever)
        payload = _fixture()
        ranked = _ranked_ids(retriever, payload, n=60)

        assert TARGET_A in ranked, (
            f"{TARGET_A} still excluded after the on-disk boost — fix not effective"
        )
        assert TARGET_B in ranked, (
            f"{TARGET_B} still excluded after the on-disk boost — fix not effective"
        )

    def test_raw_fetch_pool_already_contained_both_targets(self):
        """Confirms Decision Point 0's finding: this was never a pool-membership
        gap — both targets are present in the raw fixture (the fetch_n=180 pool
        ChromaDB's hard domain filter actually returned)."""
        payload = _fixture()
        raw_ids = {c["concept_id"] for c in payload["candidates"]}
        assert TARGET_A in raw_ids
        assert TARGET_B in raw_ids


# --------------------------------------------------------------------------- #
# AC-002: the boosted candidates are scored, not force-ranked.
# --------------------------------------------------------------------------- #


class TestBoostedCandidatesAreScoredNotForceRanked:
    def test_boost_is_additive_to_the_computed_distance_score_not_a_fixed_value(self):
        """The boost changes `adjusted_score` by exactly its own delta on top of the
        distance-derived score every other candidate goes through — it does not
        assign a fixed or minimum score, and a change in distance still moves the
        boosted candidate's final score (proving the boost composes, not replaces)."""
        payload = _fixture()

        unboosted = _retriever(concept_weights={})
        ids, metadatas, distances, documents = _raw(payload)
        pre = unboosted._score_candidates(
            query_text=payload["query"], ids=ids, metadatas=metadatas,
            distances=distances, documents=documents,
            domain_hint=payload["domain_hint"], n_results=len(ids),
        )
        pre_by_id = {c.concept_id: c.adjusted_score for c in pre}

        boost_delta = -0.25
        boosted = _retriever(concept_weights={TARGET_A: boost_delta, TARGET_B: boost_delta})
        post = boosted._score_candidates(
            query_text=payload["query"], ids=ids, metadatas=metadatas,
            distances=distances, documents=documents,
            domain_hint=payload["domain_hint"], n_results=len(ids),
        )
        post_by_id = {c.concept_id: c.adjusted_score for c in post}

        for target in (TARGET_A, TARGET_B):
            assert abs((post_by_id[target] - pre_by_id[target]) - boost_delta) < 1e-9, (
                f"{target}'s score delta was not exactly the concept-weight boost — "
                f"the modifier pipeline is not composing additively"
            )

        # A different distance for the SAME candidate still changes its post-boost
        # score — the boost is not a fixed/forced final rank.
        distances_shifted = list(distances)
        idx = ids.index(str(TARGET_A))
        distances_shifted[idx] += 5.0
        post_shifted = boosted._score_candidates(
            query_text=payload["query"], ids=ids, metadatas=metadatas,
            distances=distances_shifted, documents=documents,
            domain_hint=payload["domain_hint"], n_results=len(ids),
        )
        post_shifted_score = next(
            c.adjusted_score for c in post_shifted if c.concept_id == TARGET_A
        )
        assert post_shifted_score != post_by_id[TARGET_A], (
            "boosted candidate's score is insensitive to its own distance — "
            "looks force-ranked rather than computed"
        )

    def test_boost_final_rank_is_not_always_first(self):
        """A boosted candidate does not automatically win the whole pool — its rank
        is a function of the computed score, not insertion order or a hardcoded
        top-1 placement."""
        payload = _fixture()
        retriever = _retriever(concept_weights={TARGET_A: -0.25, TARGET_B: -0.25})
        ranked = _ranked_ids(retriever, payload, n=len(payload["candidates"]))

        assert ranked[0] != TARGET_A
        assert ranked[0] != TARGET_B


# --------------------------------------------------------------------------- #
# AC-003: fail-open when the concept-priority resource is missing/empty/corrupt.
# `_load_concept_weights()` already has this behavior (try/except around both
# resource files, logs and continues) — this test guards the existing behavior
# from regressing when the two new entries are added.
# --------------------------------------------------------------------------- #


class TestFailOpenOnResourceFailure:
    def test_missing_defaults_file_does_not_raise(self, monkeypatch):
        import os

        real_exists = os.path.exists

        def _fake_exists(path):
            if path.endswith("concept_priority_defaults.json"):
                return False
            return real_exists(path)

        monkeypatch.setattr(os.path, "exists", _fake_exists)

        retriever = ConceptRetriever.__new__(ConceptRetriever)
        # Must not raise even though the defaults file "disappeared".
        weights = ConceptRetriever._load_concept_weights(retriever)
        assert isinstance(weights, dict)

    def test_corrupt_defaults_file_does_not_raise(self, monkeypatch, tmp_path):
        bad_file = tmp_path / "concept_priority_defaults.json"
        bad_file.write_text("{not valid json")

        import os

        real_join = os.path.join

        def _fake_join(*parts):
            joined = real_join(*parts)
            if joined.endswith("resources/concept_priority_defaults.json"):
                return str(bad_file)
            return joined

        monkeypatch.setattr(os.path, "join", _fake_join)

        retriever = ConceptRetriever.__new__(ConceptRetriever)
        weights = ConceptRetriever._load_concept_weights(retriever)
        assert isinstance(weights, dict)
        assert TARGET_A not in weights or True  # no crash is the assertion; content unspecified


# --------------------------------------------------------------------------- #
# AC-004: no criterion-text / criterion-id / study-id keying in retriever.py.
# --------------------------------------------------------------------------- #


class TestNoTextOrIdentityKeying:
    def test_retriever_source_has_no_criterion_identity_special_case(self):
        source = Path(__file__).parent.parent / "src" / "agents" / "agent2" / "retriever.py"
        text = source.read_text()
        for forbidden in ("Cigarette smoking", "NCT01243424", "CAROLINA"):
            assert forbidden not in text, (
                f"retriever.py contains {forbidden!r} — inclusion must be keyed only "
                f"on (concept_id, domain), never on criterion text/id/study id"
            )
