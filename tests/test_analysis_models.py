"""
Unit tests for Phase 3.3-3.4: Propensity Score & Cox Regression.
TDD: Tests written BEFORE implementation.
"""
import pytest
import numpy as np


class TestPropensityScore:
    """Tests for propensity score estimation."""
    
    def test_ps_model_fit(self):
        """Propensity score model should fit on covariates."""
        from src.analysis.propensity import PropensityScoreModel
        
        # Synthetic data
        X = np.array([[1, 0, 0], [0, 1, 0], [1, 1, 0], [0, 0, 1]])
        y = np.array([1, 0, 1, 0])  # Treatment assignment
        
        model = PropensityScoreModel()
        model.fit(X, y)
        
        assert model.is_fitted
    
    def test_ps_predict_probabilities(self):
        """PS model should predict probabilities between 0 and 1."""
        from src.analysis.propensity import PropensityScoreModel
        
        X = np.random.randn(100, 5)
        y = np.random.binomial(1, 0.5, 100)
        
        model = PropensityScoreModel()
        model.fit(X, y)
        ps_scores = model.predict(X)
        
        assert all(0 <= p <= 1 for p in ps_scores)
    
    def test_psm_matching(self):
        """PSM should create matched pairs."""
        from src.analysis.propensity import PropensityMatcher
        
        ps_treated = np.array([0.3, 0.5, 0.7])
        ps_control = np.array([0.32, 0.48, 0.72, 0.1])
        
        matcher = PropensityMatcher(caliper=0.05)
        matched_pairs = matcher.match(ps_treated, ps_control)
        
        # Should match at least some pairs
        assert len(matched_pairs) > 0
    
    def test_iptw_weights(self):
        """IPTW should calculate inverse probability weights."""
        from src.analysis.propensity import calculate_iptw_weights
        
        ps_scores = np.array([0.3, 0.7, 0.5])
        treatment = np.array([1, 0, 1])  # 1=treated, 0=control
        
        weights = calculate_iptw_weights(ps_scores, treatment)
        
        # Treated: 1/PS, Control: 1/(1-PS)
        assert weights[0] == pytest.approx(1/0.3, rel=0.01)
        assert weights[1] == pytest.approx(1/(1-0.7), rel=0.01)


class TestBalanceDiagnostics:
    """Tests for covariate balance checking."""
    
    def test_smd_calculation(self):
        """Calculate Standardized Mean Difference."""
        from src.analysis.balance import calculate_smd
        
        treated_values = np.array([10, 12, 11, 13])
        control_values = np.array([8, 9, 10, 7])
        
        smd = calculate_smd(treated_values, control_values)
        
        # SMD should be > 0 since treated > control
        assert smd > 0
    
    def test_balance_report(self):
        """Generate balance report for all covariates."""
        from src.analysis.balance import BalanceChecker
        
        covariates = {
            "age": {"treated": [65, 70, 68], "control": [64, 69, 67]},
            "bmi": {"treated": [25, 30, 28], "control": [24, 29, 27]}
        }
        
        checker = BalanceChecker()
        report = checker.check(covariates)
        
        assert "age" in report
        assert "bmi" in report
        assert "smd" in report["age"]


class TestCoxRegression:
    """Tests for Cox Proportional Hazards model."""
    
    def test_cox_model_fit(self):
        """Cox model should fit on survival data."""
        from src.analysis.cox import CoxModel
        
        model = CoxModel()
        
        # Minimal check: model should have fit method
        assert hasattr(model, 'fit')
    
    def test_hazard_ratio_extraction(self):
        """Extract Hazard Ratio with confidence interval."""
        from src.analysis.cox import CoxModel
        import pandas as pd
        
        # Synthetic survival data
        df = pd.DataFrame({
            'time': [100, 200, 150, 300, 250],
            'event': [1, 0, 1, 0, 1],
            'treatment': [1, 0, 1, 0, 1],
            'age': [65, 70, 55, 60, 75]
        })
        
        model = CoxModel()
        model.fit(df, duration_col='time', event_col='event')
        
        results = model.get_hazard_ratio('treatment')
        
        assert 'hr' in results
        assert 'ci_lower' in results
        assert 'ci_upper' in results
        assert 'p_value' in results


class TestKaplanMeier:
    """Tests for Kaplan-Meier survival curves."""
    
    def test_km_fit(self):
        """KM fitter should fit survival data."""
        from src.analysis.km import KaplanMeierAnalysis
        
        times = [10, 20, 30, 40, 50]
        events = [1, 1, 0, 1, 0]
        
        km = KaplanMeierAnalysis()
        km.fit(times, events)
        
        assert km.is_fitted
    
    def test_km_survival_function(self):
        """Get survival probability at timepoints."""
        from src.analysis.km import KaplanMeierAnalysis
        
        times = [10, 20, 30, 40, 50]
        events = [1, 1, 0, 1, 0]
        
        km = KaplanMeierAnalysis()
        km.fit(times, events)
        
        survival_at_30 = km.survival_function_at(30)
        
        assert 0 <= survival_at_30 <= 1
