"""A measured bound whose extraction dropped the unit takes it from its own verified threshold span.

Agent 1 wrote ``unitText: ''`` on four P8 MAIN (2026-10-20) rows whose protocol line states the
unit right after the number, and the annotation step's ``threshold_span`` -- span-checked against
that line -- quotes it:

* CARMELINA inclusion 15, "HbA1c of >= 6.5% and <= 10.0%": the range conversion declined ("the
  criterion states no unit"), so the file kept "at least 1 HbA1c in 6.5..10.0" (check (v)).
* CAROLINA inclusion 25, "BMI <= 45 kg/m2": the same decline, check (v).
* CAROLINA inclusion 44 (label of 45), "BMI =< 45kg/m²": the label's bound resolved to no unit, so
  the hand-down stranded member 45 (check (i), ``stranded-group-threshold``).
* CAROLINA inclusion 22, "SBP > 140 mmHg": emitted as a bare number (check (q)).

Format only: the characters right after the bound's own number in the span, accepted only when
they resolve to a UCUM unit through :func:`normalize_unit` -- the table every unit already goes
through. No word is read. Real rows: ``tests/fixtures/p8_unit_dropped_rows.json``.
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from src.services.criterion_annotation import applied_value_constraint

ROWS: dict[str, Any] = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "p8_unit_dropped_rows.json").read_text()
)


@pytest.mark.parametrize(
    ("row", "unit"),
    [
        (ROWS["carmelina_inclusion_15"], "%"),
        (ROWS["carolina_inclusion_25"], "kg/m2"),
        (ROWS["carolina_inclusion_44_45"][0], "kg/m²"),
        (ROWS["carolina_inclusion_22"], "mmHg"),
    ],
    ids=["carmelina-15-hba1c", "carolina-25-bmi", "carolina-44-bmi-label", "carolina-22-sbp"],
)
def test_should_take_the_unit_the_span_states_after_the_bound(row, unit):
    assert applied_value_constraint(row)["unitText"] == unit


def test_should_leave_a_bound_whose_span_states_no_unit_unitless():
    """EMPA-REG inclusion 12, "Body Mass index <= 45 at Visit 1": the protocol states none."""
    assert applied_value_constraint(ROWS["empareg_inclusion_12"])["unitText"] == ""


def test_should_leave_an_age_bound_alone():
    """CARMELINA inclusion 16 "Age >= 18 years": built as a CIRCE Age, which carries no unit."""
    assert applied_value_constraint(ROWS["carmelina_inclusion_16"])["unitText"] == ""


def test_should_not_invent_a_unit_the_table_does_not_resolve():
    row = deepcopy(ROWS["carmelina_inclusion_15"])
    row["protocolLine"] = "6. HbA1c of ≥ 6.5 foo and ≤ 10.0 foo at Visit 1 (screening)"
    row["annotation"]["threshold_span"] = "≥ 6.5 foo and ≤ 10.0 foo"

    assert applied_value_constraint(row)["unitText"] == ""


def test_should_keep_a_unit_extraction_already_wrote():
    row = deepcopy(ROWS["carolina_inclusion_25"])
    row["valueConstraint"]["unitText"] = "kg/m2"

    assert applied_value_constraint(row) == {**row["valueConstraint"], "referenceBound": "absolute"}
