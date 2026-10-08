"""Build the ATC drug-class index with names borrowed from SNOMED's substance classes.

`scripts/populate_chromadb.py` indexes each ATC 1st-4th level class under its bare
ATC name. ATC names are terse and route-shaped ("Dipeptidyl peptidase 4 (DPP-4)
inhibitors", "Platelet aggregation inhibitors excl. heparin"), so protocol wording
that names the same class differently ("DPP-IV inhibitors", "antiplatelet agents")
lands far from it. This script writes a second collection in which an ATC class with an
equivalent SNOMED substance class gets a second document: its ATC name followed by the
names of the SNOMED classes that hold the same ingredients. The bare ATC name stays
indexed as the first document, unchanged, so no class can end up further from a query
than in the old collection: measured 2026-10-08, replacing A10A's document with
"INSULINS AND ANALOGUES; Insulin; Pancreatic hormone" moved the query "insulin" from
0.453 to 0.611, behind A10AE (long-acting) at 0.597. The expander merges hits on one
class, so a class is as close as its closer document.

Equivalence is decided by ingredient sets, never by text:

- ATC side: the RxNorm ingredients under the class, minus combination partners (an
  ingredient that is never on its own under the class but is on its own elsewhere --
  the same rule `drug_class_expander.class_ingredients` applies at query time).
- SNOMED side: a valid SNOMED Substance concept that maps to no ingredient itself (a
  class, not a substance), with the ingredients its 'Is a' descendants map to.
- The two are equivalent when their Jaccard overlap, counted over ingredients SNOMED's
  substance hierarchy can express at all, is at least ``--tau`` (0.7). Each SNOMED class
  goes to the ATC class(es) it overlaps best, so a name is never spread over a parent
  and its children unless their sets are identical.

The existing collection is never touched. Production reads the collection named by
AGENT2_ATC_COLLECTION (default ``atc_drug_classes``), so building this changes nothing
until that variable is set.

Usage:
    python scripts/build_atc_class_index.py --dry-run          # print the equivalents
    python scripts/build_atc_class_index.py                    # write atc_drug_classes_v2
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_COLLECTION = "atc_drug_classes_v2"
DEFAULT_TAU = 0.7
_SEPARATOR = "; "


def equivalent_names(
    atc_sets: dict[int, set[int]],
    snomed_sets: dict[int, set[int]],
    snomed_names: dict[int, str],
    tau: float = DEFAULT_TAU,
) -> dict[int, list[str]]:
    """Pair ATC classes with SNOMED classes that hold the same ingredients.

    :param atc_sets: ATC class concept_id -> its ingredient concept_ids.
    :param snomed_sets: SNOMED class concept_id -> ingredient concept_ids of its descendants.
    :param snomed_names: SNOMED class concept_id -> concept_name.
    :param tau: minimum Jaccard overlap for two sets to count as the same class.
    :returns: ATC class concept_id -> SNOMED names, closest overlap first.
    """
    expressible = set().union(*snomed_sets.values()) if snomed_sets else set()
    holders: dict[int, set[int]] = collections.defaultdict(set)
    for node, ingredients in snomed_sets.items():
        for ingredient in ingredients:
            holders[ingredient].add(node)

    overlaps: dict[int, list[tuple[float, int]]] = collections.defaultdict(list)
    for atc_id, ingredients in atc_sets.items():
        comparable = ingredients & expressible
        if len(comparable) < 2:
            continue
        for node in set().union(*(holders[i] for i in comparable)):
            other = snomed_sets[node]
            jaccard = len(comparable & other) / len(comparable | other)
            if jaccard >= tau:
                overlaps[node].append((jaccard, atc_id))

    paired: dict[int, list[tuple[float, str]]] = collections.defaultdict(list)
    for node, found in overlaps.items():
        best = max(j for j, _ in found)
        for jaccard, atc_id in found:
            if jaccard == best:
                paired[atc_id].append((jaccard, snomed_names[node]))
    return {
        atc_id: [n for _, n in sorted(names, key=lambda x: (-x[0], x[1]))]
        for atc_id, names in paired.items()
    }


def document_text(atc_name: str, equivalents: list[str]) -> str:
    """The indexed text for one ATC class: its own name, then the borrowed ones.

    :param atc_name: the ATC concept_name.
    :param equivalents: SNOMED class names judged equivalent, possibly empty.
    :returns: the document string; the bare ATC name when nothing is equivalent.
    """
    extra = [n for n in equivalents if n.casefold() != atc_name.casefold()]
    return _SEPARATOR.join([atc_name, *extra])


def documents_for(concept_id: int, atc_name: str, equivalents: list[str]) -> list[tuple[str, str]]:
    """The (id, document) pairs indexed for one ATC class.

    :param concept_id: the ATC concept_id.
    :param atc_name: the ATC concept_name.
    :param equivalents: SNOMED class names judged equivalent, possibly empty.
    :returns: the bare name under the concept_id, plus the enriched text under
        ``<concept_id>+`` when there is anything to add.
    """
    docs = [(str(concept_id), atc_name)]
    enriched = document_text(atc_name, equivalents)
    if enriched != atc_name:
        docs.append((f"{concept_id}+", enriched))
    return docs


def _load(cur, schema: str):
    """Read ATC classes, their kept ingredients, and SNOMED substance classes."""
    from src.agents.agent2.drug_class_expander import class_ingredients

    cur.execute(f"""
        SELECT concept_id, concept_code, concept_name, concept_class_id
        FROM {schema}.concept
        WHERE vocabulary_id = 'ATC'
          AND concept_class_id IN ('ATC 1st', 'ATC 2nd', 'ATC 3rd', 'ATC 4th')
          AND invalid_reason IS NULL
        ORDER BY concept_code
    """)
    atc_rows = cur.fetchall()
    atc_sets = {row[0]: set(class_ingredients(cur, schema, row[0])) for row in atc_rows}

    cur.execute(f"""
        SELECT concept_id, concept_name FROM {schema}.concept
        WHERE vocabulary_id = 'SNOMED' AND concept_class_id = 'Substance'
          AND invalid_reason IS NULL
    """)
    names = dict(cur.fetchall())
    cur.execute(f"""
        SELECT cr.concept_id_1, cr.concept_id_2
        FROM {schema}.concept_relationship cr
        JOIN {schema}.concept c1 ON c1.concept_id = cr.concept_id_1
        JOIN {schema}.concept c2 ON c2.concept_id = cr.concept_id_2
        WHERE cr.relationship_id = 'Is a' AND cr.invalid_reason IS NULL
          AND c1.vocabulary_id = 'SNOMED' AND c1.concept_class_id = 'Substance'
          AND c1.invalid_reason IS NULL
          AND c2.vocabulary_id = 'SNOMED' AND c2.concept_class_id = 'Substance'
          AND c2.invalid_reason IS NULL
    """)
    children: dict[int, set[int]] = collections.defaultdict(set)
    for child, parent in cur.fetchall():
        children[parent].add(child)
    cur.execute(f"""
        SELECT cr.concept_id_1, cr.concept_id_2
        FROM {schema}.concept_relationship cr
        JOIN {schema}.concept c1 ON c1.concept_id = cr.concept_id_1
        JOIN {schema}.concept c2 ON c2.concept_id = cr.concept_id_2
        WHERE cr.relationship_id IN ('Maps to', 'SNOMED - RxNorm eq')
          AND cr.invalid_reason IS NULL
          AND c1.vocabulary_id = 'SNOMED' AND c1.concept_class_id = 'Substance'
          AND c1.invalid_reason IS NULL
          AND c2.vocabulary_id IN ('RxNorm', 'RxNorm Extension')
          AND c2.concept_class_id = 'Ingredient' AND c2.standard_concept = 'S'
    """)
    maps: dict[int, set[int]] = collections.defaultdict(set)
    for node, ingredient in cur.fetchall():
        maps[node].add(ingredient)

    closure: dict[int, frozenset[int]] = {}

    def _closure(node: int) -> frozenset[int]:
        # Iterative post-order walk; the substance hierarchy is deep enough to make
        # recursion fragile, and a cycle (none observed) would otherwise never end.
        stack, seen = [node], set()
        while stack:
            current = stack[-1]
            if current in closure:
                stack.pop()
                continue
            pending = [c for c in children.get(current, ()) if c not in closure and c not in seen]
            if pending:
                seen.add(current)
                stack.extend(pending)
                continue
            acc = set(maps.get(current, ()))
            for c in children.get(current, ()):
                acc |= closure.get(c, frozenset())
            closure[current] = frozenset(acc)
            stack.pop()
        return closure[node]

    snomed_sets = {}
    for node in names:
        if maps.get(node):
            continue  # maps to an ingredient itself: a substance, not a class
        ingredients = _closure(node)
        if len(ingredients) >= 2:
            snomed_sets[node] = set(ingredients)
    return atc_rows, atc_sets, snomed_sets, names


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--tau", type=float, default=DEFAULT_TAU)
    parser.add_argument("--dry-run", action="store_true",
                        help="print the equivalents as JSON and write nothing")
    args = parser.parse_args(argv)
    if args.collection == "atc_drug_classes":
        parser.error("refusing to write the production collection 'atc_drug_classes'")

    import psycopg2

    from src.settings import settings

    conn = psycopg2.connect(settings.DATABASE_URL)
    try:
        cur = conn.cursor()
        atc_rows, atc_sets, snomed_sets, names = _load(cur, settings.CDM_SCHEMA)
    finally:
        conn.close()
    equivalents = equivalent_names(atc_sets, snomed_sets, names, args.tau)

    report = {code: {"atc_name": name, "equivalents": equivalents[cid]}
              for cid, code, name, _cls in atc_rows if cid in equivalents}
    if args.dry_run:
        print(json.dumps(report, indent=1, sort_keys=True))
        print(f"{len(report)} of {len(atc_rows)} ATC classes gained a name", file=sys.stderr)
        return 0

    from src.utils.vector import get_chroma_client

    client = get_chroma_client()
    if args.collection in [c.name for c in client.list_collections()]:
        print(f"collection {args.collection!r} already exists; delete it first", file=sys.stderr)
        return 1
    collection = client.create_collection(name=args.collection)
    ids, documents, metadatas = [], [], []
    for cid, code, name, level in atc_rows:
        for doc_id, doc in documents_for(cid, name, equivalents.get(cid, [])):
            ids.append(doc_id)
            documents.append(doc)
            metadatas.append({
                "concept_id": cid,
                "concept_code": code,
                "concept_class_id": level,
                "vocabulary_id": "ATC",
                "concept_name": name,
                "equivalents": _SEPARATOR.join(equivalents.get(cid, [])),
            })
    collection.add(ids=ids, documents=documents, metadatas=metadatas)
    print(f"{args.collection}: {len(atc_rows)} ATC classes in {collection.count()} documents, "
          f"{len(report)} with borrowed names (tau={args.tau})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
