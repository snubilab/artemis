"""
Test 08: PubMed Paper Fetching (Subtask 02).
Tests abstract fetching from PubMed. Finding the eligibility criteria in an abstract is the
segmentation step's job and is tested in tests/test_eligibility_segmentation.py.
"""
from unittest.mock import patch, MagicMock


SAMPLE_ABSTRACT = """
BACKGROUND: The Liraglutide Effect and Action in Diabetes: Evaluation of Cardiovascular 
Outcome Results (LEADER) trial is designed to evaluate the long-term cardiovascular safety 
of liraglutide in subjects with type 2 diabetes.

METHODS: LEADER is a multinational, double-blind, placebo-controlled clinical trial. 
Key inclusion criteria include: adults with type 2 diabetes, HbA1c ≥7.0%, and either 
age ≥50 years with established cardiovascular, cerebrovascular, or peripheral vascular 
disease, chronic heart failure NYHA class II-III, or chronic kidney disease stage ≥3, 
or age ≥60 years with at least one cardiovascular risk factor.
Key exclusion criteria include: type 1 diabetes, use of GLP-1 receptor agonists within 
90 days, acute coronary or cerebrovascular event within 14 days, planned revascularization, 
familial or personal history of MEN2 or medullary thyroid carcinoma, and malignant neoplasm 
requiring treatment in the last 5 years.

CONCLUSIONS: LEADER will provide important data on the CV safety of liraglutide.
"""


class TestPubMedFetcher:
    """Tests for fetching PubMed abstracts."""

    def test_fetch_abstract_success(self):
        """
        Given: Valid PMID
        When:  fetch_pubmed_abstract is called (mocked)
        Then:  Returns abstract text
        """
        from src.agents.agent1.pubmed_fetcher import fetch_pubmed_abstract

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = f"""<?xml version="1.0" ?>
        <PubmedArticleSet>
            <PubmedArticle>
                <MedlineCitation>
                    <Article>
                        <ArticleTitle>LEADER Trial Design</ArticleTitle>
                        <Abstract>
                            <AbstractText>{SAMPLE_ABSTRACT}</AbstractText>
                        </Abstract>
                    </Article>
                </MedlineCitation>
            </PubmedArticle>
        </PubmedArticleSet>"""

        with patch("requests.get", return_value=mock_response):
            result = fetch_pubmed_abstract("23953384")

        assert result is not None
        assert "LEADER" in result.title
        assert "type 2 diabetes" in result.abstract

    def test_fetch_abstract_not_found(self):
        """
        Given: PMID that doesn't exist
        When:  fetch_pubmed_abstract is called
        Then:  Returns None
        """
        from src.agents.agent1.pubmed_fetcher import fetch_pubmed_abstract

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = """<?xml version="1.0" ?>
        <PubmedArticleSet></PubmedArticleSet>"""

        with patch("requests.get", return_value=mock_response):
            result = fetch_pubmed_abstract("99999999")

        assert result is None
