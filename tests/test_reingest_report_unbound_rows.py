"""Which re-ingested rows the report prints as "states a reference bound, carries none".

The print used to fire on a regex over the row's description (``ULN`` / "upper limit of
normal"), a word rule (AGENTS.md § PROMPTS AND TEXT RULES). It now reads the row's
verified annotation: ``reference_bound`` uln/lln with its ``threshold_span`` re-checked
against ``protocolLine`` (`criterion_annotation.stated_threshold`). The description is
not read.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.reingest_protocol_pdfs import report  # noqa: E402

FLAG = "! no valueConstraint"


def _study(row: dict) -> dict:
    return {"eligibility": {"inclusionCriteria": [row], "exclusionCriteria": []}}


def test_should_flag_a_row_without_a_value_when_its_annotation_states_a_reference_bound(
    capsys: pytest.CaptureFixture[str],
) -> None:
    row = {
        "description": "Liver enzymes",
        "protocolLine": "ALT > 3 x ULN",
        "annotation": {
            "threshold_span": "> 3 x ULN",
            "quantity_kind": "lab_value",
            "reference_bound": "uln",
        },
    }

    report("after", _study(row))

    assert FLAG in capsys.readouterr().out


def test_should_not_flag_a_row_when_only_its_description_names_the_upper_limit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    row = {"description": "ALT above the upper limit of normal (ULN)"}

    report("after", _study(row))

    assert FLAG not in capsys.readouterr().out


def test_should_not_flag_a_row_whose_annotation_states_an_absolute_bound(
    capsys: pytest.CaptureFixture[str],
) -> None:
    row = {
        "description": "Platelets",
        "protocolLine": "Platelets < 100,000/mm3",
        "annotation": {
            "threshold_span": "< 100,000/mm3",
            "quantity_kind": "lab_value",
            "reference_bound": "none",
        },
    }

    report("after", _study(row))

    assert FLAG not in capsys.readouterr().out
