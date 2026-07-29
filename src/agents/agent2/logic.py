"""
Agent 2 - Concept Logician.

Handles decomposition of combination concepts and pruning.
DB operations are OPTIONAL — if DB is unreachable, gracefully falls back
to returning the original concept IDs without decomposition/pruning.
"""
import re
from typing import List, Set
import logging

logger = logging.getLogger(__name__)

# DB availability flag - checked once, cached
_db_available: bool | None = None

# Regex to extract the ingredient name from an RxNorm-style concept name.
# RxNorm drug name patterns: "{ingredient} {dose} {form} [brand/supplier...]"
# Examples:
#   "ticagrelor 90 MG Oral Tablet Box of 56 by Viatris Healthcare" → "ticagrelor"
#   "apixaban 5 MG Oral Tablet by Key" → "apixaban"
#   "insulin degludec 100 UNT/ML / liraglutide 3.6 MG/ML Pen Injector" → multi-ingredient
_DOSE_PATTERN = re.compile(
    r"^(.*?)\s+\d[\d.,]*\s*(mg|mcg|unt|iu|ml|g|mg/ml|unt/ml|mg/actuat|meq|%|pct)",
    re.IGNORECASE,
)


def _check_db() -> bool:
    """Check if PostgreSQL is available. Result is cached."""
    global _db_available
    if _db_available is not None:
        return _db_available

    try:
        from sqlalchemy import text
        from src.utils.db import engine
        # Quick connectivity check with 2-second timeout
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        _db_available = True
        logger.info("[Logician] PostgreSQL connection OK")
    except Exception as e:
        _db_available = False
        logger.warning(f"[Logician] PostgreSQL unavailable ({e}). "
                      f"Decomposition/pruning will be skipped.")
    return _db_available


class ConceptLogician:
    def __init__(self):
        from src.settings import settings
        self.schema = settings.CDM_SCHEMA

    @staticmethod
    def _dedupe_preserve_order(concept_ids: List[int]) -> List[int]:
        """Return concept IDs without duplicates while preserving order."""
        seen: Set[int] = set()
        ordered: List[int] = []
        for concept_id in concept_ids:
            if concept_id not in seen:
                seen.add(concept_id)
                ordered.append(concept_id)
        return ordered

    def _resolve_ingredient_by_name(
        self, concept_name: str, db: object
    ) -> List[int]:
        """
        Extract ingredient name(s) from a drug product concept name and look up
        the corresponding RxNorm standard Ingredient concept IDs.

        This is a fallback path for RxNorm Extension Marketed Products that have
        no concept_ancestor entries mapping them to an ingredient. The drug_era
        table records only RxNorm ingredient-level concepts, so product codes must
        be normalised to their ingredient(s) for DrugEra-based cohort matching.

        Strategy: strip the dose/form/supplier suffix from the concept name to
        obtain the ingredient portion, then match exactly against the concept
        table for vocabulary_id='RxNorm' AND concept_class_id='Ingredient'.
        """
        from sqlalchemy import text as sa_text

        # Multi-ingredient products contain " / " (e.g. "insulin degludec / liraglutide")
        # Split on " / " first, then strip dose suffix from each part.
        parts = [p.strip() for p in concept_name.split(" / ")]
        ingredient_names: List[str] = []
        for part in parts:
            m = _DOSE_PATTERN.match(part)
            candidate = m.group(1).strip() if m else part.strip()
            if candidate:
                ingredient_names.append(candidate.lower())

        if not ingredient_names:
            return []

        try:
            rows = db.execute(
                sa_text(f"""
                    SELECT concept_id
                    FROM {self.schema}.concept
                    WHERE LOWER(concept_name) = ANY(:names)
                      AND vocabulary_id = 'RxNorm'
                      AND concept_class_id = 'Ingredient'
                      AND standard_concept = 'S'
                      AND invalid_reason IS NULL
                """),
                {"names": ingredient_names},
            ).fetchall()
            return [row[0] for row in rows]
        except Exception as exc:
            logger.debug("[Logician] Ingredient-by-name lookup failed: %s", exc)
            return []

    def roll_up_to_rxnorm_ingredients(self, concept_ids: List[int]) -> List[int]:
        """
        Normalize drug concept IDs to RxNorm ingredient level when possible.

        Product/formulation concepts in RxNorm Extension do not match DrugEra rows,
        which are recorded at the RxNorm ingredient level. When an ingredient
        ancestor exists, replace the original concept with that ingredient.

        Two-stage approach:
        1. concept_ancestor lookup (works for RxNorm Clinical Drug Comp/Drug concepts)
        2. Name-based fallback for RxNorm Extension Marketed Products that have no
           ancestor entries — extracts ingredient name from the concept name and
           resolves the standard RxNorm Ingredient by exact name match.
        """
        if not concept_ids:
            return []

        deduped = self._dedupe_preserve_order(concept_ids)
        if not _check_db():
            return deduped

        try:
            from sqlalchemy import text
            from src.utils.db import get_db

            # Stage 1: concept_ancestor path (fast, works for Clinical Drug Comp/Drug)
            ancestor_query = text(f"""
                SELECT DISTINCT
                    ca.descendant_concept_id,
                    ca.ancestor_concept_id
                FROM {self.schema}.concept_ancestor ca
                JOIN {self.schema}.concept c
                  ON c.concept_id = ca.ancestor_concept_id
                WHERE ca.descendant_concept_id = ANY(:cids)
                  AND c.concept_class_id = 'Ingredient'
                  AND c.vocabulary_id = 'RxNorm'
                  AND c.standard_concept = 'S'
                  AND c.invalid_reason IS NULL
                ORDER BY ca.descendant_concept_id, ca.ancestor_concept_id
            """)

            # Stage 2: fetch concept metadata for ids without ancestor results
            meta_query = text(f"""
                SELECT concept_id, concept_name, vocabulary_id, concept_class_id
                FROM {self.schema}.concept
                WHERE concept_id = ANY(:cids)
                  AND invalid_reason IS NULL
            """)

            ingredient_map: dict[int, List[int]] = {}
            with next(get_db()) as db:
                rows = db.execute(ancestor_query, {"cids": deduped}).fetchall()
                for descendant_id, ancestor_id in rows:
                    ingredient_map.setdefault(descendant_id, []).append(ancestor_id)

                # Identify concepts that could not be resolved via concept_ancestor
                unresolved = [cid for cid in deduped if cid not in ingredient_map]
                if unresolved:
                    meta_rows = db.execute(meta_query, {"cids": unresolved}).fetchall()
                    meta_map = {row[0]: (row[1], row[2], row[3]) for row in meta_rows}

                    for cid in unresolved:
                        meta = meta_map.get(cid)
                        if meta is None:
                            continue
                        concept_name, vocab, concept_class = meta
                        # Only attempt name-based fallback for RxNorm Extension
                        # product-level classes that commonly lack ancestor entries.
                        if vocab == "RxNorm Extension" and concept_class in {
                            "Marketed Product",
                            "Branded Drug",
                            "Branded Drug Comp",
                            "Branded Drug Box",
                            "Clinical Drug Box",
                            "Quant Branded Drug",
                            "Quant Clinical Drug",
                        }:
                            resolved = self._resolve_ingredient_by_name(concept_name, db)
                            if resolved:
                                ingredient_map[cid] = resolved
                                logger.info(
                                    "[Logician] Name-based ingredient fallback %s (%s) → %s",
                                    cid,
                                    concept_name[:50],
                                    resolved,
                                )

            # Everything below stays inside the session. The safety-net query used
            # to sit outside it: Session.__exit__ had already returned the
            # connection, so execute() checked out a fresh one that nothing ever
            # returned. Measured, checkedout climbed 1, 2, 3... per call until the
            # pool hit "QueuePool limit of size 20 overflow 40 reached" and every
            # rollup from then on was skipped -- silently keeping product-level
            # concept ids that match no drug_exposure rows.
                rolled_up: List[int] = []
                for concept_id in deduped:
                    replacements = ingredient_map.get(concept_id)
                    if replacements:
                        rolled_up.extend(replacements)
                    else:
                        rolled_up.append(concept_id)

                result = self._dedupe_preserve_order(rolled_up)

                # Safety net: if no Ingredient-class concept ended up in the
                # result, extract ingredient names from the product-level
                # concept names and resolve them directly.  Synthea CDMs store
                # drug_exposure at the RxNorm Ingredient level, so a concept
                # set without the Ingredient will match 0 patients.
                ingredient_check = text(f"""
                    SELECT concept_id
                    FROM {self.schema}.concept
                    WHERE concept_id = ANY(:cids)
                      AND concept_class_id = 'Ingredient'
                      AND vocabulary_id = 'RxNorm'
                """)
                ing_rows = db.execute(ingredient_check, {"cids": result}).fetchall()
                if not ing_rows:
                    # No ingredient in result — try name-based resolution
                    # for ALL concepts, not just specific product classes
                    all_meta = db.execute(meta_query, {"cids": result}).fetchall()
                    for _, cname, vocab, cclass in all_meta:
                        resolved = self._resolve_ingredient_by_name(cname, db)
                        if resolved:
                            result.extend(resolved)
                            logger.info(
                                "[Logician] Ingredient safety-net: '%s' → %s",
                                cname[:50],
                                resolved,
                            )
                            break  # one ingredient match is enough
                    result = self._dedupe_preserve_order(result)

                if result != deduped:
                    logger.info(
                        "[Logician] Rolled up drug concepts to RxNorm ingredients: %s -> %s",
                        deduped,
                        result,
                    )
                return result
        except Exception as e:
            logger.warning(
                "[Logician] Ingredient rollup skipped; using original concept IDs. "
                f"concept_ids={deduped} error_type={type(e).__name__} error={e}"
            )
            return deduped
    
    def decompose_combination(self, concept_id: int) -> List[int]:
        """
        Normalize a drug concept to RxNorm ingredient level.

        Combination drugs expand to multiple ingredients; single-ingredient
        products collapse to one ingredient. Falls back to [concept_id] if the
        database is unavailable.
        """
        return self.roll_up_to_rxnorm_ingredients([concept_id])

    def prune_empty_concepts(self, concept_ids: List[int]) -> List[int]:
        """
        Filters out concepts not present in patient data tables.
        Currently a passthrough — returns all IDs.
        """
        # TODO: Implement domain-aware pruning when DB is available.
        # For now, pass through all concepts to avoid blocking development.
        return self._dedupe_preserve_order(concept_ids)


logician = ConceptLogician()
