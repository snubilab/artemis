"""What a reader must be able to learn from the PDF-enrichment log.

`_enrich_from_pdf` runs once per discovered PDF, and a study can have several.
On the six-study cold run of 2026-09-07 that meant nine invocations, three of
which found an eligibility section and two of which found no criteria at all.
The log those nine produced could not be read:

- a failure line named no PDF, so "PDF enrichment FAILED" for ARISTOTLE's
  appendix was read as "ARISTOTLE has no PDF criteria" while the protocol PDF
  for the same study had in fact succeeded three lines earlier;
- success was reported twice for the same fact, once through `logger` and once
  through `print`;
- success went through `logger` and failure through `warnings`, so under
  unconfigured logging (measured: module logger effective level WARNING, root
  handlers `[]`) the reader saw only the failures — a log biased toward
  breakage;
- the 20000-char section cap fired silently, and falling back to whole-paper text
  was printed as a neutral note (both went with the heading extractor when the
  segmentation step replaced it; its own announcements are tested in
  tests/test_eligibility_segmentation.py).

These tests fix the reader-facing contract, not the wording: every per-PDF
outcome names its PDF, is emitted exactly once, reaches the same stream whether
it succeeded or failed, and marks a degradation as one.
"""
import re
import subprocess
import warnings
from dataclasses import dataclass, field

import pytest

from src.agents.agent1 import parser as parser_module
from src.agents.agent1.parser import LogicDecomposer
from src.agents.agent1.segmentation import Segmentation

PDF_PATH = "/app/data/papers/NCT00412984/nejmoa1107039_appendix.pdf"
PDF_NAME = "nejmoa1107039_appendix.pdf"

GOOD_TEXT = """Protocol synopsis for the trial.

INCLUSION CRITERIA
1. Age 18 years or older
2. Documented atrial fibrillation
3. At least one additional risk factor for stroke

EXCLUSION CRITERIA
1. Severe renal impairment
2. Active bleeding

References
"""

class _FakeCompleted:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


@dataclass
class _Trial:
    """Stand-in for TrialData — `_enrich_from_pdf` only reads the two lists."""

    nct_id: str = "NCT00412984"
    inclusion_criteria: list = field(default_factory=list)
    exclusion_criteria: list = field(default_factory=list)


def _fake_enrich_trial_data(trial, criteria, strategy="merge"):
    return _Trial(
        trial.nct_id,
        trial.inclusion_criteria + criteria["inclusion"],
        trial.exclusion_criteria + criteria["exclusion"],
    )


CRITERIA_FOUND = {
    "inclusion": ["Age 18 years or older", "Documented atrial fibrillation"],
    "exclusion": ["Severe renal impairment"],
}
CRITERIA_NOT_FOUND = {"inclusion": [], "exclusion": []}


def _decomposer():
    """A LogicDecomposer without its LLM — `_enrich_from_pdf` needs no model."""
    return LogicDecomposer.__new__(LogicDecomposer)


_RAISED_WARNINGS = []


def _enrich(monkeypatch, *, stdout="", returncode=0, stderr="", raises=None,
            criteria=None, pdf_path=PDF_PATH, role="supplement"):
    """Drive `_enrich_from_pdf` with pdftotext and its two collaborators pinned.

    The segmentation step and the merge are stubbed rather than run live: what is
    under test here is the reporting, and the step's own behaviour is tested on the
    real corpus in tests/test_eligibility_segmentation.py.
    """
    def fake_run(*_args, **_kwargs):
        if raises is not None:
            raise raises
        return _FakeCompleted(stdout=stdout, returncode=returncode, stderr=stderr)

    monkeypatch.setattr(subprocess, "run", fake_run)
    found = criteria if criteria is not None else CRITERIA_FOUND
    monkeypatch.setattr(
        parser_module, "segment_eligibility",
        lambda _text: Segmentation(items={kind: list(found[kind]) for kind in found}, parts=1),
    )
    monkeypatch.setattr(parser_module, "enrich_trial_data", _fake_enrich_trial_data)

    _RAISED_WARNINGS.clear()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        enriched = _decomposer()._enrich_from_pdf(_Trial(), pdf_path, role=role)
    _RAISED_WARNINGS.extend(str(w.message) for w in caught)
    return enriched


def _reader_sees(capsys, caplog):
    """Every channel a reader of the run could be watching, joined.

    stdout, stderr, the logging records, and the warnings — so a test cannot
    pass merely because the fact reached *some* channel.
    """
    captured = capsys.readouterr()
    logged = [record.getMessage() for record in caplog.records]
    return "\n".join([captured.out, captured.err, *logged, *_RAISED_WARNINGS])


_SUCCESS_VERDICT = re.compile(r"\d+\s*->\s*\d+\s+inclusion")


def _failure_verdicts(text):
    """The lines that announce a per-PDF enrichment failure."""
    return [line for line in text.splitlines() if "FAILED" in line]


def _success_verdicts(text):
    """The lines that announce a per-PDF enrichment success."""
    return [line for line in text.splitlines() if _SUCCESS_VERDICT.search(line)]


FAILURE_CASES = {
    "pdftotext_returns_nonzero": dict(returncode=1, stderr="Syntax Error: broken xref"),
    "extracted_text_too_short": dict(stdout="two lines\nonly"),
    "no_criteria_in_the_text": dict(stdout=GOOD_TEXT, criteria=CRITERIA_NOT_FOUND),
    "pdftotext_is_not_installed": dict(raises=FileNotFoundError("pdftotext")),
    "an_unexpected_error_is_raised": dict(raises=ValueError("boom")),
}


class TestEveryFailureNamesItsPdf:
    """A1 — the filename appeared only in a separate earlier line, so a reader
    had to correlate a failure with a print by position."""

    @pytest.mark.parametrize("case", list(FAILURE_CASES), ids=list(FAILURE_CASES))
    def test_should_name_the_pdf_when_enrichment_fails(
        self, case, monkeypatch, capsys, caplog
    ):
        _enrich(monkeypatch, **FAILURE_CASES[case])
        verdicts = _failure_verdicts(_reader_sees(capsys, caplog))
        assert verdicts, "the failure was never announced"
        assert all(PDF_NAME in line for line in verdicts), (
            f"a failure verdict does not name its PDF: {verdicts}"
        )

    @pytest.mark.parametrize("case", list(FAILURE_CASES), ids=list(FAILURE_CASES))
    def test_should_say_other_pdfs_may_still_succeed_when_one_pdf_fails(
        self, case, monkeypatch, capsys, caplog
    ):
        """The misdiagnosis this prevents: one PDF's failure read as the whole
        study having no PDF criteria."""
        _enrich(monkeypatch, **FAILURE_CASES[case])
        seen = _reader_sees(capsys, caplog).lower()
        assert "other pdf" in seen and "may still succeed" in seen


class TestOneFactIsReportedOnce:
    """A2 — success went out through both `logger.info` and `print`."""

    def test_should_report_the_enrichment_outcome_once_when_a_pdf_succeeds(
        self, monkeypatch, capsys, caplog
    ):
        caplog.set_level(0)
        _enrich(monkeypatch, stdout=GOOD_TEXT)
        outcomes = re.findall(r"\d+\s*->\s*\d+\s+inclusion", _reader_sees(capsys, caplog))
        assert len(outcomes) == 1, f"outcome reported {len(outcomes)} times: {outcomes}"


class TestSuccessAndFailureShareOneChannel:
    """A3 — success through `logger` and failure through `warnings` means that
    under unconfigured logging only the failures survive."""

    def test_should_show_the_success_outcome_when_logging_is_unconfigured(
        self, monkeypatch, capsys
    ):
        enriched = _enrich(monkeypatch, stdout=GOOD_TEXT)
        assert enriched.inclusion_criteria, "fixture must actually enrich"
        assert _success_verdicts(capsys.readouterr().out), (
            "the success verdict never reached stdout, so a run with logging "
            "unconfigured cannot see that this PDF worked"
        )

    def test_should_show_the_failure_outcome_on_the_stream_the_success_used(
        self, monkeypatch, capsys
    ):
        _enrich(monkeypatch, stdout=GOOD_TEXT)
        success_stream = capsys.readouterr().out

        _enrich(monkeypatch, stdout=GOOD_TEXT, criteria=CRITERIA_NOT_FOUND)
        failure_stream = capsys.readouterr().out

        assert _success_verdicts(success_stream)
        assert _failure_verdicts(failure_stream), (
            "the failure reached the reader on a stream the success did not, so "
            "an unconfigured run shows only breakage"
        )
