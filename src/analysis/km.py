"""
Kaplan-Meier survival analysis.
Phase 3.4: Survival curve estimation.
"""
import numpy as np
from typing import Optional, List
from dataclasses import dataclass


class KaplanMeierAnalysis:
    """Kaplan-Meier survival curve estimator."""
    
    def __init__(self):
        self.km_fitter = None
        self.is_fitted = False
        self.label = "Survival"
    
    def fit(
        self, 
        times: List[float], 
        events: List[int],
        label: str = "Survival"
    ) -> 'KaplanMeierAnalysis':
        """
        Fit Kaplan-Meier estimator.
        
        Args:
            times: Duration/time values
            events: Event indicators (1=event, 0=censored)
            label: Label for the survival curve
            
        Returns:
            self
        """
        from lifelines import KaplanMeierFitter
        
        self.km_fitter = KaplanMeierFitter()
        self.km_fitter.fit(times, events, label=label)
        self.label = label
        self.is_fitted = True
        return self
    
    def survival_function_at(self, time: float) -> float:
        """
        Get survival probability at a specific time.
        
        Args:
            time: Timepoint to evaluate
            
        Returns:
            Survival probability
        """
        if not self.is_fitted:
            raise RuntimeError("Not fitted. Call fit() first.")
        
        sf = self.km_fitter.survival_function_at_times([time])
        return float(sf.values[0])
    
    def median_survival(self) -> Optional[float]:
        """Get median survival time."""
        if not self.is_fitted:
            raise RuntimeError("Not fitted.")
        return self.km_fitter.median_survival_time_
    
    def survival_function(self):
        """Get full survival function as DataFrame."""
        if not self.is_fitted:
            raise RuntimeError("Not fitted.")
        return self.km_fitter.survival_function_
    
    def confidence_interval(self):
        """Get confidence interval for survival function."""
        if not self.is_fitted:
            raise RuntimeError("Not fitted.")
        return self.km_fitter.confidence_interval_


@dataclass
class KMComparisonResult:
    """Result of comparing two KM curves."""
    logrank_statistic: float
    p_value: float
    significant: bool  # p < 0.05


def compare_survival_curves(
    times_1: List[float], events_1: List[int],
    times_2: List[float], events_2: List[int]
) -> KMComparisonResult:
    """
    Compare two survival curves using log-rank test.
    
    Args:
        times_1, events_1: First group survival data
        times_2, events_2: Second group survival data
        
    Returns:
        KMComparisonResult with test statistic and p-value
    """
    from lifelines.statistics import logrank_test
    
    result = logrank_test(times_1, times_2, events_1, events_2)
    
    return KMComparisonResult(
        logrank_statistic=result.test_statistic,
        p_value=result.p_value,
        significant=result.p_value < 0.05
    )
