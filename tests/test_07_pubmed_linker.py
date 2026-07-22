"""
Test 07: NCT → PMID Linking (Subtask 01).
Tests the PubMed linker that extracts PMIDs from NCT references
and falls back to PubMed esearch.
"""
import pytest
from unittest.mock import patch, MagicMock


class TestPubMedLinker:
    """Tests for NCT → PMID linking."""

    def test_extract_pmids_from_nct_references(self):
        """
        Given: NCT data with referencesModule containing PMIDs
        When:  extract_pmids_from_nct is called
        Then:  Returns PMID list from references
        """
        from src.agents.agent1.pubmed_linker import extract_pmids_from_nct

        nct_data = {
            "protocolSection": {
                "referencesModule": {
                    "references": [
                        {"pmid": "27295427", "type": "RESULT",
                         "citation": "Marso SP, et al. N Engl J Med. 2016"},
                        {"pmid": "23953384", "type": "BACKGROUND",
                         "citation": "Marso SP, et al. Am Heart J. 2013"},
                        {"type": "BACKGROUND",
                         "citation": "Something without PMID"},
                    ]
                }
            }
        }

        pmids = extract_pmids_from_nct(nct_data)
        assert len(pmids) == 2
        assert "27295427" in pmids
        assert "23953384" in pmids

    def test_extract_pmids_no_references_module(self):
        """
        Given: NCT data without referencesModule
        When:  extract_pmids_from_nct is called
        Then:  Returns empty list
        """
        from src.agents.agent1.pubmed_linker import extract_pmids_from_nct

        nct_data = {"protocolSection": {}}
        pmids = extract_pmids_from_nct(nct_data)
        assert pmids == []

    def test_search_pubmed_for_nct(self):
        """
        Given: NCT ID
        When:  search_pubmed_for_nct is called (mocked API)
        Then:  Returns PMIDs from PubMed esearch
        """
        from src.agents.agent1.pubmed_linker import search_pubmed_for_nct

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = """<?xml version="1.0" ?>
        <eSearchResult>
            <IdList>
                <Id>27295427</Id>
                <Id>23953384</Id>
            </IdList>
        </eSearchResult>"""

        with patch("requests.get", return_value=mock_response):
            pmids = search_pubmed_for_nct("NCT01179048")

        assert len(pmids) == 2
        assert "27295427" in pmids

    def test_search_pubmed_api_failure(self):
        """
        Given: API returns error
        When:  search_pubmed_for_nct is called
        Then:  Returns empty list (graceful fallback)
        """
        from src.agents.agent1.pubmed_linker import search_pubmed_for_nct

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = Exception("Server Error")

        with patch("requests.get", return_value=mock_response):
            pmids = search_pubmed_for_nct("NCT01179048")

        assert pmids == []

    def test_get_design_paper_pmids(self):
        """
        Given: NCT data with references (some RESULT, some BACKGROUND)
        When:  get_design_paper_pmids is called
        Then:  Prioritizes BACKGROUND type (design papers)
        """
        from src.agents.agent1.pubmed_linker import get_design_paper_pmids

        nct_data = {
            "protocolSection": {
                "referencesModule": {
                    "references": [
                        {"pmid": "27295427", "type": "RESULT",
                         "citation": "Marso SP. Liraglutide and outcomes. NEJM 2016"},
                        {"pmid": "23953384", "type": "BACKGROUND",
                         "citation": "Marso SP. LEADER design. Am Heart J. 2013"},
                    ]
                }
            }
        }

        pmids = get_design_paper_pmids(nct_data)
        # BACKGROUND papers come first (design papers)
        assert pmids[0] == "23953384"
