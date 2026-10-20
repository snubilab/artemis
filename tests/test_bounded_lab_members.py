"""A criterion with a numeric bound keeps only lab tests that can carry that number.

P7 EMPA-REG exclusion "ALT, AST or AP > 3x ULN" shipped AST with 3010587 'Aspartate
aminotransferase [Presence]' (scale Ord: a present/absent result, no number to compare) and
40757631 'macromolecular/total' (a different component); AP with the bone, heat-stable and 'other
fractions' components. Candidates the
refinement adds were already restricted to quantitative, point-in-time tests of the analyte's own
component (`_candidates`); the mapper's own members were not.

Every LabTest below is the vocabulary row (synthea23m, 2026-10-20). Scale and component are
LOINC axes; no name or criterion text is read.
"""

from __future__ import annotations

import pytest

from src.services.loinc_specimen import POINT_IN_TIME as PT
from src.services.loinc_specimen import LabTest, plan_specimen_refinement

SP = "Serum or Plasma"
CAT = "Catalytic Concentration"


def _ast(cid, component, component_id, prop, scale, time=PT):
    return LabTest(cid, f"AST stand-in {cid}", component, SP, prop, scale, str(cid),
                   component_id=component_id, time_aspect=time, system_id=1)


AST_QN = _ast(3013721, "Aspartate aminotransferase", 40785861, CAT, "Qn")
AST_QN_2 = _ast(3037081, "Aspartate aminotransferase", 40785861, CAT, "Qn")
AST_PRESENCE = _ast(3010587, "Aspartate aminotransferase", 40785861, "Presence or Threshold", "Ord")
AST_STUDY_MAX = _ast(3042781, "Aspartate aminotransferase", 40785861, CAT, "Qn", "Stdy^max")
AST_MACRO_FRACTION = _ast(
    40757631, "Aspartate aminotransferase.macromolecular/Aspartate aminotransferase.total",
    37062508, "Catalytic Fraction", "Qn")
MEMBERS = [AST_PRESENCE, AST_QN, AST_STUDY_MAX, AST_MACRO_FRACTION, AST_QN_2]


def _accept_serum(_analyte, options):
    return frozenset(o.key for o in options if o.system == SP)


#: LOINC Component ``Is a`` ancestors (synthea23m): macromolecular/total > macromolecular > AST.
#: 37059767 stands in for 'Aspartate aminotransferase.macromolecular', which no member holds.
ANCESTORS = {37062508: frozenset({37059767, 40785861})}


def _plan(numeric: bool, members=MEMBERS, ancestors=ANCESTORS):
    return plan_specimen_refinement(
        member_ids=[m.concept_id for m in members],
        lab_tests={m.concept_id: m for m in members},
        unit_prop=None,
        numeric_bound=numeric,
        analyte_lab_tests=lambda _a: [],
        judge=_accept_serum,
        component_ancestors=ancestors,
    )


def _removed(plan) -> set[int]:
    return {cid for cid, _ in plan.removed}


def test_should_drop_members_that_cannot_carry_the_number_when_the_criterion_has_a_bound():
    plan = _plan(numeric=True)
    assert plan.analyte == "Aspartate aminotransferase"
    assert _removed(plan) == {3010587, 40757631}
    # The time axis governs additions only (test_loinc_specimen::TestTimeAspect).
    assert 3042781 not in _removed(plan)


def test_should_keep_every_member_when_the_criterion_has_no_bound():
    """'Known elevated AST' with no number: a [Presence] result is a fair reading of it."""
    assert _removed(_plan(numeric=False)) == set()


def test_should_name_the_axis_each_dropped_member_fails():
    reasons = dict(_plan(numeric=True).removed)
    assert any("scale" in r for r in reasons[3010587])
    assert any("component" in r for r in reasons[40757631])


def _lab(cid, component, component_id, prop="Catalytic Concentration"):
    return LabTest(cid, f"stand-in {cid}", component, SP, prop, "Qn", str(cid),
                   component_id=component_id, time_aspect=PT, system_id=1)


def test_should_drop_alkaline_phosphatase_fractions_and_then_find_the_analyte():
    """P7 EMPA-REG cs14 declined on a 1:1:1:1 analyte tie: each fraction voted as an analyte."""
    total = _lab(3035995, "Alkaline phosphatase", 40789190)
    bone = _lab(3002069, "Alkaline phosphatase.bone/Alkaline phosphatase.total", 37065628,
                "Catalytic Fraction")
    heat = _lab(3046195, "Alkaline phosphatase.heat stable/Alkaline phosphatase.total", 37024925,
                "Catalytic Fraction")
    other = _lab(3045684, "Alkaline phosphatase.other fractions", 37060816)
    isoenzymes = 37024000  # stand-in id for 'Alkaline phosphatase isoenzymes' (between them and AP)
    plan = _plan(True, [total, bone, heat, other], {
        37065628: frozenset({isoenzymes, 40789190}),
        37024925: frozenset({isoenzymes, 40789190}),
        37060816: frozenset({isoenzymes, 40789190}),
    })
    assert plan.analyte == "Alkaline phosphatase"
    assert _removed(plan) == {3002069, 3046195, 3045684}


def test_should_keep_every_analyte_an_or_criterion_names():
    """P7 PLATO 'Troponin I or T or CK-MB': the two troponins are unrelated components, so
    neither is a part of the other and both stay."""
    tni = _lab(3021337, "Troponin I.cardiac", 3000001, "Mass Concentration")
    tnt = [_lab(3019800 + i, "Troponin T.cardiac", 3000002, "Mass Concentration") for i in range(3)]
    plan = _plan(True, [tni, *tnt], {})
    assert 3021337 not in _removed(plan)


@pytest.mark.integration
def test_should_read_the_component_hierarchy_from_the_vocabulary():
    from src.services.loinc_specimen import PostgresLabTestVocabulary
    from src.settings import settings

    try:
        vocab = PostgresLabTestVocabulary(settings.DATABASE_URL, settings.CDM_SCHEMA)
    except Exception as e:  # noqa: BLE001 -- unreachable vocabulary skips, as elsewhere
        pytest.skip(f"OMOP vocabulary unreachable: {e}")
    try:
        found = vocab.component_ancestors([37062508, 40789190, 37065628])
    finally:
        vocab.close()
    assert 40785861 in found[37062508]  # macromolecular/total is a part of AST
    assert 40789190 in found[37065628]  # bone/total is a part of alkaline phosphatase
    assert 37065628 not in found.get(40789190, frozenset())
