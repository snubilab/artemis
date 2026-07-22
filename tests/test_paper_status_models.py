"""Unit tests for PaperStatus Pydantic models (SPEC-UI-011 T1)."""

import pytest

from src.api.models.tte import (
    DownloadResult,
    DownloadUrl,
    PaperDownloadInfo,
    PaperStatus,
)


# ---------------------------------------------------------------------------
# DownloadResult
# ---------------------------------------------------------------------------


class TestDownloadResult:
    def test_instantiation_with_required_fields(self):
        # Arrange / Act
        result = DownloadResult(url="https://example.com/paper.pdf", role="main", status="downloaded")

        # Assert
        assert result.url == "https://example.com/paper.pdf"
        assert result.role == "main"
        assert result.status == "downloaded"
        assert result.saved_path is None

    def test_instantiation_with_saved_path(self):
        result = DownloadResult(
            url="https://example.com/paper.pdf",
            role="supplement",
            status="downloaded",
            saved_path="/tmp/papers/paper.pdf",
        )
        assert result.saved_path == "/tmp/papers/paper.pdf"

    @pytest.mark.parametrize("status", ["downloaded", "paywalled", "unavailable", "error"])
    def test_all_status_values(self, status: str):
        result = DownloadResult(url="https://x.com", role="main", status=status)
        assert result.status == status

    @pytest.mark.parametrize("role", ["main", "supplement"])
    def test_all_role_values(self, role: str):
        result = DownloadResult(url="https://x.com", role=role, status="downloaded")
        assert result.role == role

    def test_serialization_round_trip(self):
        original = DownloadResult(
            url="https://example.com/paper.pdf",
            role="main",
            status="downloaded",
            saved_path="/tmp/paper.pdf",
        )
        data = original.model_dump()
        restored = DownloadResult.model_validate(data)
        assert restored == original

    def test_serialization_none_saved_path_omitted_behavior(self):
        result = DownloadResult(url="https://x.com", role="main", status="error")
        data = result.model_dump()
        assert "saved_path" in data
        assert data["saved_path"] is None


# ---------------------------------------------------------------------------
# DownloadUrl
# ---------------------------------------------------------------------------


class TestDownloadUrl:
    def test_instantiation_with_required_field_only(self):
        url = DownloadUrl(article_url="https://doi.org/10.1056/NEJMoa1107039")

        assert url.article_url == "https://doi.org/10.1056/NEJMoa1107039"
        assert url.journal is None
        assert url.doi is None
        assert url.supplement_hint is None
        assert url.role == "supplement"  # default

    def test_instantiation_with_all_fields(self):
        url = DownloadUrl(
            journal="NEJM",
            doi="10.1056/NEJMoa1107039",
            article_url="https://doi.org/10.1056/NEJMoa1107039",
            supplement_hint="Click 'Supplementary Appendix'",
            role="main",
        )
        assert url.journal == "NEJM"
        assert url.doi == "10.1056/NEJMoa1107039"
        assert url.supplement_hint == "Click 'Supplementary Appendix'"
        assert url.role == "main"

    def test_default_role_is_supplement(self):
        url = DownloadUrl(article_url="https://example.com")
        assert url.role == "supplement"

    @pytest.mark.parametrize("journal", ["NEJM", "Lancet", "JAMA", "BMJ", None])
    def test_journal_nullable(self, journal):
        url = DownloadUrl(journal=journal, article_url="https://example.com")
        assert url.journal == journal

    def test_serialization_round_trip(self):
        original = DownloadUrl(
            journal="JAMA",
            doi="10.1001/jama.2021.0001",
            article_url="https://doi.org/10.1001/jama.2021.0001",
        )
        restored = DownloadUrl.model_validate(original.model_dump())
        assert restored == original

    def test_json_round_trip(self):
        original = DownloadUrl(article_url="https://example.com", journal="Lancet")
        json_str = original.model_dump_json()
        restored = DownloadUrl.model_validate_json(json_str)
        assert restored == original


# ---------------------------------------------------------------------------
# PaperDownloadInfo
# ---------------------------------------------------------------------------


class TestPaperDownloadInfo:
    def test_instantiation(self):
        info = PaperDownloadInfo(name="supplement.pdf", role="supplement", source="pmc")

        assert info.name == "supplement.pdf"
        assert info.role == "supplement"
        assert info.source == "pmc"

    @pytest.mark.parametrize("role", ["supplement", "appendix", "main", "protocol"])
    def test_all_roles(self, role: str):
        info = PaperDownloadInfo(name="file.pdf", role=role, source="local")
        assert info.role == role

    @pytest.mark.parametrize("source", ["local", "pmc", "journal_download"])
    def test_all_sources(self, source: str):
        info = PaperDownloadInfo(name="file.pdf", role="main", source=source)
        assert info.source == source

    def test_serialization_round_trip(self):
        original = PaperDownloadInfo(name="protocol.pdf", role="protocol", source="local")
        restored = PaperDownloadInfo.model_validate(original.model_dump())
        assert restored == original


# ---------------------------------------------------------------------------
# PaperStatus
# ---------------------------------------------------------------------------


class TestPaperStatus:
    def test_default_instantiation(self):
        status = PaperStatus()

        assert status.source == "nct_only"
        assert status.papers_found == []
        assert status.supplement_available is False
        assert status.manual_download_needed is True
        assert status.download_urls == []
        assert status.download_results == []

    @pytest.mark.parametrize(
        "source",
        ["local", "pmc_supplement", "pmc_fulltext", "journal_download", "pubmed_abstract", "nct_only"],
    )
    def test_all_source_types(self, source: str):
        status = PaperStatus(source=source)
        assert status.source == source

    def test_with_papers_found(self):
        paper = PaperDownloadInfo(name="appendix.pdf", role="appendix", source="pmc")
        status = PaperStatus(source="pmc_supplement", papers_found=[paper], supplement_available=True)

        assert len(status.papers_found) == 1
        assert status.papers_found[0].name == "appendix.pdf"
        assert status.supplement_available is True

    def test_with_download_urls(self):
        url = DownloadUrl(journal="NEJM", article_url="https://example.com")
        status = PaperStatus(manual_download_needed=True, download_urls=[url])

        assert len(status.download_urls) == 1
        assert status.download_urls[0].journal == "NEJM"

    def test_with_download_results(self):
        result = DownloadResult(url="https://example.com/s.pdf", role="supplement", status="downloaded")
        status = PaperStatus(source="journal_download", download_results=[result])

        assert len(status.download_results) == 1
        assert status.download_results[0].status == "downloaded"

    def test_fully_populated_round_trip(self):
        original = PaperStatus(
            source="pmc_fulltext",
            papers_found=[PaperDownloadInfo(name="main.pdf", role="main", source="pmc")],
            supplement_available=True,
            manual_download_needed=False,
            download_urls=[DownloadUrl(article_url="https://example.com", doi="10.1/x")],
            download_results=[
                DownloadResult(url="https://example.com/s.pdf", role="supplement", status="paywalled")
            ],
        )
        restored = PaperStatus.model_validate(original.model_dump())
        assert restored == original

    def test_json_round_trip(self):
        original = PaperStatus(source="local", supplement_available=True, manual_download_needed=False)
        restored = PaperStatus.model_validate_json(original.model_dump_json())
        assert restored == original

    def test_empty_lists_serialization(self):
        status = PaperStatus()
        data = status.model_dump()

        assert data["papers_found"] == []
        assert data["download_urls"] == []
        assert data["download_results"] == []

    def test_none_fields_in_nested_models(self):
        url = DownloadUrl(article_url="https://example.com")
        status = PaperStatus(download_urls=[url])
        data = status.model_dump()

        assert data["download_urls"][0]["journal"] is None
        assert data["download_urls"][0]["doi"] is None
        assert data["download_urls"][0]["supplement_hint"] is None
