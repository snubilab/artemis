"""
Test: PMC Supplementary Materials Downloader.
Tests downloading supplement PDFs from PMC OA service.
"""
import io
import tarfile
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tgz_bytes(members: dict[str, bytes]) -> bytes:
    """Build an in-memory .tar.gz with the given {name: content} mapping."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    buf.seek(0)
    return buf.read()


PMC_OA_XML_WITH_TGZ = """<?xml version="1.0" encoding="UTF-8"?>
<OA>
  <records returned-count="1">
    <record id="PMC1234567" citation="Author et al.">
      <link format="tgz" href="https://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_package/ab/cd/PMC1234567.tar.gz" />
      <link format="pdf" href="https://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_pdf/ab/cd/PMC1234567.pdf" />
    </record>
  </records>
</OA>
"""

PMC_OA_XML_PDF_ONLY = """<?xml version="1.0" encoding="UTF-8"?>
<OA>
  <records returned-count="1">
    <record id="PMC9999999" citation="Foo et al.">
      <link format="pdf" href="https://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_pdf/xx/yy/PMC9999999.pdf" />
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


# ---------------------------------------------------------------------------
# fetch_pmc_file_list
# ---------------------------------------------------------------------------

class TestFetchPmcFileList:
    """Tests for fetch_pmc_file_list()."""

    def test_returns_tgz_and_pdf_entries(self):
        """
        Given: PMC OA API returns XML with both tgz and pdf links
        When:  fetch_pmc_file_list is called
        Then:  Returns list with both file entries including url and format
        """
        from src.agents.agent1.pmc_supplement import fetch_pmc_file_list

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = PMC_OA_XML_WITH_TGZ

        with patch("requests.get", return_value=mock_resp) as mock_get:
            files = fetch_pmc_file_list("PMC1234567")

        assert len(files) == 2
        urls = [f["url"] for f in files]
        assert any("tar.gz" in u for u in urls)
        assert any(".pdf" in u for u in urls)
        formats = {f["format"] for f in files}
        assert "tgz" in formats
        assert "pdf" in formats

    def test_returns_pdf_only_when_no_tgz(self):
        """
        Given: PMC OA API returns XML with only a pdf link
        When:  fetch_pmc_file_list is called
        Then:  Returns single-entry list with pdf format
        """
        from src.agents.agent1.pmc_supplement import fetch_pmc_file_list

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = PMC_OA_XML_PDF_ONLY

        with patch("requests.get", return_value=mock_resp):
            files = fetch_pmc_file_list("PMC9999999")

        assert len(files) == 1
        assert files[0]["format"] == "pdf"

    def test_returns_empty_list_when_no_records(self):
        """
        Given: PMC OA API returns XML with no records (article not in OA)
        When:  fetch_pmc_file_list is called
        Then:  Returns empty list
        """
        from src.agents.agent1.pmc_supplement import fetch_pmc_file_list

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = PMC_OA_XML_EMPTY

        with patch("requests.get", return_value=mock_resp):
            files = fetch_pmc_file_list("PMC0000000")

        assert files == []

    def test_returns_empty_list_on_http_error(self):
        """
        Given: PMC OA API returns HTTP error
        When:  fetch_pmc_file_list is called
        Then:  Returns empty list (graceful failure)
        """
        from src.agents.agent1.pmc_supplement import fetch_pmc_file_list

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("500 Server Error")

        with patch("requests.get", return_value=mock_resp):
            files = fetch_pmc_file_list("PMC1234567")

        assert files == []

    def test_returns_empty_list_on_network_exception(self):
        """
        Given: Network is unreachable
        When:  fetch_pmc_file_list is called
        Then:  Returns empty list
        """
        from src.agents.agent1.pmc_supplement import fetch_pmc_file_list

        with patch("requests.get", side_effect=ConnectionError("unreachable")):
            files = fetch_pmc_file_list("PMC1234567")

        assert files == []

    def test_calls_correct_oa_api_url(self):
        """
        Given: A PMCID
        When:  fetch_pmc_file_list is called
        Then:  Calls PMC OA endpoint with the correct id parameter
        """
        from src.agents.agent1.pmc_supplement import fetch_pmc_file_list, PMC_OA_URL

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = PMC_OA_XML_EMPTY

        with patch("requests.get", return_value=mock_resp) as mock_get:
            fetch_pmc_file_list("PMC1234567")

        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args
        assert PMC_OA_URL in str(call_kwargs)
        assert "PMC1234567" in str(call_kwargs)


# ---------------------------------------------------------------------------
# classify_supplement
# ---------------------------------------------------------------------------

class TestClassifySupplement:
    """Tests for classify_supplement()."""

    @pytest.mark.parametrize("filename,expected", [
        ("supplement_s1.pdf", "supplement"),
        ("Supplementary_Table_1.pdf", "supplement"),
        ("supp_material.pdf", "supplement"),
        ("appendix_A.pdf", "appendix"),
        ("Appendix.pdf", "appendix"),
        ("table_s1.pdf", "supplement"),
        ("figure_s2.pdf", "supplement"),
        ("PMC1234567.pdf", "main"),
        ("main_article.pdf", "main"),
        ("random_file.pdf", "main"),
        ("SUPPLEMENT.PDF", "supplement"),
        ("APPENDIX_B.PDF", "appendix"),
    ])
    def test_classify_by_filename(self, filename: str, expected: str):
        """
        Given: Various filenames
        When:  classify_supplement is called
        Then:  Returns the correct role string
        """
        from src.agents.agent1.pmc_supplement import classify_supplement

        result = classify_supplement(filename)
        assert result == expected, f"Expected '{expected}' for '{filename}', got '{result}'"

    def test_classify_empty_string(self):
        """
        Given: Empty filename
        When:  classify_supplement is called
        Then:  Returns 'other'
        """
        from src.agents.agent1.pmc_supplement import classify_supplement

        assert classify_supplement("") == "other"


# ---------------------------------------------------------------------------
# download_pmc_supplements
# ---------------------------------------------------------------------------

class TestDownloadPmcSupplements:
    """Tests for download_pmc_supplements()."""

    def test_downloads_supplement_pdfs_from_tgz(self, tmp_path):
        """
        Given: PMC OA returns a tgz containing supplement and main PDFs
        When:  download_pmc_supplements is called
        Then:  Downloads and extracts supplement PDFs, returns correct metadata
        """
        from src.agents.agent1.pmc_supplement import download_pmc_supplements

        tgz_content = _make_tgz_bytes({
            "PMC1234567.pdf": b"%PDF-1.4 main article content",
            "PMC1234567_supplement_s1.pdf": b"%PDF-1.4 supplement content",
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
                pmcid="PMC1234567",
                nct_id="NCT01234567",
                output_dir=str(tmp_path),
            )

        # Should find the supplement PDF
        supplement_results = [r for r in results if r["role"] == "supplement"]
        assert len(supplement_results) >= 1
        assert all(Path(r["path"]).exists() for r in results)
        assert all("name" in r for r in results)

    def test_returns_main_pdf_when_no_supplements_in_tgz(self, tmp_path):
        """
        Given: PMC OA returns a tgz with only a main PDF (no supplements)
        When:  download_pmc_supplements is called
        Then:  Returns the main PDF with role='main'
        """
        from src.agents.agent1.pmc_supplement import download_pmc_supplements

        tgz_content = _make_tgz_bytes({
            "PMC1234567.pdf": b"%PDF-1.4 main article content",
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
                pmcid="PMC1234567",
                nct_id="NCT01234567",
                output_dir=str(tmp_path),
            )

        assert len(results) == 1
        assert results[0]["role"] == "main"

    def test_falls_back_to_direct_pdf_when_no_tgz(self, tmp_path):
        """
        Given: PMC OA API returns only a direct PDF link (no tgz)
        When:  download_pmc_supplements is called
        Then:  Downloads the PDF directly and returns it with role='main'
        """
        from src.agents.agent1.pmc_supplement import download_pmc_supplements

        oa_resp = MagicMock()
        oa_resp.status_code = 200
        oa_resp.text = PMC_OA_XML_PDF_ONLY

        pdf_resp = MagicMock()
        pdf_resp.status_code = 200
        pdf_resp.content = b"%PDF-1.4 main article content"

        def fake_get(url, **kwargs):
            if "oa.fcgi" in url:
                return oa_resp
            return pdf_resp

        with patch("requests.get", side_effect=fake_get):
            results = download_pmc_supplements(
                pmcid="PMC9999999",
                nct_id="NCT09999999",
                output_dir=str(tmp_path),
            )

        assert len(results) == 1
        assert results[0]["role"] == "main"
        assert Path(results[0]["path"]).exists()

    def test_returns_empty_list_when_article_not_in_oa(self, tmp_path):
        """
        Given: PMC OA API returns no records (article not in OA)
        When:  download_pmc_supplements is called
        Then:  Returns empty list with a warning (no crash)
        """
        from src.agents.agent1.pmc_supplement import download_pmc_supplements

        oa_resp = MagicMock()
        oa_resp.status_code = 200
        oa_resp.text = PMC_OA_XML_EMPTY

        with patch("requests.get", return_value=oa_resp):
            results = download_pmc_supplements(
                pmcid="PMC0000000",
                nct_id="NCT00000000",
                output_dir=str(tmp_path),
            )

        assert results == []

    def test_creates_output_directory_if_missing(self, tmp_path):
        """
        Given: output_dir does not yet exist
        When:  download_pmc_supplements is called
        Then:  Creates the directory and saves files into it
        """
        from src.agents.agent1.pmc_supplement import download_pmc_supplements

        tgz_content = _make_tgz_bytes({
            "PMC1234567_supp.pdf": b"%PDF-1.4 supplement",
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

        new_dir = tmp_path / "NCT01234567"
        assert not new_dir.exists()

        with patch("requests.get", side_effect=fake_get):
            results = download_pmc_supplements(
                pmcid="PMC1234567",
                nct_id="NCT01234567",
                output_dir=str(new_dir),
            )

        assert new_dir.exists()
        assert len(results) >= 1

    def test_result_format_matches_discover_pdfs(self, tmp_path):
        """
        Given: Successful download of a supplement
        When:  download_pmc_supplements is called
        Then:  Each result dict has exactly 'path', 'role', and 'name' keys
               matching the format expected by parser.py _discover_pdfs()
        """
        from src.agents.agent1.pmc_supplement import download_pmc_supplements

        tgz_content = _make_tgz_bytes({
            "supp_table_s1.pdf": b"%PDF-1.4 supplement table",
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
                pmcid="PMC1234567",
                nct_id="NCT01234567",
                output_dir=str(tmp_path),
            )

        assert len(results) >= 1
        for r in results:
            assert set(r.keys()) >= {"path", "role", "name"}
            assert r["role"] in ("main", "supplement", "appendix", "other")
            assert Path(r["path"]).is_absolute()

    def test_returns_empty_list_on_download_failure(self, tmp_path):
        """
        Given: tgz download raises a network error
        When:  download_pmc_supplements is called
        Then:  Returns empty list (graceful failure, no crash)
        """
        from src.agents.agent1.pmc_supplement import download_pmc_supplements

        oa_resp = MagicMock()
        oa_resp.status_code = 200
        oa_resp.text = PMC_OA_XML_WITH_TGZ

        def fake_get(url, **kwargs):
            if "oa.fcgi" in url:
                return oa_resp
            raise ConnectionError("network failure")

        with patch("requests.get", side_effect=fake_get):
            results = download_pmc_supplements(
                pmcid="PMC1234567",
                nct_id="NCT01234567",
                output_dir=str(tmp_path),
            )

        assert results == []

    def test_uses_default_output_dir_when_none_given(self, tmp_path):
        """
        Given: output_dir is None
        When:  download_pmc_supplements is called
        Then:  Uses the default data/papers/{nct_id}/ path
        """
        from src.agents.agent1 import pmc_supplement as mod

        tgz_content = _make_tgz_bytes({
            "PMC1234567_supplement.pdf": b"%PDF-1.4 supp",
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

        default_base = tmp_path / "papers"
        with patch.object(mod, "DEFAULT_PAPERS_DIR", default_base):
            with patch("requests.get", side_effect=fake_get):
                results = mod.download_pmc_supplements(
                    pmcid="PMC1234567",
                    nct_id="NCT01234567",
                )

        assert len(results) >= 1
        # All paths should be under the (patched) default papers dir
        for r in results:
            assert str(default_base) in r["path"]
