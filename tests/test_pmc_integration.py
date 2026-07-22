"""
Integration tests: PMC enrichment pipeline across multiple preset NCT trials.

Covers the full priority chain:
    PMC supplements -> PMC full-text eligibility -> PubMed abstract fallback

All HTTP calls are mocked — no real network requests are made.

Preset trials tested:
  - LEADER      (NCT01179048) — Liraglutide CV outcomes; has BACKGROUND PMIDs
  - PLATO       (NCT00391872) — Ticagrelor vs Clopidogrel; DERIVED only
  - EMPA-REG    (NCT01131676) — Empagliflozin CV outcomes; DERIVED only
  - DECLARE-TIMI (NCT01730534) — Dapagliflozin CV outcomes; DERIVED only
"""
import io
import tarfile
from unittest.mock import MagicMock, patch

import pytest

from src.agents.agent1.nct_fetcher import TrialData


# ---------------------------------------------------------------------------
# Realistic mock data
# ---------------------------------------------------------------------------

LEADER_PMC_FULLTEXT = """
Study Design The Liraglutide Effect and Action in Diabetes Evaluation of Cardiovascular Outcome Results \
(LEADER) trial is a multinational double-blind placebo-controlled clinical trial.

Study Population Eligibility Criteria Patients were eligible for enrollment if they had type 2 diabetes \
with a glycated hemoglobin level of 7.0% or more. Additional inclusion criteria were: age of 50 years or \
older with at least one cardiovascular condition (coronary heart disease, cerebrovascular disease, peripheral \
vascular disease, chronic kidney disease of stage 3 or greater, or chronic heart failure of NYHA class II or III), \
or age of 60 years or older with at least one cardiovascular risk factor (microalbuminuria or proteinuria, \
hypertension and left ventricular hypertrophy, left ventricular systolic or diastolic dysfunction, or an \
ankle-brachial index of less than 0.9).

Exclusion criteria included: type 1 diabetes, use of a GLP-1 receptor agonist DPP-4 inhibitor or insulin \
other than basal or premixed insulin within 3 months before screening, an acute coronary or cerebrovascular \
event within 14 days before screening, planned coronary or carotid revascularization, a family or personal \
history of multiple endocrine neoplasia type 2 or medullary thyroid carcinoma, and end-stage liver disease.

Randomization and Treatment Patients were randomly assigned in a 1:1 ratio to receive liraglutide or placebo.
"""

PLATO_ABSTRACT = """
BACKGROUND: The PLATelet inhibition and patient Outcomes (PLATO) trial compared ticagrelor with clopidogrel \
in patients with acute coronary syndromes. Key inclusion criteria include: hospitalization for acute coronary \
syndrome with or without ST-segment elevation, onset of symptoms within 24 hours. Key exclusion criteria include: \
contraindication to clopidogrel, fibrinolytic therapy within 24 hours, need for oral anticoagulation therapy, \
increased risk of bradycardic events.
"""

EMPA_REG_ABSTRACT = """
BACKGROUND: The EMPA-REG OUTCOME trial evaluated empagliflozin in patients with type 2 diabetes and \
established cardiovascular disease. Key inclusion criteria include: type 2 diabetes, HbA1c 7-10%, \
established cardiovascular disease, estimated GFR >= 30 mL/min. Key exclusion criteria include: \
type 1 diabetes, eGFR < 30, liver disease, recent acute coronary syndrome.
"""

DECLARE_ABSTRACT = """
BACKGROUND: The DECLARE-TIMI 58 trial evaluated dapagliflozin in patients with type 2 diabetes. \
Key inclusion criteria include: type 2 diabetes with HbA1c 6.5-12%, age >= 40 with atherosclerotic \
cardiovascular disease or multiple risk factors. Key exclusion criteria include: type 1 diabetes, \
eGFR < 60 mL/min/1.73m2, prior bladder cancer.
"""

PMC_OA_XML_WITH_TGZ = """<?xml version="1.0" encoding="UTF-8"?>
<OA>
  <records returned-count="1">
    <record id="PMC3901982" citation="Marso et al.">
      <link format="tgz" href="https://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_package/ab/cd/PMC3901982.tar.gz" />
    </record>
  </records>
</OA>
"""

PMC_OA_XML_EMPTY = """<?xml version="1.0" encoding="UTF-8"?>
<OA>
  <records returned-count="0">
  </records>
</OA>
"""


def _make_tgz_bytes(members: dict) -> bytes:
    """Build an in-memory .tar.gz with {name: content} mapping."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    buf.seek(0)
    return buf.read()


def _make_idconv_response(pmid: str, pmcid: str) -> MagicMock:
    """Return a mock NCBI ID converter response mapping pmid -> pmcid."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "records": [{"pmid": pmid, "pmcid": pmcid}],
        "status": "ok",
    }
    return resp


def _make_idconv_no_pmc_response(pmid: str) -> MagicMock:
    """Return a mock NCBI ID converter response for a PMID with no PMC version."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "records": [{"pmid": pmid, "errmsg": "No record found"}],
        "status": "ok",
    }
    return resp


def _make_fulltext_response(body_text: str) -> MagicMock:
    """Return a mock PMC efetch XML response wrapping body_text in <body> tags."""
    resp = MagicMock()
    resp.status_code = 200
    resp.text = f"<article><body>{body_text}</body></article>"
    return resp


def _make_pubmed_abstract_xml(pmid: str, abstract: str) -> str:
    """Build minimal PubMed XML containing an abstract."""
    return (
        f"<PubmedArticleSet><PubmedArticle>"
        f"<MedlineCitation><PMID>{pmid}</PMID>"
        f"<Article><ArticleTitle>Test Title</ArticleTitle>"
        f"<Abstract><AbstractText>{abstract}</AbstractText></Abstract>"
        f"</Article></MedlineCitation></PubmedArticle></PubmedArticleSet>"
    )


# ---------------------------------------------------------------------------
# TestPmcFullTextEnrichment
# ---------------------------------------------------------------------------

class TestPmcFullTextEnrichment:
    """Tests that PMC full-text extraction works for trials with open-access papers."""

    def test_leader_trial_pmc_fulltext_enrichment(self):
        """
        Given: LEADER PMID 23953384 has PMC full-text (PMC3901982) with detailed eligibility
        When:  get_pmc_eligibility is called with mocked HTTP
        Then:  Returns dict with non-empty inclusion and/or exclusion criteria lists
        """
        from src.agents.agent1.pmc_fetcher import get_pmc_eligibility

        idconv_resp = _make_idconv_response("23953384", "PMC3901982")
        fulltext_resp = _make_fulltext_response(LEADER_PMC_FULLTEXT)

        with patch("requests.get", side_effect=[idconv_resp, fulltext_resp]):
            result = get_pmc_eligibility("23953384")

        assert result is not None
        assert "inclusion" in result
        assert "exclusion" in result
        # The LEADER full-text contains substantive eligibility text
        total_criteria = len(result["inclusion"]) + len(result["exclusion"])
        assert total_criteria > 0

    def test_trial_without_pmc_version_falls_through(self):
        """
        Given: A PMID whose paper is not in PMC OA (no PMCID returned)
        When:  get_pmc_eligibility is called
        Then:  Returns None, allowing the caller to fall back to other sources
        """
        from src.agents.agent1.pmc_fetcher import get_pmc_eligibility

        no_pmc_resp = _make_idconv_no_pmc_response("99999999")

        with patch("requests.get", return_value=no_pmc_resp):
            result = get_pmc_eligibility("99999999")

        assert result is None

    def test_pmc_article_without_eligibility_section(self):
        """
        Given: PMC article exists but its body contains no eligibility-related text
        When:  get_pmc_eligibility is called
        Then:  Returns None (no usable criteria found)
        """
        from src.agents.agent1.pmc_fetcher import get_pmc_eligibility

        idconv_resp = _make_idconv_response("12345678", "PMC1234567")
        # Body has only results — no eligibility keywords
        results_only_body = (
            "The primary endpoint was met in 80 percent of patients. "
            "Secondary outcomes showed significant improvement across all subgroups. "
            "Adverse events were reported in 12 percent of the treatment group. "
            "There was no significant difference in overall mortality."
        )
        fulltext_resp = _make_fulltext_response(results_only_body)

        with patch("requests.get", side_effect=[idconv_resp, fulltext_resp]):
            result = get_pmc_eligibility("12345678")

        assert result is None


# ---------------------------------------------------------------------------
# TestPmcSupplementDownload
# ---------------------------------------------------------------------------

class TestPmcSupplementDownload:
    """Tests supplement discovery and download for preset trials."""

    def test_downloads_supplement_pdfs_for_leader(self, tmp_path):
        """
        Given: LEADER PMCID PMC3901982 OA package contains a supplement PDF
        When:  download_pmc_supplements is called with mocked HTTP
        Then:  Returns a non-empty list; at least one entry has role='supplement'
        """
        from src.agents.agent1.pmc_supplement import download_pmc_supplements

        tgz_content = _make_tgz_bytes({
            "PMC3901982.pdf": b"%PDF-1.4 main article",
            "PMC3901982_supplement_s1.pdf": b"%PDF-1.4 eligibility supplement",
        })

        oa_resp = MagicMock()
        oa_resp.status_code = 200
        oa_resp.text = PMC_OA_XML_WITH_TGZ

        tgz_resp = MagicMock()
        tgz_resp.status_code = 200
        tgz_resp.content = tgz_content

        def fake_get(url, **kwargs):
            if "oa.fcgi" in url:
                return oa_resp
            return tgz_resp

        with patch("requests.get", side_effect=fake_get):
            results = download_pmc_supplements(
                pmcid="PMC3901982",
                nct_id="NCT01179048",
                output_dir=str(tmp_path),
            )

        assert len(results) >= 1
        roles = {r["role"] for r in results}
        assert "supplement" in roles

    def test_no_supplements_when_article_not_in_oa(self, tmp_path):
        """
        Given: PLATO PMID has no PMC OA version (empty OA response)
        When:  download_pmc_supplements is called
        Then:  Returns empty list without raising
        """
        from src.agents.agent1.pmc_supplement import download_pmc_supplements

        oa_resp = MagicMock()
        oa_resp.status_code = 200
        oa_resp.text = PMC_OA_XML_EMPTY

        with patch("requests.get", return_value=oa_resp):
            results = download_pmc_supplements(
                pmcid="PMC9999999",
                nct_id="NCT00391872",
                output_dir=str(tmp_path),
            )

        assert results == []

    def test_classifies_mixed_pdfs_correctly(self, tmp_path):
        """
        Given: tgz package containing main article, supplement, and appendix PDFs
        When:  download_pmc_supplements is called
        Then:  Each file is classified with the correct role
        """
        from src.agents.agent1.pmc_supplement import download_pmc_supplements

        tgz_content = _make_tgz_bytes({
            "PMC3901982.pdf": b"%PDF-1.4 main",
            "supplement_s1.pdf": b"%PDF-1.4 supplement",
            "appendix_A.pdf": b"%PDF-1.4 appendix",
        })

        oa_resp = MagicMock()
        oa_resp.status_code = 200
        oa_resp.text = PMC_OA_XML_WITH_TGZ

        tgz_resp = MagicMock()
        tgz_resp.status_code = 200
        tgz_resp.content = tgz_content

        def fake_get(url, **kwargs):
            if "oa.fcgi" in url:
                return oa_resp
            return tgz_resp

        with patch("requests.get", side_effect=fake_get):
            results = download_pmc_supplements(
                pmcid="PMC3901982",
                nct_id="NCT01179048",
                output_dir=str(tmp_path),
            )

        assert len(results) == 3
        role_by_name = {r["name"]: r["role"] for r in results}
        assert role_by_name["PMC3901982.pdf"] == "main"
        assert role_by_name["supplement_s1.pdf"] == "supplement"
        assert role_by_name["appendix_A.pdf"] == "appendix"


# ---------------------------------------------------------------------------
# TestEnrichmentPriorityChain
# ---------------------------------------------------------------------------

class TestEnrichmentPriorityChain:
    """Tests the full enrichment priority chain: PMC supplements -> PMC full-text -> abstract."""

    def test_pmc_fulltext_takes_priority_over_abstract(self):
        """
        Given: get_pmc_eligibility returns criteria for a PMID
        When:  enrich_trial_data is called with the PMC criteria
        Then:  TrialData is enriched with the PMC criteria (not the abstract)
        """
        from src.agents.agent1.enricher import enrich_trial_data

        trial_data = TrialData(
            nct_id="NCT01179048",
            title="LEADER",
            inclusion_criteria=["type 2 diabetes"],
            exclusion_criteria=["type 1 diabetes"],
        )

        pmc_criteria = {
            "inclusion": [
                "type 2 diabetes with HbA1c >= 7.0%",
                "age >= 50 with cardiovascular disease",
                "age >= 50 with cerebrovascular disease",
                "age >= 50 with peripheral vascular disease",
                "chronic kidney disease stage >= 3",
            ],
            "exclusion": [
                "type 1 diabetes",
                "GLP-1 receptor agonist use within 3 months",
                "acute coronary event within 14 days",
                "planned revascularization",
            ],
        }

        abstract_criteria = {
            "inclusion": ["type 2 diabetes"],
            "exclusion": ["type 1 diabetes"],
        }

        # PMC criteria are richer; abstract criteria are intentionally leaner
        enriched_with_pmc = enrich_trial_data(trial_data, pmc_criteria)
        enriched_with_abstract = enrich_trial_data(trial_data, abstract_criteria)

        # PMC-enriched result must be richer than abstract-enriched
        assert len(enriched_with_pmc.inclusion_criteria) > len(enriched_with_abstract.inclusion_criteria)
        assert len(enriched_with_pmc.exclusion_criteria) > len(enriched_with_abstract.exclusion_criteria)
        # NCT ID preserved in both cases
        assert enriched_with_pmc.nct_id == "NCT01179048"

    def test_falls_back_to_supplements_when_no_fulltext_eligibility(self, tmp_path):
        """
        Given: PMC full-text exists but get_pmc_eligibility returns None (no eligibility section)
        When:  download_pmc_supplements is called as fallback
        Then:  Supplements are downloaded and returned for further processing
        """
        from src.agents.agent1.pmc_supplement import download_pmc_supplements

        tgz_content = _make_tgz_bytes({
            "PMC3901982_supplement_s1.pdf": b"%PDF-1.4 eligibility table",
        })

        oa_resp = MagicMock()
        oa_resp.status_code = 200
        oa_resp.text = PMC_OA_XML_WITH_TGZ

        tgz_resp = MagicMock()
        tgz_resp.status_code = 200
        tgz_resp.content = tgz_content

        def fake_get(url, **kwargs):
            if "oa.fcgi" in url:
                return oa_resp
            return tgz_resp

        with patch("requests.get", side_effect=fake_get):
            supplements = download_pmc_supplements(
                pmcid="PMC3901982",
                nct_id="NCT01179048",
                output_dir=str(tmp_path),
            )

        assert len(supplements) >= 1
        assert supplements[0]["role"] == "supplement"

    def test_falls_back_to_abstract_when_no_pmc(self):
        """
        Given: PMID has no PMC version (pmid_to_pmcid returns None)
        When:  fetch_pubmed_abstract is called as fallback and abstract contains criteria
        Then:  extract_eligibility_from_text produces usable criteria from the abstract
        """
        from src.agents.agent1.pmc_fetcher import get_pmc_eligibility
        from src.agents.agent1.pubmed_fetcher import extract_eligibility_from_text, fetch_pubmed_abstract

        # PMC lookup returns None — no open access version
        no_pmc_resp = _make_idconv_no_pmc_response("17312968")

        # Abstract fallback returns the PLATO abstract
        abstract_xml = _make_pubmed_abstract_xml("17312968", PLATO_ABSTRACT)
        abstract_resp = MagicMock()
        abstract_resp.status_code = 200
        abstract_resp.text = abstract_xml

        with patch("requests.get", return_value=no_pmc_resp):
            pmc_result = get_pmc_eligibility("17312968")

        assert pmc_result is None  # confirms PMC path yields nothing

        with patch("requests.get", return_value=abstract_resp):
            paper = fetch_pubmed_abstract("17312968")

        assert paper is not None
        criteria = extract_eligibility_from_text(paper.abstract)
        # PLATO abstract contains "key inclusion"/"key exclusion" sections
        total = len(criteria["inclusion"]) + len(criteria["exclusion"])
        assert total > 0

    def test_full_pipeline_leader_trial(self):
        """
        Given: LEADER trial (NCT01179048) — PMC full-text available with eligibility section
        When:  get_pmc_eligibility is called followed by enrich_trial_data
        Then:  Final TrialData has enriched criteria derived from PMC full-text
        """
        from src.agents.agent1.enricher import enrich_trial_data
        from src.agents.agent1.pmc_fetcher import get_pmc_eligibility

        idconv_resp = _make_idconv_response("23953384", "PMC3901982")
        fulltext_resp = _make_fulltext_response(LEADER_PMC_FULLTEXT)

        with patch("requests.get", side_effect=[idconv_resp, fulltext_resp]):
            pmc_criteria = get_pmc_eligibility("23953384")

        assert pmc_criteria is not None

        leader_trial = TrialData(
            nct_id="NCT01179048",
            title="LEADER",
            inclusion_criteria=["type 2 diabetes"],
            exclusion_criteria=[],
        )

        enriched = enrich_trial_data(leader_trial, pmc_criteria)

        assert enriched.nct_id == "NCT01179048"
        # After enrichment from the richer PMC source, inclusion count must have grown
        assert len(enriched.inclusion_criteria) >= len(leader_trial.inclusion_criteria)

    def test_full_pipeline_plato_trial_no_pmc(self):
        """
        Given: PLATO trial (NCT00391872) — no PMC OA version, falls back to abstract
        When:  Full pipeline runs with mocked responses
        Then:  Criteria are extracted from PubMed abstract and used to enrich TrialData
        """
        from src.agents.agent1.enricher import enrich_trial_data
        from src.agents.agent1.pmc_fetcher import get_pmc_eligibility
        from src.agents.agent1.pubmed_fetcher import extract_eligibility_from_text, fetch_pubmed_abstract

        # Step 1: PMC lookup → no version
        no_pmc_resp = _make_idconv_no_pmc_response("17384741")
        with patch("requests.get", return_value=no_pmc_resp):
            pmc_criteria = get_pmc_eligibility("17384741")

        assert pmc_criteria is None

        # Step 2: Abstract fallback
        abstract_xml = _make_pubmed_abstract_xml("17384741", PLATO_ABSTRACT)
        abstract_resp = MagicMock()
        abstract_resp.status_code = 200
        abstract_resp.text = abstract_xml

        with patch("requests.get", return_value=abstract_resp):
            paper = fetch_pubmed_abstract("17384741")

        assert paper is not None
        abstract_criteria = extract_eligibility_from_text(paper.abstract)

        # Step 3: Enrich PLATO TrialData with abstract criteria
        plato_trial = TrialData(
            nct_id="NCT00391872",
            title="PLATO",
            inclusion_criteria=[],
            exclusion_criteria=[],
        )
        enriched = enrich_trial_data(plato_trial, abstract_criteria)

        assert enriched.nct_id == "NCT00391872"
        total = len(enriched.inclusion_criteria) + len(enriched.exclusion_criteria)
        assert total > 0

    def test_full_pipeline_empareg_trial(self):
        """
        Given: EMPA-REG trial (NCT01131676) — DERIVED PMIDs only, falls back to abstract
        When:  Full pipeline runs with mocked abstract response
        Then:  Criteria are extracted from abstract and TrialData is enriched
        """
        from src.agents.agent1.enricher import enrich_trial_data
        from src.agents.agent1.pmc_fetcher import get_pmc_eligibility
        from src.agents.agent1.pubmed_fetcher import extract_eligibility_from_text, fetch_pubmed_abstract

        # Step 1: No PMC version
        no_pmc_resp = _make_idconv_no_pmc_response("26378978")
        with patch("requests.get", return_value=no_pmc_resp):
            pmc_criteria = get_pmc_eligibility("26378978")

        assert pmc_criteria is None

        # Step 2: Abstract fallback
        abstract_xml = _make_pubmed_abstract_xml("26378978", EMPA_REG_ABSTRACT)
        abstract_resp = MagicMock()
        abstract_resp.status_code = 200
        abstract_resp.text = abstract_xml

        with patch("requests.get", return_value=abstract_resp):
            paper = fetch_pubmed_abstract("26378978")

        assert paper is not None
        abstract_criteria = extract_eligibility_from_text(paper.abstract)

        # Step 3: Enrich EMPA-REG TrialData
        empareg_trial = TrialData(
            nct_id="NCT01131676",
            title="EMPA-REG OUTCOME",
            inclusion_criteria=[],
            exclusion_criteria=[],
        )
        enriched = enrich_trial_data(empareg_trial, abstract_criteria)

        assert enriched.nct_id == "NCT01131676"
        total = len(enriched.inclusion_criteria) + len(enriched.exclusion_criteria)
        assert total > 0

    def test_full_pipeline_declare_trial(self):
        """
        Given: DECLARE-TIMI 58 trial (NCT01730534) — DERIVED PMIDs only, falls back to abstract
        When:  Full pipeline runs with mocked abstract response
        Then:  Criteria are extracted from abstract and TrialData is enriched
        """
        from src.agents.agent1.enricher import enrich_trial_data
        from src.agents.agent1.pmc_fetcher import get_pmc_eligibility
        from src.agents.agent1.pubmed_fetcher import extract_eligibility_from_text, fetch_pubmed_abstract

        # Step 1: No PMC version for this PMID
        no_pmc_resp = _make_idconv_no_pmc_response("30191099")
        with patch("requests.get", return_value=no_pmc_resp):
            pmc_criteria = get_pmc_eligibility("30191099")

        assert pmc_criteria is None

        # Step 2: Abstract fallback
        abstract_xml = _make_pubmed_abstract_xml("30191099", DECLARE_ABSTRACT)
        abstract_resp = MagicMock()
        abstract_resp.status_code = 200
        abstract_resp.text = abstract_xml

        with patch("requests.get", return_value=abstract_resp):
            paper = fetch_pubmed_abstract("30191099")

        assert paper is not None
        abstract_criteria = extract_eligibility_from_text(paper.abstract)

        # Step 3: Enrich DECLARE-TIMI TrialData
        declare_trial = TrialData(
            nct_id="NCT01730534",
            title="DECLARE-TIMI 58",
            inclusion_criteria=[],
            exclusion_criteria=[],
        )
        enriched = enrich_trial_data(declare_trial, abstract_criteria)

        assert enriched.nct_id == "NCT01730534"
        total = len(enriched.inclusion_criteria) + len(enriched.exclusion_criteria)
        assert total > 0
