"""The denominator of the alias-tier refusal rate has to be the right population.

``scripts/analyze_alias_tier_refusals.py`` reports how often
``TTEService._alias_ingredient_mapping`` refuses. That rate is only meaningful over the
trials the tier can actually be reached for: a trial whose arms already spell the
generic name resolves one tier earlier and never gets here, so counting it as a refusal
inflates the rate and points the fix at the wrong branch.

``load_trials`` decides that population, and it decides it by reading only the
sponsor-authored drug names -- arm labels, intervention names, otherNames -- and not the
titles. These tests pin that choice against the two real trials it has to separate.

DB-free: the resolution step is covered by tests/test_defect_b_exact_ingredient_gate.py.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_alias_tier_refusals import load_trials

REPO_ROOT = Path(__file__).resolve().parents[1]
NCT_CACHE = REPO_ROOT / "data" / "nct_cache"

# The trial the tier was built for: MeSH says 'empagliflozin', every sponsor field
# says 'BI 10773'.
EMPA_REG_NCT = "NCT01131676"
# The trial that must NOT count as a refusal: both arms are indexed under their
# generic names, and the sponsor used those names too, so the seed resolves directly.
PLATO_NCT = "NCT00391872"


def _is_sponsor_silent(trial: dict) -> bool:
    return not any(term.lower() in trial["sponsor_names"] for term in trial["terms"])


def _by_nct(cache_dir: Path = NCT_CACHE) -> dict[str, dict]:
    return {t["nct"]: t for t in load_trials(cache_dir)}


def test_should_treat_empa_reg_as_sponsor_silent_when_every_arm_is_a_development_code():
    trial = _by_nct()[EMPA_REG_NCT]
    assert trial["terms"] == ["empagliflozin"]
    assert "empagliflozin" not in trial["sponsor_names"]
    assert _is_sponsor_silent(trial) is True


def test_should_not_treat_plato_as_sponsor_silent_when_the_arms_carry_the_generic_names():
    trial = _by_nct()[PLATO_NCT]
    assert trial["terms"] == ["Ticagrelor", "Clopidogrel"]
    assert _is_sponsor_silent(trial) is False


def test_should_read_other_names_as_sponsor_authored_text():
    # PLATO's interventions list 'AZD6140' and 'Plavix' as otherNames. A generic name
    # hiding there still means the sponsor wrote it, so otherNames must be included.
    trial = _by_nct()[PLATO_NCT]
    assert "azd6140" in trial["sponsor_names"]


def test_should_skip_a_trial_that_carries_no_mesh_terms(tmp_path):
    (tmp_path / "NCT00000001.json").write_text(json.dumps({
        "protocolSection": {"armsInterventionsModule": {
            "interventions": [{"name": "Some Drug"}]}},
        "derivedSection": {"interventionBrowseModule": {"meshes": []}},
    }))
    assert load_trials(tmp_path) == []


def test_should_ignore_titles_when_deciding_sponsor_silence(tmp_path):
    # A generic name in the official title does not stop the sponsor from naming every
    # arm after the development code, and the seed follows the arms. Counting the title
    # would drop this trial out of the population the tier exists to serve.
    (tmp_path / "NCT00000002.json").write_text(json.dumps({
        "protocolSection": {
            "identificationModule": {
                "briefTitle": "A Study of Empagliflozin",
                "officialTitle": "A Trial of Empagliflozin in Adults",
            },
            "armsInterventionsModule": {
                "armGroups": [{"label": "BI 10773 low dose", "type": "EXPERIMENTAL"}],
                "interventions": [{"type": "DRUG", "name": "BI 10773 low dose"}],
            },
        },
        "derivedSection": {"interventionBrowseModule": {"meshes": [{"term": "empagliflozin"}]}},
    }))
    trial = load_trials(tmp_path)[0]
    assert _is_sponsor_silent(trial) is True
