"""
UMLS Synonym Expander for Agent 2.

Uses a local SQLite database built from MRCONSO.RRF to expand
clinical terms into their UMLS synonyms before vector search.

Strategy (Multi-query):
    1. Look up query text in MRCONSO (exact → fuzzy fallback)
    2. Collect all CUIs matching the query
    3. For each CUI, gather all synonym strings
    4. Return expanded synonyms for multi-query ChromaDB search
"""

import logging
import os
import sqlite3
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Default path relative to project root
_DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "data", "umls", "mrconso.sqlite"
)

# Preferred source vocabularies for synonym selection (ordered by relevance)
_PREFERRED_SABS = [
    "SNOMEDCT_US",  # Clinical terms
    "LNC",          # LOINC (lab tests)
    "RXNORM",       # Drug names
    "NCI",          # NCI Thesaurus
    "MSH",          # MeSH
    "CHV",          # Consumer Health (lay terms)
    "HPO",          # Human Phenotype Ontology
]

# OMOP domain_hint → UMLS Semantic Type (STY) mapping
# Used to filter CUIs by domain when MRSTY table is available.
# Reference: https://lhncbc.nlm.nih.gov/semanticnetwork/
DOMAIN_TO_STY: Dict[str, Set[str]] = {
    "Condition": {
        "Disease or Syndrome",
        "Neoplastic Process",
        "Finding",
        "Sign or Symptom",
        "Pathologic Function",
        "Mental or Behavioral Dysfunction",
        "Congenital Abnormality",
        "Injury or Poisoning",
        "Cell or Molecular Dysfunction",
        "Acquired Abnormality",
    },
    "Drug": {
        "Pharmacologic Substance",
        "Clinical Drug",
        "Antibiotic",
        "Organic Chemical",
        "Amino Acid, Peptide, or Protein",  # biologics
        "Hormone",
        "Vitamin",
        "Immunologic Factor",
    },
    "Procedure": {
        "Therapeutic or Preventive Procedure",
        "Diagnostic Procedure",
        "Health Care Activity",
        "Laboratory Procedure",
        "Research Activity",
    },
    "Measurement": {
        "Laboratory or Test Result",
        "Laboratory Procedure",
        "Diagnostic Procedure",
        "Clinical Attribute",
    },
}


class UMLSSynonymExpander:
    """
    Expands clinical terms into UMLS synonyms via local SQLite.
    
    Gracefully degrades if DB is not available (returns empty list).
    """
    
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.path.normpath(_DEFAULT_DB_PATH)
        self._conn: Optional[sqlite3.Connection] = None
        self._available = False
        self._has_mrsty = False
        self._init_db()
    
    def _init_db(self) -> None:
        """Initialize DB connection. Fail silently if DB not found."""
        if not os.path.exists(self.db_path):
            logger.info(
                f"UMLS SQLite not found at {self.db_path}. "
                "Synonym expansion disabled. "
                "Run: python scripts/build_umls_sqlite.py to create."
            )
            return
        
        try:
            self._conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
            )
            self._conn.execute("PRAGMA query_only=ON")
            self._conn.execute("PRAGMA cache_size=-50000")  # 50MB cache
            self._available = True
            
            # Quick sanity check
            cur = self._conn.execute("SELECT COUNT(*) FROM mrconso")
            count = cur.fetchone()[0]
            
            # Check if MRSTY table exists
            cur2 = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='mrsty'"
            )
            if cur2.fetchone():
                self._has_mrsty = True
                mrsty_count = self._conn.execute("SELECT COUNT(*) FROM mrsty").fetchone()[0]
                logger.info(
                    f"UMLS Synonym Expander loaded: {count:,} mrconso + "
                    f"{mrsty_count:,} mrsty rows from {self.db_path}"
                )
            else:
                logger.info(
                    f"UMLS Synonym Expander loaded: {count:,} rows from {self.db_path} "
                    f"(MRSTY table not found — domain filtering disabled)"
                )
        except Exception as e:
            logger.warning(f"Failed to load UMLS SQLite: {e}")
            self._available = False
    
    @property
    def is_available(self) -> bool:
        return self._available
    
    def _cui_matches_sty(self, cui: str, allowed_stys: Set[str]) -> bool:
        """Check if a CUI has any semantic type in the allowed set."""
        cur = self._conn.cursor()
        cur.execute("SELECT sty FROM mrsty WHERE cui = ?", (cui,))
        cui_stys = {row[0] for row in cur.fetchall()}
        return bool(cui_stys & allowed_stys)

    def _filter_cuis_by_domain(
        self, cuis: List[str], domain_hint: Optional[str], query: str = ""
    ) -> List[str]:
        """
        Filter CUIs by MRSTY semantic type matching the domain_hint.

        For short queries (<=5 chars, abbreviation-like) with domain_hint,
        strict mode drops non-matching CUIs instead of keeping all.
        Toggle: AGENT2_UMLS_STRICT (default "true").

        Graceful degradation: returns original list if no matches after
        filtering (unless strict mode applies).
        """
        if not domain_hint or not cuis or not self._has_mrsty:
            return cuis

        allowed_stys = DOMAIN_TO_STY.get(domain_hint)
        if not allowed_stys:
            return cuis

        filtered = [cui for cui in cuis if self._cui_matches_sty(cui, allowed_stys)]

        if filtered:
            if len(filtered) < len(cuis):
                logger.info(
                    f"[UMLS] MRSTY filter (domain={domain_hint}): "
                    f"{len(cuis)} → {len(filtered)} CUIs"
                )
            return filtered

        # No CUI matched the domain.
        # Strict mode for short queries (abbreviations): drop non-matching CUIs
        # to prevent abbreviation confusion (e.g., MI matching "milia" instead
        # of "Myocardial Infarction" in Condition domain).
        # Toggle: AGENT2_UMLS_STRICT (default "true").
        strict = os.environ.get("AGENT2_UMLS_STRICT", "true").lower() == "true"
        if strict and domain_hint and len(query.strip()) <= 5:
            logger.info(
                f"[UMLS] Short query '{query}' with domain={domain_hint}: "
                f"dropped {len(cuis)} non-matching CUIs (strict mode)"
            )
            return []

        # Fallback: keep original to avoid empty result
        logger.debug(
            f"[UMLS] MRSTY filter found 0 matches for domain={domain_hint}, "
            f"keeping all {len(cuis)} CUIs"
        )
        return cuis

    def get_cuis(
        self, query: str, domain_hint: Optional[str] = None,
    ) -> List[str]:
        """
        Find CUIs matching the query text.
        
        Strategy:
            1. Exact match (case-insensitive)
            2. Fallback: LIKE '%query%' for partial matches
            3. If domain_hint provided and MRSTY available, filter by semantic type
        
        Args:
            query: Clinical term to look up
            domain_hint: OMOP domain (e.g., 'Condition', 'Drug') for filtering
        
        Returns:
            List of CUI strings (e.g. ['C0019018'])
        """
        if not self._available:
            return []
        
        query = query.strip()
        if not query:
            return []
        
        cur = self._conn.cursor()
        
        # 1. Exact match (case-insensitive via COLLATE NOCASE index)
        cur.execute(
            "SELECT DISTINCT cui FROM mrconso WHERE str = ? COLLATE NOCASE",
            (query,),
        )
        cuis = [row[0] for row in cur.fetchall()]
        
        if cuis:
            logger.debug(f"[UMLS] Exact match '{query}' → {len(cuis)} CUIs: {cuis[:5]}")
            return self._filter_cuis_by_domain(cuis, domain_hint, query=query)
        
        # 2. Fuzzy fallback: LIKE match (limit to avoid explosion)
        cur.execute(
            "SELECT DISTINCT cui FROM mrconso WHERE str LIKE ? COLLATE NOCASE LIMIT 10",
            (f"%{query}%",),
        )
        cuis = [row[0] for row in cur.fetchall()]
        
        if cuis:
            logger.debug(f"[UMLS] Fuzzy match '{query}' → {len(cuis)} CUIs: {cuis[:5]}")
        else:
            logger.debug(f"[UMLS] No match for '{query}'")
        
        return self._filter_cuis_by_domain(cuis, domain_hint)
    
    def get_synonyms_for_cui(
        self,
        cui: str,
        max_synonyms: int = 10,
        preferred_sabs: Optional[List[str]] = None,
    ) -> List[str]:
        """
        Get all synonym strings for a given CUI.
        
        Prioritizes preferred vocabularies and preferred terms (ISPREF='Y').
        Deduplicates case-insensitively.
        """
        if not self._available:
            return []
        
        sabs = preferred_sabs or _PREFERRED_SABS
        cur = self._conn.cursor()
        
        # Get all strings for this CUI, ordered by preference
        # ISPREF='Y' = preferred form, TS='P' = preferred LUI
        cur.execute(
            """
            SELECT DISTINCT str, sab, ispref, ts
            FROM mrconso
            WHERE cui = ?
            ORDER BY
                ispref DESC,  -- Preferred forms first
                ts ASC,       -- P (preferred) before S
                sab ASC       -- Alphabetical for consistency
            """,
            (cui,),
        )
        
        rows = cur.fetchall()
        
        # Deduplicate case-insensitively, prefer entries from relevant SABs
        seen_lower: set = set()
        prioritized: List[str] = []
        others: List[str] = []
        
        for str_val, sab, ispref, ts in rows:
            lower = str_val.lower()
            if lower in seen_lower:
                continue
            seen_lower.add(lower)
            
            if sab in sabs:
                prioritized.append(str_val)
            else:
                others.append(str_val)
        
        # Combine: preferred SABs first, then others
        all_synonyms = prioritized + others
        return all_synonyms[:max_synonyms]
    
    def expand(
        self,
        query: str,
        max_synonyms: int = 5,
        exclude_original: bool = True,
        domain_hint: Optional[str] = None,
    ) -> List[str]:
        """
        Expand a clinical term into its UMLS synonyms.
        
        This is the main entry point for Agent 2 integration.
        
        Args:
            query: Clinical term to expand
            max_synonyms: Maximum number of synonyms to return
            exclude_original: If True, don't include the original query in results
            domain_hint: OMOP domain for MRSTY-based CUI filtering
            
        Returns:
            List of synonym strings (excluding the query itself)
        """
        if not self._available:
            return []
        
        query = query.strip()
        if not query or len(query) < 2:
            return []
        
        # Get CUIs (domain-filtered if MRSTY available)
        cuis = self.get_cuis(query, domain_hint=domain_hint)
        if not cuis:
            return []
        
        # Collect synonyms from all CUIs (usually 1, sometimes multiple)
        all_synonyms: List[str] = []
        seen_lower: set = {query.lower()} if exclude_original else set()
        
        for cui in cuis[:3]:  # Limit CUIs to avoid explosion
            syns = self.get_synonyms_for_cui(cui, max_synonyms=max_synonyms * 2)
            for s in syns:
                if s.lower() not in seen_lower:
                    seen_lower.add(s.lower())
                    all_synonyms.append(s)
                    if len(all_synonyms) >= max_synonyms:
                        break
            if len(all_synonyms) >= max_synonyms:
                break
        
        if all_synonyms:
            logger.info(
                f"[UMLS] Expanded '{query}' (domain={domain_hint}) → "
                f"{len(all_synonyms)} synonyms: "
                f"{all_synonyms[:3]}{'...' if len(all_synonyms) > 3 else ''}"
            )
        
        return all_synonyms
    
    def close(self) -> None:
        """Close DB connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
            self._available = False


# ============================================================
# Singleton management
# ============================================================
_instance: Optional[UMLSSynonymExpander] = None


def get_umls_expander(db_path: Optional[str] = None) -> UMLSSynonymExpander:
    """Get or create UMLS Synonym Expander instance (lazy singleton)."""
    global _instance
    if _instance is None:
        _instance = UMLSSynonymExpander(db_path=db_path)
    return _instance
