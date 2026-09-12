"""
Tests for paper status collection in Agent1 parser (SPEC-UI-011 Task T2).

Verifies that parse_nct() populates self.last_paper_status correctly
depending on which enrichment path succeeds.
"""
from __future__ import annotations

import importlib
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
#
# `parser.py` is imported directly, with no `sys.modules` stubbing.
#
# This file used to install MagicMock modules for `langchain_core`,
# `src.utils.llm`, `src.models.ir`, `src.agents.agent1.prompts` and six
# `src.agents.agent1.*` submodules before importing the parser, "so parser.py
# imports without env setup". Measured on this checkout, that is no longer
# needed: `import src.agents.agent1.parser` succeeds on its own, including under
# a scrubbed environment.
#
# The stubbing was not merely redundant, it was actively harmful, in two ways
# that no amount of teardown could fix:
#
#   1. Attribute assignment onto a REAL module. The installer skipped a module
#      already present in `sys.modules`, then assigned stubs onto it anyway --
#      `sys.modules["src.agents.agent1.pubmed_fetcher"].extract_eligibility_from_text
#      = MagicMock(...)`. Popping a `sys.modules` entry does not undo an attribute
#      assignment on an object other modules still reference, so the mock outlived
#      this file for the rest of the session.
#   2. Teardown that ran too late to matter. pytest imports EVERY test module
#      during collection, before running any test, so a module collected after
#      this one bound the MagicMocks at ITS import -- long before
#      `teardown_module` could remove them.
#
# Measured cost: 12 tests failed in a combined run across this file,
# `test_07_pubmed_linker.py` and `test_08_pubmed_fetcher.py`, while each file
# passed on its own.
#
# Behaviour stubbing now happens per test, in `_stub_enrichment_paths` below,
# through `monkeypatch`.

from src.agents.agent1.parser import LogicDecomposer
from src.api.models.tte import PaperStatus


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


@pytest.fixture(autouse=True)
def _stub_enrichment_paths(monkeypatch):
    """Point every enrichment path at a stub, and let `monkeypatch` put it back.

    `monkeypatch.setattr` records the previous value and restores it at the end
    of each test, so nothing survives into another file. That is the whole
    difference from the plain module-attribute assignments this replaces -- the
    module comment at the top of this file records what those cost.

    **Target choice.** `parser.py` binds most of these with
    `from <module> import <name>` at import time, so it holds its OWN reference
    and patching the source module would not reach the code under test. Those are
    patched on the parser module itself, resolved through
    `LogicDecomposer.__module__` so it is provably the same module object the
    tests' `LogicDecomposer` came from rather than whatever a fresh import would
    return. The four names parser imports INSIDE a function
    (`DEFAULT_CACHE_DIR` at parser.py:1124, `get_pmc_eligibility` /
    `pmid_to_pmcid` at :1152, `download_pmc_supplements` at :1153) are looked up
    at call time, so those are patched on their source modules.

    **Ordering.** `monkeypatch` needs none of the dependency ordering a manual
    restore does. Each `setattr` is independent -- it saves one attribute on one
    object and puts that one value back -- so there is no import graph to walk
    and no "restore `nct_fetcher` before `enricher` or it re-binds the mock
    `TrialData`" hazard. That hazard is real for a reload-based repair, which
    re-executes a module body and therefore re-resolves its imports; `setattr`
    never re-executes anything.
    """
    parser_mod = sys.modules[LogicDecomposer.__module__]

    # Bound into parser's namespace at import time -> patch parser.
    for name, stub in {
        "fetch_or_load_trial_data": MagicMock(),
        "load_trial_data_from_file": MagicMock(),
        "fetch_trial_data": MagicMock(),
        "TrialData": MagicMock(),
        "extract_pmids_from_nct": MagicMock(return_value=[]),
        "get_design_paper_pmids": MagicMock(return_value=[]),
        "search_pubmed_for_nct": MagicMock(return_value=[]),
        "fetch_pubmed_abstract": MagicMock(return_value=None),
        "extract_eligibility_from_text": MagicMock(
            return_value={"inclusion": [], "exclusion": []}
        ),
        "enrich_trial_data": MagicMock(side_effect=lambda td, *a, **kw: td),
    }.items():
        monkeypatch.setattr(parser_mod, name, stub)

    # Imported inside a function -> resolved at call time, so patch the source.
    for module_name, name, stub in [
        ("src.agents.agent1.nct_fetcher", "DEFAULT_CACHE_DIR",
         Path("/nonexistent_cache_dir_for_tests")),
        ("src.agents.agent1.pmc_fetcher", "get_pmc_eligibility", MagicMock(return_value=None)),
        ("src.agents.agent1.pmc_fetcher", "pmid_to_pmcid", MagicMock(return_value=None)),
        ("src.agents.agent1.pmc_supplement", "download_pmc_supplements",
         MagicMock(return_value=[])),
    ]:
        # No `raising=False`: every one of these attributes exists today, and a
        # rename should fail here loudly rather than leave the path unstubbed.
        monkeypatch.setattr(importlib.import_module(module_name), name, stub)


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
