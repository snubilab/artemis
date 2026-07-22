"""
Test: PMC Full-Text Fetcher & Eligibility Section Extraction.
Tests PMID-to-PMCID conversion, full-text XML fetching, and eligibility section parsing.
"""
import re
import pytest
from unittest.mock import patch, MagicMock


SAMPLE_IDCONV_JSON = """
{
    "records": [
        {
            "pmid": "23953384",
            "pmcid": "PMC3901982",
            "doi": "10.1111/dom.12177"
        }
    ],
    "status": "ok"
}
"""

SAMPLE_IDCONV_NO_PMC_JSON = """
{
    "records": [
        {
            "pmid": "99999999",
            "errmsg": "No record found"
        }
    ],
    "status": "ok"
}
"""

SAMPLE_PMC_XML = """<?xml version="1.0" encoding="UTF-8"?>
<article>
  <body>
    <sec sec-type="methods">
      <title>Methods</title>
      <sec>
        <title>Eligibility Criteria</title>
        <p>Patients were eligible if they had type 2 diabetes and HbA1c >= 7.0%.</p>
        <p>Inclusion criteria: adults aged 50 or older with cardiovascular disease.</p>
        <p>Exclusion criteria: type 1 diabetes, GLP-1 receptor agonist use within 90 days.</p>
      </sec>
    </sec>
  </body>
</article>
"""

SAMPLE_PMC_XML_STUDY_POPULATION = """<?xml version="1.0" encoding="UTF-8"?>
<article>
  <body>
    <sec sec-type="methods">
      <title>Methods</title>
      <sec>
        <title>Study Population</title>
        <p>Eligible participants included adults with confirmed diagnosis.</p>
        <p>Participants were excluded if they had prior treatment failure.</p>
      </sec>
    </sec>
  </body>
</article>
"""

SAMPLE_PMC_XML_NO_ELIGIBILITY = """<?xml version="1.0" encoding="UTF-8"?>
<article>
  <body>
    <sec sec-type="results">
      <title>Results</title>
      <p>The primary endpoint was reached in 80% of patients.</p>
    </sec>
  </body>
</article>
"""

SAMPLE_PMC_XML_METHODS_FALLBACK = """<?xml version="1.0" encoding="UTF-8"?>
<article>
  <body>
    <sec sec-type="methods">
      <title>Methods</title>
      <p>All patients were enrolled after giving informed consent.</p>
      <p>Key inclusion: age 18 or older, confirmed diagnosis. Key exclusion: prior malignancy.</p>
    </sec>
  </body>
</article>
"""


class TestPmidToPmcid:
    """Tests for PMID to PMCID conversion via NCBI ID Converter API."""

    def test_converts_pmid_to_pmcid_success(self):
        """
        Given: Valid PMID with a PMC version
        When:  pmid_to_pmcid is called (mocked)
        Then:  Returns the PMCID string
        """
        from src.agents.agent1.pmc_fetcher import pmid_to_pmcid

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "records": [{"pmid": "23953384", "pmcid": "PMC3901982"}],
            "status": "ok",
        }

        with patch("requests.get", return_value=mock_response):
            result = pmid_to_pmcid("23953384")

        assert result == "PMC3901982"

    def test_returns_none_when_no_pmcid(self):
        """
        Given: PMID with no open-access PMC version
        When:  pmid_to_pmcid is called
        Then:  Returns None
        """
        from src.agents.agent1.pmc_fetcher import pmid_to_pmcid

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "records": [{"pmid": "99999999", "errmsg": "No record found"}],
            "status": "ok",
        }

        with patch("requests.get", return_value=mock_response):
            result = pmid_to_pmcid("99999999")

        assert result is None

    def test_returns_none_on_http_error(self):
        """
        Given: API returns an HTTP error
        When:  pmid_to_pmcid is called
        Then:  Returns None (graceful fallback)
        """
        from src.agents.agent1.pmc_fetcher import pmid_to_pmcid

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("HTTP 500")

        with patch("requests.get", return_value=mock_response):
            result = pmid_to_pmcid("23953384")

        assert result is None

    def test_returns_none_on_empty_records(self):
        """
        Given: API returns empty records list
        When:  pmid_to_pmcid is called
        Then:  Returns None
        """
        from src.agents.agent1.pmc_fetcher import pmid_to_pmcid

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"records": [], "status": "ok"}

        with patch("requests.get", return_value=mock_response):
            result = pmid_to_pmcid("23953384")

        assert result is None


class TestFetchPmcFulltext:
    """Tests for fetching and extracting full-text XML from PMC OA."""

    def test_fetch_fulltext_success(self):
        """
        Given: Valid PMCID with open-access full-text
        When:  fetch_pmc_fulltext is called (mocked)
        Then:  Returns extracted body text
        """
        from src.agents.agent1.pmc_fetcher import fetch_pmc_fulltext

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = SAMPLE_PMC_XML

        with patch("requests.get", return_value=mock_response):
            result = fetch_pmc_fulltext("PMC3901982")

        assert result is not None
        assert "type 2 diabetes" in result.lower()

    def test_fetch_fulltext_returns_none_on_error(self):
        """
        Given: API request fails
        When:  fetch_pmc_fulltext is called
        Then:  Returns None (graceful fallback)
        """
        from src.agents.agent1.pmc_fetcher import fetch_pmc_fulltext

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("HTTP 404")

        with patch("requests.get", return_value=mock_response):
            result = fetch_pmc_fulltext("PMC9999999")

        assert result is None

    def test_fetch_fulltext_strips_xml_tags(self):
        """
        Given: PMC XML response with body tags
        When:  fetch_pmc_fulltext is called
        Then:  Returns plain text without XML tags
        """
        from src.agents.agent1.pmc_fetcher import fetch_pmc_fulltext

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = SAMPLE_PMC_XML

        with patch("requests.get", return_value=mock_response):
            result = fetch_pmc_fulltext("PMC3901982")

        assert result is not None
        # XML tags should be stripped — no angle-bracket tag patterns remain
        assert not re.search(r"<\s*\w", result), "XML opening tags should be stripped"
        assert not re.search(r"</\s*\w", result), "XML closing tags should be stripped"

    def test_fetch_fulltext_returns_none_when_no_body(self):
        """
        Given: XML response with no <body> element
        When:  fetch_pmc_fulltext is called
        Then:  Returns None
        """
        from src.agents.agent1.pmc_fetcher import fetch_pmc_fulltext

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = """<?xml version="1.0"?><article><front><title>Test</title></front></article>"""

        with patch("requests.get", return_value=mock_response):
            result = fetch_pmc_fulltext("PMC3901982")

        assert result is None


class TestExtractEligibilitySection:
    """Tests for extracting eligibility/methods sections from PMC full-text."""

    def test_extracts_eligibility_criteria_section(self):
        """
        Given: Full-text with explicit 'Eligibility Criteria' section
        When:  extract_eligibility_section is called
        Then:  Returns the eligibility section text
        """
        from src.agents.agent1.pmc_fetcher import extract_eligibility_section, fetch_pmc_fulltext

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = SAMPLE_PMC_XML

        with patch("requests.get", return_value=mock_response):
            fulltext = fetch_pmc_fulltext("PMC3901982")

        assert fulltext is not None
        section = extract_eligibility_section(fulltext)
        assert "type 2 diabetes" in section.lower()

    def test_extracts_study_population_section(self):
        """
        Given: Full-text with 'Study Population' section (no Eligibility header)
        When:  extract_eligibility_section is called
        Then:  Returns the study population section text
        """
        from src.agents.agent1.pmc_fetcher import extract_eligibility_section, fetch_pmc_fulltext

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = SAMPLE_PMC_XML_STUDY_POPULATION

        with patch("requests.get", return_value=mock_response):
            fulltext = fetch_pmc_fulltext("PMC0000001")

        assert fulltext is not None
        section = extract_eligibility_section(fulltext)
        assert len(section) > 0
        assert "eligible" in section.lower() or "excluded" in section.lower()

    def test_falls_back_to_methods_section(self):
        """
        Given: Full-text with no eligibility/population section, but methods section exists
        When:  extract_eligibility_section is called
        Then:  Returns the methods section text as fallback
        """
        from src.agents.agent1.pmc_fetcher import extract_eligibility_section, fetch_pmc_fulltext

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = SAMPLE_PMC_XML_METHODS_FALLBACK

        with patch("requests.get", return_value=mock_response):
            fulltext = fetch_pmc_fulltext("PMC0000002")

        assert fulltext is not None
        section = extract_eligibility_section(fulltext)
        assert len(section) > 0

    def test_returns_empty_string_when_no_relevant_section(self):
        """
        Given: Full-text with only a results section (no methods, no patient criteria)
        When:  extract_eligibility_section is called
        Then:  Returns empty string
        """
        from src.agents.agent1.pmc_fetcher import extract_eligibility_section

        results_only_text = (
            "The primary endpoint was met in 80% of patients. "
            "Secondary outcomes showed significant improvement. "
            "Adverse events were reported in 12% of the treatment group."
        )
        result = extract_eligibility_section(results_only_text)
        assert result == ""

    def test_returns_empty_string_on_empty_input(self):
        """
        Given: Empty string input
        When:  extract_eligibility_section is called
        Then:  Returns empty string
        """
        from src.agents.agent1.pmc_fetcher import extract_eligibility_section

        assert extract_eligibility_section("") == ""


class TestGetPmcEligibility:
    """Tests for the high-level convenience function combining all steps."""

    def test_get_pmc_eligibility_full_pipeline(self):
        """
        Given: A PMID that has a PMC version with eligibility section
        When:  get_pmc_eligibility is called (all HTTP calls mocked)
        Then:  Returns Dict with inclusion/exclusion lists
        """
        from src.agents.agent1.pmc_fetcher import get_pmc_eligibility

        idconv_response = MagicMock()
        idconv_response.status_code = 200
        idconv_response.json.return_value = {
            "records": [{"pmid": "23953384", "pmcid": "PMC3901982"}],
            "status": "ok",
        }

        fulltext_response = MagicMock()
        fulltext_response.status_code = 200
        fulltext_response.text = SAMPLE_PMC_XML

        with patch("requests.get", side_effect=[idconv_response, fulltext_response]):
            result = get_pmc_eligibility("23953384")

        assert result is not None
        assert "inclusion" in result
        assert "exclusion" in result

    def test_get_pmc_eligibility_returns_none_when_no_pmc(self):
        """
        Given: A PMID with no open-access PMC version
        When:  get_pmc_eligibility is called
        Then:  Returns None
        """
        from src.agents.agent1.pmc_fetcher import get_pmc_eligibility

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "records": [{"pmid": "99999999", "errmsg": "No record found"}],
            "status": "ok",
        }

        with patch("requests.get", return_value=mock_response):
            result = get_pmc_eligibility("99999999")

        assert result is None

    def test_get_pmc_eligibility_returns_none_when_no_eligibility_section(self):
        """
        Given: PMC article with no eligibility-relevant sections
        When:  get_pmc_eligibility is called
        Then:  Returns None
        """
        from src.agents.agent1.pmc_fetcher import get_pmc_eligibility

        idconv_response = MagicMock()
        idconv_response.status_code = 200
        idconv_response.json.return_value = {
            "records": [{"pmid": "12345678", "pmcid": "PMC1234567"}],
            "status": "ok",
        }

        fulltext_response = MagicMock()
        fulltext_response.status_code = 200
        fulltext_response.text = SAMPLE_PMC_XML_NO_ELIGIBILITY

        with patch("requests.get", side_effect=[idconv_response, fulltext_response]):
            result = get_pmc_eligibility("12345678")

        assert result is None
