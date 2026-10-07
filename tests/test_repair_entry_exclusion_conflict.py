"""Unit tests for the export-time repair of an entry event excluded by its own rule.

DB-free, on the same seam the detector's tests use: ``PrefetchedVocabulary`` over
hand-built ancestor edges, so the real closure resolver runs and the ancestry hop
that makes the conflict invisible to grep (201826 reaching codeset 29 only as a
descendant of 201820) is exercised rather than mocked.

The shape under test is the measured one from
``deliveries/2026-09-12/empa-reg_comparator.circe.json``. Each declining test
holds the other two conditions true, so it fails for exactly one reason.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.services.conceptset_closure import PrefetchedVocabulary  # noqa: E402
from src.services.entry_exclusion_repair import (  # noqa: E402
    iter_repair_candidates,
    repair_entry_exclusion_conflicts,
)

# Concept ids from the real file.
T2DM = 201826  # Type 2 diabetes mellitus -- the entry concept
T2DM_OTHER = 44793113  # the entry set's second member
DM = 201820  # Diabetes mellitus -- what codeset 29 actually lists
T2DM_ULCER = 4099651  # a T2DM descendant, so also under DM
PITUITARY = 23986  # an endocrine disorder outside the entry closure
UNRELATED = 4030518

RULE_NAME = "Endocrine disorder (excluding T2DM)"


def vocabulary() -> PrefetchedVocabulary:
    return PrefetchedVocabulary(
        concept_invalid_reason={
            cid: None
            for cid in (T2DM, T2DM_OTHER, DM, T2DM_ULCER, PITUITARY, UNRELATED)
        },
        ancestor_edges={
            DM: {DM, T2DM, T2DM_OTHER, T2DM_ULCER},
            T2DM: {T2DM, T2DM_ULCER},
            T2DM_OTHER: {T2DM_OTHER},
            PITUITARY: {PITUITARY},
            UNRELATED: {UNRELATED},
        },
    )


def item(concept_id: int, *, descendants: bool = False, excluded: bool = False) -> dict:
    return {
        "concept": {"CONCEPT_ID": concept_id, "CONCEPT_NAME": f"concept {concept_id}"},
        "includeDescendants": descendants,
        "includeMapped": False,
        "isExcluded": excluded,
    }


def concept_set(set_id: int, name: str, *items: dict) -> dict:
    return {"id": set_id, "name": name, "expression": {"items": list(items)}}


def absence_criterion(
    codeset_id: int,
    *,
    domain: str = "ConditionOccurrence",
    start: int = -9999,
    end: int = 0,
) -> dict:
    return {
        "Criteria": {domain: {"CodesetId": codeset_id}},
        "StartWindow": {
            "Start": {"Days": abs(start), "Coeff": -1 if start < 0 else 1},
            "End": {"Days": abs(end), "Coeff": -1 if end < 0 else 1},
        },
        "Occurrence": {"Type": 0, "Count": 0},
    }


def rule(name: str, *criteria: dict, group_type: str = "ALL") -> dict:
    return {
        "name": name,
        "expression": {
            "Type": "ALL",
            "CriteriaList": [],
            "Groups": [{"Type": group_type, "CriteriaList": list(criteria), "Groups": []}],
        },
    }


def entry_set() -> dict:
    return concept_set(2, "Type 2 Diabetes Mellitus",
                       item(T2DM, descendants=True), item(T2DM_OTHER, descendants=True))


def endocrine_set() -> dict:
    return concept_set(29, "Endocrine disorder",
                       item(DM, descendants=True), item(PITUITARY, descendants=True))


def cohort(*, concept_sets: list[dict], rules: list[dict], entry_codeset: int = 2) -> dict:
    return {
        "ConceptSets": concept_sets,
        "PrimaryCriteria": {
            "CriteriaList": [{"ConditionOccurrence": {"CodesetId": entry_codeset, "First": True}}]
        },
        "InclusionRules": rules,
    }


def excluded_ids(base: dict, codeset_id: int) -> set[int]:
    cs = next(c for c in base["ConceptSets"] if c["id"] == codeset_id)
    return {
        i["concept"]["CONCEPT_ID"]
        for i in cs["expression"]["items"]
        if i.get("isExcluded")
    }


# --------------------------------------------------------------------------
# fires
# --------------------------------------------------------------------------

def test_should_exclude_the_entry_concepts_when_the_rule_name_states_the_exception():
    """The measured defect: rule 14 says 'excluding T2DM' and codeset 29 does not."""
    base = cohort(concept_sets=[entry_set(), endocrine_set()],
                  rules=[rule(RULE_NAME, absence_criterion(29))])

    repairs = repair_entry_exclusion_conflicts(base, vocabulary())

    assert [r.codeset_id for r in repairs] == [29]
    assert repairs[0].rule_number == 1
    assert excluded_ids(base, 29) == {T2DM, T2DM_OTHER}
    # The entry set itself is untouched, and so is every other concept set.
    assert excluded_ids(base, 2) == set()


def test_should_leave_the_rule_satisfiable_when_it_has_repaired_it():
    """After the repair the absence closure no longer contains the entry closure."""
    from src.services.conceptset_closure import resolve_concept_set

    base = cohort(concept_sets=[entry_set(), endocrine_set()],
                  rules=[rule(RULE_NAME, absence_criterion(29))])
    lookup = vocabulary()
    entry_closure = resolve_concept_set(base["ConceptSets"][0], lookup).concept_ids

    repair_entry_exclusion_conflicts(base, lookup)

    absence_closure = resolve_concept_set(base["ConceptSets"][1], lookup).concept_ids
    assert entry_closure & absence_closure == set()
    assert PITUITARY in absence_closure  # the rest of the set survives


def test_should_do_nothing_on_a_second_pass():
    base = cohort(concept_sets=[entry_set(), endocrine_set()],
                  rules=[rule(RULE_NAME, absence_criterion(29))])
    lookup = vocabulary()

    assert repair_entry_exclusion_conflicts(base, lookup)
    assert repair_entry_exclusion_conflicts(base, lookup) == []


# --------------------------------------------------------------------------
# declines -- one condition false, the other two held true
# --------------------------------------------------------------------------

def test_should_decline_when_the_rule_name_states_no_exception():
    """Condition 1. Overlap alone must never trigger a repair: a set with no
    exception clause may be excluding the entry concepts deliberately."""
    base = cohort(concept_sets=[entry_set(), endocrine_set()],
                  rules=[rule("Endocrine disorder", absence_criterion(29))])

    assert repair_entry_exclusion_conflicts(base, vocabulary()) == []
    assert excluded_ids(base, 29) == set()


def test_should_decline_when_the_absence_set_covers_only_part_of_the_entry_closure():
    """Condition 2. Partial overlap is a population cut, not an unsatisfiable rule."""
    partial = concept_set(30, "T2DM with ulcer", item(T2DM_ULCER))
    base = cohort(concept_sets=[entry_set(), partial],
                  rules=[rule("Ulcer (excluding T2DM)", absence_criterion(30))])

    assert repair_entry_exclusion_conflicts(base, vocabulary()) == []
    assert excluded_ids(base, 30) == set()


def test_should_decline_when_the_criterion_sits_under_a_non_all_group():
    """Condition 3a. Under ANY a sibling branch can still satisfy the rule."""
    base = cohort(concept_sets=[entry_set(), endocrine_set()],
                  rules=[rule(RULE_NAME, absence_criterion(29), group_type="ANY")])

    assert repair_entry_exclusion_conflicts(base, vocabulary()) == []
    assert excluded_ids(base, 29) == set()


def test_should_decline_when_the_window_excludes_index_day():
    """Condition 3b. A washout ending at -1d can be satisfied by a patient whose
    first qualifying event IS the index event."""
    base = cohort(concept_sets=[entry_set(), endocrine_set()],
                  rules=[rule(RULE_NAME, absence_criterion(29, start=-7, end=-1))])

    assert repair_entry_exclusion_conflicts(base, vocabulary()) == []
    assert excluded_ids(base, 29) == set()


def test_should_decline_when_the_entry_set_carries_an_excluded_item():
    """A mirrored exclusion cannot express the entry set's own subtraction, so the
    repair would remove more from the absence set than the entry actually admits."""
    entry = concept_set(2, "Type 2 Diabetes Mellitus",
                        item(T2DM, descendants=True), item(T2DM_ULCER, excluded=True))
    base = cohort(concept_sets=[entry, endocrine_set()],
                  rules=[rule(RULE_NAME, absence_criterion(29))])

    assert repair_entry_exclusion_conflicts(base, vocabulary()) == []
    assert excluded_ids(base, 29) == set()


# --------------------------------------------------------------------------
# the DB-free pre-gate
# --------------------------------------------------------------------------

def test_should_report_no_candidate_without_a_vocabulary_when_no_rule_names_an_exception():
    """The service wrapper skips the vocabulary round trip on this answer."""
    base = cohort(concept_sets=[entry_set(), endocrine_set()],
                  rules=[rule("Endocrine disorder", absence_criterion(29))])

    assert list(iter_repair_candidates(base)) == []


def test_should_report_a_candidate_without_a_vocabulary_on_the_measured_shape():
    base = cohort(concept_sets=[entry_set(), endocrine_set()],
                  rules=[rule(RULE_NAME, absence_criterion(29))])

    candidates = list(iter_repair_candidates(base))
    assert len(candidates) == 1
    assert candidates[0].exception.excepted == ["T2DM"]


# --------------------------------------------------------------------------
# the second path: a stated exception applied to part of the entry only
# --------------------------------------------------------------------------
#
# The shape the description-stated exception produces on the EMPA-REG comparator:
# codeset 29 gains 201826 'T2DM' as isExcluded, but still forbids 44793113 through
# 201820 -- a sibling of 201826, not a descendant. The set no longer covers the WHOLE
# entry closure, so condition 2 is false and the full-coverage path declines.

def endocrine_set_excepting_t2dm() -> dict:
    return concept_set(29, "Endocrine disorder (excluding T2DM)",
                       item(DM, descendants=True), item(PITUITARY, descendants=True),
                       item(T2DM, descendants=True, excluded=True))


def test_should_exclude_the_residual_when_the_set_already_excepts_part_of_the_entry():
    base = cohort(concept_sets=[entry_set(), endocrine_set_excepting_t2dm()],
                  rules=[rule(RULE_NAME, absence_criterion(29))])

    repairs = repair_entry_exclusion_conflicts(base, vocabulary())

    assert [(r.codeset_id, r.path, r.excluded_concept_ids) for r in repairs] == [
        (29, "residual-after-exception", [T2DM_OTHER])
    ]
    assert excluded_ids(base, 29) == {T2DM, T2DM_OTHER}


def test_should_not_duplicate_an_entry_concept_when_the_set_already_excludes_it():
    base = cohort(concept_sets=[entry_set(), endocrine_set_excepting_t2dm()],
                  rules=[rule(RULE_NAME, absence_criterion(29))])

    repair_entry_exclusion_conflicts(base, vocabulary())

    items = base["ConceptSets"][1]["expression"]["items"]
    assert [i["concept"]["CONCEPT_ID"] for i in items].count(T2DM) == 1


def test_should_leave_no_residual_when_it_has_repaired_the_partial_exception():
    from src.services.conceptset_closure import resolve_concept_set

    base = cohort(concept_sets=[entry_set(), endocrine_set_excepting_t2dm()],
                  rules=[rule(RULE_NAME, absence_criterion(29))])
    lookup = vocabulary()
    entry_closure = resolve_concept_set(base["ConceptSets"][0], lookup).concept_ids

    repair_entry_exclusion_conflicts(base, lookup)

    absence_closure = resolve_concept_set(base["ConceptSets"][1], lookup).concept_ids
    assert entry_closure & absence_closure == set()
    assert {DM, PITUITARY} <= absence_closure  # the rest of the set survives


def test_should_do_nothing_on_a_second_pass_when_it_has_repaired_the_residual():
    base = cohort(concept_sets=[entry_set(), endocrine_set_excepting_t2dm()],
                  rules=[rule(RULE_NAME, absence_criterion(29))])
    lookup = vocabulary()

    assert repair_entry_exclusion_conflicts(base, lookup)
    assert repair_entry_exclusion_conflicts(base, lookup) == []


def test_should_decline_when_the_excluded_item_lies_outside_the_entry_closure():
    """Condition (a) is the safety condition: an exception that touches no entry
    concept says nothing about the entry, so a partial overlap stays a population cut."""
    partial = concept_set(30, "T2DM with ulcer",
                          item(T2DM_ULCER), item(UNRELATED, excluded=True))
    base = cohort(concept_sets=[entry_set(), partial],
                  rules=[rule("Ulcer (excluding T2DM)", absence_criterion(30))])

    assert repair_entry_exclusion_conflicts(base, vocabulary()) == []
    assert excluded_ids(base, 30) == {UNRELATED}


def test_should_decline_the_residual_when_the_rule_name_states_no_exception():
    """Condition 1 still gates the second path."""
    base = cohort(concept_sets=[entry_set(), endocrine_set_excepting_t2dm()],
                  rules=[rule("Endocrine disorder", absence_criterion(29))])

    assert repair_entry_exclusion_conflicts(base, vocabulary()) == []
    assert excluded_ids(base, 29) == {T2DM}


# --------------------------------------------------------------------------
# the measured files, through the real vocabulary
# --------------------------------------------------------------------------

DELIVERY = REPO_ROOT / "deliveries" / "2026-09-23"


def _real(name: str) -> dict:
    import json

    return json.loads((DELIVERY / name).read_text())


def _with_part1_exception(cohort_doc: dict) -> dict:
    """Codeset 29 as the description-stated exception now maps it: the mirrored
    exclusions stripped, then 201826 appended the way `resolve_entity_exception` does."""
    from src.services.entity_subtraction import ExceptedConcept, apply_entity_subtraction

    cs = next(c for c in cohort_doc["ConceptSets"] if c["id"] == 29)
    kept = [i for i in cs["expression"]["items"] if not i.get("isExcluded")]
    cs["expression"]["items"] = apply_entity_subtraction(
        kept, [ExceptedConcept(T2DM, "Type 2 diabetes mellitus",
                               {"CONCEPT_ID": T2DM, "CONCEPT_NAME": "Type 2 diabetes mellitus"})]
    ).items
    return cohort_doc


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
@pytest.mark.skipif(not DELIVERY.is_dir(), reason=f"delivery not present: {DELIVERY}")
def test_should_repair_the_measured_comparator_to_zero_residual_when_t2dm_is_excepted():
    from scripts.verify_entry_exclusion_conflict import check_cohort
    from src.utils.circe_lint import closure_subsumed_presence_criteria

    base = _with_part1_exception(_real("empa-reg_comparator.circe.json"))
    lookup = _real_lookup(base)

    repairs = repair_entry_exclusion_conflicts(base, lookup)

    assert [(r.rule_number, r.path, r.excluded_concept_ids) for r in repairs] == [
        (15, "residual-after-exception", [T2DM_OTHER])
    ]
    assert excluded_ids(base, 29) == {T2DM, T2DM_OTHER}
    findings, _notes = check_cohort(base, lookup)
    assert findings == []
    assert closure_subsumed_presence_criteria(base, lookup) == []


@pytest.mark.integration
@pytest.mark.skipif(not DELIVERY.is_dir(), reason=f"delivery not present: {DELIVERY}")
@pytest.mark.parametrize("part1", [False, True], ids=["as-delivered", "t2dm-excepted"])
def test_should_leave_the_treatment_file_unchanged_when_its_entry_is_a_drug(part1):
    import copy
    import json

    base = _real("empa-reg_treatment.circe.json")
    if part1:
        base = _with_part1_exception(base)
    before = json.dumps(copy.deepcopy(base), sort_keys=True)

    assert repair_entry_exclusion_conflicts(base, _real_lookup(base)) == []
    assert json.dumps(base, sort_keys=True) == before


def test_should_decline_when_the_mirror_would_still_leave_a_residual():
    """The post-condition guard. 201826 is already excluded WITHOUT descendants, so the
    dedupe skips mirroring it and 4099651 (a T2DM descendant) would stay forbidden. The
    repair declines rather than ship a half-repair, and the gate still fails the file."""
    from scripts.verify_entry_exclusion_conflict import check_cohort

    narrow = concept_set(29, "Endocrine disorder (excluding T2DM)",
                         item(DM, descendants=True), item(T2DM, excluded=True))
    base = cohort(concept_sets=[entry_set(), narrow],
                  rules=[rule(RULE_NAME, absence_criterion(29))])

    assert repair_entry_exclusion_conflicts(base, vocabulary()) == []
    assert excluded_ids(base, 29) == {T2DM}
    findings, _ = check_cohort(base, vocabulary())
    assert [(f.severity, sorted(f.sample_ids)) for f in findings] == [
        ("FAIL", sorted([T2DM_OTHER, T2DM_ULCER]))
    ]
