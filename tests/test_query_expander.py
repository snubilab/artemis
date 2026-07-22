"""Tests for UMLS-backed query pre-expansion.

Verifies that short clinical abbreviations (MI, GLP-1, etc.) are expanded
to canonical clinical terms before ChromaDB search, using UMLS MRCONSO
with domain filtering.
"""
import os

import pytest
from unittest.mock import MagicMock, patch


def _make_expander_with_mock_umls(
    cui_map: dict[str, list[tuple[str, str, str]]] | None = None,
    domain_filtered: dict[str, str] | None = None,
):
    """Create QueryExpander with mocked UMLS expander.

    Args:
        cui_map: Maps query text -> list of (CUI, preferred_name, semantic_type).
                 Used for simple lookups without domain filtering.
        domain_filtered: Maps "query|domain_hint" -> preferred_name.
                        Used for domain-aware disambiguation tests.
    """
    from src.agents.agent2.query_expander import QueryExpander

    mock_umls = MagicMock()
    mock_umls.is_available = True

    def mock_get_cuis(text: str, domain_hint: str | None = None) -> list[str]:
        # Domain-filtered path
        if domain_filtered:
            key = f"{text}|{domain_hint}" if domain_hint else text
            if key in domain_filtered:
                return ["C_MOCK"]

        # Simple CUI map path
        if cui_map and text in cui_map:
            return [entry[0] for entry in cui_map[text]]
        return []

    def mock_get_synonyms(cui: str, max_synonyms: int = 1) -> list[str]:
        # Domain-filtered path: return the preferred name
        if domain_filtered:
            for value in domain_filtered.values():
                return [value]

        # Simple CUI map path: find preferred name by CUI
        if cui_map:
            for entries in cui_map.values():
                for entry_cui, pref_name, _ in entries:
                    if entry_cui == cui:
                        return [pref_name]
        return []

    mock_umls.get_cuis = mock_get_cuis
    mock_umls.get_synonyms_for_cui = mock_get_synonyms
    return QueryExpander(umls_expander=mock_umls)


class TestQueryExpander:
    """Tests for QueryExpander abbreviation expansion."""

    def test_short_abbreviation_expanded(self):
        """MI with Condition domain -> Myocardial Infarction."""
        expander = _make_expander_with_mock_umls(
            cui_map={
                "MI": [("C0027051", "Myocardial Infarction", "Disease or Syndrome")]
            }
        )
        result = expander.expand("MI", domain_hint="Condition")
        assert "myocardial infarction" in result.lower()

    def test_long_query_unchanged(self):
        """Full clinical terms (>6 chars) should not be modified."""
        expander = _make_expander_with_mock_umls(cui_map={})
        result = expander.expand("Myocardial infarction", domain_hint="Condition")
        assert result == "Myocardial infarction"

    def test_no_domain_hint_unchanged(self):
        """Without domain hint, short queries pass through."""
        expander = _make_expander_with_mock_umls(cui_map={})
        result = expander.expand("MI", domain_hint=None)
        assert result == "MI"

    def test_drug_abbreviation(self):
        """GLP-1 with Drug domain -> Glucagon-Like Peptide 1."""
        expander = _make_expander_with_mock_umls(
            cui_map={
                "GLP-1": [
                    ("C0061355", "Glucagon-Like Peptide 1", "Amino Acid, Peptide, or Protein")
                ]
            }
        )
        result = expander.expand("GLP-1", domain_hint="Drug")
        assert "glucagon" in result.lower()

    def test_env_var_disable(self):
        """AGENT2_QUERY_EXPAND=false disables expansion."""
        with patch.dict(os.environ, {"AGENT2_QUERY_EXPAND": "false"}):
            expander = _make_expander_with_mock_umls(
                cui_map={
                    "MI": [("C0027051", "Myocardial Infarction", "Disease or Syndrome")]
                }
            )
            result = expander.expand("MI", domain_hint="Condition")
            assert result == "MI"

    def test_ambiguous_abbreviation_domain_disambiguates(self):
        """MI with Condition domain -> Myocardial Infarction, not Mitral Insufficiency."""
        expander = _make_expander_with_mock_umls(
            domain_filtered={"MI|Condition": "Myocardial Infarction"}
        )
        result = expander.expand("MI", domain_hint="Condition")
        assert "myocardial" in result.lower()
        assert "mitral" not in result.lower()

    def test_no_umls_expander_passes_through(self):
        """When UMLS expander is None, queries pass through unchanged."""
        from src.agents.agent2.query_expander import QueryExpander

        expander = QueryExpander(umls_expander=None)
        result = expander.expand("MI", domain_hint="Condition")
        assert result == "MI"

    def test_umls_lookup_error_passes_through(self):
        """When UMLS lookup raises an exception, query passes through."""
        from src.agents.agent2.query_expander import QueryExpander

        mock_umls = MagicMock()
        mock_umls.is_available = True
        mock_umls.get_cuis.side_effect = RuntimeError("SQLite error")
        expander = QueryExpander(umls_expander=mock_umls)
        result = expander.expand("MI", domain_hint="Condition")
        assert result == "MI"

    def test_empty_query_unchanged(self):
        """Empty or whitespace-only queries pass through."""
        expander = _make_expander_with_mock_umls(cui_map={})
        assert expander.expand("", domain_hint="Condition") == ""
        assert expander.expand("   ", domain_hint="Condition") == "   "

    def test_six_char_boundary(self):
        """Queries with exactly 6 chars are expanded; 7 chars are not."""
        expander = _make_expander_with_mock_umls(
            cui_map={
                "ABCDEF": [("C_TEST", "Expanded Term", "Test Type")],
                "ABCDEFG": [("C_TEST2", "Should Not Expand", "Test Type")],
            }
        )
        result_6 = expander.expand("ABCDEF", domain_hint="Condition")
        assert result_6 == "Expanded Term"

        result_7 = expander.expand("ABCDEFG", domain_hint="Condition")
        assert result_7 == "ABCDEFG"
