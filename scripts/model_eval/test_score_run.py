#!/usr/bin/env python3
"""Self-check for the scoring logic. Run: python scripts/model_eval/test_score_run.py

Covers the parts that are not obvious by inspection: gold-name normalisation,
the Circe walkers, the hierarchy relation ladder, and JSON schema detection.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_model import _json_status  # noqa: E402
from score_run import (  # noqa: E402
    Hierarchy,
    align_terms,
    all_concept_ids,
    concept_sets,
    entry_domain,
    jaccard,
    normalize_name,
    relation_profile,
    value_constraints,
)


class FakeHierarchy:
    """(ancestor, descendant) pairs and direct parents, no database."""

    def __init__(self, pairs: set[tuple[int, int]], parents: dict[int, set[int]]) -> None:
        self.pairs = pairs
        self.parents = parents
        self.names = {}

    relation = Hierarchy.relation  # exercise the real ladder, fake the tables


def cohort(sets: list[tuple[str, list[int]]], entry: str = "DrugEra", extra: dict | None = None) -> dict:
    return {
        "PrimaryCriteria": {"CriteriaList": [{entry: {}}]},
        "ConceptSets": [
            {"id": i, "name": name,
             "expression": {"items": [{"concept": {"CONCEPT_ID": c}} for c in ids]}}
            for i, (name, ids) in enumerate(sets)
        ],
        **(extra or {}),
    }


def test_gold_name_normalisation_strips_curation_bookkeeping() -> None:
    assert normalize_name("[TROY condition] Ischemic stroke") == normalize_name("ischemic stroke")
    assert normalize_name("COPY OF: [TROY] History of malignant neoplasm") == \
        normalize_name("malignant neoplasm")
    assert normalize_name("proliferative retinopathy_cond") == normalize_name("Proliferative Retinopathy")
    # A gold name and an unrelated generated name must not collide.
    assert jaccard(normalize_name("linagliptin"), normalize_name("metformin")) == 0.0


def test_circe_walkers() -> None:
    c = cohort([("a", [1, 2]), ("b", [2, 3])], entry="ConditionOccurrence")
    assert all_concept_ids(c) == {1, 2, 3}
    assert entry_domain(c) == "ConditionOccurrence"
    assert entry_domain(cohort([])) == "DrugEra"


def test_value_constraints_counted_by_constrained_field() -> None:
    circe = {"InclusionRules": [
        {"expression": {"Criteria": {"Measurement": {"ValueAsNumber": {"Op": "gt", "Value": 7}}}}},
        {"expression": {"Criteria": {"ConditionOccurrence": {"Age": {"Op": "gte", "Value": 18}}}}},
    ]}
    assert value_constraints(circe) == {"ValueAsNumber": 1, "Age": 1}
    assert value_constraints({"a": 1}) == {}


def test_relation_ladder_orders_exact_over_descendant_over_sibling() -> None:
    # 10 is gold; 11 is its child; 12 is 11's sibling; 99 is disconnected.
    h = FakeHierarchy(pairs={(10, 11), (10, 12)}, parents={11: {10}, 12: {10}, 99: {77}})
    gold = {10}
    assert h.relation(10, gold) == "exact"
    assert h.relation(11, gold) == "descendant"
    assert h.relation(99, gold) == "unrelated"
    # sibling only fires when neither exact nor an ancestor path exists
    h2 = FakeHierarchy(pairs=set(), parents={11: {10}, 12: {10}})
    assert h2.relation(12, {11}) == "sibling"


def test_relation_profile_flags_the_wrong_compound_case() -> None:
    # The BI 10773 defect shape: nothing generated is anywhere near gold.
    h = FakeHierarchy(pairs=set(), parents={})
    profile = relation_profile({500}, {10}, h)
    assert profile["unrelated_rate"] == 1.0
    assert profile["exact_rate"] == 0.0
    assert profile["gold_recall"] == 0.0
    good = relation_profile({10}, {10}, h)
    assert good["exact_rate"] == 1.0 and good["gold_recall"] == 1.0


def test_alignment_reports_unmatched_on_both_sides() -> None:
    h = FakeHierarchy(pairs=set(), parents={})
    gold = cohort([("[TROY condition] Ischemic stroke", [10]), ("[TROY lab] eGFR", [20])])
    gen = cohort([("Ischemic Stroke", [10]), ("Body Mass Index", [30])])
    out = align_terms(concept_sets(gold), concept_sets(gen), 0.34, h)
    assert out["aligned_terms"] == 1
    assert out["pairs"][0]["align_score"] == 1.0
    assert out["pairs"][0]["any_exact"] is True
    assert out["gold_unmatched"] == ["[TROY lab] eGFR"]
    assert out["gen_unmatched"] == ["Body Mass Index"]


def test_json_status_separates_first_try_from_repaired() -> None:
    assert _json_status('{"a": 1}') == (True, True)
    assert _json_status('```json\n{"a": 1}\n```') == (False, True)
    assert _json_status('Sure! Here you go: {"a": 1}') == (False, True)
    assert _json_status("I cannot help with that.") == (False, False)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all scoring self-checks passed")
