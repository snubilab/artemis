"""
SPEC-PERF-001 M1: Worker Concurrency — Tests for MAX_WORKERS configuration.

Tests:
- Module-level MAX_WORKERS defaults to 16
- AGENT2_MAX_WORKERS env var overrides the default
- MAX_WORKERS is used in ThreadPoolExecutor calls
"""

import importlib
import os
from unittest.mock import patch

import pytest


class TestMaxWorkersDefault:
    """Verify MAX_WORKERS module-level constant defaults to 16."""

    def test_default_value_is_16(self):
        """MAX_WORKERS should be 16 when AGENT2_MAX_WORKERS is not set."""
        env = os.environ.copy()
        env.pop("AGENT2_MAX_WORKERS", None)
        with patch.dict(os.environ, env, clear=True):
            import src.agents.agent2.workflow as wf_mod
            wf_mod = importlib.reload(wf_mod)
            assert wf_mod.MAX_WORKERS == 16


class TestMaxWorkersEnvOverride:
    """Verify AGENT2_MAX_WORKERS env var overrides the default."""

    def test_env_var_override(self):
        """Setting AGENT2_MAX_WORKERS should change MAX_WORKERS."""
        with patch.dict(os.environ, {"AGENT2_MAX_WORKERS": "8"}):
            import src.agents.agent2.workflow as wf_mod
            wf_mod = importlib.reload(wf_mod)
            assert wf_mod.MAX_WORKERS == 8

    def test_env_var_with_string_value(self):
        """AGENT2_MAX_WORKERS should parse string to int."""
        with patch.dict(os.environ, {"AGENT2_MAX_WORKERS": "32"}):
            import src.agents.agent2.workflow as wf_mod
            wf_mod = importlib.reload(wf_mod)
            assert wf_mod.MAX_WORKERS == 32


class TestMaxWorkersLogging:
    """Verify effective worker count is logged at module import."""

    def test_logs_worker_count_at_import(self):
        """Module import should log effective worker count at INFO level."""
        with patch.dict(os.environ, {"AGENT2_MAX_WORKERS": "12"}):
            import src.agents.agent2.workflow as wf_mod
            with patch.object(wf_mod.logger, "info") as mock_info:
                wf_mod = importlib.reload(wf_mod)
                log_messages = [str(call) for call in mock_info.call_args_list]
                found = any("MAX_WORKERS" in msg and "12" in msg for msg in log_messages)
                assert found, f"Expected MAX_WORKERS=12 log, got: {log_messages}"
