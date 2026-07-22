"""
Concept Set Refiner — Post-KG-expansion precision filter.

Sits between KG Expansion/Critic and Assembler to prune overbroad concepts.
Introduced per lab meeting 2026-03-09 consensus (3-model agreement).

Pipeline position:
  Vector Search → KG Expansion → Critic → **ConceptSetRefiner** → Assembler

Two-pass algorithm:
  Pass 1: Ancestor Subsumption — if both ancestor and descendant present, prune ancestor
  Pass 2: Footprint Guard — flag concepts with desc > FOOTPRINT_THRESHOLD as overbroad
"""

import os
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Set, TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.agents.agent2.kg_expander import KGConcept

logger = logging.getLogger(__name__)

# Concepts with more descendants than this are flagged as overbroad.
# Their includeDescendants will be set to false by the Assembler.
FOOTPRINT_THRESHOLD = 3000


@dataclass
class RefinementResult:
    """Output of the ConceptSetRefiner."""
    kept_ids: List[int] = field(default_factory=list)
    pruned_ids: List[int] = field(default_factory=list)       # removed by ancestor subsumption
    overbroad_ids: List[int] = field(default_factory=list)    # flagged for includeDescendants=false
    rollback_used: bool = False


class ConceptSetRefiner:
    """
    Post-KG-expansion concept set refinement.

    Reduces false positives by pruning overbroad concepts while preserving
    recall through hierarchy-aware subsumption analysis.
    
    Toggle: ENABLE_REFINER=0 to disable (default: enabled).
    """

    def _get_db_connection(self):
        """Create a new PostgreSQL connection (thread-safe: per-call)."""
        import psycopg2
        from src.settings import settings
        return psycopg2.connect(settings.DATABASE_URL)

    def _get_schema(self) -> str:
        from src.settings import settings
        return settings.CDM_SCHEMA

    def _should_include_descendants(self, concept_id: int, domain: str) -> bool:
        """Data-driven decision: include descendants based on hierarchy breadth.

        Uses concept_ancestor to determine if a concept's descendant tree is
        narrow enough to be useful (> 1) but not so broad it becomes noise (< 50000).

        Drug domain always returns True (existing behavior — drug ancestors like
        "Incretin mimetics" have descendants that are valid class members).

        Toggle: AGENT2_INCLUDE_DESCENDANTS_AUTO (default "true").
        When "false", reverts to old behavior (always False for ancestors).

        Fallback: If DB query fails, defaults to True for Condition domain
        (safe default matching Gold behavior).
        """
        auto_mode = os.environ.get("AGENT2_INCLUDE_DESCENDANTS_AUTO", "true").lower()
        if auto_mode != "true":
            # Old behavior: ancestors/climb always get includeDescendants=False
            return False

        if domain == "Drug":
            return True

        desc_count = self._get_single_descendant_count(concept_id)
        if desc_count is None:
            # DB unavailable — safe default for Condition domain
            return domain == "Condition"

        return 1 < desc_count < 50000

    def _get_single_descendant_count(self, concept_id: int) -> Optional[int]:
        """Get descendant count for a single concept from concept_ancestor.

        Returns None if DB query fails (caller should use fallback logic).
        """
        conn = None
        try:
            conn = self._get_db_connection()
            if conn is None:
                return None
            schema = self._get_schema()
            cur = conn.cursor()
            cur.execute(f"""
                SELECT COUNT(DISTINCT descendant_concept_id)
                FROM {schema}.concept_ancestor
                WHERE ancestor_concept_id = %s
                  AND ancestor_concept_id != descendant_concept_id
            """, (concept_id,))
            row = cur.fetchone()
            cur.close()
            return row[0] if row else 0
        except Exception as e:
            logger.warning(f"[Refiner] Descendant count query failed for {concept_id}: {e}")
            return None
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def refine(
        self,
        seed_ids: List[int],
        kg_concepts: List["KGConcept"],
        query_text: str,
        domain_hint: str = None,
    ) -> RefinementResult:
        """
        Refine KG expansion output by pruning overbroad concepts.

        Args:
            seed_ids: Original seed concept IDs (NEVER pruned).
            kg_concepts: KG-expanded concepts (unique_kg from workflow).
            query_text: Original clinical query for logging.

        Returns:
            RefinementResult with kept_ids, pruned_ids, overbroad_ids.
        """
        result = RefinementResult()
        seed_set = set(seed_ids)

        if not kg_concepts:
            result.kept_ids = list(seed_ids)
            return result

        # ── Pass 1: Relation-Aware Ancestor Subsumption ──
        # Only target concepts added via "ancestor" or "ancestor_climb" relationship.
        # If any non-ancestor concept is a descendant of this ancestor → prune ancestor.
        ancestor_candidates = [
            c for c in kg_concepts
            if c.relationship in ("ancestor", "ancestor_climb")
        ]
        non_ancestor_concepts = [
            c for c in kg_concepts
            if c.relationship not in ("ancestor", "ancestor_climb")
        ]

        subsumed_ids: Set[int] = set()
        if ancestor_candidates and non_ancestor_concepts:
            subsumed_ids = self._find_subsumed_ancestors(
                ancestor_ids=[c.concept_id for c in ancestor_candidates],
                descendant_ids=[c.concept_id for c in non_ancestor_concepts] + list(seed_set),
            )
            if subsumed_ids:
                logger.info(
                    f"[Refiner] Pass 1: {len(subsumed_ids)} ancestors subsumed "
                    f"for query '{query_text}': {subsumed_ids}"
                )

        # ── Pass 2: includeDescendants Policy ──
        # Lab meeting 2026-03-10 consensus (refined after ablation):
        # - Seeds: includeDescendants=true (query directly asked for them)
        # - Siblings: includeDescendants=true (same granularity as seed)
        # - Ancestors: includeDescendants=false (broader → descendant explosion)
        # - Ancestor_climb: includeDescendants=false (by definition broader)
        # - Unknown/other: includeDescendants=true (conservative default)
        #
        # Toggle: INCLUDE_DESC_SEEDS_ONLY=0 to revert to legacy threshold mode.
        seeds_only = os.environ.get("INCLUDE_DESC_SEEDS_ONLY", "1") != "0"
        overbroad: Set[int] = set()

        if seeds_only:
            # Relationship-aware policy: ancestors/climb → false, rest → true
            # EXCEPTION: Drug domain — ancestor expansion is essential because
            # Drug ancestors (e.g., GLP1-RA → "Incretin mimetics") have
            # descendants that are valid drug class members, unlike Condition
            # ancestors that explode into 100K+ descendants.
            if domain_hint == "Drug":
                logger.info(
                    f"[Refiner] Pass 2 (hybrid): skipped ancestor gating "
                    f"for Drug domain query '{query_text}'"
                )
            else:
                for c in kg_concepts:
                    if c.concept_id not in subsumed_ids and c.concept_id not in seed_set:
                        if c.relationship in ("ancestor", "ancestor_climb"):
                            if not self._should_include_descendants(c.concept_id, domain_hint or ""):
                                overbroad.add(c.concept_id)
                            else:
                                logger.info(
                                    f"[Refiner] Pass 2: data-driven includeDescendants=true "
                                    f"for ancestor {c.concept_id} (query '{query_text}')"
                                )
                if overbroad:
                    logger.info(
                        f"[Refiner] Pass 2 (hybrid): {len(overbroad)} ancestor/climb concepts "
                        f"→ includeDescendants=false for query '{query_text}'"
                    )

            # ── Pass 3: Footprint Guard (on top of hybrid) ──
            # Codex review 2026-03-11: approved as separate pass.
            # Targets sibling/maps_to concepts with desc > threshold → includeDescendants=false.
            # Seeds are NEVER affected. Ancestors already handled by Pass 2.
            # Toggle: FOOTPRINT_GUARD_IN_HYBRID=0 to disable.
            footprint_guard = os.environ.get("FOOTPRINT_GUARD_IN_HYBRID", "0") != "0"
            if footprint_guard:
                threshold = int(os.environ.get(
                    "REFINER_FOOTPRINT_THRESHOLD", "1000"
                ))
                # Only check non-seed, non-subsumed, non-ancestor concepts
                guard_targets = [
                    c for c in kg_concepts
                    if c.concept_id not in subsumed_ids
                    and c.concept_id not in seed_set
                    and c.concept_id not in overbroad  # not already flagged by Pass 2
                ]
                if guard_targets:
                    # Fetch descendant counts for concepts that need it
                    need_count = [c for c in guard_targets if c.descendant_count == 0]
                    if need_count:
                        desc_counts = self._batch_get_descendant_counts(
                            [c.concept_id for c in need_count]
                        )
                        for c in need_count:
                            if c.concept_id in desc_counts:
                                c.descendant_count = desc_counts[c.concept_id]
                    pass3_overbroad = set()
                    for c in guard_targets:
                        if c.descendant_count > threshold:
                            pass3_overbroad.add(c.concept_id)
                    if pass3_overbroad:
                        logger.info(
                            f"[Refiner] Pass 3 (footprint guard): {len(pass3_overbroad)} "
                            f"concepts with desc > {threshold} "
                            f"→ includeDescendants=false for query '{query_text}': "
                            f"{pass3_overbroad}"
                        )
                        overbroad |= pass3_overbroad
        else:
            # Legacy: static threshold mode
            threshold = int(os.environ.get("REFINER_FOOTPRINT_THRESHOLD", str(FOOTPRINT_THRESHOLD)))
            concepts_needing_count = [
                c for c in kg_concepts
                if c.concept_id not in subsumed_ids and c.descendant_count == 0
            ]
            if concepts_needing_count:
                desc_counts = self._batch_get_descendant_counts(
                    [c.concept_id for c in concepts_needing_count]
                )
                for c in concepts_needing_count:
                    if c.concept_id in desc_counts:
                        c.descendant_count = desc_counts[c.concept_id]
            for c in kg_concepts:
                if c.concept_id not in subsumed_ids and c.concept_id not in seed_set:
                    if c.descendant_count > threshold:
                        overbroad.add(c.concept_id)
            if overbroad:
                logger.info(
                    f"[Refiner] Pass 2 (legacy): {len(overbroad)} overbroad concepts "
                    f"(desc > {threshold}) for query '{query_text}': {overbroad}"
                )

        # ── Build result ──
        kept = list(seed_ids)  # Seeds always first
        pruned = []

        for c in kg_concepts:
            if c.concept_id in seed_set:
                continue  # Already in kept via seed_ids
            if c.concept_id in subsumed_ids:
                pruned.append(c.concept_id)
            else:
                kept.append(c.concept_id)

        # ── Rollback Guard ──
        # If pruning was too aggressive (kept fewer than seeds), rollback.
        if len(kept) < len(seed_ids):
            logger.warning(
                f"[Refiner] ROLLBACK: kept ({len(kept)}) < seeds ({len(seed_ids)}) "
                f"for query '{query_text}'. Restoring all candidates."
            )
            kept = list(seed_ids) + [c.concept_id for c in kg_concepts if c.concept_id not in seed_set]
            pruned = []
            overbroad = set()
            result.rollback_used = True

        result.kept_ids = kept
        result.pruned_ids = pruned
        result.overbroad_ids = list(overbroad)

        logger.info(
            f"[Refiner] Result for '{query_text}': "
            f"kept={len(result.kept_ids)}, pruned={len(result.pruned_ids)}, "
            f"overbroad={len(result.overbroad_ids)}, rollback={result.rollback_used}"
        )

        return result

    def _find_subsumed_ancestors(
        self,
        ancestor_ids: List[int],
        descendant_ids: List[int],
    ) -> Set[int]:
        """
        Batch check: which ancestor_ids have at least one descendant in descendant_ids?
        
        Uses concept_ancestor table with set-wise SQL (Codex review: avoid O(n²) loops).
        An ancestor is "subsumed" if a more specific concept (descendant) is already
        in the kept set, making the ancestor redundant.
        
        Returns set of subsumed ancestor concept_ids.
        """
        if not ancestor_ids or not descendant_ids:
            return set()

        try:
            conn = self._get_db_connection()
            schema = self._get_schema()
            cur = conn.cursor()

            # Single batch query: find ancestors that have at least one descendant
            # in the candidate set. min_levels_of_separation > 0 avoids self-matches.
            cur.execute(f"""
                SELECT DISTINCT ca.ancestor_concept_id
                FROM {schema}.concept_ancestor ca
                WHERE ca.ancestor_concept_id = ANY(%s)
                  AND ca.descendant_concept_id = ANY(%s)
                  AND ca.min_levels_of_separation > 0
            """, (ancestor_ids, descendant_ids))

            subsumed = {row[0] for row in cur.fetchall()}
            cur.close()
            conn.close()
            return subsumed

        except Exception as e:
            logger.warning(f"[Refiner] Ancestor subsumption query failed: {e}")
            return set()

    def _batch_get_descendant_counts(self, concept_ids: List[int]) -> dict:
        """Batch get descendant counts from concept_ancestor."""
        if not concept_ids:
            return {}
        try:
            conn = self._get_db_connection()
            schema = self._get_schema()
            cur = conn.cursor()
            cur.execute(f"""
                SELECT ancestor_concept_id, COUNT(DISTINCT descendant_concept_id) - 1
                FROM {schema}.concept_ancestor
                WHERE ancestor_concept_id = ANY(%s)
                GROUP BY ancestor_concept_id
            """, (concept_ids,))
            counts = {row[0]: row[1] for row in cur.fetchall()}
            cur.close()
            conn.close()
            return counts
        except Exception as e:
            logger.warning(f"[Refiner] Descendant count query failed: {e}")
            return {}


# ── Lazy Singleton ──

_refiner_instance: Optional[ConceptSetRefiner] = None


def get_concept_set_refiner() -> ConceptSetRefiner:
    """Get or create ConceptSetRefiner instance."""
    global _refiner_instance
    if _refiner_instance is None:
        _refiner_instance = ConceptSetRefiner()
    return _refiner_instance
