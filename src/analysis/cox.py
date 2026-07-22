"""
Cox Proportional Hazards regression.
Phase 3.4: Outcome modeling with hazard ratio estimation.
"""
import pandas as pd
from typing import Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class HazardRatioResult:
    """Results from Cox model for a single covariate."""
    hr: float  # Hazard Ratio
    ci_lower: float  # 95% CI lower bound
    ci_upper: float  # 95% CI upper bound
    p_value: float
    covariate: str


class CoxModel:
    """Cox Proportional Hazards model wrapper."""
    
    def __init__(self, penalizer: float = 0.01):
        """
        Args:
            penalizer: L2 regularization strength
        """
        self.penalizer = penalizer
        self.model = None
        self.is_fitted = False
    
    def fit(
        self, 
        df: pd.DataFrame, 
        duration_col: str = 'time',
        event_col: str = 'event',
        weights_col: Optional[str] = None,
        formula: Optional[str] = None
    ) -> 'CoxModel':
        """
        Fit Cox PH model.
        
        Args:
            df: DataFrame with survival data
            duration_col: Column name for time to event
            event_col: Column name for event indicator
            weights_col: Column name for weights (IPTW)
            formula: Optional formula for covariates
            
        Returns:
            self
        """
        from lifelines import CoxPHFitter
        
        self.model = CoxPHFitter(penalizer=self.penalizer)
        
        fit_kwargs = {
            'duration_col': duration_col,
            'event_col': event_col
        }
        if weights_col:
            fit_kwargs['weights_col'] = weights_col
            fit_kwargs['robust'] = True  # Required for non-integer IPTW weights
        if formula:
            fit_kwargs['formula'] = formula
        
        self.model.fit(df, **fit_kwargs)
        self.is_fitted = True
        return self
    
    def get_hazard_ratio(self, covariate: str) -> Dict[str, float]:
        """
        Get hazard ratio for a specific covariate.
        
        Args:
            covariate: Name of covariate
            
        Returns:
            Dict with hr, ci_lower, ci_upper, p_value
        """
        if not self.is_fitted:
            raise RuntimeError("Model not fitted.")
        
        summary = self.model.summary
        
        if covariate not in summary.index:
            raise ValueError(f"Covariate '{covariate}' not in model.")
        
        row = summary.loc[covariate]
        
        return {
            'hr': row['exp(coef)'],
            'ci_lower': row['exp(coef) lower 95%'],
            'ci_upper': row['exp(coef) upper 95%'],
            'p_value': row['p']
        }
    
    def summary(self) -> pd.DataFrame:
        """Get full model summary."""
        if not self.is_fitted:
            raise RuntimeError("Model not fitted.")
        return self.model.summary
    
    def concordance_index(self) -> float:
        """Get model's concordance index (C-statistic)."""
        if not self.is_fitted:
            raise RuntimeError("Model not fitted.")
        return self.model.concordance_index_
