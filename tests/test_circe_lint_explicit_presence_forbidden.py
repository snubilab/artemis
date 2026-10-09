"""Check (y): a mandatory absence forbids a concept a mandatory presence names explicitly.

The case the gate missed, 2026-10-09 arm A (no UMLS), CARMELINA treatment::

    #1 'Type 2 Diabetes Mellitus'  >=1 ConditionOccurrence cs2  {201826, 44793113}
    #3 'Type 1 diabetes mellitus'  ==0 ConditionOccurrence cs10 {..., 44793113, ...}

A patient whose T2DM is recorded as 44793113 'Diabetes mellitus with multiple
complications' satisfies #1 and is removed by #3. Check (t) needs the WHOLE presence
closure inside the absence (3 of 16 concepts are); check (x) only WARNs a partial cut on a
mandatory target; the entry-exclusion check reads the entry, here a drug.

What is compared was decided by measurement across 09-12, 09-23, the 10-08 dry rebuild,
both 10-09 arms, and the 18 gold files:

* closure against closure would report the gold's own "T2DM but not hyperglycaemia /
  metabolic acidosis / ESRD" pairs (2-8 shared descendants each, 8 files) -- the
  legitimate "has X but not complication Y" shape;
* explicit against explicit misses the 10-08 dry EMPA-REG residual, where the absence
  reaches 44793113 only through 201820's descendants;
* the presence's explicit members against the absence's resolved closure reports both
  real cases and none of the gold pairs.

DB-free: ``PrefetchedVocabulary`` over hand-built ancestor edges.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.services.conceptset_closure import PrefetchedVocabulary
from src.utils.circe_lint import absence_overlap_findings, closure_subsumed_presence_criteria

REPO = Path(__file__).resolve().parents[1]
REAL_CASE = REPO / "tests" / "fixtures" / "carmelina_t1dm_shares_t2dm_concept_2026-10-09.json"

DM, T1DM, T2DM, MULTI, T2DM_LEAF, DRUG, OTHER = (
    201820, 201254, 201826, 44793113, 4129519, 1580747, 23986,
)

VOCAB = PrefetchedVocabulary(
    concept_invalid_reason={c: None for c in (DM, T1DM, T2DM, MULTI, T2DM_LEAF, DRUG, OTHER)},
    ancestor_edges={
        DM: {DM, T1DM, T2DM, MULTI, T2DM_LEAF},
        T1DM: {T1DM},
        T2DM: {T2DM, T2DM_LEAF},
        MULTI: {MULTI},
        T2DM_LEAF: {T2DM_LEAF},
        DRUG: {DRUG},
        OTHER: {OTHER},
    },
)


def _check(cohort: dict[str, Any], vocab: PrefetchedVocabulary = VOCAB) -> list[str]:
    # Imported here so the gate-level tests below still run, and fail on their own
    # assertion, while the lint function does not exist yet.
    from src.utils.circe_lint import forbidden_explicit_presence_criteria

    return forbidden_explicit_presence_criteria(cohort, vocab)


def _item(cid: int, *, excluded: bool = False) -> dict[str, Any]:
    return {"concept": {"CONCEPT_ID": cid, "CONCEPT_NAME": f"c{cid}"},
            "isExcluded": excluded, "includeDescendants": True, "includeMapped": False}


def _set(set_id: int, name: str, *items: dict) -> dict[str, Any]:
    return {"id": set_id, "name": name, "expression": {"items": list(items)}}


def _entry(codeset: int, occurrence: tuple[int, int], window=(-9999, 0)) -> dict[str, Any]:
    start, end = window
    return {
        "Criteria": {"ConditionOccurrence": {"CodesetId": codeset}},
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


def _cohort(*, presence_items, absence_items, presence_kind="ALL",
            presence_window=(-9999, 0), absence_window=(-9999, 0)) -> dict[str, Any]:
    """Drug entry, a T2DM presence in #1 and a 'Type 1 diabetes mellitus' absence in #2."""
    return {
        "ConceptSets": [
            _set(1, "linagliptin", _item(DRUG)),
            _set(2, "Type 2 Diabetes Mellitus", *presence_items),
            _set(10, "Type 1 diabetes mellitus", *absence_items),
        ],
        "PrimaryCriteria": {"CriteriaList": [{"DrugEra": {"CodesetId": 1}}]},
        "InclusionRules": [
            {"name": "Type 2 Diabetes Mellitus",
             "expression": _group(presence_kind,
                                  _entry(2, PRESENT, window=presence_window))},
            {"name": "Type 1 diabetes mellitus",
             "expression": _group("ALL", _entry(10, ABSENT, window=absence_window))},
        ],
    }


# --------------------------------------------------------------------------
# FAIL
# --------------------------------------------------------------------------

class TestFail:
    def test_should_fail_when_both_sets_list_the_same_concept(self):
        cohort = _cohort(presence_items=[_item(T2DM), _item(MULTI)],
                         absence_items=[_item(T1DM), _item(MULTI)])

        findings = _check(cohort)

        assert len(findings) == 1, findings
        assert "#2 'Type 1 diabetes mellitus'" in findings[0]
        assert "#1 'Type 2 Diabetes Mellitus'" in findings[0]
        assert str(MULTI) in findings[0] and str(T2DM) not in findings[0]

    def test_should_fail_when_the_absence_reaches_a_named_concept_through_descendants(self):
        """The 10-08 dry EMPA-REG residual: 201826 excepted from 'Diabetes mellitus',
        44793113 not -- named as qualifying by the presence and forbidden by the absence."""
        cohort = _cohort(presence_items=[_item(T2DM), _item(MULTI)],
                         absence_items=[_item(DM), _item(T2DM, excluded=True)])

        findings = _check(cohort)

        assert len(findings) == 1, findings
        assert str(MULTI) in findings[0]

    def test_should_fail_the_real_arm_a_carmelina_case(self):
        cohort = json.loads(REAL_CASE.read_text())
        ids = {item["concept"]["CONCEPT_ID"]
               for concept_set in cohort["ConceptSets"]
               for item in concept_set["expression"]["items"]}
        # Concept-ancestor facts for the fixture's ids: each its own descendant, plus the
        # one real edge among them (4129519 'Pregnancy and type 2 diabetes mellitus' sits
        # under 201826, measured against omop_vocab).
        edges = {cid: {cid} for cid in ids}
        edges[T2DM] = {T2DM, T2DM_LEAF}
        vocab = PrefetchedVocabulary(
            concept_invalid_reason={cid: None for cid in ids}, ancestor_edges=edges
        )

        findings = _check(cohort, vocab)

        assert len(findings) == 1, findings
        assert "#2 'Type 1 diabetes mellitus'" in findings[0]
        assert "#1 'Type 2 Diabetes Mellitus'" in findings[0]
        assert "44793113 'Diabetes mellitus with multiple complications'" in findings[0]
        # The descendant the absence also lists is NOT a named presence concept.
        assert "4129519" not in findings[0]
        # Neither neighbouring check fails it -- the gap this check closes.
        assert closure_subsumed_presence_criteria(cohort, vocab) == []
        assert absence_overlap_findings(cohort, vocab)[0] == []


# --------------------------------------------------------------------------
# legitimate shapes and owned elsewhere -- must not report
# --------------------------------------------------------------------------

class TestSilence:
    def test_should_not_report_an_absence_of_a_descendant_complication(self):
        """'Has T2DM but not this complication of it': the closures overlap by design,
        and no concept the presence names is forbidden."""
        cohort = _cohort(presence_items=[_item(T2DM)], absence_items=[_item(T2DM_LEAF)])

        assert _check(cohort) == []

    def test_should_not_report_an_absence_whose_stated_exception_is_implemented(self):
        cohort = _cohort(presence_items=[_item(T2DM), _item(MULTI)],
                         absence_items=[_item(DM), _item(T2DM, excluded=True),
                                        _item(MULTI, excluded=True)])

        assert _check(cohort) == []

    def test_should_leave_a_whole_closure_inside_the_absence_to_check_t(self):
        cohort = _cohort(presence_items=[_item(T2DM), _item(MULTI)],
                         absence_items=[_item(DM)])

        assert len(closure_subsumed_presence_criteria(cohort, VOCAB)) == 1
        assert _check(cohort) == []

    def test_should_not_report_a_presence_under_any(self):
        cohort = _cohort(presence_items=[_item(T2DM), _item(MULTI)],
                         absence_items=[_item(T1DM), _item(MULTI)], presence_kind="ANY")

        assert _check(cohort) == []

    def test_should_not_report_a_presence_window_lying_before_the_absence_window(self):
        cohort = _cohort(presence_items=[_item(T2DM), _item(MULTI)],
                         absence_items=[_item(T1DM), _item(MULTI)],
                         presence_window=(-9999, -61), absence_window=(-60, 0))

        assert _check(cohort) == []


# --------------------------------------------------------------------------
# one defect, one report
# --------------------------------------------------------------------------

class TestNoDoubleReport:
    def test_should_take_the_pair_off_check_x_warn_list(self):
        cohort = _cohort(presence_items=[_item(T2DM), _item(MULTI)],
                         absence_items=[_item(DM), _item(T2DM, excluded=True)])

        assert len(_check(cohort)) == 1
        assert absence_overlap_findings(cohort, VOCAB) == ([], [])

    def test_should_leave_a_descendant_complication_cut_on_check_x_warn_list(self):
        cohort = _cohort(presence_items=[_item(T2DM)], absence_items=[_item(T2DM_LEAF)])

        fail, warn = absence_overlap_findings(cohort, VOCAB)

        assert fail == [] and len(warn) == 1, warn


# --------------------------------------------------------------------------
# the delivery gate runs it
# --------------------------------------------------------------------------

class TestTheDeliveryGateRunsTheCheck:
    """A lint nobody calls is indistinguishable from one that returns nothing."""

    @staticmethod
    def _run_gate(monkeypatch, tmp_path, capsys, cohort, vocab):
        monkeypatch.delenv("TTE_STORE_PATH", raising=False)
        import scripts.verify_circe_delivery as gate

        class _FakeVocabulary:
            def __init__(self, *_args):
                pass

            def prefetch(self, _items):
                return vocab

            def close(self):
                pass

        monkeypatch.setattr(gate, "_open_vocabulary", _FakeVocabulary)
        study = {
            "id": 9, "name": "Study 9", "comparisonMode": "target_minus_treatment",
            "treatmentArms": [{"name": "linagliptin"}, {"name": "Placebo"}],
            "eligibility": {"structuredExpression": json.loads(json.dumps(cohort))},
        }
        for role in ("treatment", "comparator"):
            (tmp_path / f"carmelina_{role}.circe.json").write_text(json.dumps(cohort))
        store = tmp_path / "studies.json"
        store.write_text(json.dumps([study]))
        rc = gate.main(["--dir", str(tmp_path), "--store", str(store), "--map", "carmelina=9"])
        return rc, capsys.readouterr().out

    def test_should_fail_the_delivery_when_an_absence_forbids_a_named_presence_concept(
        self, monkeypatch, tmp_path, capsys
    ):
        cohort = _cohort(presence_items=[_item(T2DM), _item(MULTI)],
                         absence_items=[_item(T1DM), _item(MULTI)])

        rc, out = self._run_gate(monkeypatch, tmp_path, capsys, cohort, VOCAB)

        assert rc == 1, out
        assert "absence forbids a concept a mandatory presence names (1)" in out, out

    def test_should_pass_the_delivery_on_a_descendant_complication_cut(
        self, monkeypatch, tmp_path, capsys
    ):
        cohort = _cohort(presence_items=[_item(T2DM)], absence_items=[_item(T2DM_LEAF)])

        rc, out = self._run_gate(monkeypatch, tmp_path, capsys, cohort, VOCAB)

        assert "absence forbids a concept a mandatory presence names" not in out, out
        assert rc == 0, out
