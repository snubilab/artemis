"""The residual-after-exception repair, extended from the entry to mandatory presences.

Measured on the 2026-10-08 dry rebuild, ``empa-reg_treatment.circe.json``::

    entry  DrugEra cs1 'BI 10773'
    #2     'Type 2 Diabetes Mellitus'             >=1 ConditionOccurrence cs2  [-9999, 0]
           cs2 = 201826, 44793113 (both includeDescendants)
    #15    'Endocrine disorder (excluding T2DM)'  ==0 ConditionOccurrence cs29 [-9999, 0]
           cs29 = 201820 'Diabetes mellitus' (desc) + 23 others, 201826 isExcluded

44793113 sits under 201820 as a SIBLING of 201826, so the stated exception removed only
part of what #2 requires: a patient coded only 44793113 satisfies #2 and is removed by
#15. Check (t) is silent -- the overlap is partial, not a subset -- and the entry-only
repair is silent too, because the entry is a drug.

DB-free: ``PrefetchedVocabulary`` over hand-built ancestor edges, so the real closure
resolver runs. Each declining test holds every other condition true.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.services.conceptset_closure import (  # noqa: E402
    PrefetchedVocabulary,
    resolve_concept_set,
)
from src.services.entry_exclusion_repair import (  # noqa: E402
    PATH_RESIDUAL_AFTER_EXCEPTION,
    repair_entry_exclusion_conflicts,
)

DM, T2DM, MULTI, T2DM_LEAF, PITUITARY, DRUG = 201820, 201826, 44793113, 4000001, 23986, 45774751
RULE_NAME = "Endocrine disorder (excluding T2DM)"

#: What the criterion behind codeset 29 states (RFC-016): the repair is triggered by this,
#: keyed by concept set, and no longer by the rule's name.
STATED = {29: ["T2DM"]}


def vocabulary() -> PrefetchedVocabulary:
    return PrefetchedVocabulary(
        concept_invalid_reason={c: None for c in (DM, T2DM, MULTI, T2DM_LEAF, PITUITARY, DRUG)},
        ancestor_edges={
            DM: {DM, T2DM, MULTI, T2DM_LEAF},
            T2DM: {T2DM, T2DM_LEAF},
            MULTI: {MULTI},
            PITUITARY: {PITUITARY},
            DRUG: {DRUG},
        },
    )


def item(cid: int, *, excluded: bool = False, descendants: bool = True) -> dict:
    return {
        "concept": {"CONCEPT_ID": cid, "CONCEPT_NAME": f"c{cid}"},
        "isExcluded": excluded, "includeDescendants": descendants, "includeMapped": False,
    }


def criterion(codeset: int, occurrence: tuple[int, int], window=(-9999, 0),
              criteria_type: str = "ConditionOccurrence", **attrs) -> dict:
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


def cohort(*, presence_group: str = "ALL", presence=None, absence=None, rule_name=RULE_NAME,
           absence_items=None, presence_items=None) -> dict:
    """The dry-rebuild EMPA-REG treatment shape."""
    absence_items = absence_items if absence_items is not None else [
        item(DM), item(PITUITARY), item(T2DM, excluded=True)]
    presence_items = presence_items if presence_items is not None else [item(T2DM), item(MULTI)]
    presence = presence or criterion(2, PRESENT)
    return {
        "ConceptSets": [
            {"id": 1, "name": "empagliflozin", "expression": {"items": [item(DRUG)]}},
            {"id": 2, "name": "Type 2 Diabetes Mellitus", "expression": {"items": presence_items}},
            {"id": 29, "name": RULE_NAME, "expression": {"items": absence_items}},
            {"id": 30, "name": "Hypertension", "expression": {"items": [item(PITUITARY)]}},
        ],
        "PrimaryCriteria": {"CriteriaList": [{"DrugEra": {"CodesetId": 1}}]},
        "InclusionRules": [
            {"name": "Type 2 Diabetes Mellitus", "expression": {
                "Type": presence_group,
                "CriteriaList": [presence] + (
                    [criterion(30, PRESENT)] if presence_group != "ALL" else []),
                "DemographicCriteriaList": [], "Groups": []}},
            {"name": rule_name, "expression": {
                "Type": "ALL", "CriteriaList": [], "DemographicCriteriaList": [],
                "Groups": [{"Type": "ALL", "CriteriaList": [absence or criterion(29, ABSENT)],
                            "DemographicCriteriaList": [], "Groups": []}]}},
        ],
    }


def excluded_ids(base: dict, codeset_id: int) -> set[int]:
    cs = next(c for c in base["ConceptSets"] if c["id"] == codeset_id)
    return {i["concept"]["CONCEPT_ID"] for i in cs["expression"]["items"] if i.get("isExcluded")}


def forbidden_presence(base: dict, lookup) -> set[int]:
    sets = {c["id"]: c for c in base["ConceptSets"]}
    return (resolve_concept_set(sets[2], lookup).concept_ids
            & resolve_concept_set(sets[29], lookup).concept_ids)


# --------------------------------------------------------------------------
# fires
# --------------------------------------------------------------------------

def test_should_mirror_the_presence_set_when_a_stated_exception_leaves_a_residual():
    base = cohort()
    lookup = vocabulary()
    assert forbidden_presence(base, lookup) == {MULTI}  # the defect, before

    repairs = repair_entry_exclusion_conflicts(base, lookup, STATED)

    assert [(r.rule_number, r.codeset_id, r.path, r.target, r.excluded_concept_ids)
            for r in repairs] == [
        (2, 29, PATH_RESIDUAL_AFTER_EXCEPTION, "presence #1 'Type 2 Diabetes Mellitus'", [MULTI])
    ]
    assert excluded_ids(base, 29) == {T2DM, MULTI}
    assert forbidden_presence(base, lookup) == set()


def test_should_change_nothing_but_the_absence_set_when_it_repairs_the_residual():
    base = cohort()
    before = copy.deepcopy(base)

    repair_entry_exclusion_conflicts(base, vocabulary(), STATED)

    added = [i for i in base["ConceptSets"][2]["expression"]["items"]
             if i not in before["ConceptSets"][2]["expression"]["items"]]
    assert [i["concept"]["CONCEPT_ID"] for i in added] == [MULTI]
    base["ConceptSets"][2]["expression"]["items"] = before["ConceptSets"][2]["expression"]["items"]
    assert json.dumps(base, sort_keys=True) == json.dumps(before, sort_keys=True)


def test_should_do_nothing_on_a_second_pass_when_it_has_repaired_the_presence_residual():
    base = cohort()
    lookup = vocabulary()

    assert repair_entry_exclusion_conflicts(base, lookup, STATED)
    assert repair_entry_exclusion_conflicts(base, lookup, STATED) == []


def test_should_repair_when_the_absence_window_ends_before_index_but_contains_the_presence():
    """Index day is the ENTRY path's condition. Against a presence what matters is that
    every event the presence can count falls inside the window being required empty."""
    base = cohort(presence=criterion(2, PRESENT, window=(-9999, -1)),
                  absence=criterion(29, ABSENT, window=(-9999, -1)))

    assert [r.excluded_concept_ids for r in repair_entry_exclusion_conflicts(base, vocabulary(), STATED)] \
        == [[MULTI]]


# --------------------------------------------------------------------------
# declines -- one condition false, the rest held true
# --------------------------------------------------------------------------

def test_should_decline_when_the_criterion_states_no_exception():
    base = cohort(rule_name="Endocrine disorder")

    assert repair_entry_exclusion_conflicts(base, vocabulary(), {}) == []
    assert excluded_ids(base, 29) == {T2DM}


def test_should_decline_when_no_excluded_item_reaches_the_presence():
    """Full coverage with nothing excepted is check (t)'s finding, not a stated
    exception applied incompletely -- the repair implements only what was begun."""
    base = cohort(absence_items=[item(DM), item(PITUITARY)])

    assert repair_entry_exclusion_conflicts(base, vocabulary(), STATED) == []
    assert excluded_ids(base, 29) == set()


def test_should_decline_when_the_presence_sits_under_an_any_group():
    base = cohort(presence_group="ANY")

    assert repair_entry_exclusion_conflicts(base, vocabulary(), STATED) == []
    assert excluded_ids(base, 29) == {T2DM}


def test_should_decline_when_the_presence_window_reaches_outside_the_absence_window():
    base = cohort(absence=criterion(29, ABSENT, window=(-365, 0)))

    assert repair_entry_exclusion_conflicts(base, vocabulary(), STATED) == []
    assert excluded_ids(base, 29) == {T2DM}


def test_should_decline_when_the_presence_reads_another_table():
    base = cohort(presence=criterion(2, PRESENT, criteria_type="Observation"))

    assert repair_entry_exclusion_conflicts(base, vocabulary(), STATED) == []
    assert excluded_ids(base, 29) == {T2DM}


def test_should_decline_when_the_absence_is_narrowed():
    """A narrowed absence forbids only some events, so a patient can satisfy the
    presence through the rest; mirroring would widen the absence's escape hatch."""
    base = cohort(absence=criterion(29, ABSENT, ConditionType=[{"CONCEPT_ID": 32020}]))

    assert repair_entry_exclusion_conflicts(base, vocabulary(), STATED) == []
    assert excluded_ids(base, 29) == {T2DM}


def test_should_decline_when_the_presence_set_carries_an_excluded_item():
    base = cohort(presence_items=[item(T2DM), item(MULTI), item(T2DM_LEAF, excluded=True)])

    assert repair_entry_exclusion_conflicts(base, vocabulary(), STATED) == []
    assert excluded_ids(base, 29) == {T2DM}


# --------------------------------------------------------------------------
# the detector, on the same shared predicate
# --------------------------------------------------------------------------

def _check(base: dict):
    from scripts.verify_entry_exclusion_conflict import check_cohort

    findings, _notes = check_cohort(base, vocabulary())
    return [(f.severity, f.target, f.n_overlap, f.sample_ids) for f in findings]


def test_should_fail_the_residual_against_a_mandatory_presence_when_the_entry_is_a_drug():
    assert _check(cohort()) == [("FAIL", "presence #1 'Type 2 Diabetes Mellitus'", 1, [MULTI])]


def test_should_report_nothing_when_the_repair_has_closed_the_residual():
    base = cohort()
    repair_entry_exclusion_conflicts(base, vocabulary(), STATED)

    assert _check(base) == []


def test_should_fail_a_presence_the_absence_covers_whole_when_nothing_is_excepted():
    """Not repairable (no exception begun) and still an empty cohort -- the gate refuses it."""
    base = cohort(absence_items=[item(DM), item(PITUITARY)])

    assert _check(base) == [
        ("FAIL", "presence #1 'Type 2 Diabetes Mellitus'", 3, sorted([T2DM, T2DM_LEAF, MULTI]))
    ]


def test_should_warn_when_the_presence_window_reaches_outside_the_absence_window():
    base = cohort(absence=criterion(29, ABSENT, window=(-365, 0)))

    assert [s for s, *_ in _check(base)] == ["WARN"]


def test_should_report_nothing_for_a_presence_under_an_any_group():
    assert _check(cohort(presence_group="ANY")) == []


def test_should_report_nothing_for_a_partial_overlap_no_exception_reached():
    """A population cut, not a stated exception left incomplete: R1's WARN, not this gate's."""
    base = cohort(absence_items=[item(MULTI), item(PITUITARY)])

    assert _check(base) == []


# --------------------------------------------------------------------------
# the measured files, through the real vocabulary
# --------------------------------------------------------------------------

DRYRUN = REPO_ROOT / "output" / "site_gap" / "2026-10-08_dryrun" / "DELIVERY"


def _real_lookup(cohort_doc: dict):
    from scripts.verify_entry_exclusion_conflict import DEFAULT_DSN
    from src.services.conceptset_closure import (
        DEFAULT_VOCAB_SCHEMA,
        PostgresVocabulary,
        items_of_cohort,
    )

    with PostgresVocabulary(DEFAULT_DSN, DEFAULT_VOCAB_SCHEMA) as vocab:
        return vocab.prefetch(items_of_cohort(cohort_doc))


@pytest.mark.integration
@pytest.mark.skipif(not DRYRUN.is_dir(), reason=f"dry rebuild not present: {DRYRUN}")
def test_should_close_the_dry_rebuild_residual_when_it_repairs_the_treatment_file():
    from scripts.verify_entry_exclusion_conflict import check_cohort

    base = json.loads((DRYRUN / "empa-reg_treatment.circe.json").read_text())
    lookup = _real_lookup(base)
    assert forbidden_presence(base, lookup) == {MULTI}

    repairs = repair_entry_exclusion_conflicts(base, lookup, STATED)

    assert [(r.rule_number, r.codeset_id, r.path, r.excluded_concept_ids) for r in repairs] == [
        (15, 29, PATH_RESIDUAL_AFTER_EXCEPTION, [MULTI])
    ]
    assert forbidden_presence(base, lookup) == set()
    findings, _notes = check_cohort(base, lookup)
    assert [f for f in findings if f.severity == "FAIL"] == []
