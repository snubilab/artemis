"""The delivery scripts must not depend on the caller remembering an env var.

On 2026-09-08 the sanctioned export ran without ``TTE_DRUG_ANCHORED_ENTRY``. Every
treatment arm was built with its ``PrimaryCriteria`` swapped from the arm's own drug
to a disease anchor -- a cohort of patients who never took the drug -- and the batch
was rejected by its own lint with six ``entry_mismatch`` and two ``missing_arm``
violations. The code was correct; the mode was simply unreachable from the command
line, and forgetting it changed what a cohort means.

These tests pin the two properties that make that impossible to repeat:

1. With the variable UNSET, the export path resolves to drug-anchored entry and the
   service that reads the variable agrees (never a silent disease-anchored arm).
2. ``export_seeded_cohorts.py`` and ``verify_circe_delivery.py`` resolve the SAME
   mode. A gate that disagrees with the exporter compares against the wrong expected
   entry, which is worse than no gate.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.utils.delivery_mode import (
    DRUG_ANCHORED_ENTRY_ENV,
    DeliveryModeConflictError,
    resolve_drug_anchored_entry,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPORT_SCRIPT = REPO_ROOT / "scripts" / "export_seeded_cohorts.py"
VERIFY_SCRIPT = REPO_ROOT / "scripts" / "verify_circe_delivery.py"


def _mode_line(stderr: str) -> str:
    """The single 'entry anchor mode: ...' line a delivery script prints."""
    lines = [line.strip() for line in stderr.splitlines() if line.startswith("entry anchor mode:")]
    assert len(lines) == 1, f"expected exactly one mode line, got {lines!r} in:\n{stderr}"
    return lines[0]


def _run_script(
    script: Path, argv: list[str], env_value: str | None
) -> subprocess.CompletedProcess:
    """Run a delivery script in a child process with the mode env var set or absent."""
    env = dict(os.environ)
    env.pop("TTE_STORE_PATH", None)
    if env_value is None:
        env.pop(DRUG_ANCHORED_ENTRY_ENV, None)
    else:
        env[DRUG_ANCHORED_ENTRY_ENV] = env_value
    return subprocess.run(
        [sys.executable, str(script), *argv],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


def _export_argv(tmp_path: Path) -> list[str]:
    # A store that does not exist: the run aborts right after the mode is resolved,
    # so the mode line is observable without building any cohort.
    return [
        "--store",
        str(tmp_path / "no-such-store.json"),
        "--out",
        str(tmp_path / "out"),
        "--study-id",
        "8",
    ]


def _verify_argv(tmp_path: Path) -> list[str]:
    return ["--dir", str(tmp_path), "--store", str(tmp_path / "no-such-store.json")]


class TestUnsetResolvesToDrugAnchoredEntry:
    """V1 -- the variable being absent must not silently change what a cohort means."""

    def test_should_resolve_drug_anchored_when_the_caller_left_the_variable_unset(
        self, monkeypatch
    ):
        monkeypatch.delenv(DRUG_ANCHORED_ENTRY_ENV, raising=False)

        mode = resolve_drug_anchored_entry()

        assert mode.drug_anchored is True
        assert os.environ[DRUG_ANCHORED_ENTRY_ENV] == "1"

    def test_should_report_drug_anchored_to_the_service_when_the_caller_left_it_unset(
        self, monkeypatch
    ):
        """The resolver's whole job is that the reader of the variable agrees with it.

        ``TTEService._drug_anchored_entry`` is the consumer at ``tte_service.py:419``
        whose False answer produced the rejected batch.
        """
        from src.services.tte_service import TTEService

        monkeypatch.delenv(DRUG_ANCHORED_ENTRY_ENV, raising=False)
        service = TTEService.__new__(TTEService)
        assert service._drug_anchored_entry() is False, "precondition: unset reads as disabled"

        resolve_drug_anchored_entry()

        assert service._drug_anchored_entry() is True

    def test_should_say_the_resolved_mode_in_its_output_when_exporting(self, tmp_path):
        result = _run_script(EXPORT_SCRIPT, _export_argv(tmp_path), env_value=None)

        line = _mode_line(result.stderr)
        assert "drug-anchored" in line
        assert f"{DRUG_ANCHORED_ENTRY_ENV}=1" in line
        assert "set by this script" in line

    def test_should_keep_the_environment_value_when_it_already_agrees(self, monkeypatch):
        monkeypatch.setenv(DRUG_ANCHORED_ENTRY_ENV, "true")

        mode = resolve_drug_anchored_entry()

        assert mode.drug_anchored is True
        assert mode.env_value == "true"
        assert os.environ[DRUG_ANCHORED_ENTRY_ENV] == "true"


class TestExplicitlyDisabledIsRefused:
    """An ambient value that contradicts delivery aborts instead of being overridden."""

    def test_should_refuse_when_the_environment_disables_drug_anchored_entry(self, monkeypatch):
        monkeypatch.setenv(DRUG_ANCHORED_ENTRY_ENV, "0")

        with pytest.raises(DeliveryModeConflictError) as exc_info:
            resolve_drug_anchored_entry()

        message = str(exc_info.value)
        assert DRUG_ANCHORED_ENTRY_ENV in message
        assert "'0'" in message

    def test_should_abort_the_export_when_the_environment_disables_it(self, tmp_path):
        result = _run_script(EXPORT_SCRIPT, _export_argv(tmp_path), env_value="0")

        assert result.returncode == 2
        assert DRUG_ANCHORED_ENTRY_ENV in result.stderr


class TestExporterAndGateResolveTheSameMode:
    """V2 -- a gate that resolves a different mode compares against the wrong entry."""

    def test_should_resolve_the_same_mode_in_the_exporter_and_the_gate_when_unset(self, tmp_path):
        export = _run_script(EXPORT_SCRIPT, _export_argv(tmp_path), env_value=None)
        verify = _run_script(VERIFY_SCRIPT, _verify_argv(tmp_path), env_value=None)

        assert _mode_line(export.stderr) == _mode_line(verify.stderr)

    def test_should_refuse_in_both_the_exporter_and_the_gate_when_the_mode_conflicts(
        self, tmp_path
    ):
        export = _run_script(EXPORT_SCRIPT, _export_argv(tmp_path), env_value="0")
        verify = _run_script(VERIFY_SCRIPT, _verify_argv(tmp_path), env_value="0")

        assert (export.returncode, verify.returncode) == (2, 2)
        assert DRUG_ANCHORED_ENTRY_ENV in export.stderr
        assert DRUG_ANCHORED_ENTRY_ENV in verify.stderr

    def test_should_route_both_scripts_through_the_one_resolver(self):
        """One authoritative home: neither script may re-derive the mode locally."""
        import scripts.export_seeded_cohorts as export_module
        import scripts.verify_circe_delivery as verify_module

        assert (
            export_module.resolve_drug_anchored_entry
            is verify_module.resolve_drug_anchored_entry
            is resolve_drug_anchored_entry
        )
