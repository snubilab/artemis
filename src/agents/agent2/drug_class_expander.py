"""
Drug Class Expander for Agent 2.

When Agent 2 receives a drug class name (e.g., "DPP-4 inhibitors"),
this module expands it into individual ingredient concept IDs.

Strategy (waterfall — all vocabulary-based):
1. UMLS MRREL: drug class CUI → MRREL `isa` children → RxNorm names → OMOP concept_id
2. ATC vocab: ChromaDB ATC collection → class selection → concept_ancestor expansion
"""
from dataclasses import dataclass
from typing import Callable, List, Optional, Dict, Set, Tuple
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

# How many ranked ATC classes `expand_drug_class_via_vocab` considers. Rank 1 is not
# the only candidate: its parent/child holding the same ingredients, or a descendant
# holding most of them, may sit right behind it.
_ATC_CANDIDATES = 5

# The collection the ATC classes are read from. `atc_drug_classes` indexes each class
# under its bare ATC name; `scripts/build_atc_class_index.py` writes
# `atc_drug_classes_v2`, which appends the names of SNOMED substance classes holding
# the same ingredients. Read per call, so setting the variable takes effect at once.
_ATC_COLLECTION_DEFAULT = "atc_drug_classes"

# A class with fewer ingredients than this is a residual bucket ("Other antiobesity
# drugs", 1 ingredient) rather than the class the wording names; its parent is tried.
_MIN_CLASS_SIZE = 3

# An ATC descendant of the best hit within threshold replaces it only when it keeps at
# least this share of the best hit's ingredients: then it is the same class with a
# residual removed (H02A keeps 20 of H02's 23; the 3 dropped are the antiadrenals). The
# closest child of A10A "INSULINS AND ANALOGUES", A10AE, keeps 6 of 29 -- a subdivision
# the query did not choose. Observed shares: 0.87 for the one case that should descend,
# at most 0.48 for those that should not. The ATC code hierarchy and this share decide;
# the class NAMES are not read (RFC-016 §4, C5).
_MIN_EXTENSION_SHARE = 2 / 3

# Rank 1 just over the distance threshold is accepted when nothing else is near it.
# Calibrated on the 2026-09-22 verify5 store's Drug class seeds: see
# tests/test_atc_class_selection.py for the observed distances on both sides. With the
# v2 index no correct match in that data sits over the threshold, so these defaults
# admit none of it; they are set to keep the CYP3A -> Pi3K false match (gap 0.096) out.
_ATC_MARGIN_BAND = float(os.environ.get("AGENT2_ATC_MARGIN_BAND", "0.05"))
_ATC_MARGIN_GAP = float(os.environ.get("AGENT2_ATC_MARGIN_GAP", "0.15"))


@dataclass(frozen=True)
class AtcHit:
    """One ranked ATC class from the vector index.

    :param concept_id: the ATC concept_id.
    :param code: the ATC code; its prefixes are its ancestors (B01 > B01A > B01AC).
    :param name: the ATC concept_name, not the indexed document.
    :param distance: vector distance from the query; lower is closer.
    """

    concept_id: int
    code: str
    name: str
    distance: float


def _related(a: AtcHit, b: AtcHit) -> bool:
    """True when one class is the other or its ATC ancestor (an ATC code's prefixes are
    its ancestors: B01 > B01A > B01AC)."""
    return a.code.startswith(b.code) or b.code.startswith(a.code)


def _same_class(a: AtcHit, b: AtcHit, share_of_parent: Callable[[AtcHit, AtcHit], float]) -> bool:
    """One concept, or an ATC ancestor and descendant holding the same ingredients."""
    if a.concept_id == b.concept_id:
        return True
    if not _related(a, b):
        return False
    parent, child = (a, b) if len(a.code) <= len(b.code) else (b, a)
    return share_of_parent(child, parent) >= 1.0


def merge_same_class(
    hits: List[AtcHit], share_of_parent: Callable[[AtcHit, AtcHit], float]
) -> List[AtcHit]:
    """Collapse a class and its ATC ancestor when they hold the same ingredients.

    B01 "ANTITHROMBOTIC AGENTS" has the single child B01A, and both hold the same 65
    ingredients: one class, indexed twice. The shallower code is kept at the closer
    distance. The same concept indexed twice (the v2 collection's A10BJ at 0.387 and 0.618)
    is one class too. Classes in different subtrees, and an ancestor/descendant pair whose
    ingredients differ (A10X and A10XX), stay apart. Names are not compared.

    :param hits: ranked hits, closest first.
    :param share_of_parent: (child, parent) -> fraction of the parent's ingredients the
        child holds.
    :returns: the hits with same-class pairs merged, closest first.
    """
    merged: List[AtcHit] = []
    for hit in hits:
        for k, kept in enumerate(merged):
            if _same_class(kept, hit, share_of_parent):
                shallow = kept if len(kept.code) <= len(hit.code) else hit
                merged[k] = AtcHit(shallow.concept_id, shallow.code, shallow.name,
                                   min(kept.distance, hit.distance))
                break
        else:
            merged.append(hit)
    return sorted(merged, key=lambda h: h.distance)


def _narrower(child: AtcHit, parent: AtcHit) -> bool:
    """True when the child is a proper ATC descendant of the parent."""
    return child.code != parent.code and child.code.startswith(parent.code)


def select_atc_class(
    hits: List[AtcHit],
    threshold: float,
    band: float = _ATC_MARGIN_BAND,
    gap: float = _ATC_MARGIN_GAP,
    *,
    share_of_parent: Callable[[AtcHit, AtcHit], float],
) -> Optional[AtcHit]:
    """Pick the ATC class a drug-class phrase names, or None.

    1. Hits of one class count once (`merge_same_class`).
    2. The closest class within ``threshold`` is the best hit. With none within it,
       rank 1 is still accepted when it is at most ``band`` over the threshold and the
       next distinct class exists and is at least ``gap`` further away.
    3. An ATC descendant of the best hit, within threshold, which keeps at least
       `_MIN_EXTENSION_SHARE` of the best hit's ingredients replaces it (H02 -> H02A),
       closest first, repeated while one exists.

    :param hits: ranked hits in any order.
    :param threshold: maximum distance for an ordinary match.
    :param band: how far over the threshold an isolated rank 1 may sit.
    :param gap: minimum distance from rank 1 to the next distinct class.
    :param share_of_parent: (child, parent) -> fraction of the parent's ingredients
        the child holds.
    :returns: the chosen hit, or None.
    """
    ordered = sorted(hits, key=lambda h: h.distance)
    if not ordered:
        return None
    # Ingredients are consulted only where a choice depends on them: among the classes
    # within threshold, or between rank 1 and the hits behind it in the margin rule. A
    # class past both is never looked up.
    within = merge_same_class([h for h in ordered if h.distance <= threshold], share_of_parent)
    if not within:
        first = ordered[0]
        same = [h for h in ordered[1:] if _same_class(first, h, share_of_parent)]
        distinct = [h for h in ordered[1:] if h not in same]
        # Isolation has to be seen: with no runner-up there is no gap to measure.
        if not distinct:
            return None
        runner_up = distinct[0]
        if first.distance <= threshold + band and runner_up.distance - first.distance >= gap:
            shallow = min([first, *same], key=lambda h: len(h.code))
            return AtcHit(shallow.concept_id, shallow.code, shallow.name, first.distance)
        return None
    best = within[0]
    while True:
        longer = [h for h in within if _narrower(h, best)
                  and share_of_parent(h, best) >= _MIN_EXTENSION_SHARE]
        if not longer:
            return best
        best = longer[0]


def drop_combination_partners(
    ingredients: List[int], alone_in_class: Set[int], alone_anywhere: Set[int]
) -> List[int]:
    """Remove ingredients that belong to a class only as a combination partner.

    An ingredient is dropped when it is sold on its own somewhere but never on its
    own under the class: bupropion reaches ATC A08 only through bupropion/naltrexone,
    and is an antidepressant on its own. An ingredient that is never sold on its own
    (insulin aspart protamine, premixed only) is kept -- combining is what it is.

    :param ingredients: the class's ingredient concept_ids, in order.
    :param alone_in_class: ingredients of single-ingredient drug forms under the class.
    :param alone_anywhere: ingredients of single-ingredient drug forms anywhere.
    :returns: the kept ingredients, order preserved.
    """
    return [i for i in ingredients if i in alone_in_class or i not in alone_anywhere]


_INGREDIENT = ("{alias}.concept_class_id = 'Ingredient' "
               "AND {alias}.vocabulary_id IN ('RxNorm', 'RxNorm Extension') "
               "AND {alias}.invalid_reason IS NULL")
_DRUG_FORM = ("{alias}.concept_class_id = 'Clinical Drug Form' "
              "AND {alias}.vocabulary_id IN ('RxNorm', 'RxNorm Extension')")


def class_ingredients(cur, schema: str, class_id: int) -> List[int]:
    """RxNorm ingredients of an ATC class, without combination partners.

    :param cur: an open cursor on the OMOP vocabulary.
    :param schema: the vocabulary schema.
    :param class_id: the ATC concept_id.
    :returns: ingredient concept_ids (see `drop_combination_partners`).
    """
    cur.execute(f"""
        SELECT DISTINCT c2.concept_id
        FROM {schema}.concept_ancestor ca
        JOIN {schema}.concept c2 ON ca.descendant_concept_id = c2.concept_id
        WHERE ca.ancestor_concept_id = %s
          AND {_INGREDIENT.format(alias="c2")}
    """, (class_id,))
    ingredients = [row[0] for row in cur.fetchall()]
    if not ingredients:
        return []

    # Single-ingredient drug forms under the class, by their one ingredient.
    cur.execute(f"""
        SELECT MIN(ci.ancestor_concept_id)
        FROM {schema}.concept_ancestor cf
        JOIN {schema}.concept f ON f.concept_id = cf.descendant_concept_id
        JOIN {schema}.concept_ancestor ci ON ci.descendant_concept_id = f.concept_id
        JOIN {schema}.concept i ON i.concept_id = ci.ancestor_concept_id
        WHERE cf.ancestor_concept_id = %s
          AND {_DRUG_FORM.format(alias="f")}
          AND i.concept_class_id = 'Ingredient'
        GROUP BY f.concept_id
        HAVING COUNT(DISTINCT ci.ancestor_concept_id) = 1
    """, (class_id,))
    alone_in_class = {row[0] for row in cur.fetchall()}
    residual = [i for i in ingredients if i not in alone_in_class]
    if not residual:
        return ingredients

    # Of the rest, which exist as a single-ingredient drug form anywhere at all.
    cur.execute(f"""
        SELECT DISTINCT ci.ancestor_concept_id
        FROM {schema}.concept_ancestor ci
        JOIN {schema}.concept f ON f.concept_id = ci.descendant_concept_id
        WHERE ci.ancestor_concept_id = ANY(%s)
          AND {_DRUG_FORM.format(alias="f")}
          AND NOT EXISTS (
            SELECT 1 FROM {schema}.concept_ancestor co
            JOIN {schema}.concept o ON o.concept_id = co.ancestor_concept_id
            WHERE co.descendant_concept_id = f.concept_id
              AND o.concept_class_id = 'Ingredient'
              AND o.concept_id <> ci.ancestor_concept_id)
    """, (residual,))
    alone_anywhere = {row[0] for row in cur.fetchall()}
    return drop_combination_partners(ingredients, alone_in_class, alone_anywhere)


def atc_parent(cur, schema: str, class_id: int) -> Optional[Tuple[int, str, str, str]]:
    """The ATC class one level above, as (concept_id, code, name, concept_class_id).

    :param cur: an open cursor on the OMOP vocabulary.
    :param schema: the vocabulary schema.
    :param class_id: the ATC concept_id.
    :returns: the parent, or None at the top of the hierarchy.
    """
    cur.execute(f"""
        SELECT a.concept_id, a.concept_code, a.concept_name, a.concept_class_id
        FROM {schema}.concept_ancestor ca
        JOIN {schema}.concept a ON a.concept_id = ca.ancestor_concept_id
        WHERE ca.descendant_concept_id = %s AND ca.min_levels_of_separation = 1
          AND a.vocabulary_id = 'ATC' AND a.invalid_reason IS NULL
    """, (class_id,))
    row = cur.fetchone()
    return tuple(row) if row else None


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
        logger.warning(
            "[DrugClass] MRREL/MRCONSO SQLite not available (%s, %s): UMLS class "
            "expansion skipped, ATC only", mrrel_path, conso_path,
        )
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
        # 0.4 admitted only near-verbatim names. Across all 31 ATC decisions in the
        # 2026-08-12 six-trial remap: 4 accepted (max distance 0.134), 27 rejected
        # (min 0.453), and the rejected 0.453-0.735 band was correct matches without
        # exception -- DPP-4, SGLT2 x3, GLP-1 x3, insulin x3, corticosteroids,
        # anti-obesity. The first wrong match is at 0.760 (CYP3A inhibitors ->
        # Pi3K inhibitors), so 0.75 takes 14 true positives and no false one.
        # It cost recall 0.04 on a 2093-concept gold set: ATC A10BH expands to 8 of
        # the 10 gold DPP-4 ingredients with nothing extra, and never ran.
        # Re-checked 2026-10-08 on the 40 ATC query texts of the 2026-09-22 verify5
        # store, on both collections: the furthest accepted correct-or-broader rank 1 is
        # 0.716 ('human NPH insulin' -> A10A), the nearest wrong one a threshold can
        # separate is 0.773 ('treated with specific drugs' -> J04AM). 0.75 stays.
        # The wrong matches inside it (Short-acting -> A10AE 0.410, Systemic steroids ->
        # A14A 0.523, premixed -> A10AB 0.627) are lexical neighbours no threshold separates.
        # Note this default binds at import; setting the env var later has no effect.
        os.environ.get("AGENT2_ATC_DISTANCE_THRESHOLD", "0.75")
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
    collection_name = os.environ.get("AGENT2_ATC_COLLECTION", _ATC_COLLECTION_DEFAULT)
    try:
        from src.utils.vector import get_chroma_client
        client = get_chroma_client()
        atc_collection = client.get_collection(collection_name)
    except Exception as e:
        logger.warning(f"[DrugClass] ATC collection '{collection_name}' not available: {e}")
        return None, []

    results = atc_collection.query(query_texts=[text], n_results=_ATC_CANDIDATES)
    if not results['documents'][0]:
        return None, []

    hits = [
        AtcHit(int(meta['concept_id']), meta.get('concept_code', '?'),
               meta.get('concept_name') or doc, distance)
        for doc, meta, distance in zip(
            results['documents'][0], results['metadatas'][0], results['distances'][0])
    ]
    cur = db_conn.cursor()
    known: Dict[int, List[int]] = {}

    def _ingredients(class_id: int) -> List[int]:
        if class_id not in known:
            known[class_id] = class_ingredients(cur, schema, class_id)
        return known[class_id]

    def _share(child: AtcHit, parent: AtcHit) -> float:
        held = set(_ingredients(parent.concept_id))
        return len(held & set(_ingredients(child.concept_id))) / len(held) if held else 0.0

    chosen = select_atc_class(hits, distance_threshold, share_of_parent=_share)
    ranking = ", ".join(f"{h.code} {h.distance:.3f}"
                        for h in sorted(hits, key=lambda h: h.distance))
    if chosen is None:
        logger.info(f"[DrugClass] ATC match '{text}' rejected "
                    f"(threshold={distance_threshold}; {ranking})")
        return None, []
    logger.info(f"[DrugClass] ATC match '{text}' → '{chosen.name}' "
                f"(code={chosen.code}, dist={chosen.distance:.3f}; {ranking})")

    # The phrase is not read for a route (RFC-016 step 4, A12). A route the protocol line
    # states is applied after mapping, from the vocabulary's dose-form routes
    # (`route_subtraction`), so a too-small route-specific class climbs like any other and
    # the stated route then excludes the parent's other-route forms.
    class_id, code, name = chosen.concept_id, chosen.code, chosen.name
    climbed = {class_id}
    while True:
        ingredient_ids = _ingredients(class_id)
        if len(ingredient_ids) >= _MIN_CLASS_SIZE:
            logger.info(f"[DrugClass] ATC '{code}' → {len(ingredient_ids)} RxNorm Ingredients")
            return name, ingredient_ids
        parent = atc_parent(cur, schema, class_id)
        if parent is None or parent[3] == "ATC 1st" or parent[0] in climbed:
            logger.info(f"[DrugClass] ATC '{code}' rejected: {len(ingredient_ids)} "
                        f"ingredients and no therapeutic parent to try")
            return None, []
        logger.info(f"[DrugClass] ATC '{code}' has {len(ingredient_ids)} ingredients; "
                    f"trying its parent {parent[1]}")
        class_id, code, name = parent[0], parent[1], parent[2]
        climbed.add(class_id)
