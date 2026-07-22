"""
Tests for artemis/src/agents/agent1/paper_url_mapper.py

Covers:
- extract_doi_from_pubmed_xml() with real PubMed XML snippets
- build_paper_urls() for each journal prefix
- _extract_doi_stem() various DOI formats
- _get_journal_info() known and unknown prefixes
- try_download_paper() with mock HTTP responses
- _generate_filename() various URL patterns
"""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import the module directly (bypasses src/agents/agent1/__init__.py which
# triggers settings validation errors in non-Docker environments).
# ---------------------------------------------------------------------------
_MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "agents" / "agent1" / "paper_url_mapper.py"
_MODULE_NAME = "artemis_paper_url_mapper"
_spec = importlib.util.spec_from_file_location(_MODULE_NAME, _MODULE_PATH)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_MODULE_NAME] = _mod
_spec.loader.exec_module(_mod)

extract_doi_from_pubmed_xml = _mod.extract_doi_from_pubmed_xml
_get_journal_info = _mod._get_journal_info
_extract_doi_stem = _mod._extract_doi_stem
build_paper_urls = _mod.build_paper_urls
_generate_filename = _mod._generate_filename
try_download_paper = _mod.try_download_paper
DownloadAttempt = _mod.DownloadAttempt

# Patch target uses the registered module name so unittest.mock can resolve it
_PATCH_TARGET = f"{_MODULE_NAME}.requests.get"


# ---------------------------------------------------------------------------
# extract_doi_from_pubmed_xml
# ---------------------------------------------------------------------------

class TestExtractDoiFromPubmedXml:
    """Tests for DOI extraction from PubMed XML."""

    def test_extracts_doi_from_article_id_tag(self):
        xml = """
        <PubmedArticle>
          <MedlineCitation>
            <Article>
              <ArticleTitle>A Randomized Trial</ArticleTitle>
            </Article>
          </MedlineCitation>
          <PubmedData>
            <ArticleIdList>
              <ArticleId IdType="pubmed">27295072</ArticleId>
              <ArticleId IdType="doi">10.1056/NEJMoa1603827</ArticleId>
            </ArticleIdList>
          </PubmedData>
        </PubmedArticle>
        """
        assert extract_doi_from_pubmed_xml(xml) == "10.1056/NEJMoa1603827"

    def test_extracts_doi_from_elocation_id_tag(self):
        xml = """
        <PubmedArticle>
          <MedlineCitation>
            <Article>
              <ELocationID EIdType="doi" ValidYN="Y">10.1016/S0140-6736(15)60733-3</ELocationID>
            </Article>
          </MedlineCitation>
        </PubmedArticle>
        """
        assert extract_doi_from_pubmed_xml(xml) == "10.1016/S0140-6736(15)60733-3"

    def test_article_id_takes_priority_over_elocation_id(self):
        xml = """
        <PubmedArticle>
          <MedlineCitation>
            <Article>
              <ELocationID EIdType="doi" ValidYN="Y">10.1001/jama.2015.1420</ELocationID>
            </Article>
          </MedlineCitation>
          <PubmedData>
            <ArticleIdList>
              <ArticleId IdType="doi">10.1001/jama.2015.9461</ArticleId>
            </ArticleIdList>
          </PubmedData>
        </PubmedArticle>
        """
        # ArticleId pattern is searched first, so it wins
        assert extract_doi_from_pubmed_xml(xml) == "10.1001/jama.2015.9461"

    def test_strips_whitespace_from_doi(self):
        xml = '<ArticleId IdType="doi">  10.1136/bmj.h2458  </ArticleId>'
        assert extract_doi_from_pubmed_xml(xml) == "10.1136/bmj.h2458"

    def test_returns_none_when_no_doi_present(self):
        xml = """
        <PubmedArticle>
          <PubmedData>
            <ArticleIdList>
              <ArticleId IdType="pubmed">12345678</ArticleId>
              <ArticleId IdType="pmc">PMC123456</ArticleId>
            </ArticleIdList>
          </PubmedData>
        </PubmedArticle>
        """
        assert extract_doi_from_pubmed_xml(xml) is None

    def test_returns_none_for_empty_xml(self):
        assert extract_doi_from_pubmed_xml("") is None

    def test_handles_jama_doi(self):
        xml = '<ArticleId IdType="doi">10.1001/jama.2019.11350</ArticleId>'
        assert extract_doi_from_pubmed_xml(xml) == "10.1001/jama.2019.11350"

    def test_handles_annals_doi(self):
        xml = '<ArticleId IdType="doi">10.7326/M18-3137</ArticleId>'
        assert extract_doi_from_pubmed_xml(xml) == "10.7326/M18-3137"


# ---------------------------------------------------------------------------
# _get_journal_info
# ---------------------------------------------------------------------------

class TestGetJournalInfo:
    """Tests for journal info lookup by DOI prefix."""

    def test_returns_nejm_info_for_10_1056(self):
        info = _get_journal_info("10.1056/NEJMoa1603827")
        assert info["name"] == "NEJM"
        assert info["main_url"] is not None
        assert info["supp_url"] is not None

    def test_returns_lancet_info_for_10_1016(self):
        info = _get_journal_info("10.1016/S0140-6736(15)60733-3")
        assert info["name"] == "Lancet/Elsevier"
        assert info["main_url"] is None  # Complex URL, uses DOI resolver
        assert info["supp_url"] is None

    def test_returns_jama_info_for_10_1001(self):
        info = _get_journal_info("10.1001/jama.2019.11350")
        assert info["name"] == "JAMA"
        assert info["hint"] == "Supplement tab on article page"

    def test_returns_bmj_info_for_10_1136(self):
        info = _get_journal_info("10.1136/bmj.h2458")
        assert info["name"] == "BMJ"
        assert info["hint"] == "Supplementary materials section"

    def test_returns_annals_info_for_10_7326(self):
        info = _get_journal_info("10.7326/M18-3137")
        assert info["name"] == "Annals of Internal Medicine"
        assert info["hint"] == "Supplements section on article page"

    def test_returns_default_for_unknown_prefix(self):
        info = _get_journal_info("10.9999/unknown.article")
        assert info["name"] is None
        assert info["main_url"] is None
        assert info["supp_url"] is None
        assert "supplementary materials" in info["hint"].lower()

    def test_handles_doi_without_slash(self):
        info = _get_journal_info("10.1056")
        assert info["name"] == "NEJM"


# ---------------------------------------------------------------------------
# _extract_doi_stem
# ---------------------------------------------------------------------------

class TestExtractDoiStem:
    """Tests for DOI stem extraction."""

    def test_extracts_stem_from_nejm_doi(self):
        assert _extract_doi_stem("10.1056/NEJMoa1603827") == "nejmoa1603827"

    def test_extracts_stem_from_jama_doi(self):
        assert _extract_doi_stem("10.1001/jama.2019.11350") == "jama.2019.11350"

    def test_extracts_stem_from_lancet_doi(self):
        assert _extract_doi_stem("10.1016/S0140-6736(15)60733-3") == "s0140-6736(15)60733-3"

    def test_extracts_stem_from_bmj_doi(self):
        assert _extract_doi_stem("10.1136/bmj.h2458") == "bmj.h2458"

    def test_result_is_lowercase(self):
        result = _extract_doi_stem("10.1056/NEJMoa9999999")
        assert result == result.lower()

    def test_handles_doi_without_slash(self):
        assert _extract_doi_stem("10.1056") == "10.1056"


# ---------------------------------------------------------------------------
# build_paper_urls
# ---------------------------------------------------------------------------

class TestBuildPaperUrls:
    """Tests for URL construction from DOI."""

    def test_nejm_returns_two_urls(self):
        urls = build_paper_urls("10.1056/NEJMoa1603827")
        assert len(urls) == 2

    def test_nejm_main_url_is_pdf_link(self):
        urls = build_paper_urls("10.1056/NEJMoa1603827")
        main = next(u for u in urls if u["role"] == "main")
        assert "www.nejm.org/doi/pdf/" in main["url"]
        assert "NEJMoa1603827" in main["url"]
        assert main["hint"] is None

    def test_nejm_supplement_url_contains_stem(self):
        urls = build_paper_urls("10.1056/NEJMoa1603827")
        supp = next(u for u in urls if u["role"] == "supplement")
        assert "nejmoa1603827" in supp["url"]
        assert "_appendix.pdf" in supp["url"]

    def test_lancet_falls_back_to_doi_resolver(self):
        doi = "10.1016/S0140-6736(15)60733-3"
        urls = build_paper_urls(doi)
        assert len(urls) == 1
        assert urls[0]["role"] == "main"
        assert urls[0]["url"] == f"https://doi.org/{doi}"

    def test_lancet_no_supplement_without_supp_url(self):
        urls = build_paper_urls("10.1016/S0140-6736(15)60733-3")
        supp = [u for u in urls if u["role"] == "supplement"]
        assert len(supp) == 0

    def test_jama_falls_back_to_doi_resolver(self):
        doi = "10.1001/jama.2019.11350"
        for u in build_paper_urls(doi):
            assert u["url"] == f"https://doi.org/{doi}"

    def test_bmj_falls_back_to_doi_resolver(self):
        doi = "10.1136/bmj.h2458"
        for u in build_paper_urls(doi):
            assert u["url"] == f"https://doi.org/{doi}"

    def test_annals_falls_back_to_doi_resolver(self):
        doi = "10.7326/M18-3137"
        for u in build_paper_urls(doi):
            assert u["url"] == f"https://doi.org/{doi}"

    def test_unknown_journal_uses_doi_resolver(self):
        doi = "10.9999/unknown.article"
        urls = build_paper_urls(doi)
        assert len(urls) == 1
        assert urls[0]["role"] == "main"
        assert urls[0]["url"] == f"https://doi.org/{doi}"

    def test_all_urls_have_required_keys(self):
        for u in build_paper_urls("10.1056/NEJMoa1603827"):
            for key in ("journal", "doi", "url", "role", "hint"):
                assert key in u

    def test_doi_preserved_in_result(self):
        doi = "10.1056/NEJMoa1603827"
        for u in build_paper_urls(doi):
            assert u["doi"] == doi

    def test_roles_are_main_and_supplement(self):
        urls = build_paper_urls("10.1056/NEJMoa1603827")
        assert {u["role"] for u in urls} == {"main", "supplement"}


# ---------------------------------------------------------------------------
# _generate_filename
# ---------------------------------------------------------------------------

class TestGenerateFilename:
    """Tests for filename generation from URL."""

    def test_returns_pdf_filename_from_direct_link(self):
        url = "https://www.nejm.org/doi/suppl/10.1056/NEJMoa1603827/suppl_file/nejmoa1603827_appendix.pdf"
        assert _generate_filename(url, "supplement") == "nejmoa1603827_appendix.pdf"

    def test_appends_role_when_no_pdf_extension(self):
        url = "https://doi.org/10.1056/NEJMoa1603827"
        result = _generate_filename(url, "main")
        assert result.endswith(".pdf")

    def test_supplement_role_in_fallback_name(self):
        url = "https://doi.org/10.1056/NEJMoa1603827"
        result = _generate_filename(url, "supplement")
        assert "supplement" in result
        assert result.endswith(".pdf")

    def test_fallback_for_root_url(self):
        url = "https://example.com/"
        assert _generate_filename(url, "main") == "paper_main.pdf"

    def test_result_always_ends_with_pdf(self):
        for url in [
            "https://example.com/paper.pdf",
            "https://doi.org/10.1056/NEJMoa1603827",
            "https://example.com/",
            "https://example.com/article?id=123",
        ]:
            assert _generate_filename(url, "main").endswith(".pdf")


# ---------------------------------------------------------------------------
# try_download_paper
# ---------------------------------------------------------------------------

class TestTryDownloadPaper:
    """Tests for paper download with mocked HTTP."""

    def test_successful_pdf_download_by_content_type(self, tmp_path):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/pdf"}
        mock_resp.content = b"%PDF-1.4 fake pdf content"
        mock_resp.raise_for_status = MagicMock()

        with patch(_PATCH_TARGET, return_value=mock_resp):
            result = try_download_paper(
                url="https://www.nejm.org/doi/pdf/10.1056/NEJMoa1603827",
                save_dir=tmp_path,
                role="main",
            )

        assert result.status == "downloaded"
        assert result.saved_path is not None
        assert Path(result.saved_path).exists()

    def test_successful_pdf_download_by_magic_bytes(self, tmp_path):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/octet-stream"}
        mock_resp.content = b"%PDF-1.4 fake pdf content"
        mock_resp.raise_for_status = MagicMock()

        with patch(_PATCH_TARGET, return_value=mock_resp):
            result = try_download_paper(
                url="https://example.com/paper.pdf",
                save_dir=tmp_path,
                role="supplement",
            )

        assert result.status == "downloaded"

    def test_returns_paywalled_for_403(self, tmp_path):
        mock_resp = MagicMock()
        mock_resp.status_code = 403

        with patch(_PATCH_TARGET, return_value=mock_resp):
            result = try_download_paper(
                url="https://www.nejm.org/doi/pdf/10.1056/NEJMoa1603827",
                save_dir=tmp_path,
                role="main",
            )

        assert result.status == "paywalled"
        assert result.saved_path is None

    def test_returns_paywalled_for_401(self, tmp_path):
        mock_resp = MagicMock()
        mock_resp.status_code = 401

        with patch(_PATCH_TARGET, return_value=mock_resp):
            result = try_download_paper(
                url="https://example.com/paper",
                save_dir=tmp_path,
                role="main",
            )

        assert result.status == "paywalled"

    def test_returns_unavailable_for_404(self, tmp_path):
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch(_PATCH_TARGET, return_value=mock_resp):
            result = try_download_paper(
                url="https://example.com/missing.pdf",
                save_dir=tmp_path,
                role="supplement",
            )

        assert result.status == "unavailable"
        assert result.saved_path is None

    def test_returns_unavailable_for_html_response(self, tmp_path):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "text/html; charset=utf-8"}
        mock_resp.content = b"<html>Not a PDF</html>"
        mock_resp.raise_for_status = MagicMock()

        with patch(_PATCH_TARGET, return_value=mock_resp):
            result = try_download_paper(
                url="https://www.nejm.org/doi/10.1056/NEJMoa1603827",
                save_dir=tmp_path,
                role="main",
            )

        assert result.status == "unavailable"

    def test_returns_error_on_connection_error(self, tmp_path):
        import requests as req

        with patch(_PATCH_TARGET, side_effect=req.ConnectionError("Network unreachable")):
            result = try_download_paper(
                url="https://example.com/paper.pdf",
                save_dir=tmp_path,
                role="main",
            )

        assert result.status == "error"
        assert result.saved_path is None

    def test_returns_error_on_timeout(self, tmp_path):
        import requests as req

        with patch(_PATCH_TARGET, side_effect=req.Timeout("Timed out")):
            result = try_download_paper(
                url="https://example.com/paper.pdf",
                save_dir=tmp_path,
                role="supplement",
            )

        assert result.status == "error"

    def test_creates_save_directory_if_missing(self, tmp_path):
        save_dir = tmp_path / "NCT12345678" / "papers"
        assert not save_dir.exists()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/pdf"}
        mock_resp.content = b"%PDF-1.4 fake content"
        mock_resp.raise_for_status = MagicMock()

        with patch(_PATCH_TARGET, return_value=mock_resp):
            result = try_download_paper(
                url="https://example.com/paper.pdf",
                save_dir=save_dir,
                role="main",
            )

        assert save_dir.exists()
        assert result.status == "downloaded"

    def test_result_contains_url_and_role(self, tmp_path):
        import requests as req

        url = "https://example.com/paper.pdf"
        with patch(_PATCH_TARGET, side_effect=req.ConnectionError("err")):
            result = try_download_paper(url=url, save_dir=tmp_path, role="main")

        assert result.url == url
        assert result.role == "main"

    def test_download_attempt_dataclass_defaults(self):
        attempt = DownloadAttempt(url="https://example.com", role="main", status="paywalled")
        assert attempt.saved_path is None
