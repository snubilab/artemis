"""A mandatory presence whose whole closure a mandatory absence forbids.

``deliveries/2026-09-23/empa-reg_treatment.circe.json`` returns 0 people on any CDM:

    #2  'Type 2 Diabetes Mellitus'            >=1 ConditionOccurrence cs2  [-9999, 0]
        cs2 = 201826, 44793113 (both includeDescendants)
    #15 'Endocrine disorder (excluding T2DM)' ==0 ConditionOccurrence cs29 [-9999, 0]
        cs29 = 23 members incl. 201820 'Diabetes mellitus' (includeDescendants), 0 excluded

201826 and 44793113 sit under 201820, so every patient #2 admits #15 removes.
``unsatisfiable_presence_rules`` reported 0: it pairs criteria on identical member
lists, and cs2 and cs29 share no literal member -- the subsumption arrives only through
``concept_ancestor``. The comparator file carries the same two rules with 201826 and
44793113 as ``isExcluded`` in cs29, which is the negative control.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.services.conceptset_closure import PrefetchedVocabulary
from src.utils.circe_lint import (
    closure_subsumed_presence_criteria,
    closure_subsumption_codesets,
)

REPO = Path(__file__).resolve().parents[1]
DELIVERY = REPO / "deliveries" / "2026-09-23"

DM, T2DM, MULTI, T2DM_LEAF, PITUITARY = 201820, 201826, 44793113, 4000001, 23986

# concept_ancestor carries a level-0 self row for every concept, as the real table does.
VOCAB = PrefetchedVocabulary(
    concept_invalid_reason={c: None for c in (DM, T2DM, MULTI, T2DM_LEAF, PITUITARY)},
    ancestor_edges={
        DM: {DM, T2DM, MULTI, T2DM_LEAF},
        T2DM: {T2DM, T2DM_LEAF},
        MULTI: {MULTI},
        PITUITARY: {PITUITARY},
    },
)


def _item(cid: int, *, excluded: bool = False) -> dict[str, Any]:
    return {
        "concept": {"CONCEPT_ID": cid, "CONCEPT_NAME": f"c{cid}", "DOMAIN_ID": "Condition",
                    "VOCABULARY_ID": "SNOMED", "CONCEPT_CLASS_ID": "Clinical Finding",
                    "CONCEPT_CODE": str(cid), "STANDARD_CONCEPT": "S"},
        "isExcluded": excluded, "includeDescendants": True, "includeMapped": False,
    }


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


def _cohort(*, absence_items=None, presence_entry=None, absence_entry=None,
            absence_group: str = "ALL") -> dict[str, Any]:
    """The EMPA-REG treatment shape: DrugEra entry, T2DM required, endocrine forbidden."""
    absence_items = absence_items if absence_items is not None else [_item(DM), _item(PITUITARY)]
    return {
        "ConceptSets": [
            {"id": 1, "name": "empagliflozin", "expression": {"items": [{
                "concept": {"CONCEPT_ID": 45774751, "CONCEPT_NAME": "empagliflozin",
                            "DOMAIN_ID": "Drug", "VOCABULARY_ID": "RxNorm",
                            "CONCEPT_CLASS_ID": "Ingredient", "CONCEPT_CODE": "1"},
                "isExcluded": False, "includeDescendants": True}]}},
            {"id": 2, "name": "Type 2 diabetes mellitus",
             "expression": {"items": [_item(T2DM), _item(MULTI)]}},
            {"id": 29, "name": "Endocrine disorder", "expression": {"items": absence_items}},
        ],
        "PrimaryCriteria": {"CriteriaList": [{"DrugEra": {"CodesetId": 1}}]},
        "InclusionRules": [
            {"name": "Type 2 Diabetes Mellitus", "expression": {
                "Type": "ALL", "CriteriaList": [presence_entry or _entry(2, PRESENT)],
                "DemographicCriteriaList": [], "Groups": []}},
            {"name": "Endocrine disorder (excluding T2DM)", "expression": {
                "Type": "ALL", "CriteriaList": [], "DemographicCriteriaList": [],
                "Groups": [{"Type": absence_group,
                            "CriteriaList": [absence_entry or _entry(29, ABSENT)],
                            "DemographicCriteriaList": [], "Groups": []}]}},
        ],
    }


class TestTheTreatmentShapeIsCaught:
    def test_should_flag_the_pair_when_the_presence_closure_lies_inside_the_absence(self):
        findings = closure_subsumed_presence_criteria(_cohort(), VOCAB)
        assert len(findings) == 1, findings
        assert "InclusionRules[0] #1 'Type 2 Diabetes Mellitus'" in findings[0]
        assert "InclusionRules[1] #2 'Endocrine disorder (excluding T2DM)'" in findings[0]

    def test_should_flag_it_when_the_presence_window_lies_strictly_inside(self):
        cohort = _cohort(presence_entry=_entry(2, PRESENT, window=(-365, -30)))
        assert len(closure_subsumed_presence_criteria(cohort, VOCAB)) == 1

    def test_should_name_both_codesets_for_the_vocabulary_when_a_pair_is_possible(self):
        assert closure_subsumption_codesets(_cohort()) == {2, 29}


class TestTheSatisfiableShapesStaySilent:
    def test_should_stay_silent_when_the_absence_excludes_the_presence_concepts(self):
        """The comparator file: the entry-exclusion repair mirrored cs2 into cs29."""
        cohort = _cohort(absence_items=[_item(DM), _item(PITUITARY),
                                        _item(T2DM, excluded=True), _item(MULTI, excluded=True)])
        assert closure_subsumed_presence_criteria(cohort, VOCAB) == []

    def test_should_stay_silent_when_only_part_of_the_presence_closure_is_forbidden(self):
        """Excluding 201826 alone leaves 44793113 forbidden -- a population cut, not empty."""
        cohort = _cohort(absence_items=[_item(DM), _item(T2DM, excluded=True)])
        assert closure_subsumed_presence_criteria(cohort, VOCAB) == []

    def test_should_stay_silent_when_the_absence_sits_under_any(self):
        assert closure_subsumed_presence_criteria(_cohort(absence_group="ANY"), VOCAB) == []

    def test_should_stay_silent_when_the_presence_window_reaches_outside_the_absence(self):
        cohort = _cohort(absence_entry=_entry(29, ABSENT, window=(-365, -1)))
        assert closure_subsumed_presence_criteria(cohort, VOCAB) == []

    def test_should_stay_silent_when_the_two_read_different_tables(self):
        cohort = _cohort(absence_entry=_entry(29, ABSENT, criteria_type="ConditionEra"))
        assert closure_subsumed_presence_criteria(cohort, VOCAB) == []

    def test_should_stay_silent_when_the_absence_is_narrowed(self):
        cohort = _cohort(absence_entry=_entry(29, ABSENT, First=True))
        assert closure_subsumed_presence_criteria(cohort, VOCAB) == []

    def test_should_leave_an_identical_codeset_to_the_existing_check_when_both_read_one(self):
        """`contradictory_presence_absence_criteria` already reports this one."""
        cohort = _cohort(absence_entry=_entry(2, ABSENT))
        assert closure_subsumed_presence_criteria(cohort, VOCAB) == []

    def test_should_need_no_vocabulary_when_no_pair_is_possible(self):
        assert closure_subsumption_codesets(_cohort(absence_group="ANY")) == set()


@pytest.mark.integration
@pytest.mark.skipif(not DELIVERY.is_dir(), reason=f"delivery not present: {DELIVERY}")
class TestTheRealDelivery:
    @staticmethod
    def _findings(name: str) -> list[str]:
        from scripts.verify_circe_delivery import _open_vocabulary, _subsumption_lookup
        from scripts.verify_entry_exclusion_conflict import DEFAULT_DSN
        from src.services.conceptset_closure import DEFAULT_VOCAB_SCHEMA

        cohort = json.loads((DELIVERY / name).read_text())
        with _open_vocabulary(DEFAULT_DSN, DEFAULT_VOCAB_SCHEMA) as vocab:
            return closure_subsumed_presence_criteria(cohort, _subsumption_lookup(cohort, vocab))

    def test_should_fail_the_treatment_file_naming_rules_2_and_15(self):
        findings = self._findings("empa-reg_treatment.circe.json")
        assert any(
            "#2 'Type 2 Diabetes Mellitus'" in f
            and "#15 'Endocrine disorder (excluding T2DM)'" in f
            for f in findings
        ), findings

    def test_should_not_flag_that_pair_in_the_comparator_file(self):
        findings = self._findings("empa-reg_comparator.circe.json")
        assert not any("#2 'Type 2" in f and "#15 'Endocrine" in f for f in findings), findings


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
            "id": 8, "name": "Study 8", "comparisonMode": "target_minus_treatment",
            "treatmentArms": [{"name": "BI 10773"}, {"name": "Placebo"}],
            "eligibility": {"structuredExpression": json.loads(json.dumps(cohort))},
        }
        for role in ("treatment", "comparator"):
            (tmp_path / f"empa-reg_{role}.circe.json").write_text(json.dumps(cohort))
        store = tmp_path / "studies.json"
        store.write_text(json.dumps([study]))
        return store

    def _run(self, monkeypatch, tmp_path, capsys, cohort, opener=None):
        monkeypatch.delenv("TTE_STORE_PATH", raising=False)
        import scripts.verify_circe_delivery as gate

        self._FakeVocabulary.opened = 0
        monkeypatch.setattr(gate, "_open_vocabulary", opener or self._FakeVocabulary)
        store = self._deliver(tmp_path, cohort)
        rc = gate.main(["--dir", str(tmp_path), "--store", str(store), "--map", "empa-reg=8"])
        captured = capsys.readouterr()
        return rc, captured.out, captured.err

    def test_should_fail_the_delivery_when_a_presence_lies_inside_an_absence(
        self, monkeypatch, tmp_path, capsys
    ):
        rc, out, _err = self._run(monkeypatch, tmp_path, capsys, _cohort())
        assert rc == 1, out
        assert "closure-subsumed presence (1)" in out, out

    def test_should_pass_the_comparator_shape_when_the_absence_excludes_it(
        self, monkeypatch, tmp_path, capsys
    ):
        cohort = _cohort(absence_items=[_item(DM), _item(PITUITARY),
                                        _item(T2DM, excluded=True), _item(MULTI, excluded=True)])
        rc, out, _err = self._run(monkeypatch, tmp_path, capsys, cohort)
        assert "closure-subsumed" not in out, out
        assert rc == 0, out

    def test_should_not_open_the_vocabulary_when_no_pair_is_possible(
        self, monkeypatch, tmp_path, capsys
    ):
        self._run(monkeypatch, tmp_path, capsys, _cohort(absence_group="ANY"))
        assert self._FakeVocabulary.opened == 0

    def test_should_abort_when_a_pair_needs_the_vocabulary_and_it_is_unreachable(
        self, monkeypatch, tmp_path, capsys
    ):
        def _unreachable(*_args):
            raise OSError("connection refused")

        rc, _out, err = self._run(monkeypatch, tmp_path, capsys, _cohort(), opener=_unreachable)
        assert rc == 2
        assert "vocabulary unreachable" in err
