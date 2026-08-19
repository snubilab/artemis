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

    def drop_qualitative_findings(self, concept_ids: List[int]) -> List[int]:
        """Remove Clinical Finding concepts from a Measurement-domain selection.

        A Measurement concept set exists to be compared against a value. SNOMED's
        `... - finding` concepts sit in `domain_id = Measurement` alongside the LOINC
        Lab Test and SNOMED Procedure concepts, are equally standard, and so survive
        every domain filter — but they are qualitative statements about a measurement,
        not the measurement, and their descendants are findings. `Platelet count -
        finding` expands to 177 of them; `Platelets [#/volume] in Blood` expands to
        itself. Against the gold lab set the first scores zero.

        Caller MUST gate this on the Measurement domain. `Clinical Finding` is the
        correct class for most of the Condition domain — Myocardial infarction is one —
        so applying it there would delete the mapping instead of repairing it.

        Args:
            concept_ids: Selected concept IDs for a Measurement-domain criterion.

        Returns:
            The same IDs in order, minus Clinical Finding members. Returns the input
            unchanged when every member is a finding (an empty set is a silent gap,
            which is worse than an imprecise one) or when the database is unreachable.
        """
        if not concept_ids:
            return []

        deduped = self._dedupe_preserve_order(concept_ids)
        if not _check_db():
            return deduped

        try:
            from sqlalchemy import text
            from src.utils.db import get_db

            finding_query = text(f"""
                SELECT concept_id
                FROM {self.schema}.concept
                WHERE concept_id = ANY(:cids)
                  AND concept_class_id = 'Clinical Finding'
                  AND invalid_reason IS NULL
            """)
            with next(get_db()) as db:
                rows = db.execute(finding_query, {"cids": deduped}).fetchall()
            findings = {row[0] for row in rows}
        except Exception as exc:
            logger.debug("[Logician] Finding-class lookup failed: %s", exc)
            return deduped

        if not findings:
            return deduped

        kept = [cid for cid in deduped if cid not in findings]
        if not kept:
            logger.info(
                "[Logician] All %d Measurement concepts are Clinical Findings; keeping "
                "them rather than emptying the set", len(deduped),
            )
            return deduped

        logger.info(
            "[Logician] Dropped %d Clinical Finding concept(s) from a Measurement set: %s",
            len(findings), sorted(findings),
        )
        return kept

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

    def drop_wrong_entity_class_for_condition(self, concept_ids: List[int]) -> List[int]:
        """Remove LOINC Survey/Question, Procedure, and history-of-Observation concepts
        from a Condition-domain selection.

        A Condition criterion records a clinical event a patient has experienced.
        Three concept classes slip through because their names overlap the criterion text:

        1. LOINC Survey/Question (concept_class_id IN ('Survey', 'Question')):
           These are questionnaire instruments — "History of stroke [USAUDIT]" — not
           the clinical event. The reranker says query_has_match=true because the name
           contains the condition term; the modifier framing ('History of') caused the
           match, not the condition itself. Plan-044 example: 'History of stroke' mapped
           to a LOINC Survey concept.

        2. Procedure domain (domain_id = 'Procedure'):
           A procedure for a condition is not the condition. 'Atrial fibrillation
           ablation' (catheter ablation) is a Procedure; gold 'Atrial fibrillation and
           flutter' is a Condition. The shared 'atrial fibrillation' substring is the
           modifier that fooled the gate. Plan-044 example.

        3. Observation-domain "history of" concepts (domain_id = 'Observation' AND
           concept_class_id IN ('Context-dependent', 'Clinical Observation')):
           Same modifier-match shape as case 1, one layer down: 'History of
           cerebrovascular accident' (SNOMED, Context-dependent) is a discrete
           "clinician explicitly documented this history" record, structurally
           different from — and far more sparsely populated than — the base Condition
           concept ('Cerebrovascular accident') a cohort's any-time-before-index
           occurrence check needs. Verified against data/gold/ (2026-08-19): 0 of the
           763 distinct concept ids referenced across every gold Circe set are
           Observation-domain Context-dependent or Clinical Observation class; gold's
           only legitimate Observation-domain use is concept_class_id 'Clinical
           Finding', untouched by this filter.

        Caller MUST gate this on the Condition domain. The Survey filter would drop
        valid questionnaire concepts in Observation criteria; the Procedure filter is
        inapplicable to Procedure-domain criteria; the history-of filter would drop
        valid Clinical Finding concepts in genuine Observation-domain criteria. See
        drop_qualitative_findings for the Measurement-domain analog.

        Args:
            concept_ids: Selected concept IDs for a Condition-domain criterion.

        Returns:
            The same IDs in order, minus wrong-entity members. Returns [] when every
            member is a wrong-entity concept — the caller falls through to the RAG
            fallback so the miss is recorded, not silently kept with the wrong entity.
            Returns the input unchanged when the database is unreachable (fail-open on
            connectivity; do NOT fail-open when the lookup ran and all are wrong).
        """
        if not concept_ids:
            return []

        deduped = self._dedupe_preserve_order(concept_ids)
        if not _check_db():
            return deduped

        try:
            from sqlalchemy import text
            from src.utils.db import get_db

            wrong_entity_query = text(f"""
                SELECT concept_id
                FROM {self.schema}.concept
                WHERE concept_id = ANY(:cids)
                  AND (
                    concept_class_id IN ('Survey', 'Question')
                    OR domain_id = 'Procedure'
                    OR (
                      domain_id = 'Observation'
                      AND concept_class_id IN ('Context-dependent', 'Clinical Observation')
                    )
                  )
                  AND invalid_reason IS NULL
            """)
            with next(get_db()) as db:
                rows = db.execute(wrong_entity_query, {"cids": deduped}).fetchall()
            wrong_entity_ids = {row[0] for row in rows}
        except Exception as exc:
            logger.debug("[Logician] Wrong-entity class lookup failed: %s", exc)
            return deduped

        if not wrong_entity_ids:
            return deduped

        kept = [cid for cid in deduped if cid not in wrong_entity_ids]
        if not kept:
            # All selected concepts are wrong entity type (e.g. sole LOINC Survey for
            # 'History of stroke', sole Procedure for 'AF ablation').  Keeping them
            # satisfies the empty-list concern but violates intent: the reranker picked
            # the wrong entity, not no entity.  Return [] so the caller (via
            # _recommend_seeded_concept_set) falls through to the RAG fallback and,
            # if that also fails, the criterion is recorded in _unmappedCriteria via
            # the existing exception-handling path.  Plan-044 sole-map fix.
            logger.info(
                "[Logician] All %d Condition concept(s) are wrong-entity class "
                "(Survey/Question, Procedure, or Observation history-of) — dropping "
                "entire set to avoid intent violation: %s",
                len(deduped), sorted(deduped),
            )
            return []

        logger.info(
            "[Logician] Dropped %d wrong-entity concept(s) from a Condition set "
            "(Survey/Question class, Procedure domain, or Observation history-of): %s",
            len(wrong_entity_ids), sorted(wrong_entity_ids),
        )
        return kept

    def prune_empty_concepts(self, concept_ids: List[int]) -> List[int]:
        """
        Filters out concepts not present in patient data tables.
        Currently a passthrough — returns all IDs.
        """
        # TODO: Implement domain-aware pruning when DB is available.
        # For now, pass through all concepts to avoid blocking development.
        return self._dedupe_preserve_order(concept_ids)


logician = ConceptLogician()
