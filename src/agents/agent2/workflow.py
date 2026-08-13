"""
Agent 2 (Intelligent Mapper) - Semantic Mapping Workflow.

Executes the full Semantic Mapping pipeline with KG-RAG:
Text -> [Complexity Check] -> [Fast Path | Slow Path] -> [KG Expansion] -> [LLM Critic] -> IDs

Enhanced with patterns from artemis_agent:
- Pattern 1: Complexity Router (Fast/Slow Path)
- Pattern 2: Rule-Based Fallback Extraction
- Pattern 3: Gap Analysis
- Pattern 4: Batch Processing
- Pattern 5: Ambiguous Term Detection (in ComplexityRouter)
- KG-RAG: Neo4j graph traversal + LLM multi-select (KRAGEN architecture)
"""

import os
import re
import threading
from typing import List, Optional, Dict, Any, Union
from concurrent.futures import ThreadPoolExecutor
import logging
import time

# @MX:NOTE: Configurable max thread-pool workers for Agent 2 parallel operations.
# Override via AGENT2_MAX_WORKERS env var. Default 16 balances concurrency with resource usage.
MAX_WORKERS = int(os.environ.get("AGENT2_MAX_WORKERS", "16"))

# @MX:NOTE: Module-level ThreadedConnectionPool for Drug class ATC expansion.
# Avoids creating+destroying a DB connection per criterion (up to 16 concurrent workers).
_db_pool = None
_db_pool_lock = threading.Lock()


def _get_db_pool():
    """Return a shared ThreadedConnectionPool, creating it on first call.

    Uses double-checked locking for thread safety. Falls back to ``None``
    when the pool cannot be created (caller should use direct connect).
    """
    global _db_pool
    if _db_pool is not None:
        return _db_pool
    with _db_pool_lock:
        if _db_pool is None:
            try:
                import psycopg2.pool
                from src.settings import settings
                _db_pool = psycopg2.pool.ThreadedConnectionPool(
                    minconn=1,
                    maxconn=MAX_WORKERS,
                    dsn=settings.DATABASE_URL,
                )
                logger.info(
                    f"[Agent 2] DB connection pool created (minconn=1, maxconn={MAX_WORKERS})"
                )
            except Exception as e:
                logger.warning(f"[Agent 2] DB pool creation failed, will use direct connect: {e}")
                return None
        return _db_pool


from src.agents.agent2.regex_rules import CodePatternMatcher
from src.agents.agent2.retriever import retriever, CandidateConcept
from src.agents.agent2.reranker import get_reranker
from src.agents.agent2.logic import logician
from src.agents.agent2.complexity_router import get_router, ComplexityRouter
from src.agents.agent2.rule_extractor import get_extractor, RuleExtractor
from src.agents.agent2.abbreviation_expander import expand_abbreviation, expand_in_context
from src.agents.agent2.drug_class_expander import expand_drug_class_via_vocab
from src.agents.agent2.umls_synonym_expander import get_umls_expander
from src.agents.agent2.kg_expander import get_kg_expander
from src.agents.agent2.critic import get_critic
from src.agents.agent2.concept_set_refiner import get_concept_set_refiner
from src.models.ir import MappingResult, GapReport
from src.utils.exceptions import LLMConfigurationError

logger = logging.getLogger(__name__)
logger.info(f"[Agent 2] MAX_WORKERS={MAX_WORKERS} (from AGENT2_MAX_WORKERS env var)")


def _exact_name_concept(query_text: str, domain_hint: Optional[str]) -> Optional[CandidateConcept]:
    """Look the query up as a literal standard concept name.

    The vector retriever answers "what is similar", which is not the same question as
    "what has exactly this name", and it can miss the exact term entirely: asked for
    'linagliptin' it returned sitagliptin first and left linagliptin out of the top 20.
    A name equality check is the cheap deterministic answer that case needed.

    :param query_text: the entity text to match against ``concept_name``
    :param domain_hint: when given, restricts to that ``domain_id`` — this is what
        separates the LOINC answer 'Ticagrelor' from the RxNorm ingredient
    :returns: the single matching concept, or ``None`` when there is no match or more
        than one. Declining on ambiguity mirrors the MeSH alias rule: two candidates
        mean the name does not identify a concept on its own, so guessing here would
        reintroduce exactly the confident-wrong-answer failure this function exists to
        prevent.
    """
    if not query_text or not query_text.strip():
        return None

    sql = """
        SELECT concept_id, concept_name, domain_id, vocabulary_id, concept_class_id
        FROM {schema}.concept
        WHERE LOWER(concept_name) = LOWER(%s)
          AND standard_concept = 'S'
          AND invalid_reason IS NULL
    """
    params: list[Any] = [query_text.strip()]
    if domain_hint:
        sql += " AND domain_id = %s"
        params.append(domain_hint)
    sql += " LIMIT 2"  # two is enough to know it is ambiguous

    pool = _get_db_pool()
    conn = None
    try:
        from src.settings import settings
        conn = pool.getconn() if pool else None
        if conn is None:
            import psycopg2
            conn = psycopg2.connect(settings.DATABASE_URL)
            borrowed = False
        else:
            borrowed = True
        with conn.cursor() as cur:
            cur.execute(sql.format(schema=settings.CDM_SCHEMA), params)
            rows = cur.fetchall()
    except Exception as e:
        logger.warning(f"[Agent 2] Exact concept_name lookup failed for {query_text!r}: {e}")
        return None
    finally:
        if conn is not None:
            if pool and borrowed:
                pool.putconn(conn)
            else:
                conn.close()

    if len(rows) != 1:
        logger.info(
            f"[Agent 2] Exact concept_name lookup for {query_text!r} "
            f"(domain={domain_hint}) → {len(rows)} matches, declining"
        )
        return None

    cid, name, domain, vocab, cls = rows[0]
    logger.info(f"[Agent 2] Exact concept_name match: {query_text!r} → {name} ({cid})")
    return CandidateConcept(
        concept_id=cid,
        concept_name=name,
        domain_id=domain,
        vocabulary_id=vocab,
        concept_class_id=cls,
        distance=0.0,
    )


def _seeds_after_rerank(
    candidates: List[CandidateConcept],
    top_concepts: List[CandidateConcept],
    exact_concept: Optional[CandidateConcept],
) -> List[CandidateConcept]:
    """Decide the seed list once the reranker has spoken.

    The force-include of the retriever's #1 used to run unconditionally, which meant a
    reranker that rejected every candidate still produced one. That turns "no match"
    into "confidently wrong", and it is silent: the empty-result branch below it was
    unreachable, so no concept set in the six trials was ever empty. It is kept here
    only for the case it was written for — the reranker chose something and the top
    hit was not in it.

    When the reranker chose nothing, an exact name match may stand in; otherwise the
    caller gets an empty list and records a gap.
    """
    if top_concepts:
        if candidates and candidates[0].concept_id not in {c.concept_id for c in top_concepts}:
            return [candidates[0]] + list(top_concepts)
        return list(top_concepts)
    if exact_concept is not None:
        return [exact_concept]
    return []


def _relevance_score(concept, seed_ids: set) -> int:
    """Compute relevance score for a KGConcept for pre-filtering.

    Priority (higher = better):
        4 — seed concept (direct vector hit)
        3 — child or sibling concept (KG 1-hop)
        2 — ancestor_climb with high IC
        1 — 2-hop traversal or other
    """
    if concept.concept_id in seed_ids:
        return 4
    rel = concept.relationship.lower() if concept.relationship else ""
    if "sibling" in rel or "child" in rel or "maps_to" in rel:
        return 3
    if "ancestor_climb" in rel or "ancestor" in rel:
        return 2
    return 1


def _prefilter_candidates(
    seed_ids: list[int],
    kg_concepts: list,
    max_candidates: int | None = None,
) -> list:
    """Pre-filter KG-expanded candidates before sending to Critic LLM.

    Caps candidates at AGENT2_MAX_CRITIC_CANDIDATES (default: 30).
    Seed concepts are never filtered out.

    Args:
        seed_ids: Concept IDs from vector search (always preserved).
        kg_concepts: KGConcept list from KG expansion.
        max_candidates: Override for max candidates (default: env var or 30).

    Returns:
        Filtered list of KGConcept objects.
    """
    if max_candidates is None:
        env_val = os.environ.get("AGENT2_MAX_CRITIC_CANDIDATES")
        if env_val is not None:
            # Explicit env override — honour it exactly (no broad-query bump)
            max_candidates = int(env_val)
        else:
            # Default path: apply broad-query heuristic
            max_candidates = 30
            # For broad queries with many KG results, allow more candidates through
            if len(kg_concepts) > 40:
                max_candidates = max(max_candidates, 50)

    if len(kg_concepts) <= max_candidates:
        return kg_concepts

    seed_set = set(seed_ids)

    # Partition: seeds always kept, rest scored and sorted
    seeds = [c for c in kg_concepts if c.concept_id in seed_set]
    non_seeds = [c for c in kg_concepts if c.concept_id not in seed_set]

    # Sort non-seeds by relevance descending
    non_seeds.sort(key=lambda c: _relevance_score(c, seed_set), reverse=True)

    remaining_slots = max(0, max_candidates - len(seeds))
    filtered = seeds + non_seeds[:remaining_slots]

    logger.debug(
        f"[Agent 2] Pre-filter: {len(kg_concepts)} → {len(filtered)} candidates "
        f"(seeds={len(seeds)}, cap={max_candidates})"
    )
    return filtered


class Agent2Workflow:
    """
    Intelligent Mapper Workflow with Fast/Slow Path Routing.
    
    Features:
    - Complexity-based routing (Pattern 1 & 5)
    - Rule-based extraction for simple terms (Pattern 2)
    - Gap analysis for unmapped items (Pattern 3)
    - Batch processing support (Pattern 4)
    """
    
    def __init__(self):
        self.router: Optional[ComplexityRouter] = None
        self.extractor: Optional[RuleExtractor] = None
        self._reranker = None
        self._umls_expander = None

    @property
    def umls_expander(self):
        """Lazy load UMLS synonym expander."""
        if self._umls_expander is None:
            self._umls_expander = get_umls_expander()
        return self._umls_expander
    
    @property
    def complexity_router(self) -> ComplexityRouter:
        """Lazy load complexity router."""
        if self.router is None:
            self.router = get_router()
        return self.router
    
    @property
    def rule_extractor(self) -> RuleExtractor:
        """Lazy load rule extractor."""
        if self.extractor is None:
            self.extractor = get_extractor()
        return self.extractor
    
    @property
    def reranker(self):
        """Lazy load reranker."""
        if self._reranker is None:
            self._reranker = get_reranker()
        return self._reranker

    def process(self, query_text: str, context: Optional[str] = None, domain_hint: Optional[str] = None) -> List[int]:
        """
        Legacy API: Process single query and return concept IDs.
        
        Args:
            query_text: Clinical term to map
            context: Optional context for disambiguation
            domain_hint: OMOP domain from Agent 1 (e.g., "Drug", "Condition")
            
        Returns:
            List of OMOP Concept IDs
        """
        result = self.process_with_details(query_text, context, domain_hint=domain_hint)
        return result.concept_ids
    
    def process_with_details(
        self,
        query_text: str,
        context: Optional[str] = None,
        domain_hint: Optional[str] = None,
        force_slow_path: bool = False,
        pre_fetched_candidates: Optional[list] = None,
    ) -> MappingResult:
        """
        Enhanced API: Process single query with full details including gap analysis.
        
        Args:
            query_text: Clinical term to map
            context: Optional context for disambiguation
            domain_hint: OMOP domain from Agent 1 (e.g., "Drug", "Condition").
                         Used for ATC drug class expansion gating and retriever filtering.
            
        Returns:
            MappingResult with concept_ids, gap_report, and routing stats
        """
        start_time = time.time()
        result = MappingResult()
        result.gap_report.total_criteria = 1
        
        logger.info(f"[Agent 2] Processing: '{query_text}'")
        
        # Step 0: Domain Pre-Check (ChromaDB top-1, no domain filter)
        # DISABLED BY DEFAULT: LEADER benchmark showed 6 harmful overrides
        # (e.g., Insulin Drug→Procedure, Microalbuminuria Measurement→Condition)
        # because ChromaDB semantic embedding returns semantically similar but
        # domain-different concepts (e.g., "Insulin" → "Administration of insulin" Procedure).
        # Toggle: DOMAIN_PRECHECK=1 to enable for experimentation
        if domain_hint and os.environ.get("DOMAIN_PRECHECK", "0") == "1":
            try:
                from src.agents.agent2.retriever import ConceptRetriever
                _precheck_retriever = ConceptRetriever()
                top1 = _precheck_retriever.search(query_text, n_results=3, domain_hint=None)
                if top1 and top1[0].distance < 0.35:
                    # Count domain votes from top-3 confident results
                    confident = [c for c in top1 if c.distance < 0.40]
                    domain_votes: dict = {}
                    for c in confident:
                        domain_votes[c.domain_id] = domain_votes.get(c.domain_id, 0) + 1
                    dominant_domain = max(domain_votes, key=domain_votes.get) if domain_votes else None
                    if dominant_domain and dominant_domain != domain_hint:
                        logger.warning(
                            f"[Agent 2] ⚠ Domain pre-check override: "
                            f"'{query_text}' domain {domain_hint} → {dominant_domain} "
                            f"(top-1: '{top1[0].concept_name}' dist={top1[0].distance:.3f}, "
                            f"votes={domain_votes})"
                        )
                        result.domain_overridden = domain_hint  # record original
                        domain_hint = dominant_domain
            except Exception as e:
                logger.debug(f"[Agent 2] Domain pre-check skipped: {e}")
        
        # Step 0a: Abbreviation Expansion
        # First try exact match (e.g., "ACS" → "Acute coronary syndrome")
        expanded_text, was_expanded = expand_abbreviation(query_text)
        if was_expanded:
            logger.info(f"[Agent 2] Abbreviation expanded: '{query_text}' → '{expanded_text}'")
            query_text = expanded_text
        else:
            # For compound queries (e.g., "ACS (excluding STEMI)"),
            # expand abbreviations within the text
            ctx_expanded = expand_in_context(query_text)
            if ctx_expanded != query_text:
                logger.info(f"[Agent 2] In-context abbreviation: '{query_text}' → '{ctx_expanded}'")
                query_text = ctx_expanded

        # Step 0a-bis: UMLS-backed query pre-expansion for short abbreviations
        # Resolves ambiguous abbreviations (MI, GLP-1) to canonical clinical
        # form BEFORE embedding search. Gated by AGENT2_QUERY_EXPAND env var.
        from src.agents.agent2.query_expander import QueryExpander
        if not hasattr(self, '_query_expander'):
            self._query_expander = QueryExpander(umls_expander=self.umls_expander)
        original_query = query_text
        query_text = self._query_expander.expand(query_text, domain_hint=domain_hint)
        if query_text != original_query:
            logger.info(f"[Agent 2] Query pre-expanded: '{original_query}' -> '{query_text}'")

        # Step 0b: Drug Class Expansion via ATC Vocabulary (RFC-006)
        # Gate: Only attempt ATC expansion when Agent 1 classifies domain as "Drug".
        # Without this gate, ATC matches non-drug queries catastrophically
        # (e.g., "Cardiovascular disease" → ATC "Cardiovascular preparations" → 392K concepts)
        if domain_hint == "Drug":
            pool = _get_db_pool()
            db_conn = None
            used_pool = False
            try:
                from src.settings import settings
                if pool is not None:
                    db_conn = pool.getconn()
                    used_pool = True
                else:
                    import psycopg2
                    db_conn = psycopg2.connect(settings.DATABASE_URL)
                # Split compound "or" queries (e.g. "GLP-1 receptor agonist or DPP-4 inhibitor")
                # so each drug class is expanded individually via ATC lookup.
                parts = [p.strip() for p in re.split(r'\s+or\s+', query_text, flags=re.IGNORECASE) if p.strip()]
                if len(parts) > 1:
                    all_ids: list[int] = []
                    matched_names: list[str] = []
                    for part in parts:
                        part_name, part_ids = expand_drug_class_via_vocab(
                            part, db_conn, schema=settings.CDM_SCHEMA
                        )
                        if part_name and part_ids:
                            all_ids.extend(part_ids)
                            matched_names.append(part_name)
                    atc_ingredient_ids = list(dict.fromkeys(all_ids))
                    atc_name = " + ".join(matched_names) if matched_names else None
                else:
                    atc_name, atc_ingredient_ids = expand_drug_class_via_vocab(
                        query_text, db_conn, schema=settings.CDM_SCHEMA
                    )
                if atc_name and atc_ingredient_ids:
                    logger.info(f"[Agent 2] ATC drug class '{atc_name}': {len(atc_ingredient_ids)} ingredients")
                    result.concept_ids = logician.roll_up_to_rxnorm_ingredients(atc_ingredient_ids)
                    result.gap_report.mapped_count = 1
                    result.route_path = "atc"
                    result.atc_expanded = True
                    result.processing_time_ms = (time.time() - start_time) * 1000
                    logger.info(
                        f"[Agent 2] ATC drug class result: {len(result.concept_ids)} concepts, "
                        f"{result.processing_time_ms:.1f}ms"
                    )
                    return result
            except Exception as e:
                logger.warning(f"[Agent 2] ATC vocab expansion failed: {e}")
            finally:
                if db_conn:
                    if used_pool and pool is not None:
                        pool.putconn(db_conn)
                    else:
                        db_conn.close()
        
        # Step 0c: Direct Code Pattern Check (fastest path)
        pattern_type = CodePatternMatcher.detect(query_text)
        if pattern_type:
            logger.info(f"[Agent 2] Code pattern detected: {pattern_type}")
            # TODO: Implement direct DB lookup by code
            # For now, continue to vector search
        
        # Step 1: Complexity Routing (Pattern 1 & 5)
        # FORCE_SLOW_PATH=1 → bypass router for ablation/benchmark
        # FORCE_FAST_PATH=1 → force fast path (no LLM reranking)
        # domain_hint is now provided by caller (Agent 1 or benchmark)
        force_slow = os.environ.get("FORCE_SLOW_PATH", "").strip()
        force_fast = os.environ.get("FORCE_FAST_PATH", "").strip()
        if force_slow_path:
            route_path = "slow"
        elif force_slow:
            route_path = "slow"
        elif force_fast:
            route_path = "fast"
        else:
            route_path = self.complexity_router.route(query_text)
        
        # Force slow path for drug class queries that need UMLS expansion.
        # Drug class terms (e.g., "Fibrinolytic agents", "CYP inhibitors") are
        # simple 2-3 word queries that the router classifies as "fast", but the
        # fast path only returns a single retriever hit without UMLS synonym
        # expansion, leading to wrong matches (e.g., fibrinolytic → fibrinogen).
        import re as _re
        _DRUG_CLASS_PATTERNS = _re.compile(
            r'\b(agents?|inhibitors?|inducers?|drugs?|blockers?|activators?|agonists?|antagonists?)\b',
            _re.IGNORECASE,
        )
        # Fast path disabled: all queries go through slow path (LLM reranker + UMLS expansion)
        # Fast path was causing wrong mappings for drug class queries and condition terms.
        # if route_path == "fast" and domain_hint == "Drug" and _DRUG_CLASS_PATTERNS.search(query_text):
        #     route_path = "slow"
        #     logger.info(f"[Agent 2] Drug class query detected → forced slow path")
        route_path = "slow"

        logger.info(f"[Agent 2] Route: {route_path} path (fast path disabled), domain_hint={domain_hint}")

        result.route_path = route_path
        # Fast path disabled — always use slow path
        # if route_path == "fast":
        #     result.fast_path_count += 1
        #     concept_ids = self._fast_path(query_text, domain_hint=domain_hint)
        # else:
        result.slow_path_count += 1
        concept_ids = self._slow_path(
            query_text, context, domain_hint=domain_hint,
            pre_fetched_candidates=pre_fetched_candidates,
        )
        
        if not concept_ids:
            # Gap Analysis (Pattern 3)
            result.gap_report.add_gap(
                item_id="Q_01",
                original_text=query_text,
                reason="No OMOP mapping found",
                domain=domain_hint,
                attempted_searches=[query_text]
            )
        else:
            # ── KG-RAG Post-processing (both fast & slow) ──
            concept_ids, overbroad_ids, critic_skipped = self._kg_expand_and_critique(
                concept_ids, query_text, context, domain_hint
            )
            # Apply ingredient rollup for Drug domain and for unknown domain
            # (domain_hint=None covers target cohort calls like "Ticagrelor" where
            # the caller does not specify a domain but the result is Drug concepts).
            # The rollup is a no-op for non-drug concepts since they have no RxNorm
            # ingredient ancestors and won't match the name-based fallback criteria.
            if domain_hint in ("Drug", None):
                concept_ids = logician.roll_up_to_rxnorm_ingredients(concept_ids)
            # The Measurement counterpart of that rollup. SNOMED "... - finding"
            # concepts are Measurement-domain and standard, so nothing upstream
            # separates them from the LOINC Lab Test — but they carry no value and
            # their descendants are findings. Which of the two the reranker picked was
            # a coin flip (4 of 5 draws at temperature 0 chose the finding), and it
            # swung one ARISTOTLE criterion's closure between 8 and 184 concepts.
            # Strictly Measurement: Clinical Finding is the correct class for most of
            # the Condition domain.
            if domain_hint == "Measurement":
                concept_ids = logician.drop_qualitative_findings(concept_ids)
            result.critic_skipped = critic_skipped
            # Persist KG cache after single-query processing
            try:
                get_kg_expander().save_cache()
            except Exception as e:
                logger.debug(f"[Agent 2] KG cache save skipped: {e}")
            result.concept_ids = concept_ids
            result.overbroad_concept_ids = overbroad_ids
            result.gap_report.mapped_count = 1
        
        result.processing_time_ms = (time.time() - start_time) * 1000
        logger.info(f"[Agent 2] Result: {len(concept_ids)} concepts, {route_path} path, {result.processing_time_ms:.1f}ms")
        # === ID LINEAGE: Final output ===
        logger.info(
            f"[Agent 2][LINEAGE] FINAL '{query_text}' → {result.concept_ids}"
        )
        
        return result
    
    def process_batch(
        self,
        queries: List[str],
        contexts: Optional[List[str]] = None
    ) -> MappingResult:
        """
        Batch processing with parallel LLM calls (Pattern 4).
        
        Args:
            queries: List of clinical terms to map
            contexts: Optional list of contexts for each query
            
        Returns:
            MappingResult with aggregated results
        """
        start_time = time.time()
        result = MappingResult()
        result.gap_report.total_criteria = len(queries)
        
        if not queries:
            return result
        
        logger.info(f"[Agent 2] Batch processing {len(queries)} queries")
        
        # Route all queries first
        fast_queries = []
        slow_queries = []
        
        for i, query in enumerate(queries):
            route = self.complexity_router.route(query)
            context = contexts[i] if contexts and i < len(contexts) else None
            
            if route == "fast":
                fast_queries.append((i, query, context))
                result.fast_path_count += 1
            else:
                slow_queries.append((i, query, context))
                result.slow_path_count += 1
        
        # Process fast path queries (parallel)
        all_results: Dict[int, List[int]] = {}
        
        if fast_queries:
            with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(fast_queries))) as pool:
                futures = [
                    (idx, pool.submit(self._fast_path, query, None))
                    for idx, query, _ in fast_queries
                ]
                for idx, future in futures:
                    try:
                        all_results[idx] = future.result()
                    except Exception as e:
                        logger.warning(f"[Agent 2] Fast path failed for idx {idx}: {e}")
                        all_results[idx] = []
        
        # Process slow path queries in batch
        if slow_queries:
            slow_results = self._slow_path_batch(slow_queries)
            for (idx, _, _), ids in zip(slow_queries, slow_results):
                all_results[idx] = ids
        
        # Aggregate results
        for i, query in enumerate(queries):
            ids = all_results.get(i, [])
            if ids:
                result.concept_ids.extend(ids)
                result.gap_report.mapped_count += 1
            else:
                result.gap_report.add_gap(
                    item_id=f"Q_{i+1:02d}",
                    original_text=query,
                    reason="No OMOP mapping found",
                    attempted_searches=[query]
                )
        
        # Remove duplicates while preserving order
        seen = set()
        unique_ids = []
        for cid in result.concept_ids:
            if cid not in seen:
                seen.add(cid)
                unique_ids.append(cid)
        result.concept_ids = unique_ids
        
        result.processing_time_ms = (time.time() - start_time) * 1000
        logger.info(f"[Agent 2] Batch result: {len(result.concept_ids)} unique concepts, "
                   f"{result.gap_report.mapped_count}/{len(queries)} mapped, "
                   f"{result.processing_time_ms:.1f}ms")
        
        return result
    
    def _fast_path(self, query_text: str, domain_hint: Optional[str] = None) -> List[int]:
        """
        Fast path: Rule-based extraction + direct lookup (no LLM).
        
        Pattern 2: Rule-Based Fallback Extraction.
        """
        logger.debug(f"[Agent 2] Fast path for: {query_text}")
        
        # Try rule-based extraction first
        domain = domain_hint
        extraction = self.rule_extractor.extract(query_text, domain)
        
        if extraction and self.rule_extractor.is_extraction_complete(extraction, domain):
            # Use extracted concept_text for search
            search_term = extraction.get("concept_text", query_text)
        else:
            search_term = query_text
        
        # Vector search with domain hint
        candidates = retriever.search(search_term, domain_hint=domain)
        if not candidates:
            return []
        
        # For fast path, take top candidate without LLM reranking
        best = candidates[0]
        logger.debug(f"[Agent 2] Fast path selected: {best.concept_name} (ID: {best.concept_id})")
        
        # Decompose if needed
        final_ids = logician.decompose_combination(best.concept_id)
        
        # Prune empty concepts
        return logician.prune_empty_concepts(final_ids)
    
    def _slow_path(
        self,
        query_text: str,
        context: Optional[str] = None,
        domain_hint: Optional[str] = None,
        pre_fetched_candidates: Optional[list] = None,
    ) -> List[int]:
        """
        Slow path: Vector search + Top-N LLM reranking.
        KG expansion is handled in post-processing (_kg_expand_and_critique).
        
        Enhanced with UMLS Multi-query: synonym-expanded queries are searched
        in parallel and their candidates merged before reranking.
        """
        logger.info(f"[Agent 2] Slow path for: '{query_text}' (domain={domain_hint})")
        
        # UMLS full-form rewrite: use UMLS synonyms to augment primary search.
        # This prevents embedding confusion (e.g., "fibrinolytic" ≈ "fibrinogen")
        # by adding diverse alternative query terms from UMLS (e.g., "Thrombolytic Drug").
        umls_rewrites: list[str] = []
        if self.umls_expander.is_available:
            cuis = self.umls_expander.get_cuis(query_text, domain_hint=domain_hint)
            if cuis:
                all_syns = self.umls_expander.get_synonyms_for_cui(
                    cuis[0], max_synonyms=10,
                    preferred_sabs=["SNOMEDCT_US", "NCI", "MSH", "RXNORM"]
                )
                # Pick up to 2 synonyms with different root words
                query_root = query_text.split()[0].lower() if query_text.split() else ""
                for s in all_syns:
                    s_root = s.split()[0].lower() if s.split() else ""
                    if s_root != query_root and s.lower() != query_text.lower():
                        umls_rewrites.append(s)
                        if len(umls_rewrites) >= 2:
                            break
                if umls_rewrites:
                    logger.info(
                        f"[Agent 2] UMLS diverse rewrites for '{query_text}': {umls_rewrites}"
                    )
        
        # Primary search — use batch pre-fetched candidates when available
        if pre_fetched_candidates:
            candidates = list(pre_fetched_candidates)
            logger.info(
                f"[Agent 2] Using {len(candidates)} pre-fetched candidates "
                f"for '{query_text}' (skipping primary ChromaDB search)"
            )
        else:
            candidates = retriever.search(query_text, domain_hint=domain_hint)
        
        # Search with UMLS diverse rewrites and merge candidates
        for rewrite in umls_rewrites:
            rewrite_candidates = retriever.search(rewrite, domain_hint=domain_hint)
            seen_ids = {c.concept_id for c in candidates}
            for rc in rewrite_candidates:
                if rc.concept_id not in seen_ids:
                    seen_ids.add(rc.concept_id)
                    candidates.append(rc)
        
        # UMLS Multi-query: expand synonyms and merge additional candidates (parallel)
        if self.umls_expander.is_available:
            synonyms = self.umls_expander.expand(query_text, max_synonyms=3, domain_hint=domain_hint)
            if synonyms:
                seen_ids = {c.concept_id for c in candidates}
                with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(synonyms))) as pool:
                    futures = [
                        pool.submit(retriever.search, syn, 10, domain_hint)
                        for syn in synonyms
                    ]
                    for future in futures:
                        try:
                            syn_candidates = future.result()
                            for sc in syn_candidates:
                                if sc.concept_id not in seen_ids:
                                    seen_ids.add(sc.concept_id)
                                    candidates.append(sc)
                        except Exception as e:
                            logger.warning(f"[Agent 2] Synonym search failed: {e}")
                logger.info(
                    f"[Agent 2] UMLS multi-query: {len(synonyms)} synonyms → "
                    f"{len(candidates)} total candidates"
                )
        
        if not candidates:
            logger.info("[Agent 2][LINEAGE] retriever → 0 candidates")
            return []
        
        # === ID LINEAGE: Retriever results ===
        logger.info(
            f"[Agent 2][LINEAGE] retriever → {len(candidates)} candidates. "
            f"Top-5: {[(c.concept_id, c.concept_name, f'{c.distance:.3f}') for c in candidates[:5]]}"
        )
        
        search_context = f"{context}: {query_text}" if context else query_text
        
        # Top-3 seeding: get multiple seed concepts to avoid single-select bottleneck
        top_concepts = self.reranker.rerank_topn(search_context, candidates, top_n=3)
        
        # === ID LINEAGE: Reranker results ===
        logger.info(
            f"[Agent 2][LINEAGE] reranker → {len(top_concepts)} selected: "
            f"{[(c.concept_id, c.concept_name) for c in top_concepts]}"
        )
        
        # A reranker that selects nothing has given an answer, not a blank. Only reach
        # for the literal name when that happens -- it costs a query, and it must not
        # override a selection the reranker did make.
        exact_concept = None if top_concepts else _exact_name_concept(query_text, domain_hint)
        top_concepts = _seeds_after_rerank(candidates, top_concepts, exact_concept)

        if not top_concepts:
            logger.info(
                f"[Agent 2][LINEAGE] reranker rejected all {len(candidates)} candidates "
                f"and {query_text!r} has no exact concept_name match → no seeds"
            )
            return []
        
        logger.debug(f"[Agent 2] Top-{len(top_concepts)} seeds: "
                     + ", ".join(f"{c.concept_name} ({c.concept_id})" for c in top_concepts))
        
        # Decompose each seed and merge
        all_ids = []
        seen = set()
        for concept in top_concepts:
            decomposed = logician.decompose_combination(concept.concept_id)
            pruned = logician.prune_empty_concepts(decomposed)
            if decomposed != [concept.concept_id] or pruned != decomposed:
                logger.info(
                    f"[Agent 2][LINEAGE] decompose {concept.concept_id} ({concept.concept_name}): "
                    f"decomposed={decomposed} → pruned={pruned}"
                )
            for cid in pruned:
                if cid not in seen:
                    seen.add(cid)
                    all_ids.append(cid)
        
        # === ID LINEAGE: Final slow path output ===
        logger.info(f"[Agent 2][LINEAGE] slow_path final IDs: {all_ids}")
        
        return all_ids
    
    def _kg_expand_and_critique(
        self,
        seed_ids: List[int],
        query_text: str,
        context: Optional[str] = None,
        domain_hint: Optional[str] = None,
    ) -> tuple:
        """
        KG-RAG post-processing: expand seed concepts via Neo4j, then LLM multi-select.
        
        Applied to BOTH fast and slow path results.
        Falls back to seed_ids on any failure.
        
        Modes (controlled by KG_EXPAND_MODE env var):
        - "clinical_anchor" (default): Anchor-only, no descendants. Critic skipped
          when anchor count ≤ 10. Delegates descendant expansion to Circe.
        - "clinical" (legacy): Full expansion with descendants + ancestor_climb + Critic.
        """
        if not seed_ids:
            return seed_ids, [], False
        
        # ── Mode selection via env var (lab meeting 2026-03-05) ──
        kg_mode = os.environ.get("KG_EXPAND_MODE", "clinical_anchor").strip()
        
        try:
            kg = get_kg_expander()
            all_kg_concepts = []
            
            if kg_mode == "clinical_anchor":
                # ── Anchor-Only Mode ──
                # No descendants, no ancestor_climb. Only anchors (ancestor/sibling/maps_to).
                # Relies on includeDescendants=true at Circe level.
                #
                # Domain-aware caps (lab meeting 2026-03-05 합의):
                #   Condition/Procedure: max 50 (seed ≤ 2), 30 (seed > 2)
                #   Drug: max 20
                #   Measurement/Device: max 15
                if domain_hint in ("Drug",):
                    kg_limit = 20
                elif domain_hint in ("Measurement", "Device"):
                    kg_limit = 15
                elif domain_hint in ("Condition", "Procedure") and len(seed_ids) <= 2:
                    kg_limit = 50
                elif domain_hint in ("Condition", "Procedure"):
                    kg_limit = 30
                else:
                    kg_limit = 30  # Default for unspecified domains
                logger.info(
                    f"[Agent 2] KG mode=clinical_anchor, limit={kg_limit} "
                    f"(domain={domain_hint}, seeds={len(seed_ids)})"
                )
                
                with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(seed_ids))) as pool:
                    futures = [
                        pool.submit(
                            kg.expand, sid, "clinical_anchor", 3, kg_limit, domain_hint
                        )
                        for sid in seed_ids
                    ]
                    for future in futures:
                        try:
                            all_kg_concepts.extend(future.result())
                        except Exception as e:
                            logger.warning(f"[Agent 2] KG anchor expansion failed: {e}")
            else:
                # ── Legacy clinical mode ──
                # Determine adaptive limit based on domain and seed count
                if domain_hint in ("Drug", "Measurement"):
                    kg_limit = 15
                elif domain_hint == "Condition" and len(seed_ids) <= 2:
                    kg_limit = 40
                else:
                    kg_limit = 20
                logger.info(f"[Agent 2] KG mode=clinical, limit={kg_limit} (domain={domain_hint}, seeds={len(seed_ids)})")
                
                # Parallel KG expansion per seed (descendants, siblings, maps_to)
                with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(seed_ids))) as pool:
                    futures = [
                        pool.submit(
                            kg.expand, sid, "clinical", 3, kg_limit, domain_hint
                        )
                        for sid in seed_ids
                    ]
                    for future in futures:
                        try:
                            all_kg_concepts.extend(future.result())
                        except Exception as e:
                            logger.warning(f"[Agent 2] KG expansion for seed failed: {e}")
                
                # Separate ancestor_climb pass (legacy only)
                if domain_hint in ("Condition", "Procedure"):
                    climb_limit = None  # uses DEFAULT_KG_CLIMB_LIMIT (40)
                    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(seed_ids))) as pool:
                        climb_futures = [
                            pool.submit(
                                kg.ancestor_climb, sid, 3, 8.0, domain_hint, climb_limit
                            )
                            for sid in seed_ids
                        ]
                        for future in climb_futures:
                            try:
                                all_kg_concepts.extend(future.result())
                            except Exception as e:
                                logger.warning(f"[Agent 2] Ancestor climb for seed failed: {e}")
                    logger.info(f"[Agent 2] Ancestor climb pass completed for {len(seed_ids)} seeds")
            
            # Note: save_cache() NOT called here — callers do it once after batch
            
            # Deduplicate
            seen = set(seed_ids)
            unique_kg = []
            for c in all_kg_concepts:
                if c.concept_id not in seen:
                    seen.add(c.concept_id)
                    unique_kg.append(c)
            
            logger.info(f"[Agent 2] KG expanded: {len(unique_kg)} related concepts for {len(seed_ids)} seeds")
            # === ID LINEAGE: KG expansion results ===
            logger.info(
                f"[Agent 2][LINEAGE] kg_expand: seeds={seed_ids} → "
                f"{len(unique_kg)} KG concepts. "
                f"Sample: {[(c.concept_id, c.concept_name, c.relationship) for c in unique_kg[:8]]}"
            )
        except Exception as e:
            logger.warning(f"[Agent 2] KG expansion failed: {e}")
            return seed_ids, [], False
        
        if not unique_kg:
            return seed_ids, [], False
        
        # ── Critic Decision ──
        # In clinical_anchor mode: skip Critic when anchor count is small (≤ 10).
        # Anchors are already curated (ancestors/siblings/maps_to), so LLM filtering
        # is unnecessary and wastes API calls (~56 calls → 0-10).
        if kg_mode == "clinical_anchor" and len(unique_kg) <= 10:
            final_ids = seed_ids + [c.concept_id for c in unique_kg]
            logger.info(
                f"[Agent 2] Critic SKIPPED (anchor mode, {len(unique_kg)} anchors ≤ 10). "
                f"Returning {len(final_ids)} concepts directly."
            )
            logger.info(
                f"[Agent 2][LINEAGE] critic_skip: seeds={seed_ids} + "
                f"anchors={[c.concept_id for c in unique_kg]} → final={final_ids}"
            )
            # ── ConceptSetRefiner (lab meeting 2026-03-09) ──
            if os.environ.get("ENABLE_REFINER", "1") == "1":
                refiner = get_concept_set_refiner()
                ref_result = refiner.refine(seed_ids, unique_kg, query_text, domain_hint=domain_hint)
                final_ids = ref_result.kept_ids
                return final_ids, ref_result.overbroad_ids, True
            return final_ids, [], True
        
        # Step 2: LLM Critic (multi-select) — used when anchor count > 10 or legacy mode
        try:
            critic_context = context
            if domain_hint and domain_hint not in ("Drug", "Measurement"):
                domain_note = f"Target domain: {domain_hint}"
                critic_context = f"{context}. {domain_note}" if context else domain_note
            
            # Pre-filter candidates before critic to reduce LLM cost (REQ-01)
            filtered_kg = _prefilter_candidates(seed_ids, unique_kg)
            logger.info(
                f"[Agent 2] Pre-filter: {len(unique_kg)} → {len(filtered_kg)} candidates for critic"
            )

            critic = get_critic()
            final_ids = critic.evaluate(
                query=query_text,
                seed_concept_ids=seed_ids,
                kg_concepts=filtered_kg,
                context=critic_context,
                domain_hint=domain_hint,
            )
            logger.info(f"[Agent 2] Critic selected: {len(final_ids)} from {len(unique_kg) + len(seed_ids)} candidates")
            # === ID LINEAGE: Critic final selection ===
            logger.info(
                f"[Agent 2][LINEAGE] critic: input_seeds={seed_ids}, "
                f"input_kg_count={len(unique_kg)} → final_ids={final_ids}"
            )
            # ── ConceptSetRefiner (lab meeting 2026-03-09) ──
            # Filter unique_kg to only critic-selected concepts to avoid bypassing critic
            if os.environ.get("ENABLE_REFINER", "1") == "1":
                critic_selected_set = set(final_ids)
                critic_kg = [c for c in unique_kg if c.concept_id in critic_selected_set]
                refiner = get_concept_set_refiner()
                ref_result = refiner.refine(seed_ids, critic_kg, query_text, domain_hint=domain_hint)
                final_ids = ref_result.kept_ids
                return final_ids, ref_result.overbroad_ids, False
            return final_ids, [], False
        except LLMConfigurationError:
            # Misconfiguration is not a degradable failure: it fails every item
            # identically and would otherwise produce a full results table built
            # from seed concepts alone.
            raise
        except Exception as e:
            logger.warning(f"[Agent 2] Critic failed: {e}")
            return seed_ids, [], False

    def _slow_path_batch(
        self, 
        queries: List[tuple]  # List of (index, query, context)
    ) -> List[List[int]]:
        """
        Batch slow path processing with parallel reranking + KG + Critic.
        
        Full pipeline per query:
          1. UMLS synonym expansion + parallel retriever search
          2. Batch Top-N LLM reranking
          3. Per-query KG expansion + Critic (parallel across queries)
        """
        # Phase 1: Retriever + UMLS multi-query for all queries
        all_candidates: List[List[CandidateConcept]] = []
        
        for _, query, _ in queries:
            domain_hint = None  # batch mode: domain not available
            candidates = retriever.search(query, domain_hint=domain_hint)
            
            # UMLS Multi-query: expand synonyms and merge (parallel)
            if self.umls_expander.is_available:
                synonyms = self.umls_expander.expand(query, max_synonyms=3)
                if synonyms:
                    seen_ids = {c.concept_id for c in candidates}
                    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(synonyms))) as pool:
                        futures = [
                            pool.submit(retriever.search, syn, 10, domain_hint)
                            for syn in synonyms
                        ]
                        for future in futures:
                            try:
                                for sc in future.result():
                                    if sc.concept_id not in seen_ids:
                                        seen_ids.add(sc.concept_id)
                                        candidates.append(sc)
                            except Exception as e:
                                logger.warning(f"[Agent 2] Batch synonym search failed for '{query}': {e}")
            
            all_candidates.append(candidates)
        
        # Phase 2: Batch Top-N reranking
        batch_items = []
        for (_, query, context), candidates in zip(queries, all_candidates):
            search_context = f"{context}: {query}" if context else query
            batch_items.append({
                "query": search_context,
                "candidates": candidates,
            })
        
        topn_results = self.reranker.rerank_topn_batch(batch_items, top_n=3)
        
        # Phase 2b: Force-include retriever's #1 candidate per query
        for i, candidates in enumerate(all_candidates):
            if candidates and topn_results[i] is not None:
                best_candidate = candidates[0]
                selected_ids = {c.concept_id for c in topn_results[i]}
                if best_candidate.concept_id not in selected_ids:
                    topn_results[i].insert(0, best_candidate)
        
        # Phase 3: Decompose + KG expand + Critic (parallel across queries)
        def _post_process_query(idx: int) -> List[int]:
            top_concepts = topn_results[idx]
            _, query, context = queries[idx]
            domain_hint = None  # batch mode: domain not available
            
            if not top_concepts:
                return []
            
            # Decompose each seed
            all_ids = []
            seen = set()
            for concept in top_concepts:
                decomposed = logician.decompose_combination(concept.concept_id)
                pruned = logician.prune_empty_concepts(decomposed)
                for cid in pruned:
                    if cid not in seen:
                        seen.add(cid)
                        all_ids.append(cid)
            
            if not all_ids:
                return []
            
            # KG expansion + Critic
            expanded, _, _ = self._kg_expand_and_critique(all_ids, query, context, domain_hint)
            return expanded
        
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(queries))) as pool:
            futures = [
                (i, pool.submit(_post_process_query, i))
                for i in range(len(queries))
            ]
            results: List[List[int]] = [[] for _ in queries]
            for idx, future in futures:
                try:
                    results[idx] = future.result()
                except Exception as e:
                    logger.warning(f"[Agent 2] Batch post-process failed for query {idx}: {e}")
                    results[idx] = []
        
        # Deferred KG cache save — single disk write after all batch queries complete
        try:
            get_kg_expander().save_cache()
        except Exception:
            logger.warning("[Agent 2] KG cache save failed after batch")
        
        return results
    
    # _guess_domain() — REMOVED
    # Domain classification is now handled by Agent 1 (via Criteria.domain field).
    # Agent 2 receives domain_hint as a parameter instead of guessing.
    # For standalone usage (e.g., A_direct benchmark), domain is extracted
    # from GOLD JSON ConceptSet DOMAIN_ID.


# Lazy singleton
_agent2_instance = None


def get_agent2() -> Agent2Workflow:
    """Get or create Agent 2 instance (lazy initialization)."""
    global _agent2_instance
    if _agent2_instance is None:
        _agent2_instance = Agent2Workflow()
    return _agent2_instance


# Global instance for backward compatibility
agent2 = None  # Use get_agent2() instead
