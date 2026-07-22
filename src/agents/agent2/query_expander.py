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
