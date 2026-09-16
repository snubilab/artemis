"""Unit tests for the entry-vs-exclusion conflict gate.

All DB-free: the vocabulary seam is ``PrefetchedVocabulary`` over hand-built
ancestor edges, so the tests exercise the real closure resolver rather than a
mock of it.

The shape under test is the measured one from
``deliveries/2026-09-12/empa-reg_comparator.circe.json``: the entry concept
(201826) is NOT a member of the excluding concept set, it arrives there as a
descendant of a member (201820). A gate comparing member ids or names as written
reports that file clean, which is why the ancestry hop is what these tests pin.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.verify_entry_exclusion_conflict import check_cohort  # noqa: E402
from src.services.conceptset_closure import PrefetchedVocabulary  # noqa: E402

# Concept ids from the real file.
T2DM = 201826  # Type 2 diabetes mellitus -- the entry concept
T2DM_OTHER = 44793113  # the entry set's second member
DM = 201820  # Diabetes mellitus -- what codeset 29 actually lists
T2DM_ULCER = 4099651  # a T2DM descendant, so also under DM
UNRELATED = 4030518  # a concept in neither branch


def vocabulary() -> PrefetchedVocabulary:
    """Valid concepts plus the ancestry that makes the conflict invisible to grep."""
    return PrefetchedVocabulary(
        concept_invalid_reason={
            cid: None for cid in (T2DM, T2DM_OTHER, DM, T2DM_ULCER, UNRELATED)
        },
        ancestor_edges={
            DM: {DM, T2DM, T2DM_OTHER, T2DM_ULCER},
            T2DM: {T2DM, T2DM_ULCER},
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
    count: int = 0,
    occurrence_type: int = 0,
) -> dict:
    return {
        "Criteria": {domain: {"CodesetId": codeset_id}},
        "StartWindow": {
            "Start": {"Days": abs(start), "Coeff": -1 if start < 0 else 1},
            "End": {"Days": abs(end), "Coeff": -1 if end < 0 else 1},
        },
        "Occurrence": {"Type": occurrence_type, "Count": count},
    }


def cohort(*, concept_sets: list[dict], rules: list[dict], entry_codeset: int = 2) -> dict:
    return {
        "ConceptSets": concept_sets,
        "PrimaryCriteria": {
            "CriteriaList": [{"ConditionOccurrence": {"CodesetId": entry_codeset, "First": True}}]
        },
        "InclusionRules": rules,
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


ENTRY_SET = concept_set(2, "Type 2 Diabetes Mellitus", item(T2DM, descendants=True),
                        item(T2DM_OTHER))


def test_should_report_fail_when_absence_set_covers_the_whole_entry_closure():
    """The measured defect: 201826 reaches codeset 29 only through 201820."""
    doc = cohort(
        concept_sets=[ENTRY_SET, concept_set(29, "Endocrine disorder", item(DM, descendants=True))],
        rules=[rule("Endocrine disorder (excluding T2DM)", absence_criterion(29))],
    )

    findings, _ = check_cohort(doc, vocabulary())

    assert [f.severity for f in findings] == ["FAIL"]
    found = findings[0]
    assert found.rule_number == 1
    assert found.codeset_id == 29
    assert found.n_overlap == found.n_entry
    assert T2DM in found.sample_ids
    # The conflict is NOT visible in the member lists themselves.
    assert DM not in {i["concept"]["CONCEPT_ID"] for i in ENTRY_SET["expression"]["items"]}


def test_should_report_warn_when_absence_set_covers_only_part_of_the_entry_closure():
    """A silent population cut, not an unsatisfiable rule."""
    doc = cohort(
        concept_sets=[ENTRY_SET, concept_set(30, "T2DM with ulcer", item(T2DM_ULCER))],
        rules=[rule("No ulcer", absence_criterion(30))],
    )

    findings, _ = check_cohort(doc, vocabulary())

    assert [f.severity for f in findings] == ["WARN"]
    assert findings[0].n_overlap == 1
    assert findings[0].n_entry > 1
    assert 0.0 < findings[0].fraction < 1.0


def test_should_report_nothing_when_the_absence_set_is_disjoint_from_the_entry():
    doc = cohort(
        concept_sets=[ENTRY_SET,
                      concept_set(31, "Something else", item(UNRELATED, descendants=True))],
        rules=[rule("No something else", absence_criterion(31))],
    )

    findings, _ = check_cohort(doc, vocabulary())

    assert findings == []


def test_should_downgrade_to_warn_when_the_window_excludes_index_day():
    """A washout ending at -1d can be satisfied by a patient whose first event is index."""
    doc = cohort(
        concept_sets=[ENTRY_SET, concept_set(29, "Endocrine disorder", item(DM, descendants=True))],
        rules=[rule("Prior endocrine disorder", absence_criterion(29, start=-7, end=-1))],
    )

    findings, _ = check_cohort(doc, vocabulary())

    assert [f.severity for f in findings] == ["WARN"]
    assert findings[0].covers_index is False
    assert findings[0].n_overlap == findings[0].n_entry


def test_should_downgrade_to_warn_when_the_criterion_sits_under_a_non_all_group():
    """Under ANY, a sibling branch can still satisfy the rule."""
    doc = cohort(
        concept_sets=[ENTRY_SET, concept_set(29, "Endocrine disorder", item(DM, descendants=True))],
        rules=[rule("Either branch", absence_criterion(29), group_type="ANY")],
    )

    findings, _ = check_cohort(doc, vocabulary())

    assert [f.severity for f in findings] == ["WARN"]
    assert findings[0].conjunctive is False


def test_should_ignore_a_presence_criterion_that_names_the_entry_concepts():
    """`Occurrence {Type: 2, Count: 1}` is a requirement, not an exclusion."""
    doc = cohort(
        concept_sets=[ENTRY_SET, concept_set(29, "Endocrine disorder", item(DM, descendants=True))],
        rules=[rule("Has an endocrine disorder",
                    absence_criterion(29, occurrence_type=2, count=1))],
    )

    findings, _ = check_cohort(doc, vocabulary())

    assert findings == []
