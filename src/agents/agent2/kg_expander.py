"""
OMOP Knowledge Graph Expander — Neo4j-based concept expansion for KG-RAG.

Uses Neo4j to traverse the OMOP concept hierarchy and find related concepts:
- Descendants: sub-concepts of a given concept (e.g., Stroke → Cerebral hemorrhage)
- Siblings: concepts sharing the same parent (e.g., Stable angina ↔ Unstable angina)
- Maps-to: cross-vocabulary mappings (e.g., ICD → SNOMED Standard)

Architecture reference: KRAGEN (Bioinformatics, 2024)
  KRAGEN: Neo4j (KG) + Weaviate (Vector) + GoT prompting
  ARTEMIS:  Neo4j (KG) + ChromaDB (Vector) + LLM Critic
"""

import os
import json
import hashlib
import logging
import math
import threading
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path

from neo4j import GraphDatabase

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────
# Configurable ancestor climb limit. Reduced from 100 to 40 to limit over-expansion.
# When results exceed this limit, they are sorted by IC descending (most specific first)
# and truncated.
DEFAULT_KG_CLIMB_LIMIT = int(os.getenv("AGENT2_KG_CLIMB_LIMIT", "40"))

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "artemis_neo4j")

# Total standard concepts in OMOP vocabulary (for IC calculation)
# IC(c) = -log2(descendants(c) / TOTAL_STANDARD_CONCEPTS)
# This value is from: SELECT COUNT(*) FROM concept WHERE standard_concept = 'S'
# Stable across minor vocabulary version changes due to log scale.
TOTAL_STANDARD_CONCEPTS = 2_750_364

# IC threshold: higher = more specific.
# IC > 8.0 ≈ descendants < ~10,700 (exact: 2,750,364 / 2^8 = 10,743)
# Empirically validated on LEADER/TROY benchmark (2026-03-02)
IC_THRESHOLD = 8.0

KG_CACHE_FILE = Path("data/cache/kg_cache.json")


@dataclass
class KGConcept:
    """A concept node from the Knowledge Graph."""
    concept_id: int
    concept_name: str
    domain_id: str
    vocabulary_id: str
    concept_class_id: str = ""
    relationship: str = ""       # How this concept relates to the seed
    separation: int = 0          # Distance from the seed concept
    descendant_count: int = 0    # Number of descendants in CONCEPT_ANCESTOR


def _truncate_by_ic(concepts: List[KGConcept], limit: int) -> List[KGConcept]:
    """Truncate concepts list by IC (Information Content) descending.

    When the number of concepts exceeds the limit, sort by IC descending
    (most specific first) and keep only the top `limit` results.
    IC(c) = -log2(descendants(c) / TOTAL_STANDARD_CONCEPTS).
    If descendant_count is 0 (leaf or unknown), IC is maximal (20.0).

    Args:
        concepts: List of KGConcept objects with descendant_count populated.
        limit: Maximum number of concepts to retain.

    Returns:
        Truncated list sorted by IC descending.
    """
    if len(concepts) <= limit:
        return concepts

    def _ic(c: KGConcept) -> float:
        if c.descendant_count <= 0:
            return 20.0
        return -math.log2(c.descendant_count / TOTAL_STANDARD_CONCEPTS)

    sorted_concepts = sorted(concepts, key=_ic, reverse=True)
    truncated = sorted_concepts[:limit]
    logger.debug(
        f"[KG Expander] Truncated {len(concepts)} → {limit} concepts by IC "
        f"(dropped {len(concepts) - limit} broad concepts)"
    )
    return truncated


class KGExpander:
    """
    Expands a seed concept into related concepts using the OMOP Knowledge Graph in Neo4j.
    
    Strategies:
    - "descendants": Find all sub-concepts (e.g., Stroke → types of stroke)
    - "siblings": Find concepts with the same parent (e.g., Stable ↔ Unstable angina)
    - "maps_to": Find cross-vocabulary mappings
    - "clinical": All of the above (default, legacy)
    - "clinical_anchor": Anchor-only mode — NO descendants.
        Returns only ancestors + siblings + maps_to as anchor concepts.
        Delegates descendant expansion to Circe `includeDescendants: true`.
        Reduces concept explosion (e.g., ~1,300 → ~100-200 for LEADER).
    """
    
    def __init__(self, use_cache: bool = True):
        self._driver = None
        self._use_cache = use_cache
        self._cache: Dict[str, List[Dict]] = {}
        self._cache_lock = threading.Lock()
        if use_cache:
            self._load_cache()
        # Mandatory: fail fast if Neo4j is unreachable
        self._verify_neo4j()

    def _verify_neo4j(self) -> None:
        """Verify Neo4j connectivity at startup. Fails fast if unreachable."""
        try:
            _ = self.driver  # triggers verify_connectivity()
            logger.info("[KG Expander] ✅ Neo4j health check passed")
        except Exception as e:
            raise RuntimeError(
                f"[KG Expander] ❌ Neo4j is not reachable at {NEO4J_URI}. "
                f"Start it with: docker start telos-neo4j\n"
                f"Error: {e}"
            ) from e

    def _load_cache(self):
        """Load KG expansion cache from disk."""
        if KG_CACHE_FILE.exists():
            try:
                with open(KG_CACHE_FILE) as f:
                    self._cache = json.load(f)
                logger.info(f"[KG Cache] Loaded {len(self._cache)} entries")
            except (json.JSONDecodeError, IOError):
                self._cache = {}

    def save_cache(self):
        """Persist KG expansion cache to disk. Call once after batch processing."""
        KG_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with self._cache_lock:
            with open(KG_CACHE_FILE, "w") as f:
                json.dump(self._cache, f, ensure_ascii=False)

    @staticmethod
    def _cache_key(concept_id: int, strategy: str, max_sep: int,
                   limit: int, domain_filter: Optional[str]) -> str:
        raw = f"{concept_id}|{strategy}|{max_sep}|{limit}|{domain_filter or ''}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
    
    @property
    def driver(self):
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)
            )
            self._driver.verify_connectivity()
            logger.info(f"[KG Expander] Connected to Neo4j at {NEO4J_URI}")
        return self._driver
    
    def close(self):
        if self._driver:
            self._driver.close()
            self._driver = None
    
    # ── Core Expansion Methods ─────────────────────────────
    
    @staticmethod
    def compute_ic(descendant_count: int) -> float:
        """Compute Information Content for a concept.
        
        IC(c) = -log2(descendants(c) / total_standard_concepts)
        Higher IC = more specific concept.
        Lower IC = more general concept.
        
        Examples (OMOP, total=2,750,364):
            Cerebral infarction (76 desc)  → IC = 15.14
            Disorder of brain  (3,774 desc) → IC =  9.51
            Disease            (91,661 desc) → IC =  4.91
        """
        if descendant_count <= 0:
            return 20.0  # leaf node = maximally specific
        return -math.log2(descendant_count / TOTAL_STANDARD_CONCEPTS)

    def expand(
        self,
        concept_id: int,
        strategy: str = "clinical",
        max_sep: int = 3,
        limit: int = 50,
        domain_filter: Optional[str] = None,
    ) -> List[KGConcept]:
        """
        Expand a concept using the specified strategy.
        
        Args:
            concept_id: OMOP concept ID to expand from
            strategy: "descendants", "siblings", "maps_to", "ancestor_climb",
                      "clinical" (all including ancestor_climb), or
                      "clinical_anchor" (anchor-only, no descendants)
            max_sep: Maximum separation for descendants (default: 3)
            limit: Maximum total results (default: 50)
            domain_filter: Optional domain to filter results (e.g., "Condition")
        
        Returns:
            List of related KGConcept objects
        """
        # Check cache first
        if self._use_cache:
            ckey = self._cache_key(concept_id, strategy, max_sep, limit, domain_filter)
            with self._cache_lock:
                cached = self._cache.get(ckey)
            if cached is not None:
                logger.debug(f"[KG Cache] HIT for concept {concept_id}")
                return [KGConcept(**c) for c in cached]

        results = []
        
        # ── clinical_anchor: Anchor-Only Mode (no descendants) ──
        # Returns ancestors + siblings + maps_to only.
        # Descendant expansion is delegated to Circe includeDescendants.
        # Lab meeting 2026-03-05 합의: KG Expander = "어떤 concept을 seed로 쓸지"
        if strategy == "clinical_anchor":
            # Phase 2.1: ancestors + siblings + maps_to + ancestor_climb
            # Descendants만 제외 (overgeneration 주범), ancestor_climb은 Recall에 기여
            results.extend(self.get_ancestors(concept_id, max_sep=2))
            results.extend(self.get_siblings(concept_id, domain_filter))
            results.extend(self.get_maps_to(concept_id))
            climbed = self.ancestor_climb(
                concept_id, domain_filter=domain_filter, limit=limit
            )
            results.extend(climbed)
            logger.info(
                f"[KG Expander] clinical_anchor for {concept_id}: "
                f"{len(results)} concepts (no descendants, with climb)"
            )
        
        # ── Legacy strategies ──
        elif strategy in ("descendants", "clinical"):
            desc = self.get_descendants(concept_id, max_sep, domain_filter)
            if desc:
                results.extend(desc)
            elif strategy == "clinical":
                # 2-hop: leaf node → go up to parent → expand down
                results.extend(
                    self.expand_from_ancestors(concept_id, max_sep, domain_filter)
                )
        
        if strategy in ("siblings", "clinical"):
            results.extend(self.get_siblings(concept_id, domain_filter))
        
        if strategy in ("maps_to", "clinical"):
            results.extend(self.get_maps_to(concept_id))
        
        # IC-based Ancestor Climbing: go UP, then expand DOWN
        if strategy in ("ancestor_climb", "clinical"):
            climbed = self.ancestor_climb(
                concept_id, domain_filter=domain_filter, limit=limit
            )
            results.extend(climbed)
        
        # Anchor & Climb: add ancestors as direct candidates
        # so the Critic can choose the right hierarchy level
        if strategy == "clinical":
            ancestors = self.get_ancestors(concept_id, max_sep=2)
            results.extend(ancestors)
        
        # Deduplicate by concept_id, keeping first occurrence
        seen = set()
        unique = []
        for c in results:
            if c.concept_id not in seen and c.concept_id != int(concept_id):
                seen.add(c.concept_id)
                unique.append(c)
        
        # Apply limit
        final = unique[:limit]

        # Save to in-memory cache (disk write deferred to save_cache())
        if self._use_cache:
            ckey = self._cache_key(concept_id, strategy, max_sep, limit, domain_filter)
            with self._cache_lock:
                self._cache[ckey] = [asdict(c) for c in final]

        return final
    
    def expand_from_ancestors(
        self,
        concept_id: int,
        max_sep: int = 3,
        domain_filter: Optional[str] = None,
    ) -> List[KGConcept]:
        """
        2-hop expansion: go up to parent via IS_A, then expand descendants.
        
        Used when a concept is a leaf node (no direct descendants).
        E.g., "Completed stroke" → parent "Cerebrovascular accident" → descendants
        
        Uses IS_A edges (direct parent-child) instead of HAS_DESCENDANT (closure).
        """
        domain_clause = "AND desc.domain_id = $domain" if domain_filter else ""
        
        query = f"""
            MATCH (seed:Concept {{concept_id: $concept_id}})
                  -[:IS_A]->(parent:Concept)
                  <-[:IS_A*1..{max_sep}]-(desc:Concept)
            WHERE desc.concept_id <> $concept_id
              {domain_clause}
            RETURN DISTINCT desc.concept_id AS cid, desc.concept_name AS name,
                   desc.domain_id AS domain, desc.vocabulary_id AS vocab,
                   desc.concept_class_id AS cclass,
                   parent.concept_name AS parent_name
            LIMIT 50
        """
        params = {"concept_id": str(concept_id)}
        if domain_filter:
            params["domain"] = domain_filter
        
        with self.driver.session() as session:
            result = session.run(query, **params)
            concepts = [
                KGConcept(
                    concept_id=int(r["cid"]),
                    concept_name=r["name"],
                    domain_id=r["domain"],
                    vocabulary_id=r["vocab"],
                    concept_class_id=r["cclass"] or "",
                    relationship=f"2-hop (via parent: {r['parent_name']})",
                    separation=2,  # parent hop + at least 1 descendant hop
                )
                for r in result
            ]
        
        logger.info(f"[KG Expander] 2-hop expansion for {concept_id}: "
                   f"found {len(concepts)} concepts via ancestors")
        return concepts
    
    def get_descendants(
        self,
        concept_id: int,
        max_sep: int = 3,
        domain_filter: Optional[str] = None,
    ) -> List[KGConcept]:
        """Find descendant concepts via reverse IS_A traversal.
        
        Uses IS_A edges (direct parent-child) instead of HAS_DESCENDANT (closure).
        Variable-length path [:IS_A*1..max_sep] limits traversal depth.
        """
        domain_clause = "AND d.domain_id = $domain" if domain_filter else ""
        
        query = f"""
            MATCH (a:Concept {{concept_id: $concept_id}})<-[:IS_A*1..{max_sep}]-(d:Concept)
            WHERE d.concept_id <> $concept_id
              {domain_clause}
            RETURN DISTINCT d.concept_id AS cid, d.concept_name AS name, 
                   d.domain_id AS domain, d.vocabulary_id AS vocab,
                   d.concept_class_id AS cclass
            LIMIT 50
        """
        params = {"concept_id": str(concept_id)}
        if domain_filter:
            params["domain"] = domain_filter
        
        with self.driver.session() as session:
            result = session.run(query, **params)
            return [
                KGConcept(
                    concept_id=int(r["cid"]),
                    concept_name=r["name"],
                    domain_id=r["domain"],
                    vocabulary_id=r["vocab"],
                    concept_class_id=r["cclass"] or "",
                    relationship="descendant",
                    separation=0,  # exact hop count not available with var-length path
                )
                for r in result
            ]
    
    def get_siblings(
        self,
        concept_id: int,
        domain_filter: Optional[str] = None,
    ) -> List[KGConcept]:
        """
        Find sibling concepts (same parent via IS_A).
        
        This is crucial for resolving semantic reversal issues
        (e.g., finding "Unstable angina" when seed is "Stable angina").
        
        Pattern: seed -[:IS_A]-> parent <-[:IS_A]- sibling
        """
        domain_clause = "AND sib.domain_id = $domain" if domain_filter else ""
        
        query = f"""
            MATCH (seed:Concept {{concept_id: $concept_id}})
                  -[:IS_A]->(parent:Concept)
                  <-[:IS_A]-(sib:Concept)
            WHERE sib.concept_id <> $concept_id
              {domain_clause}
            RETURN DISTINCT sib.concept_id AS cid, sib.concept_name AS name,
                   sib.domain_id AS domain, sib.vocabulary_id AS vocab,
                   sib.concept_class_id AS cclass,
                   parent.concept_name AS parent_name
            LIMIT 30
        """
        params = {"concept_id": str(concept_id)}
        if domain_filter:
            params["domain"] = domain_filter
        
        with self.driver.session() as session:
            result = session.run(query, **params)
            return [
                KGConcept(
                    concept_id=int(r["cid"]),
                    concept_name=r["name"],
                    domain_id=r["domain"],
                    vocabulary_id=r["vocab"],
                    concept_class_id=r["cclass"] or "",
                    relationship=f"sibling (parent: {r['parent_name']})",
                    separation=1,
                )
                for r in result
            ]
    
    def get_maps_to(self, concept_id: int) -> List[KGConcept]:
        """Find concepts connected via MAPS_TO relationship."""
        query = """
            MATCH (c1:Concept {concept_id: $concept_id})-[:MAPS_TO]->(c2:Concept)
            RETURN c2.concept_id AS cid, c2.concept_name AS name,
                   c2.domain_id AS domain, c2.vocabulary_id AS vocab,
                   c2.concept_class_id AS cclass
            LIMIT 10
        """
        with self.driver.session() as session:
            result = session.run(query, concept_id=str(concept_id))
            return [
                KGConcept(
                    concept_id=int(r["cid"]),
                    concept_name=r["name"],
                    domain_id=r["domain"],
                    vocabulary_id=r["vocab"],
                    concept_class_id=r["cclass"] or "",
                    relationship="maps_to",
                    separation=0,
                )
                for r in result
            ]
    
    def get_ancestors(
        self,
        concept_id: int,
        max_sep: int = 2,
    ) -> List[KGConcept]:
        """Find ancestor concepts (parents, grandparents) via IS_A traversal.
        
        Descendant counts are fetched from PostgreSQL CONCEPT_ANCESTOR
        for accurate IC calculation (not from Neo4j graph structure).
        """
        query = f"""
            MATCH path = (d:Concept {{concept_id: $concept_id}})-[:IS_A*1..{max_sep}]->(a:Concept)
            RETURN a.concept_id AS cid, a.concept_name AS name,
                   a.domain_id AS domain, a.vocabulary_id AS vocab,
                   a.concept_class_id AS cclass,
                   length(path) AS sep
            ORDER BY length(path) ASC
            LIMIT 5
        """
        with self.driver.session() as session:
            result = session.run(query, concept_id=str(concept_id))
            raw_ancestors = list(result)
        
        if not raw_ancestors:
            return []
        
        # Get accurate descendant counts from PostgreSQL
        ancestor_ids = [r["cid"] for r in raw_ancestors]
        desc_counts = self._get_pg_descendant_counts(ancestor_ids)
        
        ancestors = [
            KGConcept(
                concept_id=int(r["cid"]),
                concept_name=r["name"],
                domain_id=r["domain"],
                vocabulary_id=r["vocab"],
                concept_class_id=r["cclass"] or "",
                relationship="ancestor",
                separation=r["sep"],
                descendant_count=desc_counts.get(int(r["cid"]), 0),
            )
            for r in raw_ancestors
        ]
        logger.info(f"[KG Expander] Ancestors for {concept_id}: "
                   f"{[(a.concept_name, a.descendant_count) for a in ancestors]}")
        return ancestors

    def ancestor_climb(
        self,
        concept_id: int,
        max_sep: int = 3,
        ic_threshold: float = IC_THRESHOLD,
        domain_filter: Optional[str] = None,
        limit: int | None = None,
    ) -> List[KGConcept]:
        """IC-based ancestor climbing: go UP (Neo4j), filter by IC (PostgreSQL), expand DOWN (Neo4j).
        
        Hybrid approach:
          - Neo4j: find ancestors + expand descendants (fast graph traversal)
          - PostgreSQL: get accurate descendant counts from concept_ancestor
            (Neo4j only has sep<=3 edges, so its desc_count is unreliable)
        
        Strategy:
          1. Find ancestors via Neo4j (up to max_sep levels)
          2. Get accurate desc_count from PostgreSQL concept_ancestor
          3. Filter by IC > threshold
          4. Pick best ancestor (most general that passes IC)
          5. Expand its descendants via Neo4j
        
        Args:
            concept_id: Seed concept to climb from
            max_sep: Maximum ancestor levels to climb (default: 3)
            ic_threshold: Minimum IC for ancestor to be valid (default: 8.0)
            domain_filter: Only climb within this domain
            limit: Maximum results from climbing (default: AGENT2_KG_CLIMB_LIMIT or 40)

        Returns:
            List of descendant concepts from valid ancestors, sorted by IC descending
            when truncation is applied.
        """
        if limit is None:
            limit = DEFAULT_KG_CLIMB_LIMIT
        # Step 1: Get ancestor candidates from Neo4j
        # Hard filters: same domain, SNOMED vocab, Disorder class only
        domain_anc_clause = "AND a.domain_id = $domain" if domain_filter else ""
        query = f"""
            MATCH path = (d:Concept {{concept_id: $concept_id}})-[:IS_A*1..{max_sep}]->(a:Concept)
            WHERE a.concept_class_id = 'Disorder'
              AND a.vocabulary_id = 'SNOMED'
              {domain_anc_clause}
            RETURN a.concept_id AS cid, a.concept_name AS name,
                   a.domain_id AS domain, a.vocabulary_id AS vocab,
                   a.concept_class_id AS cclass,
                   length(path) AS sep
            ORDER BY length(path) ASC
        """
        params = {"concept_id": str(concept_id)}
        if domain_filter:
            params["domain"] = domain_filter
        
        with self.driver.session() as session:
            result = session.run(query, **params)
            ancestors = list(result)
        
        if not ancestors:
            return []
        
        # Step 2: Get accurate desc_count from PostgreSQL
        ancestor_ids = [a["cid"] for a in ancestors]
        # Also get seed's desc_count for dynamic threshold
        all_ids_for_counts = ancestor_ids + [str(concept_id)]
        desc_counts = self._get_pg_descendant_counts(all_ids_for_counts)
        
        # Dynamic IC threshold: only TIGHTEN (never loosen) from static default
        # Specific seeds (high IC) → raise threshold to block broad ancestors
        # Broad seeds (low IC) → keep static threshold as-is
        seed_desc = desc_counts.get(int(concept_id), 0)
        seed_ic = self.compute_ic(seed_desc)
        dynamic_threshold = max(ic_threshold, seed_ic - 2.5)
        logger.info(
            f"[Ancestor Climb] Seed {concept_id}: IC={seed_ic:.1f}, "
            f"dynamic_threshold={dynamic_threshold:.1f} "
            f"(static={ic_threshold:.1f})"
        )
        
        # Step 3: Filter ancestors by dynamic IC
        valid_ancestors = []
        for a in ancestors:
            pg_desc = desc_counts.get(int(a["cid"]), 0)
            ic = self.compute_ic(pg_desc)
            ic_ok = ic > dynamic_threshold
            
            logger.debug(
                f"[Ancestor Climb] {a['name']} (sep={a['sep']}, "
                f"desc={pg_desc}, IC={ic:.2f}) "
                f"{'✅' if ic_ok else '❌'}"
            )
            
            if ic_ok:
                valid_ancestors.append((a, pg_desc, ic))
        
        if not valid_ancestors:
            logger.info(
                f"[Ancestor Climb] No valid ancestors for concept {concept_id} "
                f"(IC threshold={ic_threshold})"
            )
            return []
        
        # Step 4+5: Expand descendants of ALL valid ancestors (top-K union)
        # Sort by (min sep, max desc_count) — closest broadest first
        valid_ancestors.sort(key=lambda t: (t[0]["sep"], -t[1]))
        
        all_climbed: Dict[int, KGConcept] = {}  # dedupe by concept_id
        domain_clause = "AND desc.domain_id = $domain" if domain_filter else ""
        # KEY CHANGE: Use IS_A*1..3 instead of HAS_DESCENDANT (closure)
        # This limits expansion to 3 direct hops, preserving topology
        desc_query = f"""
            MATCH (a:Concept {{concept_id: $ancestor_id}})
                  <-[:IS_A*1..3]-(desc:Concept)
            WHERE desc.concept_id <> $ancestor_id
              {domain_clause}
            RETURN DISTINCT desc.concept_id AS cid, desc.concept_name AS name,
                   desc.domain_id AS domain, desc.vocabulary_id AS vocab,
                   desc.concept_class_id AS cclass
            LIMIT $limit
        """
        
        for anc, anc_desc, anc_ic in valid_ancestors:
            logger.info(
                f"[Ancestor Climb] Expanding {anc['name']} "
                f"(sep={anc['sep']}, desc={anc_desc}, IC={anc_ic:.2f})"
            )
            desc_params = {"ancestor_id": str(anc["cid"]), "limit": limit}
            if domain_filter:
                desc_params["domain"] = domain_filter
            
            with self.driver.session() as session:
                result = session.run(desc_query, **desc_params)
                for r in result:
                    cid = int(r["cid"])
                    if cid not in all_climbed:
                        all_climbed[cid] = KGConcept(
                            concept_id=cid,
                            concept_name=r["name"],
                            domain_id=r["domain"],
                            vocabulary_id=r["vocab"],
                            concept_class_id=r["cclass"] or "",
                            relationship=f"ancestor_climb (via {anc['name']}, IC={anc_ic:.1f})",
                            separation=0,
                            descendant_count=0,
                        )
            
            # Stop early if we have enough
            if len(all_climbed) >= limit:
                break
        
        raw_climbed = list(all_climbed.values())
        # IC-based truncation: when results exceed limit, keep most specific concepts
        climbed = _truncate_by_ic(raw_climbed, limit)

        ancestors_used = [a[0]["name"] for a in valid_ancestors[:min(3, len(valid_ancestors))]]
        logger.info(
            f"[Ancestor Climb] Union from {len(valid_ancestors)} ancestors → "
            f"{len(climbed)} unique descendants "
            f"(ancestors: {', '.join(ancestors_used)}{'...' if len(valid_ancestors) > 3 else ''})"
        )
        return climbed
    
    def _get_pg_descendant_counts(self, concept_ids: List[int]) -> Dict[int, int]:
        """Get accurate descendant counts from PostgreSQL concept_ancestor.
        
        This is necessary because Neo4j only has sep<=3 edges loaded,
        so its descendant counts are partial and unreliable for IC calculation.
        """
        import psycopg2
        import os
        
        db_host = os.getenv("OMOP_DB_HOST", "localhost")
        db_port = os.getenv("OMOP_DB_PORT", "5432")
        db_name = os.getenv("OMOP_DB_NAME", "postgres")
        db_user = os.getenv("OMOP_DB_USER", "postgres")
        db_pass = os.getenv("OMOP_DB_PASS", "mypass")
        schema = os.getenv("CDM_SCHEMA", "synthea23m")
        
        try:
            # Cast to int — Neo4j CSV import stores IDs as strings
            int_ids = [int(cid) for cid in concept_ids]
            conn = psycopg2.connect(
                host=db_host, port=db_port, dbname=db_name,
                user=db_user, password=db_pass
            )
            cur = conn.cursor()
            cur.execute(f"""
                SELECT ancestor_concept_id, COUNT(DISTINCT descendant_concept_id)
                FROM {schema}.concept_ancestor
                WHERE ancestor_concept_id = ANY(%s)
                  AND ancestor_concept_id <> descendant_concept_id
                GROUP BY ancestor_concept_id
            """, (int_ids,))
            result = {row[0]: row[1] for row in cur.fetchall()}
            cur.close()
            conn.close()
            return result
        except Exception as e:
            logger.warning(f"[Ancestor Climb] PostgreSQL desc_count lookup failed: {e}")
            return {}
    
    # ── Utility Methods ────────────────────────────────────
    
    def get_concept_info(self, concept_id: int) -> Optional[KGConcept]:
        """Get basic info about a concept."""
        query = """
            MATCH (c:Concept {concept_id: $concept_id})
            RETURN c.concept_id AS cid, c.concept_name AS name,
                   c.domain_id AS domain, c.vocabulary_id AS vocab,
                   c.concept_class_id AS cclass
        """
        with self.driver.session() as session:
            result = session.run(query, concept_id=str(concept_id))
            record = result.single()
            if record:
                return KGConcept(
                    concept_id=int(record["cid"]),
                    concept_name=record["name"],
                    domain_id=record["domain"],
                    vocabulary_id=record["vocab"],
                    concept_class_id=record["cclass"] or "",
                )
            return None
    
    def graph_stats(self) -> Dict:
        """Get basic graph statistics."""
        with self.driver.session() as session:
            nodes = session.run("MATCH (c:Concept) RETURN count(c) AS cnt").single()["cnt"]
            rels = session.run("MATCH ()-[r]->() RETURN count(r) AS cnt").single()["cnt"]
        return {"nodes": nodes, "relationships": rels}


# ── Module-level singleton ─────────────────────────────────
_expander: Optional[KGExpander] = None


def get_kg_expander() -> KGExpander:
    """Get or create the KG expander singleton.
    
    Raises RuntimeError if Neo4j is not reachable.
    """
    global _expander
    if _expander is None:
        _expander = KGExpander()  # _verify_neo4j() called in __init__
    return _expander
