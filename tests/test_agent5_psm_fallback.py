"""
Agent 5 PSM fallback regression tests.

These tests pin the requested fallback order:
1. PSM with caliper=0.2
2. Retry PSM with caliper=0.5
3. Fall back to IPTW if both calipers fail
"""
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

import src.analysis.propensity as propensity_module
from src.agents.agent5.workflow import Agent5Workflow


def _make_synthetic_data(
    n_treated: int = 200,
    n_control: int = 200,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate a reproducible synthetic analysis dataset."""
    rng = np.random.RandomState(seed)
    n = n_treated + n_control
    treatment = np.array([1] * n_treated + [0] * n_control)

    age = np.concatenate([
        rng.normal(62, 8, n_treated),
        rng.normal(60, 8, n_control),
    ])
    gender_male = rng.binomial(1, 0.55, n)

    times, events = [], []
    for i in range(n):
        rate = 0.001 * (1 + 0.02 * (age[i] - 60))
        if treatment[i] == 1:
            rate *= 0.8
        t = rng.exponential(1 / rate)
        if t > 365:
            times.append(365)
            events.append(0)
        else:
            times.append(t)
            events.append(1)

    return pd.DataFrame({
        "person_id": range(n),
        "treatment": treatment,
        "age": age,
        "gender_male": gender_male.astype(float),
        "time": times,
        "event": events,
    })


def _make_workflow() -> Agent5Workflow:
    workflow = Agent5Workflow()
    workflow.configure(target_cohort_id=1, comparator_cohort_id=2, analysis_method="PSM")
    return workflow


def test_psm_succeeds_on_first_try_preserves_analysis_method():
    data = _make_synthetic_data()

    result = _make_workflow().run(data=data)

    assert "analysis_method" in result
    assert str(result["analysis_method"]) == "PSM"
    assert result["n_matched_pairs"] > 0


def test_psm_retries_with_wider_caliper_before_fallback():
    data = _make_synthetic_data()
    real_matcher_cls = propensity_module.PropensityMatcher
    seen_calipers = []

    def matcher_factory(caliper: float, ratio: int):
        seen_calipers.append(caliper)
        if caliper == 0.2:
            matcher = MagicMock()
            matcher.match.return_value = []
            return matcher
        return real_matcher_cls(caliper=caliper, ratio=ratio)

    with patch.object(propensity_module, "PropensityMatcher", side_effect=matcher_factory):
        result = _make_workflow().run(data=data)

    assert seen_calipers == [0.2, 0.5]
    assert "analysis_method" in result
    assert str(result["analysis_method"]) == "PSM"
    assert result["n_matched_pairs"] > 0


def test_psm_falls_back_to_iptw_after_both_calipers_fail():
    data = _make_synthetic_data()
    seen_calipers = []

    def matcher_factory(caliper: float, ratio: int):
        seen_calipers.append(caliper)
        matcher = MagicMock()
        matcher.match.return_value = []
        return matcher

    with patch.object(propensity_module, "PropensityMatcher", side_effect=matcher_factory):
        result = _make_workflow().run(data=data)

    assert seen_calipers == [0.2, 0.5]
    assert "analysis_method" in result
    assert str(result["analysis_method"]) == "IPTW (PSM fallback)"
    assert "n_matched_pairs" not in result
