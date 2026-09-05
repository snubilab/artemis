"""The export script's own INFO lines have to reach the log.

``_build_emittable_expression`` reports the entry-colliding washout correction with
``logging.info("[TTE] Ended %d washout rule(s) ...")`` on the root logger.
``scripts/export_seeded_cohorts.py`` never configured logging, so the root logger kept its
default WARNING level and that line was discarded: the only way to establish that the
correction had fired was to diff the emitted files against a previous export. A correction
that silently rewrites what is delivered, and reports it into nothing, is exactly the shape
the 2026-08-31 delivery chain was made of.

The handler admits this project's own records (the bare ``logging.*`` calls in
``src.services.tte_service``, which land on the root logger, and the ``src.*`` named
loggers) and nothing else. No library's level is touched: third-party loggers keep
whatever level they had, and their records are dropped at the handler rather than
silenced at the source.
"""

from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.export_seeded_cohorts import _configure_logging  # noqa: E402


def _emit_and_capture(record_logger: logging.Logger, message: str) -> list[str]:
    """Install the script's logging config, emit one record, return what the handler saw."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    try:
        root.handlers = []
        _configure_logging()
        captured: list[str] = []

        class _Spy(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(record.getMessage())

        # The spy carries the configured handler's own filters, so what it sees is what
        # that handler would have written -- the filter object under test, not a copy of
        # its logic.
        spy = _Spy()
        for handler in root.handlers:
            for filt in handler.filters:
                spy.addFilter(filt)
        root.addHandler(spy)
        record_logger.info(message)
        return captured
    finally:
        root.handlers = saved_handlers
        root.setLevel(saved_level)


class TestTheScriptsOwnInfoLinesAreEmitted:
    def test_should_emit_a_root_logger_info_record_when_logging_is_configured(self):
        """`_build_emittable_expression` logs through the root logger, not a named one."""
        captured = _emit_and_capture(
            logging.getLogger(), "[TTE] Ended 1 washout rule(s) a day before index"
        )
        assert captured == ["[TTE] Ended 1 washout rule(s) a day before index"]

    def test_should_emit_a_src_logger_info_record_when_logging_is_configured(self):
        captured = _emit_and_capture(logging.getLogger("src.services.tte_store"), "store line")
        assert captured == ["store line"]

    def test_should_not_emit_a_third_party_info_record(self):
        """Raising the root level must not turn every library's INFO chatter into output."""
        captured = _emit_and_capture(logging.getLogger("urllib3.connectionpool"), "GET /")
        assert captured == []

    def test_should_not_change_a_third_party_loggers_level(self):
        """Dropping the record at the handler, rather than at the source, leaves every
        library free to be configured by whoever else configures it."""
        noisy = logging.getLogger("httpx")
        before = noisy.level
        root = logging.getLogger()
        saved_handlers, saved_level = list(root.handlers), root.level
        try:
            root.handlers = []
            _configure_logging()
            assert noisy.level == before
        finally:
            root.handlers = saved_handlers
            root.setLevel(saved_level)
