"""The export's manifest must say which pipeline mode produced the cohort.

Nine settings change the CONTENT of an exported concept set. None of them was printed
and none was recorded, so a delivered batch carried no evidence of the mode it was
built under -- the same gap that let the 2026-09-08 export ship six disease-anchored
treatment arms before ``TTE_DRUG_ANCHORED_ENTRY`` was recorded.

The distinction these tests defend is the one that used to be lost: "unset, defaulted
to X" and "explicitly set to X" are different facts about a run, and both used to read
as absence.

``scripts/export_seeded_cohorts.py`` imports only ``src.utils`` at module scope (the
heavy ``src.services`` imports are deferred inside ``main``), so importing it here is
cheap and touches no store.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from src.utils.mapping_flags import MAPPING_FLAGS

REPO_ROOT = Path(__file__).resolve().parents[1]


def _export_module():
    """Load the export script by path, under a private name.

    Imported under a name of its own rather than ``export_seeded_cohorts`` so this test
    cannot collide with, or be affected by, another module of that name in
    ``sys.modules``.
    """
    spec = importlib.util.spec_from_file_location(
        "_tte_export_under_test", REPO_ROOT / "scripts" / "export_seeded_cohorts.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def manifest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """A manifest built the way the export builds it, over a throwaway store file."""
    for flag_spec in MAPPING_FLAGS:
        monkeypatch.delenv(flag_spec.name, raising=False)
    monkeypatch.setenv("ENABLE_REFINER", "0")
    monkeypatch.setenv("KG_EXPAND_MODE", "clinical")
    monkeypatch.setenv("TTE_DRUG_ANCHORED_ENTRY", "1")

    store_path = tmp_path / "studies.json"
    store_path.write_text("{}", encoding="utf-8")

    module = _export_module()
    return module.build_manifest(
        store_path=store_path,
        drug_anchored_source="set by this script; the environment did not carry it",
        manifest_studies=[],
        manifest_files=[],
        repo_dir=REPO_ROOT,
    )


def test_should_record_every_mapping_flag_when_the_manifest_is_written(manifest) -> None:
    recorded = manifest["mapping_env"]["flags"]

    missing = [spec.name for spec in MAPPING_FLAGS if spec.name not in recorded]
    assert not missing, f"manifest omits mapping flags: {missing}"


def test_should_distinguish_an_explicit_value_from_a_defaulted_one(manifest) -> None:
    """The whole point: absence and a deliberate choice must not read alike."""
    flags = manifest["mapping_env"]["flags"]

    assert flags["ENABLE_REFINER"]["source"] == "environment"
    assert flags["ENABLE_REFINER"]["value"] == "0"
    assert "explicitly set" in flags["ENABLE_REFINER"]["description"]

    assert flags["DOMAIN_PRECHECK"]["source"] == "default"
    assert flags["DOMAIN_PRECHECK"]["value"] == "0"
    assert "unset" in flags["DOMAIN_PRECHECK"]["description"]


def test_should_say_which_flags_take_part_in_the_criterion_cache_key(manifest) -> None:
    flags = manifest["mapping_env"]["flags"]

    assert flags["ENABLE_REFINER"]["in_criterion_cache_key"] is True
    assert flags["TTE_MAPPING_MAX_WORKERS"]["in_criterion_cache_key"] is False


def test_should_record_the_cache_key_signature_the_run_used(manifest) -> None:
    """Recorded whole so two manifests can be compared without re-deriving it."""
    signature = manifest["mapping_env"]["criterion_cache_key_signature"]

    assert "ENABLE_REFINER=0" in signature
    assert "KG_EXPAND_MODE=clinical" in signature


def test_should_report_no_single_default_when_the_readers_disagree(manifest) -> None:
    """REFINER_FOOTPRINT_THRESHOLD falls back to 1000 in one branch and 3000 in another.

    Recording either as "the default" would be a claim the code does not support, so
    the manifest records the disagreement instead of picking a side.
    """
    threshold = manifest["mapping_env"]["flags"]["REFINER_FOOTPRINT_THRESHOLD"]

    assert threshold["source"] == "default"
    assert threshold["value"] is None
    assert "1000" in threshold["default_note"]
    assert "3000" in threshold["default_note"]


def test_should_keep_recording_the_entry_anchor_mode(manifest) -> None:
    """The b6df569 record must survive this one being added beside it."""
    assert manifest["TTE_DRUG_ANCHORED_ENTRY"] == "1"
    assert manifest["TTE_DRUG_ANCHORED_ENTRY_source"].startswith("set by this script")
