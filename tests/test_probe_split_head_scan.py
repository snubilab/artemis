"""The --split scan must count the thing ADR-032 made a precondition for gate G1.

ADR-032 measured head omission at 0.1% in ClinicalTrials.gov source text and then
said the number that matters is the one *after* stage 1 splits a sentence, because
that is where `ALT, AST, or ALP > 3x ULN` loses its head. These tests pin the two
ways that scan could silently report a comforting zero:

  - counting group-label rows, which carry no threshold and would inflate the
    denominator, pushing the ratio down; and
  - failing to flag a fragment that really is headless, which would report 0
    regardless of the input.

The measured answer on the store was 0 headless out of 36 distinct
threshold-bearing fragments. A zero is only worth reporting if the scan can
produce a non-zero, so the second test feeds it a fragment that must be flagged.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ARTEMIS_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ARTEMIS_DIR / "scripts" / "probe_criterion_classifier.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("probe_criterion_classifier", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


MODULE = _load_module()


def _store(criteria: list[dict]) -> dict:
    return {"studies": {"1": {"eligibility": {"inclusionCriteria": criteria}}}}


def _run(tmp_path: Path, criteria: list[dict], capsys) -> str:
    path = tmp_path / "store.json"
    path.write_text(json.dumps(_store(criteria)))
    MODULE.split_head_frequency(path)
    return capsys.readouterr().out


def test_group_labels_are_not_counted_as_fragments(tmp_path, capsys):
    # A group label is a heading, not a criterion: it has no threshold of its own
    # and including it would dilute the denominator the ratio is computed against.
    out = _run(tmp_path, [
        {"description": "Cv Risk (OR group)", "isGroupLabel": True, "valueConstraint": None},
        {"description": "HbA1c >= 7.0%", "valueConstraint": {"op": "gte", "value": 7.0}},
    ], capsys)

    assert "stage-1 fragments (group labels excluded): 1" in out


def test_a_headless_fragment_is_flagged(tmp_path, capsys):
    # The exact shape ADR-032 exists to catch: the analyte name is gone and only
    # the comparator, the numeral and a unit are left.
    out = _run(tmp_path, [
        {"description": "> 1500/mm3", "valueConstraint": {"op": "gt", "value": 1500.0}},
    ], capsys)

    assert "comparator+numeral        1/1 (100.0%)" in out
    assert "distinct threshold-bearing fragments (the number to quote)  1/1 (100.0%)" in out


def test_a_fragment_that_kept_its_head_is_not_flagged(tmp_path, capsys):
    # The post-split case that actually occurs in the store: stage 1 redistributed
    # the analyte name onto each fragment rather than dropping it.
    out = _run(tmp_path, [
        {"description": "ALT > 3x ULN", "valueConstraint": {"op": "gt", "value": 3.0}},
    ], capsys)

    assert "comparator+numeral        0/1 (0.0%)" in out
