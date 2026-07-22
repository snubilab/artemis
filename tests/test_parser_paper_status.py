"""
Tests for paper status collection in Agent1 parser (SPEC-UI-011 Task T2).

Verifies that parse_nct() populates self.last_paper_status correctly
depending on which enrichment path succeeds.
"""
from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest


# ---------------------------------------------------------------------------
# Module-level setup: stub heavy dependencies before importing parser
# ---------------------------------------------------------------------------


_INJECTED_STUBS: list[str] = []  # track which modules we injected for cleanup


def _install_module_stubs():
    """Install lightweight stub modules so parser.py imports without env setup."""
    stubs: dict = {
        "langchain_core": MagicMock(),
        "langchain_core.messages": MagicMock(),
        "langchain_core.output_parsers": MagicMock(),
        "src.utils.llm": MagicMock(),
        "src.models.ir": MagicMock(),
        "src.agents.agent1.prompts": MagicMock(
            SYSTEM_PROMPT="sys",
            DECOMPOSITION_PROMPT="{query}",
            NCT_SYSTEM_PROMPT="nct_sys",
            NCT_DECOMPOSITION_PROMPT=(
                "{title}{conditions}{interventions}{outcomes}{inclusion}{exclusion}"
            ),
        ),
        "src.agents.agent1.nct_fetcher": MagicMock(),
        "src.agents.agent1.pubmed_linker": MagicMock(),
        "src.agents.agent1.pubmed_fetcher": MagicMock(),
        "src.agents.agent1.enricher": MagicMock(),
        "src.agents.agent1.pmc_fetcher": MagicMock(),
        "src.agents.agent1.pmc_supplement": MagicMock(),
    }
    for name, stub in stubs.items():
        if name not in sys.modules:
            sys.modules[name] = stub
            _INJECTED_STUBS.append(name)

    ir_stub = sys.modules["src.models.ir"]
    for cls_name in [
        "ARTEMISRequest", "CohortDefinition", "PrimaryCriteria",
        "Criteria", "CohortOutcome", "TemporalWindow", "ValueConstraint",
    ]:
        setattr(ir_stub, cls_name, MagicMock())

    sys.modules["src.utils.llm"].get_llm = MagicMock(return_value=MagicMock())

    nct = sys.modules["src.agents.agent1.nct_fetcher"]
    nct.fetch_or_load_trial_data = MagicMock()
    nct.load_trial_data_from_file = MagicMock()
    nct.fetch_trial_data = MagicMock()
    nct.TrialData = MagicMock()
    nct.DEFAULT_CACHE_DIR = Path("/nonexistent_cache_dir_for_tests")

    pl = sys.modules["src.agents.agent1.pubmed_linker"]
    pl.extract_pmids_from_nct = MagicMock(return_value=[])
    pl.get_design_paper_pmids = MagicMock(return_value=[])
    pl.search_pubmed_for_nct = MagicMock(return_value=[])

    pf = sys.modules["src.agents.agent1.pubmed_fetcher"]
    pf.fetch_pubmed_abstract = MagicMock(return_value=None)
    pf.extract_eligibility_from_text = MagicMock(return_value={"inclusion": [], "exclusion": []})

    sys.modules["src.agents.agent1.enricher"].enrich_trial_data = MagicMock(
        side_effect=lambda td, *a, **kw: td
    )

    pmc = sys.modules["src.agents.agent1.pmc_fetcher"]
    pmc.get_pmc_eligibility = MagicMock(return_value=None)
    pmc.pmid_to_pmcid = MagicMock(return_value=None)

    sys.modules["src.agents.agent1.pmc_supplement"].download_pmc_supplements = MagicMock(
        return_value=[]
    )


_install_module_stubs()

# Safe to import now
from src.agents.agent1.parser import LogicDecomposer  # noqa: E402
from src.api.models.tte import PaperStatus  # noqa: E402


def teardown_module():
    """Remove injected stubs and cached parent packages so later tests re-import real modules."""
    for name in _INJECTED_STUBS:
        sys.modules.pop(name, None)
    _INJECTED_STUBS.clear()
    # Remove parser + parent packages that cached stub references
    for mod_name in list(sys.modules):
        if mod_name.startswith("src.agents.agent1."):
            sys.modules.pop(mod_name, None)
    sys.modules.pop("src.agents.agent1", None)
    sys.modules.pop("src.models.ir", None)
    sys.modules.pop("src.utils.llm", None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trial_data():
    td = MagicMock()
    td.title = "Test Trial"
    td.conditions = ["T2DM"]
    td.interventions = ["Drug A"]
    td.primary_outcomes = ["HbA1c"]
    td.inclusion_criteria = ["Age >= 18"]
    td.exclusion_criteria = ["Pregnancy"]
    return td


def _make_ir():
    ir = MagicMock()
    ir.target = MagicMock(inclusion_rules=[], exclusion_rules=[])
    return ir


def _llm_response():
    return MagicMock(content='{"target":{}, "comparator":{}, "outcome":{}}')


# ---------------------------------------------------------------------------
# The cache file path inside parse_nct() is built like:
#   cache_dir / f"{nct_id}_{hash}.json"
# We prevent cache hits by patching `cache_file.exists()` on the specific
# Path instance — done via a custom Path subclass that intercepts __truediv__
# calls from the known cache parent directory.
# ---------------------------------------------------------------------------


def _cache_never_exists_context():
    """Context manager: make every Path(...).exists() call that touches our
    known fake cache root return False.  Real paths (like tmp_path PDFs)
    are unaffected."""
    original_exists = Path.exists

    def patched_exists(self):
        if "/nonexistent_cache_dir_for_tests" in str(self):
            return False
        return original_exists(self)

    return patch.object(Path, "exists", patched_exists)


def _suppress_cache_write():
    """Suppress the open(..., 'w') write that saves the cache JSON."""
    return patch("builtins.open", mock_open(read_data="{}"))


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def parser():
    p = LogicDecomposer.__new__(LogicDecomposer)
    p.llm = MagicMock()
    p.parser = MagicMock()
    p.last_paper_status = None
    return p


# ---------------------------------------------------------------------------
# Test: last_paper_status is None before any parse_nct() call
# ---------------------------------------------------------------------------


def test_last_paper_status_initialized_as_none(parser):
    assert parser.last_paper_status is None


# ---------------------------------------------------------------------------
# Test: local PDF scenario
# ---------------------------------------------------------------------------


class TestLocalPDFScenario:
    """PDFs exist in papers_dir → source == 'local'."""

    def test_source_is_local_when_pdfs_found(self, parser, tmp_path):
        # Create a real supplement PDF so _discover_pdfs() picks it up
        (tmp_path / "appendix.pdf").write_bytes(b"%PDF-1.4 fake")

        trial_data = _make_trial_data()
        ir = _make_ir()

        with (
            patch("src.agents.agent1.parser.fetch_or_load_trial_data", return_value=trial_data),
            patch.object(parser, "_enrich_from_pdf", return_value=trial_data),
            patch.object(parser, "_build_artemis_request", return_value=ir),
            _cache_never_exists_context(),
            _suppress_cache_write(),
        ):
            parser.llm.invoke.return_value = _llm_response()
            result = parser.parse_nct(
                nct_id="NCT99999999",
                papers_dir=str(tmp_path),
            )

        assert result is ir
        assert parser.last_paper_status is not None
        status = parser.last_paper_status
        assert status.source == "local"
        assert len(status.papers_found) == 1
        assert status.papers_found[0].name == "appendix.pdf"
        assert status.papers_found[0].role == "supplement"
        assert status.manual_download_needed is False


# ---------------------------------------------------------------------------
# Test: PMC supplement download scenario
# ---------------------------------------------------------------------------


class TestPMCSupplementScenario:
    """PMC supplement downloaded → source == 'pmc_supplement'."""

    def test_source_is_pmc_supplement(self, parser):
        trial_data = _make_trial_data()
        ir = _make_ir()

        fake_supp = {"path": "/tmp/NCT12345/suppl.pdf", "role": "supplement"}

        with (
            patch("src.agents.agent1.parser.fetch_or_load_trial_data", return_value=trial_data),
            patch.object(parser, "_enrich_from_pdf", return_value=trial_data),
            patch.object(parser, "_build_artemis_request", return_value=ir),
            # make enrich_from_pubmed see PMIDs via PubMed search (cache absent → nct_raw=None)
            patch("src.agents.agent1.parser.search_pubmed_for_nct", return_value=["12345678"]),
            # PMC supplement download succeeds via lazy imports
            patch("src.agents.agent1.pmc_fetcher.pmid_to_pmcid", return_value="PMC111111"),
            patch("src.agents.agent1.pmc_supplement.download_pmc_supplements", return_value=[fake_supp]),
            _cache_never_exists_context(),
            _suppress_cache_write(),
        ):
            parser.llm.invoke.return_value = _llm_response()
            result = parser.parse_nct(
                nct_id="NCT12345678",
                enrich_from_pubmed=True,
            )

        assert result is ir
        assert parser.last_paper_status is not None
        status = parser.last_paper_status
        assert status.source == "pmc_supplement"
        assert status.supplement_available is True
        assert status.manual_download_needed is False


# ---------------------------------------------------------------------------
# Test: journal download scenario
# ---------------------------------------------------------------------------


class TestJournalDownloadScenario:
    """PMC fails → journal download succeeds → source == 'journal_download'."""

    def test_source_is_journal_download(self, parser, tmp_path):
        trial_data = _make_trial_data()
        ir = _make_ir()

        saved_pdf = tmp_path / "paper_main.pdf"
        saved_pdf.write_bytes(b"%PDF-1.4 fake")

        from src.agents.agent1.paper_url_mapper import DownloadAttempt

        dl_attempt = DownloadAttempt(
            url="https://www.nejm.org/doi/pdf/10.1056/NEJMoa1234",
            role="main",
            status="downloaded",
            saved_path=str(saved_pdf),
        )

        with (
            patch("src.agents.agent1.parser.fetch_or_load_trial_data", return_value=trial_data),
            patch.object(parser, "_enrich_from_pdf", return_value=trial_data),
            patch.object(parser, "_build_artemis_request", return_value=ir),
            patch("src.agents.agent1.parser.search_pubmed_for_nct", return_value=["22222222"]),
            # PMC returns nothing
            patch("src.agents.agent1.pmc_fetcher.pmid_to_pmcid", return_value=None),
            patch("src.agents.agent1.pmc_fetcher.get_pmc_eligibility", return_value=None),
            # Journal download via paper_url_mapper functions imported at module top
            patch("src.agents.agent1.parser.extract_doi_from_pubmed", return_value="10.1056/NEJMoa1234"),
            patch("src.agents.agent1.parser.download_papers_for_doi", return_value=[dl_attempt]),
            _cache_never_exists_context(),
            _suppress_cache_write(),
        ):
            parser.llm.invoke.return_value = _llm_response()
            result = parser.parse_nct(
                nct_id="NCT22222222",
                enrich_from_pubmed=True,
            )

        assert result is ir
        assert parser.last_paper_status is not None
        status = parser.last_paper_status
        assert status.source == "journal_download"
        assert status.manual_download_needed is False
        assert len(status.papers_found) >= 1


# ---------------------------------------------------------------------------
# Test: fallback scenario
# ---------------------------------------------------------------------------


class TestFallbackScenario:
    """All enrichment paths fail → source == 'nct_only'."""

    def test_source_is_nct_only_when_all_fail(self, parser):
        trial_data = _make_trial_data()
        ir = _make_ir()

        with (
            patch("src.agents.agent1.parser.fetch_or_load_trial_data", return_value=trial_data),
            patch.object(parser, "_build_artemis_request", return_value=ir),
            patch("src.agents.agent1.parser.get_design_paper_pmids", return_value=[]),
            patch("src.agents.agent1.parser.search_pubmed_for_nct", return_value=[]),
            _cache_never_exists_context(),
            _suppress_cache_write(),
        ):
            parser.llm.invoke.return_value = _llm_response()
            result = parser.parse_nct(
                nct_id="NCT33333333",
                enrich_from_pubmed=True,
            )

        assert result is ir
        assert parser.last_paper_status is not None
        assert parser.last_paper_status.source == "nct_only"
