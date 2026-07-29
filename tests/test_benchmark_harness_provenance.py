"""quick_concept_benchmark_v2 must not eat an operator override, and must
record which model produced a results file.

A results file with no model is not a mislabelled measurement, it is an
unlabelled one — and resuming into it merges two models' rows silently.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ARTEMIS_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ARTEMIS_DIR / "scripts" / "quick_concept_benchmark_v2.py"

SENTINEL_URL = "http://provenance-sentinel:1/v1"


def _load_module():
    saved_env = os.environ.copy()
    saved_cwd = os.getcwd()
    spec = importlib.util.spec_from_file_location(
        "quick_concept_benchmark_v2_provenance_test",
        SCRIPT_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        os.environ.clear()
        os.environ.update(saved_env)
        os.chdir(saved_cwd)


MODULE = _load_module()

SAMPLE = [
    {
        "id": "row-1",
        "study": "DemoStudy",
        "cohort": "demo.json",
        "criterion_name": "No heart failure",
        "concept_set_name": "heart failure",
        "domain": "Condition",
        "gold_raw_ids": [11, 22],
    }
]
MAPPERS = ["RAG"]


def _args(save_path: Path) -> argparse.Namespace:
    return argparse.Namespace(dataset=Path("dataset.json"), save_path=save_path)


class TestRuntimeEnvAllowlist:
    """F5: an exported VLLM_BASE_URL must survive bootstrap_runtime_env()."""

    def test_operator_vllm_base_url_survives_bootstrap(self) -> None:
        env = dict(os.environ)
        env["VLLM_BASE_URL"] = SENTINEL_URL
        env["PYTHONPATH"] = str(ARTEMIS_DIR)
        probe = (
            "import importlib.util, os, sys;"
            f"spec=importlib.util.spec_from_file_location('h', {str(SCRIPT_PATH)!r});"
            "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);"
            "print(os.environ.get('VLLM_BASE_URL'));print(os.getcwd())"
        )
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=str(ARTEMIS_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )

        assert completed.returncode == 0, completed.stderr
        base_url, cwd = completed.stdout.strip().splitlines()[-2:]
        assert base_url == SENTINEL_URL
        assert cwd == str(ARTEMIS_DIR), "bootstrap must not relocate a relative --save-path"

    def test_allowlist_covers_every_provenance_key(self) -> None:
        assert set(MODULE.PROVENANCE_ENV_KEYS) <= MODULE.ALLOWED_RUNTIME_ENV


class TestProvenanceRecorded:
    """F15: both writers record the settings that decide which model answered."""

    @pytest.mark.parametrize("writer", ["save_progress", "save_results"])
    def test_writer_records_runtime_config(self, tmp_path: Path, writer: str, monkeypatch) -> None:
        monkeypatch.setenv("LLM_MODEL", "vllm/model-a")
        monkeypatch.setenv("VLLM_BASE_URL", SENTINEL_URL)
        save_path = tmp_path / "results.json"

        row = MODULE.make_row(SAMPLE[0], [11], 1.0, None)
        row.update(
            gold_normalized_ids=[11, 22],
            gold_unresolved_ids=[],
            pred_normalized_ids=[11],
            pred_unresolved_ids=[],
            **MODULE.compute_metrics([11], [11, 22]),
        )
        results = {"RAG": [row]}
        if writer == "save_progress":
            MODULE.save_progress(save_path, _args(save_path), SAMPLE, MAPPERS, results)
        else:
            MODULE.save_results(
                save_path, _args(save_path), SAMPLE, MAPPERS, {}, {}, results
            )

        payload = json.loads(save_path.read_text(encoding="utf-8"))
        assert payload["runtime_config"]["llm_model"] == "vllm/model-a"
        assert payload["runtime_config"]["vllm_base_url"] == SENTINEL_URL


class TestResumeRefusesMismatch:
    """F15: resume must refuse rather than merge two models into one table."""

    def _write_progress(self, save_path: Path, monkeypatch, model: str) -> None:
        monkeypatch.setenv("LLM_MODEL", model)
        rows = [MODULE.make_row(SAMPLE[0], [11], 1.0, None)]
        MODULE.save_progress(save_path, _args(save_path), SAMPLE, MAPPERS, {"RAG": rows})

    def test_same_model_resumes(self, tmp_path: Path, monkeypatch) -> None:
        save_path = tmp_path / "results.json"
        self._write_progress(save_path, monkeypatch, "vllm/model-a")

        resumed = MODULE.load_resume_rows(save_path, _args(save_path), SAMPLE, MAPPERS)

        assert len(resumed["RAG"]) == 1

    def test_different_model_refuses(self, tmp_path: Path, monkeypatch) -> None:
        save_path = tmp_path / "results.json"
        self._write_progress(save_path, monkeypatch, "vllm/model-a")

        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        resumed = MODULE.load_resume_rows(save_path, _args(save_path), SAMPLE, MAPPERS)

        assert resumed["RAG"] == []

    def test_file_without_provenance_refuses(self, tmp_path: Path, monkeypatch) -> None:
        save_path = tmp_path / "results.json"
        self._write_progress(save_path, monkeypatch, "vllm/model-a")
        payload = json.loads(save_path.read_text(encoding="utf-8"))
        del payload["runtime_config"]
        save_path.write_text(json.dumps(payload), encoding="utf-8")

        resumed = MODULE.load_resume_rows(save_path, _args(save_path), SAMPLE, MAPPERS)

        assert resumed["RAG"] == []
