"""
Agent 5 PSM → IPTW fallback tests.

Verifies that when PSM produces 0 matched pairs:
  1. caliper=0.2 → 0 pairs: widen to caliper=0.5
  2. caliper=0.5 → 0 pairs: fall back to IPTW automatically
  3. The returned result carries analysis_method == "IPTW (PSM fallback)"
"""
import logging
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd
import pytest

from src.agents.agent5.workflow import Agent5Workflow


def _make_separable_data(n: int = 100, seed: int = 7) -> pd.DataFrame:
    """
    Synthetic data where treated and control PS scores are completely
    non-overlapping so caliper=0.2 AND caliper=0.5 both produce 0 pairs.

    Treated PS ~ Uniform(0.8, 1.0), Control PS ~ Uniform(0.0, 0.2).
    """
    rng = np.random.RandomState(seed)
    half = n // 2
    treatment = np.array([1] * half + [0] * half)
    # Age: treated older to drive PS separation
    age = np.concatenate([
        rng.uniform(75, 90, half),
        rng.uniform(20, 35, half),
    ])
    gender_male = rng.binomial(1, 0.5, n).astype(float)
    times = rng.uniform(10, 365, n)
    events = rng.binomial(1, 0.3, n).astype(float)
    return pd.DataFrame({
        "person_id": range(n),
        "treatment": treatment,
        "age": age,
        "gender_male": gender_male,
        "time": times,
        "event": events,
    })


def _make_normal_data(n_treated: int = 200, n_control: int = 200, seed: int = 42) -> pd.DataFrame:
    """Normal data where PSM with caliper=0.5 does produce matches."""
    rng = np.random.RandomState(seed)
    n = n_treated + n_control
    treatment = np.array([1] * n_treated + [0] * n_control)
    age = np.concatenate([
        rng.normal(62, 8, n_treated),
        rng.normal(60, 8, n_control),
    ])
    gender_male = rng.binomial(1, 0.55, n).astype(float)
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
        "gender_male": gender_male,
        "time": times,
        "event": events,
    })


class TestPSMFallbackToIPTW:
    """When both caliper widths fail, workflow must silently switch to IPTW."""

    def _workflow_psm(self) -> Agent5Workflow:
        wf = Agent5Workflow()
        wf.configure(target_cohort_id=1, comparator_cohort_id=2, analysis_method="PSM")
        return wf

    def test_fallback_result_has_iptw_fallback_method_tag(self):
        """Result must declare analysis_method == 'IPTW (PSM fallback)'."""
        data = _make_separable_data()
        wf = self._workflow_psm()
        result = wf.run(data=data)
        assert result["analysis_method"] == "IPTW (PSM fallback)"

    def test_fallback_does_not_raise(self):
        """Should never raise ValueError when PSM produces 0 pairs."""
        data = _make_separable_data()
        wf = self._workflow_psm()
        # Must complete without exception
        result = wf.run(data=data)
        assert result is not None

    def test_fallback_result_has_required_keys(self):
        """Fallback result must include all IPTW result keys."""
        data = _make_separable_data()
        wf = self._workflow_psm()
        result = wf.run(data=data)
        required = {
            "hazard_ratio", "balance", "ps_scores", "weights",
            "treatment", "analysis_method", "survival_data",
            "n_target", "n_comparator",
        }
        assert required.issubset(result.keys())

    def test_fallback_hazard_ratio_is_valid(self):
        """Fallback HR must be a positive finite number with valid CI."""
        data = _make_separable_data()
        wf = self._workflow_psm()
        result = wf.run(data=data)
        hr = result["hazard_ratio"]
        assert hr["hr"] > 0
        assert np.isfinite(hr["hr"])
        assert hr["ci_lower"] <= hr["hr"] <= hr["ci_upper"]

    def test_fallback_logs_warning_caliper_02(self, caplog):
        """A warning must be emitted when caliper=0.2 produces 0 pairs."""
        data = _make_separable_data()
        wf = self._workflow_psm()
        with caplog.at_level(logging.WARNING):
            wf.run(data=data)
        assert any("caliper=0.2" in msg for msg in caplog.messages)

    def test_fallback_logs_warning_caliper_05(self, caplog):
        """A warning must be emitted when caliper=0.5 still produces 0 pairs."""
        data = _make_separable_data()
        wf = self._workflow_psm()
        with caplog.at_level(logging.WARNING):
            wf.run(data=data)
        assert any("caliper=0.5" in msg for msg in caplog.messages)

    def test_fallback_logs_iptw_fallback_message(self, caplog):
        """A warning must announce the IPTW fallback decision."""
        data = _make_separable_data()
        wf = self._workflow_psm()
        with caplog.at_level(logging.WARNING):
            wf.run(data=data)
        assert any("IPTW" in msg for msg in caplog.messages)


class TestPSMCaliperWidening:
    """When caliper=0.2 fails but caliper=0.5 succeeds, use PSM (not IPTW)."""

    def test_wider_caliper_used_when_02_produces_zero_pairs(self):
        """
        Patch PropensityMatcher at the import site inside _run_psm so that:
          - first instantiation (caliper=0.2) returns [] from match()
          - second instantiation (caliper=0.5) delegates to the real implementation
        Result should be a normal PSM result, not an IPTW fallback.
        """
        data = _make_normal_data()
        wf = Agent5Workflow()
        wf.configure(target_cohort_id=1, comparator_cohort_id=2, analysis_method="PSM")

        # PropensityMatcher is imported locally inside _run_psm via
        # `from src.analysis.propensity import PropensityMatcher`, so we
        # must patch the class on the propensity module directly.
        from src.analysis.propensity import PropensityMatcher as _RealMatcher

        call_count = {"n": 0}

        def _factory(caliper: float, ratio: int) -> MagicMock:
            call_count["n"] += 1
            instance = MagicMock()
            if call_count["n"] == 1:
                # caliper=0.2 attempt → simulate zero matches
                instance.match.return_value = []
            else:
                # caliper=0.5 attempt → use real matcher
                real = _RealMatcher(caliper=caliper, ratio=ratio)
                instance.match.side_effect = real.match
            return instance

        with patch("src.analysis.propensity.PropensityMatcher", side_effect=_factory):
            result = wf.run(data=data)

        # caliper=0.5 produced matches → standard PSM result (no IPTW fallback)
        assert result["analysis_method"] == "PSM"
        assert result["n_matched_pairs"] > 0


class TestPSMNormalBehaviorUnchanged:
    """Ensure normal PSM path (caliper=0.2 succeeds) is not affected."""

    def test_normal_psm_still_works(self):
        """caliper=0.2 produces matches → PSM result with no fallback."""
        data = _make_normal_data()
        wf = Agent5Workflow()
        wf.configure(target_cohort_id=1, comparator_cohort_id=2, analysis_method="PSM")
        result = wf.run(data=data)
        assert result["analysis_method"] == "PSM"
        assert result["n_matched_pairs"] > 0

    def test_normal_psm_no_fallback_keys(self):
        """Normal PSM result should NOT carry n_matched_pairs == 0."""
        data = _make_normal_data()
        wf = Agent5Workflow()
        wf.configure(target_cohort_id=1, comparator_cohort_id=2, analysis_method="PSM")
        result = wf.run(data=data)
        assert result.get("n_matched_pairs", 0) > 0
