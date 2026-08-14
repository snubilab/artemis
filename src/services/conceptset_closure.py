"""Resolve a Circe concept set to its concept closure, exactly as Circe does.

Why this lives in ``src/services`` rather than inside a script: two entrypoints
consume it (``scripts/conceptset_overlap_eval.py`` for closure-level overlap and
``scripts/compare_gold_vs_generated_circe.py`` for the DB-free raw-item view),
and the required unit tests drive it against a stubbed vocabulary, which needs an
importable module. Keeping one authoritative definition here is what stops the
"what is a resolved concept set" decision from being retyped per consumer.

GROUND TRUTH. The expansion below mirrors the SQL that WebAPI renders for a
Circe expression (POST ``/cohortdefinition/sql``), verbatim shape:

    -- included side
      select concept_id from CONCEPT where (concept_id in (<all non-excluded ids>))
    UNION
      select c.concept_id from CONCEPT c
      join CONCEPT_ANCESTOR ca on c.concept_id = ca.descendant_concept_id
      WHERE c.invalid_reason is null
        and (ca.ancestor_concept_id in (<non-excluded ids with includeDescendants>))
    UNION                                      -- rendered only when includeMapped is set
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

Three things are easy to get wrong and are pinned by tests:

1. The direct branch has NO ``invalid_reason`` filter; the descendant branch has
   one. An invalid concept listed directly still resolves.
2. An id carrying ``includeDescendants`` appears in BOTH branches, so the
   ancestor itself is always retained.
3. ``includeMapped`` renders a THIRD branch whose inner sub-block covers only the
   includeMapped subset -- not its non-mapped siblings.

Concept ids absent from CONCEPT are dropped by Circe's join without any error.
``ClosureResult.unresolvable_ids`` surfaces them; they are "dropped by Circe,
matching WebAPI", not a resolver failure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Iterator, Protocol, Sequence

# Vocabulary tables are identical in every CDM schema on this host (verified:
# 6,328,777 concepts / 75,689,500 ancestor rows in each). Default to the
# standalone vocabulary schema so closure evaluation carries no dependency on a
# trial CDM -- depending on one would re-introduce exactly what the evaluation
# rule exists to remove.
DEFAULT_VOCAB_SCHEMA = "omop_vocab"

_MISSING = object()


@dataclass(frozen=True)
class ConceptSetItem:
    """One row of a Circe ``expression.items`` array."""

    concept_id: int
    include_descendants: bool = False
    include_mapped: bool = False
    is_excluded: bool = False

    @classmethod
    def from_circe_item(cls, item: dict) -> "ConceptSetItem":
        concept_id = (item.get("concept") or {}).get("CONCEPT_ID")
        if concept_id is None:
            raise ValueError(f"concept set item has no CONCEPT_ID: {item!r}")
        return cls(
            concept_id=int(concept_id),
            include_descendants=bool(item.get("includeDescendants")),
            include_mapped=bool(item.get("includeMapped")),
            is_excluded=bool(item.get("isExcluded")),
        )


class VocabularyLookup(Protocol):
    """Batch-oriented vocabulary access. Deliberately free of any DB import."""

    def existing_concept_ids(self, concept_ids: Iterable[int]) -> set[int]:
        """Ids present in CONCEPT. No ``invalid_reason`` filter (direct branch)."""

    def descendants_of(self, ancestor_ids: Iterable[int]) -> set[int]:
        """Descendants via CONCEPT_ANCESTOR, restricted to ``invalid_reason IS NULL``."""

    def maps_to_sources(self, concept_ids: Iterable[int]) -> set[int]:
        """``concept_id_1`` of valid ``Maps to`` rows whose ``concept_id_2`` is given."""

    def standard_replacements(self, concept_ids: Iterable[int]) -> dict[int, set[int]]:
        """Deprecated id -> the standard concepts it forwards to.

        Not part of Circe. Circe resolves a retired concept to itself and stops, which is
        correct for running a cohort and wrong for COMPARING two concept sets authored
        against different vocabulary releases: a gold set built entirely from retired
        concepts shares nothing with any set built from current ones, whatever either
        says clinically. Consumers that compare must forward BOTH sides; consumers that
        reproduce WebAPI must not call this at all.

        Only ids with a non-null ``invalid_reason`` are forwarded, and only through valid
        ``Maps to`` / ``Concept replaced by`` edges landing on a standard concept.
        """


@dataclass
class PrefetchedVocabulary:
    """Pure-Python :class:`VocabularyLookup` over raw vocabulary facts.

    ``concept_invalid_reason`` maps concept_id -> invalid_reason; membership in
    the mapping IS existence in CONCEPT, and a ``None`` value means valid.
    ``ancestor_edges`` holds unfiltered CONCEPT_ANCESTOR rows; the validity
    filter is applied here so there is a single implementation of it.
    """

    concept_invalid_reason: dict[int, str | None] = field(default_factory=dict)
    ancestor_edges: dict[int, set[int]] = field(default_factory=dict)
    maps_to_edges: dict[int, set[int]] = field(default_factory=dict)
    replacement_edges: dict[int, set[int]] = field(default_factory=dict)

    def existing_concept_ids(self, concept_ids: Iterable[int]) -> set[int]:
        return {cid for cid in concept_ids if cid in self.concept_invalid_reason}

    def descendants_of(self, ancestor_ids: Iterable[int]) -> set[int]:
        out: set[int] = set()
        for ancestor in ancestor_ids:
            for descendant in self.ancestor_edges.get(ancestor, ()):
                if self.concept_invalid_reason.get(descendant, _MISSING) is None:
                    out.add(descendant)
        return out

    def maps_to_sources(self, concept_ids: Iterable[int]) -> set[int]:
        out: set[int] = set()
        for cid in concept_ids:
            out |= self.maps_to_edges.get(cid, set())
        return out

    def standard_replacements(self, concept_ids: Iterable[int]) -> dict[int, set[int]]:
        out: dict[int, set[int]] = {}
        for cid in concept_ids:
            # A concept absent from CONCEPT is not "valid"; it is unresolvable, and
            # `.get(cid)` returning None for it would silently exempt it from forwarding.
            if self.concept_invalid_reason.get(cid, _MISSING) is None:
                continue
            targets = self.replacement_edges.get(cid)
            if targets:
                out[cid] = set(targets)
        return out


@dataclass
class ClosureResult:
    concept_ids: set[int]
    unresolvable_ids: set[int]
    n_items: int
    n_excluded_items: int


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------

def iter_items(concept_set: dict) -> Iterator[ConceptSetItem]:
    """Parse a concept set's items, skipping malformed rows without a CONCEPT_ID."""
    for raw in (concept_set.get("expression") or {}).get("items") or []:
        try:
            yield ConceptSetItem.from_circe_item(raw)
        except ValueError:
            continue


def raw_item_ids(concept_set: dict) -> set[int]:
    """Non-excluded item ids as listed -- the DB-free primitive.

    This is the single definition of "raw item" shared by both entrypoints.
    """
    return {i.concept_id for i in iter_items(concept_set) if not i.is_excluded}


def all_item_ids(concept_set: dict) -> set[int]:
    return {i.concept_id for i in iter_items(concept_set)}


# --------------------------------------------------------------------------
# expansion
# --------------------------------------------------------------------------

def expand_items(items: Sequence[ConceptSetItem], lookup: VocabularyLookup) -> set[int]:
    """Expand one side (included or excluded) of a concept set.

    Mirrors the UNION of the direct, descendant and (optional) mapped branches.
    """
    items = list(items)
    if not items:
        return set()

    resolved = lookup.existing_concept_ids(i.concept_id for i in items)

    descendant_ancestors = [i.concept_id for i in items if i.include_descendants]
    if descendant_ancestors:
        resolved |= lookup.descendants_of(descendant_ancestors)

    mapped_subset = [i for i in items if i.include_mapped]
    if mapped_subset:
        # The rendered SQL wraps only the includeMapped items in the inner
        # sub-block, with their own direct + descendant branches.
        inner = expand_items(
            [
                ConceptSetItem(
                    concept_id=i.concept_id,
                    include_descendants=i.include_descendants,
                    include_mapped=False,
                    is_excluded=i.is_excluded,
                )
                for i in mapped_subset
            ],
            lookup,
        )
        resolved |= lookup.maps_to_sources(inner)

    return resolved


def resolve_concept_set(concept_set: dict, lookup: VocabularyLookup) -> ClosureResult:
    """Resolve a Circe concept set to its concept closure."""
    items = list(iter_items(concept_set))
    included = [i for i in items if not i.is_excluded]
    excluded = [i for i in items if i.is_excluded]

    concept_ids = expand_items(included, lookup) - expand_items(excluded, lookup)

    referenced = {i.concept_id for i in items}
    unresolvable = referenced - lookup.existing_concept_ids(referenced)

    return ClosureResult(
        concept_ids=concept_ids,
        unresolvable_ids=unresolvable,
        n_items=len(items),
        n_excluded_items=len(excluded),
    )


def concept_set_name(concept_set: dict) -> str:
    return str(concept_set.get("name") or f"ConceptSet {concept_set.get('id')}")


def iter_concept_sets(cohort: dict) -> Iterator[dict]:
    for cs in cohort.get("ConceptSets") or []:
        yield cs


# --------------------------------------------------------------------------
# Postgres-backed prefetch
# --------------------------------------------------------------------------

class PostgresVocabulary:
    """Builds a :class:`PrefetchedVocabulary` with three batched queries.

    Per-concept-set querying was measured at 29m19s for the six trials; this
    batched form takes ~5s and produces byte-identical closures. ``psycopg2`` is
    imported inside ``__init__`` so that importing this module (and therefore
    ``python -m src.boot_check``) never needs a database driver.
    """

    def __init__(self, dsn: str, schema: str = DEFAULT_VOCAB_SCHEMA) -> None:
        import psycopg2  # noqa: PLC0415 -- deliberately lazy; see docstring

        self.dsn = dsn
        self.schema = schema
        self._conn = psycopg2.connect(dsn)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "PostgresVocabulary":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def prefetch(self, items: Iterable[ConceptSetItem]) -> PrefetchedVocabulary:
        items = list(items)
        all_ids = sorted({i.concept_id for i in items})
        descendant_ancestors = sorted({i.concept_id for i in items if i.include_descendants})

        concept_invalid: dict[int, str | None] = {}
        ancestor_edges: dict[int, set[int]] = {}
        maps_to_edges: dict[int, set[int]] = {}

        cur = self._conn.cursor()

        if all_ids:
            cur.execute(
                f"SELECT concept_id, invalid_reason FROM {self.schema}.concept "
                f"WHERE concept_id = ANY(%s)",
                (all_ids,),
            )
            for cid, invalid in cur.fetchall():
                concept_invalid[cid] = invalid

        if descendant_ancestors:
            cur.execute(
                f"SELECT ca.ancestor_concept_id, ca.descendant_concept_id, c.invalid_reason "
                f"FROM {self.schema}.concept_ancestor ca "
                f"JOIN {self.schema}.concept c ON c.concept_id = ca.descendant_concept_id "
                f"WHERE ca.ancestor_concept_id = ANY(%s)",
                (descendant_ancestors,),
            )
            for ancestor, descendant, invalid in cur.fetchall():
                ancestor_edges.setdefault(ancestor, set()).add(descendant)
                concept_invalid[descendant] = invalid

        mapped_items = [i for i in items if i.include_mapped]
        if mapped_items:
            partial = PrefetchedVocabulary(concept_invalid, ancestor_edges, {})
            mapped_closure = sorted(
                expand_items(
                    [
                        ConceptSetItem(i.concept_id, i.include_descendants, False, i.is_excluded)
                        for i in mapped_items
                    ],
                    partial,
                )
            )
            if mapped_closure:
                cur.execute(
                    f"SELECT cr.concept_id_2, cr.concept_id_1 "
                    f"FROM {self.schema}.concept_relationship cr "
                    f"WHERE cr.relationship_id = 'Maps to' "
                    f"AND cr.invalid_reason IS NULL "
                    f"AND cr.concept_id_2 = ANY(%s)",
                    (mapped_closure,),
                )
                for target, source in cur.fetchall():
                    maps_to_edges.setdefault(target, set()).add(source)

        # Forwarding targets for the retired ids. Only DIRECT items can be retired: the
        # descendant branch filters on `invalid_reason IS NULL`, so every id a closure
        # gains from CONCEPT_ANCESTOR is already valid. That bounds this to `all_ids` and
        # keeps it one small query rather than a pass over a 100k-concept closure.
        retired = sorted(cid for cid in all_ids if concept_invalid.get(cid) is not None)
        replacement_edges: dict[int, set[int]] = {}
        if retired:
            cur.execute(
                f"SELECT cr.concept_id_1, cr.concept_id_2 "
                f"FROM {self.schema}.concept_relationship cr "
                f"JOIN {self.schema}.concept t ON t.concept_id = cr.concept_id_2 "
                f"WHERE cr.relationship_id IN ('Maps to', 'Concept replaced by') "
                f"AND cr.invalid_reason IS NULL "
                f"AND t.standard_concept = 'S' "
                f"AND t.invalid_reason IS NULL "
                f"AND cr.concept_id_1 = ANY(%s)",
                (retired,),
            )
            for source, target in cur.fetchall():
                replacement_edges.setdefault(source, set()).add(target)

        cur.close()
        return PrefetchedVocabulary(
            concept_invalid, ancestor_edges, maps_to_edges, replacement_edges
        )


def items_of_cohort(cohort: dict) -> list[ConceptSetItem]:
    """Every concept set item in a Circe cohort definition."""
    out: list[ConceptSetItem] = []
    for cs in iter_concept_sets(cohort):
        out.extend(iter_items(cs))
    return out
