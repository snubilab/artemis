"""The legacy arm has to reproduce the defect, not approximate it.

If ``legacy_value_filter`` quietly emitted RangeHighRatio for a ULN bound, the A/B
would show no difference and read as "the fix changed nothing" — the one conclusion
the benchmark exists to rule out.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from src.models.ir import ValueConstraint
from src.services.value_constraint import build_measurement_value_filter

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_value_constraint_arms.py"


@pytest.fixture(scope="module")
def harness():
    spec = importlib.util.spec_from_file_location("_arms", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _uln() -> ValueConstraint:
    """ALT > 3x the upper limit of normal."""
    return ValueConstraint(value=3.0, op="gt", reference_bound="uln", unit_text=None)


def _absolute() -> ValueConstraint:
    """HbA1c > 7 %."""
    return ValueConstraint(value=7.0, op="gt", reference_bound="absolute", unit_text="%")


def test_the_arms_disagree_on_a_uln_bound(harness) -> None:
    fixed = build_measurement_value_filter(_uln())
    legacy = harness.legacy_value_filter(_uln())

    assert "RangeHighRatio" in fixed
    assert "ValueAsNumber" not in fixed

    # The defect: 3x ULN becomes an absolute 3, which every patient exceeds.
    assert legacy == {"ValueAsNumber": {"Value": 3.0, "Op": "gt"}}


def test_the_arms_agree_on_an_absolute_threshold(harness) -> None:
    """Only ratio bounds are allowed to differ; anything else is arm contamination."""
    fixed = build_measurement_value_filter(_absolute())
    legacy = harness.legacy_value_filter(_absolute())

    assert fixed["ValueAsNumber"] == {"Value": 7.0, "Op": "gt"}
    assert legacy["ValueAsNumber"]["Value"] == 7.0
    assert legacy["ValueAsNumber"]["Op"] == "gt"


def test_legacy_nests_unit_inside_value_as_number(harness) -> None:
    """Where Circe ignores it — the second half of the defect."""
    legacy = harness.legacy_value_filter(_absolute())
    assert legacy["ValueAsNumber"]["Unit"] == 8554  # percent
    assert "Unit" not in legacy


def test_fixed_arm_puts_unit_beside_value_as_number(harness) -> None:
    fixed = build_measurement_value_filter(_absolute())
    assert "Unit" in fixed
    assert "Unit" not in fixed["ValueAsNumber"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ALT > 3x ULN", "uln"),
        ("AST greater than 3 times the upper limit of normal", "uln"),
        ("haemoglobin < 0.8x LLN", "lln"),
        ("HbA1c > 7%", None),
        ("", None),
    ],
)
def test_expected_bound_reads_the_criterion_text(harness, text: str, expected) -> None:
    assert harness.expected_bound(text) == expected


def test_unusable_constraint_yields_no_fragment(harness) -> None:
    """A malformed value must not become a filter that matches nothing."""
    assert harness.legacy_value_filter(None) == {}
    assert build_measurement_value_filter(None) == {}
