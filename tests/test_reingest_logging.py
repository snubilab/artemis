"""The re-ingest run has to show the token headroom while it is still shrinking.

``_invoke_and_extract`` logs the prompt/completion split on every call so an
approaching ceiling is visible before it is hit. The script configured no logging, so
the effective level was WARNING with no handler and every one of those records was
discarded. Only the failure was visible -- ``logger.error`` reaches stderr through
``logging.lastResort`` -- which is exactly backwards: the warning that would have
prevented the failure was the part being dropped.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.reingest_protocol_pdfs import configure_logging  # noqa: E402

PIPELINE_LOGGER = "src.agents.agent1.parser"


@pytest.fixture(autouse=True)
def _restore_logging():
    """Logging is process-global; leave it exactly as it was found."""
    pipeline = logging.getLogger("src")
    handlers, level = list(pipeline.handlers), pipeline.level
    yield
    # addHandler appends in place, so the list has to be restored by content --
    # a shallow copy of the logger's __dict__ shares this very list and restores
    # nothing.
    pipeline.handlers[:] = handlers
    pipeline.level = level


class TestTheRunCanSeeItsOwnTokenHeadroom:
    def test_should_deliver_an_info_record_from_the_pipeline_when_configured(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging()

        logging.getLogger(PIPELINE_LOGGER).info("token usage: prompt=8138 completion=6002")

        assert "token usage: prompt=8138 completion=6002" in capsys.readouterr().err

    def test_should_drop_the_record_when_not_configured(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The regression this guards: without the call, the record vanishes."""
        logging.getLogger(PIPELINE_LOGGER).info("token usage: prompt=8138 completion=6002")

        assert "token usage" not in capsys.readouterr().err

    def test_should_emit_once_when_configured_twice(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """main() may run more than once in a process; a second handler would double
        every line and make a token count look like two calls."""
        configure_logging()
        configure_logging()

        logging.getLogger(PIPELINE_LOGGER).info("once")

        assert capsys.readouterr().err.count("once") == 1

    def test_should_emit_once_when_the_root_logger_also_has_a_handler(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The run configures logging itself, but something in the import chain configures
        the root logger too — observed mid-run, where ARISTOTLE's token line appeared once
        and PLATO's appeared twice. Without propagate=False the record reaches both
        handlers and every INFO line doubles, which makes a log that exists to be counted
        unreliable for counting."""
        root = logging.getLogger()
        root_handler = logging.StreamHandler(sys.stderr)
        root.addHandler(root_handler)
        root_level = root.level
        root.setLevel(logging.INFO)
        try:
            configure_logging()

            logging.getLogger(PIPELINE_LOGGER).info("token usage: prompt=1")

            assert capsys.readouterr().err.count("token usage: prompt=1") == 1
        finally:
            root.removeHandler(root_handler)
            root.setLevel(root_level)
