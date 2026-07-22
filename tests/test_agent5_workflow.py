"""
Agent 5 Workflow integration tests.

Tests the full Agent5Workflow pipeline with synthetic data.
- Test A: IPTW mode returns expected result structure
- Test B: PSM mode returns matched-pair results
- Test C: Weighted balance improves (or doesn't worsen) SMD
- Test D: No-connector raises RuntimeError
"""
import pytest
import numpy as np
import pandas as pd

from src.agents.agent5.workflow import Agent5Workflow, AnalysisConfig


def _make_synthetic_data(
    n_treated: int = 200,
    n_control: int = 200,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate a reproducible synthetic analysis dataset."""
    rng = np.random.RandomState(seed)
    n = n_treated + n_control
    treatment = np.array([1] * n_treated + [0] * n_control)

    # Age: slight imbalance (treated ~62, control ~60)
    age = np.concatenate([
        rng.normal(62, 8, n_treated),
        rng.normal(60, 8, n_control),
    ])
    gender_male = rng.binomial(1, 0.55, n)

    # Survival: treatment has protective effect (HR ≈ 0.8)
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


class TestAgent5IPTW:
    """IPTW mode end-to-end."""

    @pytest.fixture
    def data(self):
        return _make_synthetic_data()

    @pytest.fixture
    def workflow(self):
        wf = Agent5Workflow()
        wf.configure(target_cohort_id=1, comparator_cohort_id=2, analysis_method="IPTW")
        return wf

    def test_iptw_returns_expected_keys(self, workflow, data):
        result = workflow.run(data=data)
        expected = {
            "hazard_ratio", "balance", "ps_scores", "weights",
            "treatment", "analysis_method", "survival_data",
            "n_target", "n_comparator",
        }
        assert expected.issubset(result.keys())

    def test_iptw_hazard_ratio_structure(self, workflow, data):
        result = workflow.run(data=data)
        hr = result["hazard_ratio"]
        assert "hr" in hr and "ci_lower" in hr and "ci_upper" in hr and "p_value" in hr
        assert hr["ci_lower"] <= hr["hr"] <= hr["ci_upper"]

    def test_iptw_analysis_method_tag(self, workflow, data):
        result = workflow.run(data=data)
        assert result["analysis_method"] == "IPTW"

    def test_iptw_n_counts(self, workflow, data):
        result = workflow.run(data=data)
        assert result["n_target"] == 200
        assert result["n_comparator"] == 200

    def test_iptw_balance_has_before_and_after(self, workflow, data):
        result = workflow.run(data=data)
        for col, bal in result["balance"].items():
            assert "smd_before" in bal
            assert "smd_after" in bal


class TestAgent5PSM:
    """PSM mode end-to-end."""

    @pytest.fixture
    def data(self):
        return _make_synthetic_data()

    @pytest.fixture
    def workflow(self):
        wf = Agent5Workflow()
        wf.configure(target_cohort_id=1, comparator_cohort_id=2, analysis_method="PSM")
        return wf

    def test_psm_returns_matched_pairs_count(self, workflow, data):
        result = workflow.run(data=data)
        assert "n_matched_pairs" in result
        assert result["n_matched_pairs"] > 0

    def test_psm_analysis_method_tag(self, workflow, data):
        result = workflow.run(data=data)
        assert result["analysis_method"] == "PSM"

    def test_psm_n_target_equals_n_comparator(self, workflow, data):
        """1:1 matching → equal group sizes."""
        result = workflow.run(data=data)
        assert result["n_target"] == result["n_comparator"]

    def test_psm_hazard_ratio_valid(self, workflow, data):
        result = workflow.run(data=data)
        hr = result["hazard_ratio"]
        assert hr["hr"] > 0
        assert hr["ci_lower"] <= hr["hr"] <= hr["ci_upper"]


class TestAgent5Mahalanobis:
    """Mahalanobis mode end-to-end."""

    @pytest.fixture
    def data(self):
        return _make_synthetic_data()

    @pytest.fixture
    def workflow(self):
        wf = Agent5Workflow()
        wf.configure(target_cohort_id=1, comparator_cohort_id=2, analysis_method="MAHALANOBIS")
        return wf

    def test_mahalanobis_returns_matched_pairs_count(self, workflow, data):
        result = workflow.run(data=data)
        assert "n_matched_pairs" in result
        assert result["n_matched_pairs"] > 0

    def test_mahalanobis_analysis_method_tag(self, workflow, data):
        result = workflow.run(data=data)
        assert result["analysis_method"] == "MAHALANOBIS"

    def test_mahalanobis_n_target_equals_n_comparator(self, workflow, data):
        result = workflow.run(data=data)
        assert result["n_target"] == result["n_comparator"]


class TestWeightedBalance:
    """Verify weighted balance is computed correctly (not just copied)."""

    def test_weighted_smd_different_from_raw(self):
        """After weighting, SMD should generally differ from before."""
        data = _make_synthetic_data(n_treated=300, n_control=300, seed=123)
        wf = Agent5Workflow()
        wf.configure(target_cohort_id=1, comparator_cohort_id=2, analysis_method="IPTW")
        result = wf.run(data=data)

        # At least one covariate should have different before/after SMD
        any_different = any(
            abs(b["smd_before"] - b["smd_after"]) > 1e-6
            for b in result["balance"].values()
        )
        assert any_different, "Weighted balance should differ from raw balance"


class TestExtractFeaturesGuard:
    """Verify _extract_features error handling."""

    def test_no_connector_raises(self):
        wf = Agent5Workflow(connector=None)
        wf.configure(target_cohort_id=1, comparator_cohort_id=2)
        with pytest.raises(RuntimeError, match="No OMOPConnector"):
            wf.run()

    def test_no_config_raises(self):
        wf = Agent5Workflow(connector="fake")
        with pytest.raises(RuntimeError, match="configure"):
            wf.run()
