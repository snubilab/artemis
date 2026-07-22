"""
Medical Abbreviation Expander for Agent 2.

DEPRECATED: Hardcoded dictionary removed. Abbreviation expansion is now
handled by the UMLS Synonym Expander (umls_synonym_expander.py) which
uses MRCONSO for broader, more generalizable coverage.

These functions are kept as no-ops for backward compatibility.
"""
from typing import Tuple
import logging

logger = logging.getLogger(__name__)


def expand_abbreviation(text: str) -> Tuple[str, bool]:
    """No-op. Returns input unchanged."""
    return text.strip(), False


def expand_in_context(text: str) -> str:
    """No-op. Returns input unchanged."""
    return text
