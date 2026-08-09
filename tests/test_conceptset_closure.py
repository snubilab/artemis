"""Unit tests for the Circe concept-set closure resolver.

All DB-free: every test drives ``PrefetchedVocabulary`` over hand-built raw
vocabulary facts. The semantics encoded here were verified against the SQL
that WebAPI ``/cohortdefinition/sql`` renders for a Circe expression:

    -- included branch
      select concept_id from CONCEPT where (concept_id in (<every non-excluded id>))
    UNION
      select c.concept_id from CONCEPT c
      join CONCEPT_ANCESTOR ca on c.concept_id = ca.descendant_concept_id
      WHERE c.invalid_reason is null
        and (ca.ancestor_concept_id in (<non-excluded ids with includeDescendants>))
    UNION                                            -- only when includeMapped is set
      select distinct cr.concept_id_1 as concept_id
      FROM ( <the same two branches restricted to the includeMapped subset> ) C
      join concept_relationship cr
        on C.concept_id = cr.concept_id_2
       and cr.relationship_id = 'Maps to'
       and cr.invalid_reason IS NULL
    ) I
    LEFT JOIN ( <the same three branches over the isExcluded items> ) E
      ON I.concept_id = E.concept_id
    WHERE E.concept_id is null

Note the asymmetry that the tests pin down: the direct branch has NO
``invalid_reason`` filter, the descendant branch does.
"""
from __future__ import annotations

import pytest

from src.services.conceptset_closure import (
    ConceptSetItem,
    PrefetchedVocabulary,
    raw_item_ids,
    resolve_concept_set,
)


def item(concept_id, *, descendants=False, mapped=False, excluded=False, name=""):
    """Build a Circe expression item the way Atlas serialises one."""
    return {
        "concept": {"CONCEPT_ID": concept_id, "CONCEPT_NAME": name},
        "includeDescendants": descendants,
        "includeMapped": mapped,
        "isExcluded": excluded,
    }


def concept_set(*items, name="cs", set_id=0):
    return {"id": set_id, "name": name, "expression": {"items": list(items)}}


def vocab(concepts, ancestors=None, maps_to=None):
    """concepts: {concept_id: invalid_reason}. Membership == exists in CONCEPT."""
    return PrefetchedVocabulary(
        concept_invalid_reason=dict(concepts),
        ancestor_edges={k: set(v) for k, v in (ancestors or {}).items()},
        maps_to_edges={k: set(v) for k, v in (maps_to or {}).items()},
    )


# --------------------------------------------------------------------------
# direct branch
# --------------------------------------------------------------------------

def test_should_keep_direct_item_when_concept_is_invalid():
    """Direct branch has no invalid_reason filter -- an invalid concept survives."""
    lookup = vocab({1: "D"})
    result = resolve_concept_set(concept_set(item(1)), lookup)
    assert result.concept_ids == {1}
    assert result.unresolvable_ids == set()


def test_should_drop_direct_item_when_concept_absent_from_vocabulary():
    """Circe's CONCEPT join silently drops ids the vocabulary does not have."""
    lookup = vocab({1: None})
    result = resolve_concept_set(concept_set(item(1), item(999)), lookup)
    assert result.concept_ids == {1}
    assert result.unresolvable_ids == {999}


# --------------------------------------------------------------------------
# descendant branch
# --------------------------------------------------------------------------

def test_should_drop_descendant_when_its_invalid_reason_is_set():
    lookup = vocab(
        {10: None, 11: None, 12: "D", 13: None},
        ancestors={10: {10, 11, 12, 13}},
    )
    result = resolve_concept_set(concept_set(item(10, descendants=True)), lookup)
    assert result.concept_ids == {10, 11, 13}


def test_should_keep_ancestor_when_it_is_invalid_and_include_descendants_is_set():
    """The ancestor is listed in BOTH branches, so the direct branch rescues it."""
    lookup = vocab({10: "D", 11: None}, ancestors={10: {10, 11}})
    result = resolve_concept_set(concept_set(item(10, descendants=True)), lookup)
    assert result.concept_ids == {10, 11}


def test_should_drop_descendant_when_it_is_absent_from_concept_table():
    lookup = vocab({10: None, 11: None}, ancestors={10: {10, 11, 404}})
    result = resolve_concept_set(concept_set(item(10, descendants=True)), lookup)
    assert result.concept_ids == {10, 11}


# --------------------------------------------------------------------------
# exclusion (anti-join)
# --------------------------------------------------------------------------

def test_should_subtract_concept_when_an_item_is_excluded():
    lookup = vocab({10: None, 11: None}, ancestors={10: {10, 11}})
    result = resolve_concept_set(
        concept_set(item(10, descendants=True), item(11, excluded=True)), lookup
    )
    assert result.concept_ids == {10}
    assert result.n_excluded_items == 1


def test_should_subtract_full_closure_when_excluded_item_includes_descendants():
    lookup = vocab(
        {1: None, 2: None, 3: None, 4: None},
        ancestors={1: {1, 2, 3, 4}, 3: {3, 4}},
    )
    result = resolve_concept_set(
        concept_set(item(1, descendants=True), item(3, descendants=True, excluded=True)),
        lookup,
    )
    assert result.concept_ids == {1, 2}


def test_should_keep_descendants_when_excluded_item_is_direct_only():
    lookup = vocab(
        {1: None, 2: None, 3: None, 4: None},
        ancestors={1: {1, 2, 3, 4}, 3: {3, 4}},
    )
    result = resolve_concept_set(
        concept_set(item(1, descendants=True), item(3, excluded=True)), lookup
    )
    assert result.concept_ids == {1, 2, 4}


# --------------------------------------------------------------------------
# includeMapped (third branch)
# --------------------------------------------------------------------------

def test_should_reverse_map_only_the_subset_when_one_item_sets_include_mapped():
    """The mapped sub-block wraps ONLY the includeMapped items, not their siblings."""
    lookup = vocab({1: None, 2: None}, maps_to={1: {101}, 2: {202}})
    result = resolve_concept_set(concept_set(item(1, mapped=True), item(2)), lookup)
    assert result.concept_ids == {1, 2, 101}
    assert 202 not in result.concept_ids


def test_should_reverse_map_descendants_when_include_mapped_item_also_includes_descendants():
    lookup = vocab(
        {1: None, 2: None},
        ancestors={1: {1, 2}},
        maps_to={2: {202}},
    )
    result = resolve_concept_set(
        concept_set(item(1, descendants=True, mapped=True)), lookup
    )
    assert result.concept_ids == {1, 2, 202}


def test_should_subtract_reverse_mapped_concept_when_excluded_item_sets_include_mapped():
    lookup = vocab({1: None, 2: None}, maps_to={2: {1}})
    result = resolve_concept_set(
        concept_set(item(1), item(2, mapped=True, excluded=True)), lookup
    )
    assert result.concept_ids == set()


def test_should_skip_mapped_branch_when_no_item_sets_include_mapped():
    lookup = vocab({1: None}, maps_to={1: {101}})
    result = resolve_concept_set(concept_set(item(1)), lookup)
    assert result.concept_ids == {1}


# --------------------------------------------------------------------------
# empty cases
# --------------------------------------------------------------------------

def test_should_return_empty_when_concept_set_has_no_items():
    result = resolve_concept_set(concept_set(), vocab({1: None}))
    assert result.concept_ids == set()
    assert result.n_items == 0


def test_should_return_empty_when_every_item_is_excluded():
    lookup = vocab({1: None, 2: None})
    result = resolve_concept_set(
        concept_set(item(1, excluded=True), item(2, excluded=True)), lookup
    )
    assert result.concept_ids == set()


def test_should_return_empty_when_lookup_knows_nothing():
    result = resolve_concept_set(concept_set(item(1, descendants=True)), vocab({}))
    assert result.concept_ids == set()
    assert result.unresolvable_ids == {1}


# --------------------------------------------------------------------------
# DB-free primitive
# --------------------------------------------------------------------------

def test_should_return_non_excluded_ids_when_reading_raw_items():
    cs = concept_set(item(1), item(2, descendants=True), item(3, excluded=True))
    assert raw_item_ids(cs) == {1, 2}


def test_should_ignore_item_when_it_has_no_concept_id():
    cs = {"expression": {"items": [{"concept": {}}, item(7)]}}
    assert raw_item_ids(cs) == {7}


# --------------------------------------------------------------------------
# item parsing
# --------------------------------------------------------------------------

def test_should_default_flags_to_false_when_circe_item_omits_them():
    parsed = ConceptSetItem.from_circe_item({"concept": {"CONCEPT_ID": "42"}})
    assert parsed == ConceptSetItem(42, False, False, False)


def test_should_raise_when_circe_item_has_no_concept_id():
    with pytest.raises(ValueError):
        ConceptSetItem.from_circe_item({"concept": {}})
