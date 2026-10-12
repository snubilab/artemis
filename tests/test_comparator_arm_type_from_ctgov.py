"""Whether a trial's comparator is a placebo comes from ClinicalTrials.gov, not the arm name.

RFC-016 §4 (A22): ``TTEService._is_placebo_arm`` read the arm NAME ("placebo" substring,
"sugar pill", "sham"). The registry already states it structurally:
``protocolSection.armsInterventionsModule.armGroups[].type``. The six trials' cached
records (``data/nct_cache``) and the candidate store's arms are copied verbatim into
``tests/fixtures/p3_structural_rows.json`` (section ``a22_arms``):

* LEADER, EMPA-REG, CARMELINA carry a ``PLACEBO_COMPARATOR`` arm (EMPA-REG two
  ``EXPERIMENTAL`` doses beside it);
* PLATO, ARISTOTLE, CAROLINA carry an ``ACTIVE_COMPARATOR`` arm. ARISTOTLE's labels are
  "1" and "2", so nothing in its names says which arm is which.

The cache is read, never the network: a trial missing from it is unknown, and an unknown
comparator gets neither the active- nor the placebo-comparator build.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "p3_structural_rows.json").read_text()
)["a22_arms"]

EXPECTED = {
    "NCT01179048": True,   # LEADER
    "NCT00391872": False,  # PLATO
    "NCT00412984": False,  # ARISTOTLE
    "NCT01131676": True,   # EMPA-REG
    "NCT01897532": True,   # CARMELINA
    "NCT01243424": False,  # CAROLINA
}


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    """The six cached registry records, reduced to the arms module they carry."""
    for nct_id, arm_groups in FIXTURE["arm_groups"].items():
        record = {"protocolSection": {"armsInterventionsModule": {"armGroups": arm_groups}}}
        (tmp_path / f"{nct_id}.json").write_text(json.dumps(record))
    return tmp_path


@pytest.mark.parametrize("nct_id", sorted(EXPECTED))
def test_should_read_the_comparator_type_from_the_registry_when_the_trial_is_cached(
    cache_dir: Path, nct_id: str
):
    from src.services.ctgov_arm_types import comparator_is_placebo, load_cached_arm_group_types

    assert comparator_is_placebo(load_cached_arm_group_types(nct_id, cache_dir)) is EXPECTED[nct_id]


def test_should_be_unknown_when_the_trial_is_not_in_the_cache(cache_dir: Path):
    from src.services.ctgov_arm_types import comparator_is_placebo, load_cached_arm_group_types

    assert load_cached_arm_group_types("NCT01730534", cache_dir) is None
    assert comparator_is_placebo(None) is None


@pytest.mark.parametrize("study", FIXTURE["studies"], ids=lambda s: f"study{s['id']}")
def test_should_decide_each_store_study_from_its_registry_record(
    cache_dir: Path, monkeypatch: pytest.MonkeyPatch, study: dict
):
    """The service asks the registry for the study's NCT id; the arm names are not read."""
    from src.services import ctgov_arm_types
    from src.services.tte_service import TTEService

    monkeypatch.setattr(ctgov_arm_types, "DEFAULT_CACHE_DIR", cache_dir)
    svc = TTEService.__new__(TTEService)

    assert svc._comparator_arm_is_placebo(study) is EXPECTED[study["nctId"]]
