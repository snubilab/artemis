"""
Populate ChromaDB with OMOP Vocabulary for Agent 2 Semantic Search.

Loads concepts from the local PostgreSQL OMOP vocabulary database.
"""
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import psycopg2
from tqdm import tqdm
from src.utils.vector import get_chroma_client
from src.settings import settings


# Domains relevant for clinical trial criteria
RELEVANT_DOMAINS = ['Condition', 'Drug', 'Procedure', 'Measurement', 'Observation', 'Device']

# Per-domain row limit; None loads the whole standard, valid population of that domain.
#
# A cap here is a decision about what a criterion can be mapped to, so each one is
# stated with the measurement behind it rather than a round number. Measured
# 2026-09-09 against synthea23m.
DOMAIN_LIMITS = {
    'Condition': None,      # 105,666 standard concepts
    # 100,000 of 2,048,627. The ORDER BY concept_id slice ends at id 2,042,837 and
    # holds 5,860 of 33,218 Ingredients and 30,157 of 570,985 Marketed Products.
    # KEPT ON PURPOSE, and not because it is right: lifting it is a mapping-quality
    # change (~10 GB on disk, ~6 GB RAM for the 768-d HNSW, ~74 min on GPU) that has
    # to be measured per criterion against data/gold/ with
    # scripts/conceptset_overlap_eval.py before it rides into any re-extraction.
    'Drug': 100000,
    'Procedure': None,      # 58,158 standard concepts
    'Measurement': None,    # 94,798 standard concepts
    # WAS 50,000 of 132,423. The slice ended at concept_id 4,144,455 and dropped
    # 82,423 concepts (SNOMED 67,646 / LOINC 13,767 / HCPCS 951 / OMOP Extension 59),
    # among them 812 of the 1,352 Observation concepts naming a contraindication,
    # intolerance, allergy or history-of, and 4248529 "Clopidogrel contraindicated",
    # 4170410 and 44811047 -- the three concepts that answer a criterion the mapper
    # could not map. A concept_id slice is not a relevance slice.
    'Observation': None,    # 132,423 standard concepts
    'Device': None,         # 32,168 standard concepts
}

# Every relevant domain states its own limit. There is no fallback: a domain added to
# RELEVANT_DOMAINS without a decision about its size raises here rather than silently
# taking somebody else's number.
if set(DOMAIN_LIMITS) != set(RELEVANT_DOMAINS):
    raise RuntimeError(
        "DOMAIN_LIMITS and RELEVANT_DOMAINS disagree: "
        f"only in DOMAIN_LIMITS {sorted(set(DOMAIN_LIMITS) - set(RELEVANT_DOMAINS))}, "
        f"only in RELEVANT_DOMAINS {sorted(set(RELEVANT_DOMAINS) - set(DOMAIN_LIMITS))}"
    )


def get_db_connection():
    """Get PostgreSQL connection from settings."""
    return psycopg2.connect(settings.DATABASE_URL)


def concept_query(domain: str, limit: int | None = None) -> str:
    """SQL for one domain's standard, valid concepts.

    ``domain`` is bound as a parameter, not interpolated; it is named here because the
    query is per-domain and the caller reads ``DOMAIN_LIMITS[domain]`` to fill ``limit``.

    ``limit is None`` means the whole population. A limit of 0 or less is a mistake --
    the previous ``if limit:`` read 0 as "no limit", which is the opposite of what
    anyone writing 0 could have meant.
    """
    if limit is not None and limit <= 0:
        raise ValueError(
            f"{domain}: limit must be a positive row count or None for the whole "
            f"population, got {limit!r}"
        )

    query = f"""
        SELECT
            concept_id,
            concept_name,
            vocabulary_id,
            concept_class_id,
            domain_id
        FROM {settings.CDM_SCHEMA}.concept
        WHERE domain_id = %s
          AND standard_concept = 'S'
          AND invalid_reason IS NULL
        ORDER BY concept_id"""

    if limit is not None:
        # The ordering is what makes a capped slice deterministic across runs.
        query += f" LIMIT {limit}"

    return query


def fetch_concepts(domain: str, limit: int | None = None):
    """Fetch standard concepts from OMOP vocabulary."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(concept_query(domain, limit), (domain,))
    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return rows


def sync_collection(
    collection,
    *,
    batch_size: int,
    metadata_for: Callable[[Sequence[Any]], dict],
) -> dict[str, tuple[int, int, int]]:
    """Bring ``collection`` up to the full domain table, adding only what it lacks.

    Incremental by design. The previous "collection is non-empty, skip population"
    early return meant a cap could never be lifted by re-running the script -- the
    only way to change what was indexed was to delete a 3 GB collection and rebuild
    it, which nobody does by accident and nobody did on purpose either.

    Verifies rather than assumes. ``chromadb`` 1.5.5 ``add()`` accepts an id the
    collection already holds without raising and returns nothing, so ``len(missing)``
    is not evidence that ``len(missing)`` rows landed. What counts as added is what a
    read-back confirms, and a domain that ends short of the row count the vocabulary
    promised raises instead of printing a smaller number.

    Returns ``{domain: (expected, present, added)}``.
    """
    report: dict[str, tuple[int, int, int]] = {}
    expected_total = 0

    for domain in RELEVANT_DOMAINS:
        limit = DOMAIN_LIMITS[domain]
        rows = fetch_concepts(domain, limit)
        expected = len(rows)
        present = 0
        added = 0

        for start in tqdm(range(0, expected, batch_size), desc=f"  {domain}"):
            batch = rows[start:start + batch_size]
            batch_ids = [str(row[0]) for row in batch]

            already = set(collection.get(ids=batch_ids, include=[])["ids"])
            present += len(already)

            missing = [row for row in batch if str(row[0]) not in already]
            if not missing:
                continue

            missing_ids = [str(row[0]) for row in missing]
            collection.add(
                ids=missing_ids,
                documents=[row[1] for row in missing],
                metadatas=[metadata_for(row) for row in missing],
            )
            # Count what the collection will actually answer with, not what we sent it.
            added += len(set(collection.get(ids=missing_ids, include=[])["ids"]))

        indexed = present + added
        if indexed != expected:
            raise RuntimeError(
                f"{domain}: expected {expected} indexed, found {indexed} "
                f"(present {present}, added {added})"
            )

        print(f"   {domain}: expected {expected}, present {present}, added {added}")
        report[domain] = (expected, present, added)
        expected_total += expected

    count = collection.count()
    if count != expected_total:
        raise RuntimeError(
            f"collection holds {count} documents, the domain table promises "
            f"{expected_total}"
        )

    return report


def populate_chromadb():
    """Populate ChromaDB with OMOP concepts."""
    print("="*60)
    print("ARTEMIS 3.1 - Populate ChromaDB with OMOP Vocabulary")
    print("="*60)

    client = get_chroma_client()
    collection = client.get_or_create_collection(name="omop_concepts")

    print(f"\n📊 Current documents: {collection.count()}")

    report = sync_collection(
        collection,
        batch_size=5000,
        metadata_for=lambda row: {
            "concept_id": row[0],
            "vocabulary_id": row[2],
            "concept_class_id": row[3],
            "domain_id": row[4],
        },
    )

    print("\n" + "="*60)
    print("✅ ChromaDB Population Complete!")
    print(f"   Concepts added this run: {sum(added for _, _, added in report.values())}")
    print(f"   Collection count: {collection.count()}")
    print("="*60)


def populate_atc_drug_classes():
    """
    Populate a dedicated ChromaDB collection with ATC 4th level concepts.
    
    ATC 4th level (~936 concepts) represents pharmacological drug classes
    (e.g., "GLP-1 receptor agonists", "DPP-4 inhibitors").
    Used by Agent 2 for drug class → ingredient expansion via concept_ancestor.
    
    See RFC-006 for design rationale.
    """
    print("\n" + "="*60)
    print("ARTEMIS 3.1 - Populate ATC Drug Class Collection")
    print("="*60)
    
    client = get_chroma_client()
    collection = client.get_or_create_collection(name="atc_drug_classes")
    
    if collection.count() > 0:
        print(f"⚠️  Collection already has {collection.count()} documents. Skipping.")
        print("   To repopulate, delete the collection first.")
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(f"""
        SELECT concept_id, concept_name, concept_code, concept_class_id
        FROM {settings.CDM_SCHEMA}.concept
        WHERE vocabulary_id = 'ATC'
          AND concept_class_id IN ('ATC 1st', 'ATC 2nd', 'ATC 3rd', 'ATC 4th')
          AND invalid_reason IS NULL
        ORDER BY concept_code
    """)
    rows = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    if not rows:
        print("⚠️  No ATC concepts found in database.")
        return
    
    ids = [str(r[0]) for r in rows]
    documents = [r[1] for r in rows]
    metadatas = [{
        "concept_id": r[0],
        "concept_code": r[2],
        "concept_class_id": r[3],
        "vocabulary_id": "ATC",
    } for r in rows]
    
    # Small enough to add in one batch
    collection.add(ids=ids, documents=documents, metadatas=metadatas)
    
    print(f"✅ ATC Drug Class Collection: {collection.count()} concepts indexed")
    
    # Show breakdown by level
    from collections import Counter
    levels = Counter(r[3] for r in rows)
    for level in sorted(levels):
        print(f"   {level}: {levels[level]} concepts")


if __name__ == "__main__":
    populate_chromadb()
    populate_atc_drug_classes()
