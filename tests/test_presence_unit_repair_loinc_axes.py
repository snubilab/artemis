"""The presence-unit repair and gate check (q) reading LOINC axes for unlisted members.

Rule and motivation: ``tests/test_presence_unit_loinc_axes.py``. This file gates the wiring:
the repair asks the vocabulary for the axes of the set's resolved closure, check (q) asks it
for the axes of the set's seeds, and both pass them to the one predicate
(:func:`src.utils.presence_unit_allowlist.unit_drop_verdict`), so the repair never drops a
unit the gate then reports. No database: ``lab_tests`` is a fake. Axes below were read from
``synthea23m`` via ``PostgresLabTestVocabulary.lab_tests`` on 2026-10-08.
"""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.services.conceptset_closure import PrefetchedVocabulary  # noqa: E402
from src.services.presence_unit_repair import repair_presence_unit_filters  # noqa: E402
from src.utils.circe_lint import (  # noqa: E402
    presence_unit_axes_ids,
    unitless_value_bound_criteria,
)
from src.utils.presence_unit_allowlist import lab_test_axes  # noqa: E402

PT = "Point in time (spot)"
EGFR = ("Glomerular filtration rate", "Volume Rate/Area", "Serum, Plasma or Blood", "Qn", PT)
LDL_MASS = ("Cholesterol in LDL", "Mass Concentration", "Serum or Plasma", "Qn", PT)
LDL_ARBITRARY = ("Cholesterol in LDL", "Arbitrary Concentration", "Serum or Plasma", "Qn", PT)
HDL_MASS = ("Cholesterol in HDL", "Mass Concentration", "Serum or Plasma", "Qn", PT)
HBA1C = ("Hemoglobin A1c/Hemoglobin.total", "Mass fraction", "Blood", "Qn", PT)
HBA1 = ("Hemoglobin A1/Hemoglobin.total", "Mass fraction", "Blood", "Qn", PT)
EGFR_LISTED = [3049187, 36303797, 40764999, 46236952]
EGFR_UNLISTED = [1619025, 3029859, 40771922]
#: CAROLINA codeset 24's Unit list on the dry rebuild.
EGFR_UNITS = [
    {"CONCEPT_ID": 720870, "CONCEPT_CODE": "mL/min/(173.10*-2.m2)"},
    {"CONCEPT_ID": 9117, "CONCEPT_CODE": "mL/min/1.73.m2"},
    {"CONCEPT_ID": 9062, "CONCEPT_CODE": "mL/min/{1.73}m"},
]
MG_DL = [{"CONCEPT_ID": 8840, "CONCEPT_CODE": "mg/dL"}]
PERCENT = [{"CONCEPT_ID": 8554, "CONCEPT_CODE": "%"}]

#: name -> (members, axes, bound, unit, the repair drops the unit?)
CASES = {
    "widened eGFR, every sibling on a listed member's axes": (
        EGFR_LISTED + EGFR_UNLISTED, {c: EGFR for c in EGFR_LISTED + EGFR_UNLISTED},
        {"Value": 30.0, "Op": "gte"}, EGFR_UNITS, True,
    ),
    "LDL by VAP (40758569) beside a listed LDL mass code": (
        [3028437, 40758569], {3028437: LDL_MASS, 40758569: LDL_MASS},
        {"Value": 135.0, "Op": "gte"}, MG_DL, True,
    ),
    "LDL on '[Units/volume]' (3035009), a scale no listed member reports": (
        [3028437, 3035009], {3028437: LDL_MASS, 3035009: LDL_ARBITRARY},
        {"Value": 135.0, "Op": "gte"}, MG_DL, False,
    ),
    "HDL (3007070) in an LDL set: same property, another component": (
        [3028437, 3007070], {3028437: LDL_MASS, 3007070: HDL_MASS},
        {"Value": 135.0, "Op": "gte"}, MG_DL, False,
    ),
    "HbA1 total (3005446) in a %-HbA1c set: same property, another component": (
        [3004410, 3007263, 3005446], {3004410: HBA1C, 3007263: HBA1C, 3005446: HBA1},
        {"Value": 6.5, "Op": "bt", "Extent": 8.5}, PERCENT, False,
    ),
}


def lab_tests_from(axes: dict, calls: list | None = None):
    """A fake ``PostgresLabTestVocabulary.lab_tests``: LabTest-shaped rows, LOINC ids only."""
    def lookup(concept_ids):
        ids = sorted(set(concept_ids))
        if calls is not None:
            calls.append(ids)
        return {
            cid: SimpleNamespace(
                component=a[0], property=a[1], system=a[2], scale=a[3], time_aspect=a[4]
            )
            for cid in ids if (a := axes.get(cid)) is not None
        }
    return lookup


def presence_cohort(members: list[int], value: dict, unit: list | None) -> dict:
    measurement = {"CodesetId": 24, "ValueAsNumber": dict(value)}
    if unit is not None:
        measurement["Unit"] = deepcopy(unit)
    return {
        "ConceptSets": [
            {
                "id": 24,
                "name": "analyte",
                "expression": {"items": [
                    {"concept": {"CONCEPT_ID": cid}, "includeDescendants": True,
                     "includeMapped": False, "isExcluded": False}
                    for cid in members
                ]},
            }
        ],
        "PrimaryCriteria": {"CriteriaList": []},
        "InclusionRules": [{
            "name": "rule",
            "expression": {"Type": "ALL", "Groups": [], "CriteriaList": [{
                "Criteria": {"Measurement": measurement},
                "Occurrence": {"Type": 2, "Count": 1},
            }]},
        }],
    }


def vocabulary(ids: list[int]) -> PrefetchedVocabulary:
    return PrefetchedVocabulary(
        concept_invalid_reason={cid: None for cid in ids},
        ancestor_edges={cid: {cid} for cid in ids},
    )


def unit_of(expression: dict):
    return expression["InclusionRules"][0]["expression"]["CriteriaList"][0]["Criteria"][
        "Measurement"].get("Unit")


# ---------------------------------------------------------------------------
# the repair
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", CASES)
def test_should_drop_the_unit_only_when_every_unlisted_member_has_a_listed_members_axes(case):
    members, axes, bound, unit, drops = CASES[case]
    expression = presence_cohort(members, bound, unit)
    before = deepcopy(expression)

    applied = repair_presence_unit_filters(
        expression, vocabulary(members), lab_tests=lab_tests_from(axes)
    )

    if drops:
        assert len(applied) == 1 and unit_of(expression) is None
    else:
        assert applied == [] and expression == before


def test_should_keep_the_unit_on_the_widened_set_when_the_vocabulary_has_no_axes_for_it():
    members = EGFR_LISTED + EGFR_UNLISTED
    expression = presence_cohort(members, {"Value": 30.0, "Op": "gte"}, EGFR_UNITS)

    assert repair_presence_unit_filters(
        expression, vocabulary(members), lab_tests=lab_tests_from({})
    ) == []
    assert unit_of(expression) == EGFR_UNITS


def test_should_not_ask_the_vocabulary_when_every_member_is_listed():
    members = EGFR_LISTED
    expression = presence_cohort(members, {"Value": 30.0, "Op": "gte"}, EGFR_UNITS)

    def refuse(_ids):
        raise AssertionError("lab_tests must not be read for a fully listed set")

    assert len(repair_presence_unit_filters(expression, vocabulary(members), lab_tests=refuse)) == 1


# ---------------------------------------------------------------------------
# check (q) -- the same answer as the repair
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", CASES)
def test_should_let_check_q_exempt_exactly_what_the_repair_drops_when_given_the_same_axes(case):
    members, axes, bound, unit, drops = CASES[case]
    repaired = presence_cohort(members, bound, unit)
    applied = repair_presence_unit_filters(
        repaired, vocabulary(members), lab_tests=lab_tests_from(axes)
    )
    unitless = presence_cohort(members, bound, None)
    member_axes = lab_test_axes(lab_tests_from(axes)(presence_unit_axes_ids(unitless)))

    findings = unitless_value_bound_criteria(unitless, member_axes=member_axes)

    assert bool(applied) is drops
    assert (findings == []) is drops, findings


def test_should_flag_the_unitless_widened_set_when_no_axes_are_supplied():
    """The DB-free lint is unchanged: without axes an unlisted member is unverifiable."""
    members = EGFR_LISTED + EGFR_UNLISTED
    findings = unitless_value_bound_criteria(
        presence_cohort(members, {"Value": 30.0, "Op": "gte"}, None)
    )

    assert len(findings) == 1 and "with no Unit" in findings[0]


def test_should_ask_for_axes_only_for_the_seeds_of_an_unlisted_unitless_presence():
    widened = presence_cohort(EGFR_LISTED + EGFR_UNLISTED, {"Value": 30.0, "Op": "gte"}, None)
    listed = presence_cohort(EGFR_LISTED, {"Value": 30.0, "Op": "gte"}, None)
    with_unit = presence_cohort(
        EGFR_LISTED + EGFR_UNLISTED, {"Value": 30.0, "Op": "gte"}, EGFR_UNITS
    )

    assert presence_unit_axes_ids(widened) == set(EGFR_LISTED + EGFR_UNLISTED)
    assert presence_unit_axes_ids(listed) == set()
    assert presence_unit_axes_ids(with_unit) == set()


# ---------------------------------------------------------------------------
# the delivery gate supplies the axes from its lab-test vocabulary
# ---------------------------------------------------------------------------

def _run_gate(monkeypatch, tmp_path, cohort: dict, axes: dict) -> None:
    monkeypatch.delenv("TTE_STORE_PATH", raising=False)
    import scripts.verify_circe_delivery as gate

    lab_tests = lab_tests_from(axes)

    class _Vocab:
        def lab_tests(self, ids):
            return lab_tests(ids)

        def analyte_lab_tests(self, _analyte):
            return []

        def properties(self, _ids):
            return {}

        def close(self):
            pass

    monkeypatch.setattr(gate, "_open_lab_test_vocabulary", lambda *a: _Vocab())
    study = {
        "id": 10,
        "name": "Study 10",
        "comparisonMode": "target_minus_treatment",
        "treatmentArms": [{"name": "linagliptin"}, {"name": "glimepiride"}],
        "eligibility": {"structuredExpression": json.loads(json.dumps(cohort))},
    }
    for role in ("treatment", "comparator"):
        (tmp_path / f"carolina_{role}.circe.json").write_text(json.dumps(cohort))
    store = tmp_path / "studies.json"
    store.write_text(json.dumps([study]))
    gate.main(["--dir", str(tmp_path), "--store", str(store), "--map", "carolina=10"])


@pytest.mark.parametrize("case", CASES)
def test_should_let_the_gate_decide_check_q_as_the_repair_does(monkeypatch, tmp_path, capsys, case):
    members, axes, bound, _unit, drops = CASES[case]

    _run_gate(monkeypatch, tmp_path, presence_cohort(members, bound, None), axes)
    out = capsys.readouterr().out

    assert ("unitless value bound" not in out) is drops, out


# ---------------------------------------------------------------------------
# the service passes its own lab-test vocabulary
# ---------------------------------------------------------------------------

def _service_with(monkeypatch, members: list[int], opened: list):
    from unittest.mock import MagicMock

    import src.services.conceptset_closure as closure
    from src.services.tte_service import TTEService

    class _Vocab:
        def __init__(self, *_a):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

        def prefetch(self, _items):
            return vocabulary(members)

    monkeypatch.setattr(closure, "PostgresVocabulary", _Vocab)
    service = TTEService(store=MagicMock())
    calls: list = []

    class _LabTests:
        def lab_tests(self, ids):
            return lab_tests_from({c: EGFR for c in members}, calls)(ids)

        def close(self):
            opened.append("closed")

    def open_lab_tests():
        opened.append("opened")
        return _LabTests()

    service._lab_test_vocabulary = open_lab_tests
    return service, calls


def test_should_read_axes_through_the_service_lab_test_vocabulary(monkeypatch):
    members = EGFR_LISTED + EGFR_UNLISTED
    opened: list = []
    service, calls = _service_with(monkeypatch, members, opened)
    base = presence_cohort(members, {"Value": 30.0, "Op": "gte"}, EGFR_UNITS)

    service._repair_presence_unit_filters(base)

    assert unit_of(base) is None
    assert calls == [sorted(members)]
    assert opened == ["opened", "closed"]


def test_should_not_open_the_lab_test_vocabulary_for_a_fully_listed_set(monkeypatch):
    opened: list = []
    service, _calls = _service_with(monkeypatch, EGFR_LISTED, opened)
    base = presence_cohort(EGFR_LISTED, {"Value": 30.0, "Op": "gte"}, EGFR_UNITS)

    service._repair_presence_unit_filters(base)

    assert unit_of(base) is None
    assert opened == []
