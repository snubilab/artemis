"""A subsuming seed must not drag in its own parent's other children.

A sibling is reached through a shared parent and an ancestor_climb candidate through
a climbed ancestor. When one seed of an expansion call is an ancestor of another seed
(it "subsumes" it), that seed is the broad end of the seed set, and its parent lies
above everything the seeds named: for "Type 1 diabetes mellitus" the seed 201254 is
the parent of the other seeds, and its parent "Diabetes mellitus" pulled in every other
diabetes type. A sibling/climb candidate is dropped when its parent/climbed ancestor lies
outside the closure of every seed AND is a proper ancestor of a subsuming seed —
whichever seed generated it (for "Type 2 diabetes mellitus" the non-subsuming seed
44793113 reached the same "Diabetes mellitus" siblings). A call with no subsuming seed
is left alone: there, siblings are how the right concept is reached (serum ALT through
a LOINC parent no seed covers).

The ids below are toy ids; the hierarchy is the only thing the rule reads.
"""

import hashlib
import threading
from unittest.mock import MagicMock, patch

import pytest

import src.agents.agent2.kg_expander as kge
from src.agents.agent2.kg_expander import KGConcept, KGExpander

# Toy hierarchy (child -> ancestors). 1, 2, 3 lie outside every seed set used below.
#   1 <- 10 <- 11 ; 10 <- 12 ; 1 <- 13 ; 1 <- 14
#   2 <- 20 ; 2 <- 21
#   3 <- 30 ; 3 <- 31
#   1 <- 40 ; 1 <- 41          (40: a seed beside 10, under the same outside parent 1)
ANCESTORS = {
    10: {1}, 11: {10, 1}, 12: {10, 1}, 13: {1}, 14: {1},
    20: {2}, 21: {2},
    30: {3}, 31: {3},
    40: {1}, 41: {1},
}


def _closure_members(candidate_ids, seed_ids):
    """Stand-in for concept_ancestor: ids that are a seed or a descendant of one."""
    seeds = set(seed_ids)
    return {c for c in candidate_ids if c in seeds or ANCESTORS.get(c, set()) & seeds}


def _subsuming_seeds(seed_ids):
    """Stand-in for concept_ancestor: seeds that are a proper ancestor of another seed."""
    seeds = set(seed_ids)
    return {s for s in seeds if any(s in ANCESTORS.get(t, set()) for t in seeds - {s})}


def _proper_ancestor_members(candidate_ids, of_ids):
    """Stand-in for concept_ancestor: candidates that are a proper ancestor of any of of_ids."""
    return {c for c in candidate_ids if any(c in ANCESTORS.get(o, set()) for o in of_ids)}


def _concept(cid, relationship, via=None):
    return KGConcept(
        concept_id=cid,
        concept_name=f"c{cid}",
        domain_id="Condition",
        vocabulary_id="SNOMED",
        relationship=relationship,
        via_concept_id=via,
    )


def _sib(cid, parent):
    return _concept(cid, f"sibling (parent: c{parent})", via=parent)


def _climb(cid, ancestor):
    return _concept(cid, f"ancestor_climb (via c{ancestor}, IC=14.4)", via=ancestor)


# 'Has due to' (cause) of a concept, toy ids. 50 is "complication due to 1" (1 sits above the
# subsuming seed 10), the parent of seed 51; 52 is due to 1 as well, 53 is due to the seed 10;
# 60 is "sequela of 10", due to the seed itself.
DUE_TO = {50: {1}, 51: {10}, 52: {1}, 53: {10}, 60: {10}}
ANCESTORS.update({51: {50}, 52: {50}, 53: {50}, 61: {60}, 62: {60}})


def _due_to_targets(concept_ids):
    """Stand-in for concept_relationship 'Has due to'."""
    return {c: DUE_TO[c] for c in concept_ids if c in DUE_TO}


@pytest.fixture(autouse=True)
def toy_vocabulary(monkeypatch):
    monkeypatch.setattr(kge, "_due_to_targets", _due_to_targets, raising=False)
    monkeypatch.setattr(kge, "_seed_closure_members", _closure_members)
    monkeypatch.setattr(kge, "_subsuming_seeds", _subsuming_seeds, raising=False)
    monkeypatch.setattr(kge, "_proper_ancestor_members", _proper_ancestor_members, raising=False)


@pytest.fixture
def expander():
    exp = KGExpander.__new__(KGExpander)
    exp._driver = MagicMock()
    exp._use_cache = False
    exp._cache = {}
    exp._cache_lock = threading.Lock()
    return exp


def _expand_through_workflow(monkeypatch, per_seed, seeds):
    """Run the real _kg_expand_and_critique with a stub expander; critic path not reached.

    Every scenario stays at <= 10 candidates, so the critic is skipped and, with the
    refiner off, the returned ids are seeds + every admitted candidate.
    """
    from src.agents.agent2 import workflow as wf

    stub = MagicMock()
    stub.expand.side_effect = lambda sid, *a, **k: list(per_seed.get(sid, []))
    monkeypatch.setenv("KG_EXPAND_MODE", "clinical_anchor")
    monkeypatch.setenv("ENABLE_REFINER", "0")
    monkeypatch.setattr(wf, "get_kg_expander", lambda: stub)
    workflow = wf.Agent2Workflow.__new__(wf.Agent2Workflow)
    final_ids, _, _ = workflow._kg_expand_and_critique(seeds, "q", None, "Condition")
    return final_ids


def test_should_drop_subsuming_seed_siblings_and_climbs_when_parent_is_outside_every_closure(
    monkeypatch,
):
    # T1D shape: seed 10 is the parent of seed 11; 10's parent 1 is outside both.
    per_seed = {
        11: [_sib(12, 10)],
        10: [_sib(13, 1), _climb(14, 1), _concept(1, "ancestor")],
    }

    final_ids = _expand_through_workflow(monkeypatch, per_seed, [11, 10])

    assert 13 not in final_ids and 14 not in final_ids
    assert {12, 1}.issubset(final_ids)


def test_should_drop_siblings_of_a_non_subsuming_seed_when_their_parent_is_above_a_subsuming_seed(
    monkeypatch,
):
    # T2DM shape: 10 subsumes 11; seed 40 subsumes nothing, but its parent 1 is the parent
    # of the subsuming seed 10 and outside every seed's closure.
    per_seed = {11: [], 10: [], 40: [_sib(41, 1)]}

    final_ids = _expand_through_workflow(monkeypatch, per_seed, [11, 10, 40])

    assert 41 not in final_ids


def test_should_keep_out_of_closure_siblings_when_no_seed_subsumes_another(monkeypatch):
    # Serum-ALT shape: unrelated seeds, each sibling reached through a parent no seed covers.
    per_seed = {10: [_sib(13, 1)], 20: [_sib(21, 2)]}

    final_ids = _expand_through_workflow(monkeypatch, per_seed, [10, 20])

    assert {13, 21}.issubset(final_ids)


def test_should_keep_siblings_of_a_non_subsuming_seed_when_another_seed_is_subsuming(monkeypatch):
    # 10 subsumes 11; 30 subsumes nothing, so its out-of-closure sibling 31 stays.
    per_seed = {11: [], 10: [_sib(13, 1)], 30: [_sib(31, 3)]}

    final_ids = _expand_through_workflow(monkeypatch, per_seed, [11, 10, 30])

    assert 31 in final_ids
    assert 13 not in final_ids


def test_should_drop_siblings_reached_through_a_parent_due_to_a_concept_above_a_subsuming_seed(
    monkeypatch,
):
    # T1D in the live vocabulary: seed 435216 'Disorder due to T1DM' (51) has only the parent
    # 442793 'Complication due to diabetes mellitus' (50), which is due to 'Diabetes mellitus'
    # (1), above the subsuming seed 201254 (10). Its other children are complications of any
    # diabetes: 'Diabetic foot ulcer' (52). One due to the seed itself (53) stays.
    per_seed = {11: [], 10: [], 51: [_sib(52, 50), _sib(53, 50)]}

    final_ids = _expand_through_workflow(monkeypatch, per_seed, [11, 10, 51])

    assert 52 not in final_ids
    assert 53 in final_ids


def test_should_keep_siblings_reached_through_a_parent_due_to_a_seed(monkeypatch):
    # Stroke shape: 'Sequela of cerebrovascular accident' (60) is due to the subsuming seed
    # itself, so its children (late effects of stroke) are what the seeds named.
    per_seed = {11: [], 10: [], 61: [_sib(62, 60)]}

    final_ids = _expand_through_workflow(monkeypatch, per_seed, [11, 10, 61])

    assert 62 in final_ids


def _neo4j_result(records):
    session = MagicMock()
    result = MagicMock()
    result.__iter__.return_value = records
    session.run.return_value = result
    return session


def test_should_record_parent_id_when_get_siblings_returns_a_sibling(expander):
    record = {
        "cid": "13", "name": "c13", "domain": "Condition", "vocab": "SNOMED",
        "cclass": "Disorder", "parent_name": "c1", "parent_id": "1",
    }
    expander._driver.session.return_value.__enter__.return_value = _neo4j_result([record])

    sibs = expander.get_siblings(10, "Condition")

    assert [(c.concept_id, c.via_concept_id) for c in sibs] == [(13, 1)]


def test_should_record_climbed_ancestor_id_when_ancestor_climb_returns_a_candidate(expander):
    ancestor = {"cid": "1", "name": "c1", "domain": "Condition", "vocab": "SNOMED",
                "cclass": "Disorder", "sep": 1}
    descendant = {"cid": "14", "name": "c14", "domain": "Condition", "vocab": "SNOMED",
                  "cclass": "Disorder"}
    session = MagicMock()
    up, down = MagicMock(), MagicMock()
    up.__iter__.return_value = [ancestor]
    down.__iter__.return_value = [descendant]
    session.run.side_effect = [up, down]
    expander._driver.session.return_value.__enter__.return_value = session

    with patch.object(expander, "_get_pg_descendant_counts", return_value={1: 200, 10: 100}):
        climbed = expander.ancestor_climb(10, domain_filter="Condition", limit=40)

    assert [(c.concept_id, c.via_concept_id) for c in climbed] == [(14, 1)]


def test_should_recompute_expansion_when_cache_entry_predates_parent_ids(expander):
    """An entry cached before parent ids were recorded cannot be filtered, so it must miss."""
    old_key = hashlib.sha256(b"10|clinical_anchor|3|50|Condition").hexdigest()[:16]
    stale = {"concept_id": 13, "concept_name": "c13", "domain_id": "Condition",
             "vocabulary_id": "SNOMED", "relationship": "sibling (parent: c1)"}
    expander._use_cache = True
    expander._cache = {old_key: [stale]}
    fresh = _sib(13, 1)

    with patch.object(expander, "get_ancestors", return_value=[]), \
         patch.object(expander, "get_siblings", return_value=[fresh]), \
         patch.object(expander, "get_maps_to", return_value=[]), \
         patch.object(expander, "ancestor_climb", return_value=[]):
        out = expander.expand(10, "clinical_anchor", 3, 50, "Condition")

    assert [(c.concept_id, c.via_concept_id) for c in out] == [(13, 1)]
