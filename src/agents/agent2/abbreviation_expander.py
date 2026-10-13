"""
Medical Abbreviation Expander for Agent 2.

DEPRECATED: Hardcoded dictionary removed, and no other module expands
abbreviations either: the query reaches retrieval as Agent 1 wrote it.

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
