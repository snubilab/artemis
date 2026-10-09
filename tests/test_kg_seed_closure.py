"""KG candidates reached through a parent must stay inside the seeds' own hierarchy.

A sibling is reached through a shared parent and an ancestor_climb candidate through
a climbed ancestor. Either is admitted only when that parent/ancestor is one of the
seeds or a descendant of one (the seed closure). Otherwise a seed's own parent drags
in every other child of it: the seeds of "Type 1 diabetes mellitus" pulled in the
other diabetes types and gestational diabetes through their parent "Diabetes mellitus".

The ids below are toy ids; the hierarchy is the only thing the rule reads.
"""

import hashlib
from unittest.mock import MagicMock, patch

import pytest

import src.agents.agent2.kg_expander as kge
from src.agents.agent2.kg_expander import KGConcept, KGExpander, admit_within_seed_closure

# Toy hierarchy (child -> parents):
#   1 (outside every seed)  <- 10 (seed)  <- 11 (seed)
#   10 <- 12 ; 1 <- 13 ; 1 <- 14
ANCESTORS = {10: {1}, 11: {10, 1}, 12: {10, 1}, 13: {1}, 14: {1}}


def _closure_members(candidate_ids, seed_ids):
    """Stand-in for concept_ancestor: ids that are a seed or a descendant of one."""
    seeds = set(seed_ids)
    return {c for c in candidate_ids if c in seeds or ANCESTORS.get(c, set()) & seeds}


def _concept(cid, relationship, via=None):
    return KGConcept(
        concept_id=cid,
        concept_name=f"c{cid}",
        domain_id="Condition",
        vocabulary_id="SNOMED",
        relationship=relationship,
        via_concept_id=via,
    )


@pytest.fixture(autouse=True)
def toy_closure(monkeypatch):
    monkeypatch.setattr(kge, "_seed_closure_members", _closure_members)


@pytest.fixture
def expander():
    exp = KGExpander.__new__(KGExpander)
    exp._driver = MagicMock()
    exp._use_cache = False
    exp._cache = {}
    import threading

    exp._cache_lock = threading.Lock()
    return exp


def test_should_drop_sibling_when_its_parent_is_outside_every_seed_closure():
    sib = _concept(13, "sibling (parent: c1)", via=1)

    kept = admit_within_seed_closure([sib], seed_ids=[10])

    assert kept == []


def test_should_keep_sibling_when_its_parent_is_a_seed():
    sib = _concept(12, "sibling (parent: c10)", via=10)

    kept = admit_within_seed_closure([sib], seed_ids=[10, 11])

    assert [c.concept_id for c in kept] == [12]


def test_should_keep_sibling_when_its_parent_descends_from_a_seed():
    sib = _concept(14, "sibling (parent: c11)", via=11)

    kept = admit_within_seed_closure([sib], seed_ids=[10])

    assert [c.concept_id for c in kept] == [14]


def test_should_drop_climbed_candidate_when_climbed_ancestor_is_outside_every_seed_closure():
    climbed = _concept(14, "ancestor_climb (via c1, IC=14.4)", via=1)

    kept = admit_within_seed_closure([climbed], seed_ids=[10, 11])

    assert kept == []


def test_should_keep_ancestor_and_maps_to_candidates_when_they_lie_outside_seed_closure():
    ancestor = _concept(1, "ancestor")
    mapped = _concept(99, "maps_to")

    kept = admit_within_seed_closure([ancestor, mapped], seed_ids=[10])

    assert [c.concept_id for c in kept] == [1, 99]


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
    fresh = _concept(13, "sibling (parent: c1)", via=1)

    with patch.object(expander, "get_ancestors", return_value=[]), \
         patch.object(expander, "get_siblings", return_value=[fresh]), \
         patch.object(expander, "get_maps_to", return_value=[]), \
         patch.object(expander, "ancestor_climb", return_value=[]):
        out = expander.expand(10, "clinical_anchor", 3, 50, "Condition")

    assert [(c.concept_id, c.via_concept_id) for c in out] == [(13, 1)]


def test_should_withhold_out_of_closure_candidates_from_critic_when_workflow_expands_seeds(
    expander, monkeypatch,
):
    from src.agents.agent2 import workflow as wf

    per_seed = {
        10: [_concept(13, "sibling (parent: c1)", via=1),
             _concept(14, "ancestor_climb (via c1, IC=14.4)", via=1),
             _concept(1, "ancestor")],
        11: [_concept(12, "sibling (parent: c10)", via=10)],
    }
    expander.expand = lambda sid, *a, **k: list(per_seed[sid])
    seen_by_critic = {}

    class _Critic:
        def evaluate(self, query, seed_concept_ids, kg_concepts, context, domain_hint):
            seen_by_critic["ids"] = sorted(c.concept_id for c in kg_concepts)
            return list(seed_concept_ids) + [c.concept_id for c in kg_concepts]

    monkeypatch.setenv("KG_EXPAND_MODE", "clinical_anchor")
    monkeypatch.setenv("ENABLE_REFINER", "0")
    monkeypatch.setattr(wf, "get_kg_expander", lambda: expander)
    monkeypatch.setattr(wf, "get_critic", lambda: _Critic())
    # Force the critic path (it is skipped at <= 10 candidates).
    filler = [_concept(1000 + i, "maps_to") for i in range(10)]
    per_seed[11].extend(filler)

    workflow = wf.Agent2Workflow.__new__(wf.Agent2Workflow)
    final_ids, _, _ = workflow._kg_expand_and_critique([10, 11], "q", None, "Condition")

    assert 13 not in seen_by_critic["ids"] and 14 not in seen_by_critic["ids"]
    assert {1, 12}.issubset(seen_by_critic["ids"])
    assert 13 not in final_ids and 14 not in final_ids
