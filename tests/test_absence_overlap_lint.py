"""Check (x): a mandatory absence whose effective closure meets the entry or a presence.

Measured on the 2026-10-08 dry rebuild. Agent 2 re-rolled 'Type 1 diabetes mellitus'
in CARMELINA and CAROLINA to nine concepts, among them 201826 and 44793113 (T2DM).
In CAROLINA the T2DM presence sits in an ANY group (#5 'Type 2 Diabetes Mellitus
Diagnosis + Insufficient Glycaemic Control + High Cardiovascular Risk'), so check (t)
-- which reads mandatory presences only -- stayed silent, while #3 forbids every
concept that alternative accepts.

Severity was set from the four corpora (09-12, 09-23, the dry rebuild, the 18 gold
files): FAIL is the target's WHOLE closure forbidden inside a window that sees every
event the target counts; a PARTIAL overlap on a mandatory target is WARN; a partial
overlap under ANY is silent. Legitimate shapes the corpora carry and these tests pin:
a washout whose window ends before index, a history window lying before a recent-event
absence ("MI > 60 days ago" vs "no ACS in 60 days"), and an exception the absence set
already implements.

DB-free: ``PrefetchedVocabulary`` over hand-built ancestor edges.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.services.conceptset_closure import PrefetchedVocabulary
from src.utils.circe_lint import (
    absence_overlap_codesets,
    absence_overlap_findings,
    closure_subsumed_presence_criteria,
    contradictory_absence_rules,
)

REPO = Path(__file__).resolve().parents[1]

DM, T1DM, T2DM, MULTI, T2DM_LEAF, CVD, DRUG, CLASS, OTHER = (
    201820, 201254, 201826, 44793113, 4000001, 4185932, 1580747, 21600744, 23986,
)

VOCAB = PrefetchedVocabulary(
    concept_invalid_reason={c: None for c in (DM, T1DM, T2DM, MULTI, T2DM_LEAF, CVD, DRUG,
                                              CLASS, OTHER)},
    ancestor_edges={
        DM: {DM, T1DM, T2DM, MULTI, T2DM_LEAF},
        T1DM: {T1DM},
        T2DM: {T2DM, T2DM_LEAF},
        MULTI: {MULTI},
        CVD: {CVD},
        DRUG: {DRUG},
        CLASS: {CLASS, DRUG},
        OTHER: {OTHER},
    },
)


def _item(cid: int, *, excluded: bool = False) -> dict[str, Any]:
    return {"concept": {"CONCEPT_ID": cid, "CONCEPT_NAME": f"c{cid}"},
            "isExcluded": excluded, "includeDescendants": True, "includeMapped": False}


def _set(set_id: int, name: str, *items: dict) -> dict[str, Any]:
    return {"id": set_id, "name": name, "expression": {"items": list(items)}}


def _entry(codeset: int, occurrence: tuple[int, int], window=(-9999, 0),
           criteria_type: str = "ConditionOccurrence", **attrs) -> dict[str, Any]:
    start, end = window
    return {
        "Criteria": {criteria_type: {"CodesetId": codeset, **attrs}},
        "StartWindow": {"Start": {"Days": abs(start), "Coeff": -1 if start < 0 else 1},
                        "End": {"Days": abs(end), "Coeff": -1 if end < 0 else 1}},
        "RestrictVisit": False,
        "IgnoreObservationPeriod": False,
        "Occurrence": {"Type": occurrence[0], "Count": occurrence[1]},
    }


PRESENT, ABSENT = (2, 1), (0, 0)


def _group(kind: str, *entries: dict, groups: list | None = None) -> dict[str, Any]:
    return {"Type": kind, "CriteriaList": list(entries), "DemographicCriteriaList": [],
            "Groups": groups or []}


def _rule(name: str, expression: dict) -> dict[str, Any]:
    return {"name": name, "expression": expression}


def _carolina(*, absence_items=None, absence=None, t2dm_window=(-9999, 0),
              any_kind: str = "ANY") -> dict[str, Any]:
    """The dry-rebuild CAROLINA shape: drug entry, T2DM as one alternative under ANY,
    and a 'Type 1 diabetes mellitus' absence that re-rolled onto the T2DM concepts."""
    absence_items = absence_items if absence_items is not None else [
        _item(T1DM), _item(T2DM), _item(MULTI)]
    return {
        "ConceptSets": [
            _set(1, "linagliptin", _item(DRUG)),
            _set(2, "Type 2 Diabetes Mellitus", _item(T2DM), _item(MULTI)),
            _set(4, "High risk of CV events", _item(CVD)),
            _set(32, "Type 1 diabetes mellitus", *absence_items),
        ],
        "PrimaryCriteria": {"CriteriaList": [{"DrugEra": {"CodesetId": 1}}]},
        "InclusionRules": [
            _rule("Type 1 diabetes mellitus",
                  _group("ALL", absence or _entry(32, ABSENT))),
            _rule("Type 2 Diabetes Mellitus Diagnosis + High Cardiovascular Risk",
                  _group(any_kind, groups=[
                      _group("ALL", _entry(2, PRESENT, window=t2dm_window)),
                      _group("ALL", _entry(4, PRESENT)),
                  ])),
        ],
    }


def _mandatory_t2dm(*, absence_items, rule_name="Endocrine disorder") -> dict[str, Any]:
    """The EMPA-REG treatment shape: drug entry, T2DM required on the ALL path."""
    return {
        "ConceptSets": [
            _set(1, "empagliflozin", _item(DRUG)),
            _set(2, "Type 2 Diabetes Mellitus", _item(T2DM), _item(MULTI)),
            _set(29, rule_name, *absence_items),
        ],
        "PrimaryCriteria": {"CriteriaList": [{"DrugEra": {"CodesetId": 1}}]},
        "InclusionRules": [
            _rule("Type 2 Diabetes Mellitus", _group("ALL", _entry(2, PRESENT))),
            _rule(rule_name, _group("ALL", groups=[_group("ALL", _entry(29, ABSENT))])),
        ],
    }


def _condition_entry(*, absence_items, window=(-9999, 0)) -> dict[str, Any]:
    """The EMPA-REG comparator shape: the cohort ENTERS on T2DM."""
    return {
        "ConceptSets": [
            _set(2, "Type 2 Diabetes Mellitus", _item(T2DM), _item(MULTI)),
            _set(29, "Endocrine disorder", *absence_items),
        ],
        "PrimaryCriteria": {"CriteriaList": [{"ConditionOccurrence": {"CodesetId": 2}}]},
        "InclusionRules": [
            _rule("Endocrine disorder", _group("ALL", _entry(29, ABSENT, window=window))),
        ],
    }


def _drug_entry(*, window) -> dict[str, Any]:
    return {
        "ConceptSets": [
            _set(1, "linagliptin", _item(DRUG)),
            _set(5, "DPP-4 inhibitors", _item(CLASS)),
        ],
        "PrimaryCriteria": {"CriteriaList": [{"DrugEra": {"CodesetId": 1}}]},
        "InclusionRules": [
            _rule("DPP-4 inhibitors if recent",
                  _group("ALL", _entry(5, ABSENT, window=window, criteria_type="DrugExposure"))),
        ],
    }


def _run(cohort: dict[str, Any]) -> tuple[list[str], list[str]]:
    return absence_overlap_findings(cohort, VOCAB)


# --------------------------------------------------------------------------
# FAIL
# --------------------------------------------------------------------------

class TestFail:
    def test_should_fail_when_the_absence_forbids_a_whole_alternative_under_any(self):
        fail, warn = _run(_carolina())

        assert len(fail) == 1, fail
        assert "#1 'Type 1 diabetes mellitus'" in fail[0]
        assert "#2 'Type 2 Diabetes Mellitus Diagnosis" in fail[0]
        assert "under ANY" in fail[0]
        assert warn == []

    def test_should_fail_under_an_at_least_group_too(self):
        fail, _warn = _run(_carolina(any_kind="AT_LEAST"))

        assert len(fail) == 1, fail

    def test_should_fail_when_the_absence_covers_the_entry_and_its_window_holds_index(self):
        fail, _warn = _run(_condition_entry(absence_items=[_item(DM), _item(OTHER)]))

        assert len(fail) == 1, fail
        assert "entry" in fail[0]

    def test_should_fail_a_drug_exposure_absence_covering_a_drug_era_entry_at_index(self):
        """An era is built from exposures: one table family. CIRCE counts the index
        exposure itself, so a window ending ON index removes every entered patient."""
        fail, _warn = _run(_drug_entry(window=(-7, 0)))

        assert len(fail) == 1, fail


# --------------------------------------------------------------------------
# legitimate shapes -- must not FAIL
# --------------------------------------------------------------------------

class TestLegitimateShapes:
    def test_should_not_report_a_drug_washout_whose_window_ends_before_index(self):
        assert _run(_drug_entry(window=(-7, -1))) == ([], [])

    def test_should_not_report_a_presence_window_lying_before_the_absence_window(self):
        """'History of the event > 60 days ago' beside 'no such event in 60 days'."""
        cohort = _carolina(absence=_entry(32, ABSENT, window=(-60, 0)),
                           t2dm_window=(-9999, -61))

        assert _run(cohort) == ([], [])

    def test_should_not_report_an_absence_whose_stated_exception_is_implemented(self):
        cohort = _mandatory_t2dm(
            rule_name="Endocrine disorder (excluding T2DM)",
            absence_items=[_item(DM), _item(OTHER), _item(T2DM, excluded=True),
                           _item(MULTI, excluded=True)],
        )

        assert _run(cohort) == ([], [])


# --------------------------------------------------------------------------
# WARN and silence
# --------------------------------------------------------------------------

class TestWarnAndSilence:
    def test_should_warn_when_part_of_a_mandatory_presence_is_forbidden(self):
        """'Has T2DM but not this complication of it': a descendant forbidden, none of the
        concepts the presence names. The dry-rebuild EMPA-REG residual (201826 excepted,
        44793113 still forbidden) used to sit here; forbidding a concept the presence
        names is check (y)'s FAIL now -- see test_circe_lint_explicit_presence_forbidden."""
        cohort = _mandatory_t2dm(rule_name="T2DM complication", absence_items=[_item(T2DM_LEAF)])

        fail, warn = _run(cohort)

        assert fail == []
        assert len(warn) == 1 and "1 of the 3" in warn[0], warn

    def test_should_stay_silent_on_a_partial_overlap_under_any(self):
        assert _run(_carolina(absence_items=[_item(T1DM), _item(MULTI)])) == ([], [])

    def test_should_stay_silent_when_the_absence_sits_under_any(self):
        cohort = _carolina()
        cohort["InclusionRules"][0]["expression"]["Type"] = "ANY"

        assert _run(cohort) == ([], [])

    def test_should_stay_silent_when_the_absence_is_narrowed(self):
        cohort = _carolina(absence=_entry(32, ABSENT, ConditionType=[{"CONCEPT_ID": 32020}]))

        assert _run(cohort) == ([], [])

    def test_should_stay_silent_across_table_families(self):
        cohort = _carolina(absence=_entry(32, ABSENT, criteria_type="Observation"))

        assert _run(cohort) == ([], [])

    def test_should_ignore_a_presence_under_an_at_most_group(self):
        """Forbidding an 'at most' alternative makes the rule easier to meet, not harder."""
        assert _run(_carolina(any_kind="AT_MOST")) == ([], [])


# --------------------------------------------------------------------------
# one defect, one report
# --------------------------------------------------------------------------

class TestNoDoubleReport:
    def test_should_leave_a_mandatory_presence_to_check_t(self):
        cohort = _mandatory_t2dm(absence_items=[_item(DM), _item(OTHER)])

        assert len(closure_subsumed_presence_criteria(cohort, VOCAB)) == 1
        assert _run(cohort) == ([], [])

    def test_should_leave_a_literally_listed_entry_concept_to_check_f(self):
        cohort = _condition_entry(absence_items=[_item(T2DM), _item(MULTI), _item(OTHER)])

        assert contradictory_absence_rules(cohort) == ["Endocrine disorder"]
        assert _run(cohort)[0] == []


# --------------------------------------------------------------------------
# the vocabulary pre-gate
# --------------------------------------------------------------------------

class TestPreGate:
    def test_should_name_every_codeset_a_pair_needs(self):
        """The DrugEra entry reads another table family than the Condition absence, so
        codeset 1 needs no closure; both alternatives under ANY do."""
        assert absence_overlap_codesets(_carolina()) == {2, 4, 32}

    def test_should_need_no_vocabulary_when_no_absence_is_mandatory(self):
        cohort = _carolina()
        cohort["InclusionRules"][0]["expression"]["Type"] = "ANY"

        assert absence_overlap_codesets(cohort) == set()


# --------------------------------------------------------------------------
# the delivery gate runs it
# --------------------------------------------------------------------------

class TestTheDeliveryGateRunsTheCheck:
    """A lint nobody calls is indistinguishable from one that returns nothing."""

    class _FakeVocabulary:
        opened = 0

        def __init__(self, *_args):
            type(self).opened += 1

        def prefetch(self, _items):
            return VOCAB

        def close(self):
            pass

    @staticmethod
    def _deliver(tmp_path, cohort) -> Path:
        study = {
            "id": 10, "name": "Study 10", "comparisonMode": "target_minus_treatment",
            "treatmentArms": [{"name": "linagliptin"}, {"name": "Placebo"}],
            "eligibility": {"structuredExpression": json.loads(json.dumps(cohort))},
        }
        for role in ("treatment", "comparator"):
            (tmp_path / f"carolina_{role}.circe.json").write_text(json.dumps(cohort))
        store = tmp_path / "studies.json"
        store.write_text(json.dumps([study]))
        return store

    def _run_gate(self, monkeypatch, tmp_path, capsys, cohort, opener=None):
        monkeypatch.delenv("TTE_STORE_PATH", raising=False)
        import scripts.verify_circe_delivery as gate

        self._FakeVocabulary.opened = 0
        monkeypatch.setattr(gate, "_open_vocabulary", opener or self._FakeVocabulary)
        store = self._deliver(tmp_path, cohort)
        rc = gate.main(["--dir", str(tmp_path), "--store", str(store), "--map", "carolina=10"])
        captured = capsys.readouterr()
        return rc, captured.out, captured.err

    def test_should_fail_the_delivery_when_an_absence_forbids_a_whole_alternative(
        self, monkeypatch, tmp_path, capsys
    ):
        rc, out, _err = self._run_gate(monkeypatch, tmp_path, capsys, _carolina())

        assert rc == 1, out
        assert "absence forbids a whole target (1)" in out, out

    def test_should_pass_the_delivery_and_report_a_partial_cut_as_warn(
        self, monkeypatch, tmp_path, capsys
    ):
        cohort = _mandatory_t2dm(rule_name="T2DM complication", absence_items=[_item(T2DM_LEAF)])

        rc, out, _err = self._run_gate(monkeypatch, tmp_path, capsys, cohort)

        assert "absence partly forbids a mandatory target (WARN, 1)" in out, out
        assert rc == 0, out

    def test_should_not_open_the_vocabulary_when_no_absence_is_mandatory(
        self, monkeypatch, tmp_path, capsys
    ):
        cohort = _carolina()
        cohort["InclusionRules"][0]["expression"]["Type"] = "ANY"

        self._run_gate(monkeypatch, tmp_path, capsys, cohort)

        assert self._FakeVocabulary.opened == 0

    def test_should_abort_when_the_vocabulary_is_unreachable(
        self, monkeypatch, tmp_path, capsys
    ):
        def _unreachable(*_args):
            raise OSError("connection refused")

        rc, _out, err = self._run_gate(monkeypatch, tmp_path, capsys, _carolina(),
                                       opener=_unreachable)

        assert rc == 2
        assert "vocabulary unreachable" in err and "(x)" in err


# --------------------------------------------------------------------------
# the measured files, through the real vocabulary
# --------------------------------------------------------------------------

DRYRUN = REPO / "output" / "site_gap" / "2026-10-08_dryrun" / "DELIVERY"
GOLD = sorted((REPO / "data" / "gold").glob("*/*.json"))


def _real(cohort: dict[str, Any]) -> tuple[list[str], list[str]]:
    from scripts.verify_circe_delivery import _open_vocabulary, _overlap_lookup
    from scripts.verify_entry_exclusion_conflict import DEFAULT_DSN
    from src.services.conceptset_closure import DEFAULT_VOCAB_SCHEMA

    with _open_vocabulary(DEFAULT_DSN, DEFAULT_VOCAB_SCHEMA) as vocab:
        return absence_overlap_findings(cohort, _overlap_lookup(cohort, vocab))


@pytest.mark.integration
@pytest.mark.skipif(not DRYRUN.is_dir(), reason=f"dry rebuild not present: {DRYRUN}")
@pytest.mark.parametrize("role", ["treatment", "comparator"])
def test_should_fail_the_dry_rebuild_carolina_t1dm_rule(role):
    fail, _warn = _real(json.loads((DRYRUN / f"carolina_{role}.circe.json").read_text()))

    assert len(fail) == 2, fail
    assert all("#3 'Type 1 diabetes mellitus'" in f for f in fail), fail


@pytest.mark.integration
@pytest.mark.skipif(len(GOLD) != 18, reason="the 18 TROY v1.1 gold files are not present")
def test_should_not_fail_any_gold_file():
    failing = {path.name: fail for path in GOLD
               if (fail := _real(json.loads(path.read_text()))[0])}

    assert failing == {}
