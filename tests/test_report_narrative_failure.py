"""A failed report-narrative call returns the plain report and says so; it never raises.

``_generate_report_narrative``'s handler logged through a module ``logger`` that
``tte_service`` never defines, so the first failed narrative call raised ``NameError``
from inside its own except block: the fallback report was unreachable and the analysis
report failed with an error about logging instead of the model failure.

No LLM is called: ``get_llm`` is replaced by a model whose call raises.
"""

import logging
from types import SimpleNamespace
from unittest.mock import patch

import src.services.tte_service as tte_service
from src.services.tte_service import TTEService

FAILURE_MARKER = "LLM report narrative generation failed"


def _narrative(invoke):
    svc = TTEService.__new__(TTEService)
    with patch.object(tte_service, "get_llm", lambda *a, **k: SimpleNamespace(invoke=invoke)):
        return svc._generate_report_narrative(
            title="Study", description="d", nct_id="NCT00000000", brief_title="b",
            treatment_name="apixaban", comparator_name="warfarin", outcome_name="stroke",
            analysis_method="IPTW", n_treatment=10, n_comparator=12, hr=None, ci_lower=None,
            ci_upper=None, p_value=None, treatment_events=None, comparator_events=None,
            matched_pairs=None, followup_days="365", source_key="k",
        )


def _raise(_messages):
    raise TimeoutError("read timeout")


def test_should_return_the_fallback_report_when_the_narrative_call_fails(caplog):
    caplog.set_level(logging.WARNING)

    html = _narrative(_raise)

    assert "<h2>" in html, "the fallback report was not returned"
    lines = [r.getMessage() for r in caplog.records if FAILURE_MARKER in r.getMessage()]
    assert lines == [f"{FAILURE_MARKER}: read timeout"], lines
