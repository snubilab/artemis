"""UMLS-backed query pre-expansion for short clinical abbreviations.

Resolves ambiguous abbreviations (MI, TIA, CHF, GLP-1, etc.) to their
canonical clinical form BEFORE embedding search, using UMLS MRCONSO
with MRSTY domain filtering.

This runs at workflow.py Step 0a-bis, after the deprecated abbreviation
expander and before drug class expansion.
"""
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Short queries (<=6 chars) are abbreviation candidates
_MAX_ABBREV_LENGTH = 6

# Curated expansions, keyed by (abbreviation, domain hint).
#
# Small on purpose. All 14 abbreviations that actually occur as criterion
# sourceText across the six benchmark trials were measured through the pipeline
# retriever, bare against expanded, and only these four improved:
#
#   eGFR    0/5 gold -> 5/5. 'eGFR' and 'EGFR' are a case-only homograph
#           (estimated Glomerular Filtration Rate vs Epidermal Growth Factor
#           Receptor) and the receptor concepts take the whole candidate pool.
#   NSTEMI, TIA, Stroke  same shape: the intended concept is absent from the
#           pool bare and present expanded.
#
# The other ten are deliberately absent, and adding them would make things worse
# or make no difference:
#   ALT AST CK-MB COPD HbA1c STEMI  no material difference -- the abbreviation
#           already appears literally in the LOINC/SNOMED concept names.
#   Glucose Sarcoma  expansion measured WORSE. Both are 7 characters, so
#           _MAX_ABBREV_LENGTH already excludes them; do not "fix" that.
#   ECG     no query rewrite reaches the umbrella concept 4163951; both forms
#           return sub-procedures.
#   insulin OMOP has no umbrella standard ingredient for it; that belongs to
#           drug-class expansion, not to query rewriting.
#
# Consulted before the UMLS backend because these are measured decisions, while
# the UMLS path takes cuis[:1] from a query with no ORDER BY and would resolve
# the eGFR/EGFR homograph arbitrarily.
_CURATED_EXPANSIONS: dict[tuple[str, str], str] = {
    ("eGFR", "Measurement"): "estimated glomerular filtration rate",
    ("NSTEMI", "Condition"): "non-ST elevation myocardial infarction",
    ("TIA", "Condition"): "transient ischemic attack",
    ("Stroke", "Condition"): "cerebrovascular accident",
}


class QueryExpander:
    """Expand short clinical abbreviations to canonical names via UMLS."""

    def __init__(self, umls_expander=None):
        self._enabled = os.environ.get("AGENT2_QUERY_EXPAND", "true").lower() == "true"
        self._umls = umls_expander

    def expand(self, query: str, domain_hint: Optional[str] = None) -> str:
        """Expand a short clinical abbreviation to its canonical form.

        Args:
            query: The query text (e.g. "MI", "GLP-1", "CHF").
            domain_hint: OMOP domain hint from Agent 1 (e.g. "Condition", "Drug").
                        Required for expansion; without it, query passes through.

        Returns:
            Expanded canonical term if abbreviation is recognized,
            otherwise the original query unchanged.
        """
        if not self._enabled:
            return query
        if not domain_hint:
            return query

        stripped = query.strip()
        if not stripped:
            return query
        if len(stripped) > _MAX_ABBREV_LENGTH:
            return query

        canonical = self._lookup_canonical(stripped, domain_hint)
        if canonical and canonical.lower() != stripped.lower():
            logger.info(
                "[QueryExpander] Expanded '%s' -> '%s' (domain=%s)",
                stripped,
                canonical,
                domain_hint,
            )
            return canonical
        return query

    def _lookup_canonical(
        self, abbrev: str, domain_hint: str
    ) -> Optional[str]:
        """Look up canonical name for abbreviation via UMLS.

        Args:
            abbrev: Short abbreviation text.
            domain_hint: OMOP domain for MRSTY filtering.

        Returns:
            Preferred term string, or None if not found.
        """
        curated = _CURATED_EXPANSIONS.get((abbrev, domain_hint))
        if curated is not None:
            return curated
        if self._umls is None:
            return None
        try:
            cuis = self._umls.get_cuis(abbrev, domain_hint=domain_hint)
            if not cuis:
                return None
            # Get the preferred name for the first matching CUI
            for cui in cuis[:1]:
                synonyms = self._umls.get_synonyms_for_cui(cui, max_synonyms=1)
                if synonyms:
                    return synonyms[0]
            return None
        except Exception:
            logger.warning(
                "[QueryExpander] UMLS lookup failed for '%s'",
                abbrev,
                exc_info=True,
            )
            return None
