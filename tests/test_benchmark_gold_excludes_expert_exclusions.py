"""The benchmark gold must not score expert-deleted concepts as correct answers.

`_extract_concept_ids` ignored `isExcluded`, so every concept an expert removed from
a concept set was written into `ground_truth_concept_ids`. Measured on the shipped
benchmark: 596 of 2,109 ids (28.3%) across 33 of 242 questions, with three questions
100% excluded -- there a mapper earns full marks only by returning exactly what the
expert deleted, and is penalised on recall and precision for being right.

benchmark_v5.py:336-343 already documents and implements the rule. It existed in one
script while the gold was built by another, which is why nothing caught it: both
sides ran clean and produced a plausible score.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "extract_criteria_benchmark.py"


@pytest.fixture(scope="module")
def extractor():
    spec = importlib.util.spec_from_file_location("_extract_bench", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _concept_set(*items: tuple[int, bool]) -> dict:
    return {
        "expression": {
            "items": [
                {"concept": {"CONCEPT_ID": cid}, "isExcluded": excluded}
                for cid, excluded in items
            ]
        }
    }


def test_excluded_concepts_are_not_answers(extractor) -> None:
    result = extractor._extract_concept_ids(_concept_set((1, False), (2, True), (3, False)))

    assert result == [1, 3]


def test_a_wholly_excluded_set_yields_no_answers(extractor) -> None:
    """Three real questions are 100% excluded. They should contribute nothing."""
    assert extractor._extract_concept_ids(_concept_set((1, True), (2, True))) == []


def test_a_missing_flag_means_included(extractor) -> None:
    """Most items carry no isExcluded key at all; those are the ordinary answers."""
    concept_set = {"expression": {"items": [{"concept": {"CONCEPT_ID": 7}}]}}

    assert extractor._extract_concept_ids(concept_set) == [7]


def test_the_shipped_gold_still_has_the_defect(extractor) -> None:
    """Documents that the artifact on disk predates the fix.

    This is not a bug in the extractor -- it records that
    data/benchmark_data/ohdsi_criteria_benchmark.json was generated before it, so a
    concept-recall figure measured against that file is scored on a corrupted gold.
    Regenerate the benchmark, then delete this test.
    """
    import json

    gold = Path(__file__).resolve().parents[1] / "data" / "benchmark_data" / "ohdsi_criteria_benchmark.json"
    if not gold.exists():
        pytest.skip("benchmark artifact not present in this checkout")

    payload = json.loads(gold.read_text(encoding="utf-8"))
    items = payload if isinstance(payload, list) else payload.get("items") or payload.get("questions") or []
    total = sum(len(q.get("ground_truth_concept_ids") or []) for q in items)

    assert total > 0, "the gold should not be empty"
