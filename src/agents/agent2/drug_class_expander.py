"""
Drug Class Expander for Agent 2.

When Agent 2 receives a drug class name (e.g., "DPP-4 inhibitors"),
this module expands it into individual ingredient concept IDs.

Strategy (waterfall — all vocabulary-based):
1. ATC vocab: ChromaDB ATC collection → concept_ancestor expansion
2. UMLS MRREL: drug class CUI → MRREL `isa` children → RxNorm names → OMOP concept_id
"""
from typing import List, Optional, Dict, Set, Tuple
import os
import re
import sqlite3
import logging

logger = logging.getLogger(__name__)

# ── MRREL SQLite path ──
_MRREL_DB_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "data", "umls", "mrrel.sqlite"
)
_MRCONSO_DB_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "data", "umls", "mrconso.sqlite"
)


def expand_drug_class_via_umls(
    text: str,
    db_conn,
    schema: str = "",
) -> Tuple[Optional[str], List[int]]:
    """
    UMLS MRREL-based drug class expansion.

    Path: text → UMLS CUI (via UMLSSynonymExpander) → MRREL `isa` children
          → MRCONSO RxNorm names → OMOP concept_id (exact name match).

    This is fully vocabulary-based: no hardcoded ingredient lists.

    Args:
        text: Drug class name (e.g., "Fibrinolytic agents", "anticoagulants")
        db_conn: PostgreSQL connection to OMOP CDM
        schema: CDM schema name

    Returns:
        Tuple of (class name or None, list of OMOP Ingredient concept_ids)
    """
    if not schema:
        from src.settings import Settings
        schema = Settings().CDM_SCHEMA

    # Check MRREL/MRCONSO SQLite availability
    mrrel_path = os.path.abspath(_MRREL_DB_PATH)
    conso_path = os.path.abspath(_MRCONSO_DB_PATH)
    if not os.path.exists(mrrel_path) or not os.path.exists(conso_path):
        logger.debug("[DrugClass] MRREL/MRCONSO SQLite not available")
        return None, []

    # Step 1: Get UMLS CUI for the drug class
    try:
        from src.agents.agent2.umls_synonym_expander import UMLSSynonymExpander
        expander = UMLSSynonymExpander()
        cuis = expander.get_cuis(text, domain_hint="Drug")
        expander.close()
    except Exception as e:
        logger.warning(f"[DrugClass] UMLS CUI lookup failed: {e}")
        return None, []

    if not cuis:
        logger.debug(f"[DrugClass] No UMLS CUI found for '{text}'")
        return None, []

    target_cui = cuis[0]
    logger.info(f"[DrugClass] UMLS CUI for '{text}' → {target_cui}")

    # Step 2: MRREL `isa` children (drug class → individual substances)
    try:
        mrrel_conn = sqlite3.connect(mrrel_path)
        child_cuis = set()
        # Children where drug class is parent (isa relationship)
        rows = mrrel_conn.execute("""
            SELECT DISTINCT cui2 FROM mrrel
            WHERE cui1 = ? AND rela = 'isa'
        """, (target_cui,)).fetchall()
        child_cuis.update(r[0] for r in rows)

        # Also check inverse direction
        rows = mrrel_conn.execute("""
            SELECT DISTINCT cui1 FROM mrrel
            WHERE cui2 = ? AND rela = 'inverse_isa'
        """, (target_cui,)).fetchall()
        child_cuis.update(r[0] for r in rows)
        mrrel_conn.close()
    except Exception as e:
        logger.warning(f"[DrugClass] MRREL query failed: {e}")
        return None, []

    if not child_cuis:
        logger.debug(f"[DrugClass] No MRREL children for {target_cui}")
        return None, []

    logger.info(
        f"[DrugClass] MRREL: {target_cui} → {len(child_cuis)} child CUIs"
    )

    # Step 3: Resolve child CUIs to RxNorm names via MRCONSO
    try:
        conso_conn = sqlite3.connect(conso_path)
        rxnorm_names = []
        for child_cui in child_cuis:
            rows = conso_conn.execute("""
                SELECT DISTINCT str FROM mrconso
                WHERE cui = ? AND sab = 'RXNORM' AND lat = 'ENG'
                  AND tty IN ('IN', 'PIN', 'MIN', 'BN')
                LIMIT 1
            """, (child_cui,)).fetchall()
            if rows:
                rxnorm_names.append(rows[0][0])
        conso_conn.close()
    except Exception as e:
        logger.warning(f"[DrugClass] MRCONSO query failed: {e}")
        return None, []

    if not rxnorm_names:
        logger.info(
            f"[DrugClass] No RxNorm names resolved from "
            f"{len(child_cuis)} child CUIs"
        )
        return None, []

    # Step 4: Map RxNorm names to OMOP concept IDs
    cur = db_conn.cursor()
    found_ids = []
    for name in rxnorm_names:
        cur.execute(f"""
            SELECT concept_id FROM {schema}.concept
            WHERE LOWER(concept_name) = LOWER(%s)
              AND concept_class_id = 'Ingredient'
              AND vocabulary_id IN ('RxNorm', 'RxNorm Extension')
              AND invalid_reason IS NULL
            LIMIT 1
        """, (name,))
        row = cur.fetchone()
        if row:
            found_ids.append(row[0])

    if found_ids:
        # Minimum ingredient count: real drug classes have ≥3 members.
        # If MRREL returns too few (e.g., GLP-1 → only exenatide),
        # let the caller fall through to ATC for better coverage.
        if len(found_ids) < 3:
            logger.info(
                f"[DrugClass] UMLS MRREL '{text}' ({target_cui}) → "
                f"only {len(found_ids)} ingredients, skipping (not a class)"
            )
            return None, []
        logger.info(
            f"[DrugClass] UMLS MRREL '{text}' ({target_cui}) → "
            f"{len(found_ids)}/{len(rxnorm_names)} OMOP Ingredients"
        )
    else:
        logger.info(
            f"[DrugClass] UMLS MRREL: 0 OMOP matches from "
            f"{len(rxnorm_names)} RxNorm names"
        )
        return None, []

    return text, found_ids


def expand_drug_class_via_vocab(
    text: str,
    db_conn,
    schema: str = "",
    distance_threshold: float = float(
        os.environ.get("AGENT2_ATC_DISTANCE_THRESHOLD", "0.4")
    ),
) -> Tuple[Optional[str], List[int]]:
    """
    Drug class expansion — waterfall strategy (all vocabulary-based).

    1. UMLS MRREL first: CUI → isa children → RxNorm → OMOP (precise pharmacological classes)
    2. ATC vocab fallback: ChromaDB ATC collection → concept_ancestor (broad ATC-aligned classes)

    MRREL takes priority because ATC often matches wrong classes
    (e.g., "anticoagulants" → "ANTITHROMBOTIC AGENTS" which is too broad,
    "CYP inhibitors" → "CDK inhibitors" which is entirely wrong).
    MRREL only matches when UMLS has a CUI with `isa` children, so
    individual drug names safely fall through to ATC.

    Args:
        text: Drug class name or abbreviation (e.g., "GLP1-RA", "DPP-4")
        db_conn: PostgreSQL connection to OMOP CDM
        schema: CDM schema name (default: from settings.CDM_SCHEMA)
        distance_threshold: Max ChromaDB distance for a valid match (lower = stricter)

    Returns:
        Tuple of (class name or None, list of RxNorm Ingredient concept_ids)
    """
    if not schema:
        from src.settings import Settings
        schema = Settings().CDM_SCHEMA

    # ── Strategy 1: UMLS MRREL (precise, pharmacological class) ──
    mrrel_name, mrrel_ids = expand_drug_class_via_umls(text, db_conn, schema)
    if mrrel_ids:
        return mrrel_name, mrrel_ids

    # ── Strategy 2: ATC vocab-based (broad, generalizable) ──
    try:
        from src.utils.vector import get_chroma_client
        client = get_chroma_client()
        atc_collection = client.get_collection("atc_drug_classes")
    except Exception as e:
        logger.warning(f"[DrugClass] ATC collection not available: {e}")
        return None, []

    results = atc_collection.query(query_texts=[text], n_results=1)

    if not results['documents'][0]:
        return None, []

    atc_name = results['documents'][0][0]
    atc_id = results['metadatas'][0][0]['concept_id']
    atc_code = results['metadatas'][0][0].get('concept_code', '?')
    distance = results['distances'][0][0]

    if distance > distance_threshold:
        logger.info(
            f"[DrugClass] ATC match '{text}' → '{atc_name}' rejected "
            f"(dist={distance:.3f} > {distance_threshold})"
        )
        return None, []

    logger.info(
        f"[DrugClass] ATC match '{text}' → '{atc_name}' "
        f"(code={atc_code}, dist={distance:.3f})"
    )

    cur = db_conn.cursor()
    cur.execute(f"""
        SELECT DISTINCT c2.concept_id
        FROM {schema}.concept_ancestor ca
        JOIN {schema}.concept c2 ON ca.descendant_concept_id = c2.concept_id
        WHERE ca.ancestor_concept_id = %s
          AND c2.concept_class_id = 'Ingredient'
          AND c2.vocabulary_id IN ('RxNorm', 'RxNorm Extension')
          AND c2.invalid_reason IS NULL
    """, (atc_id,))

    ingredient_ids = [row[0] for row in cur.fetchall()]

    # Minimum ingredient count: real drug classes have ≥3.
    if len(ingredient_ids) > 2:
        logger.info(
            f"[DrugClass] ATC '{atc_code}' → "
            f"{len(ingredient_ids)} RxNorm Ingredients"
        )
        return atc_name, ingredient_ids

    logger.info(
        f"[DrugClass] ATC '{atc_name}' rejected: only "
        f"{len(ingredient_ids)} ingredients (not a class)"
    )
    return None, []
