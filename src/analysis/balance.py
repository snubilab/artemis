"""
Covariate balance diagnostics.
Phase 3.3: SMD calculation and balance reporting.
"""
import numpy as np
from typing import Dict, List, Any
from dataclasses import dataclass


def calculate_smd(
    treated_values: np.ndarray, 
    control_values: np.ndarray
) -> float:
    """
    Calculate Standardized Mean Difference between groups.
    
    SMD = (mean_treated - mean_control) / pooled_std
    
    Args:
        treated_values: Values for treated group
        control_values: Values for control group
        
    Returns:
        Absolute SMD value
    """
    # Edge case: not enough data
    if len(treated_values) < 2 or len(control_values) < 2:
        return 0.0
    
    mean_t = np.mean(treated_values)
    mean_c = np.mean(control_values)
    
    var_t = np.var(treated_values, ddof=1)
    var_c = np.var(control_values, ddof=1)
    
    # Pooled standard deviation
    pooled_std = np.sqrt((var_t + var_c) / 2)
    
    if pooled_std == 0 or np.isnan(pooled_std):
        return 0.0
    
    smd = (mean_t - mean_c) / pooled_std
    return abs(smd)


@dataclass
class BalanceResult:
    """Result for a single covariate balance check."""
    name: str
    smd: float
    mean_treated: float
    mean_control: float
    is_balanced: bool  # SMD < 0.1


class BalanceChecker:
    """Check covariate balance between treatment groups."""
    
    def __init__(self, threshold: float = 0.1):
        """
        Args:
            threshold: SMD threshold for balance (default 0.1)
        """
        self.threshold = threshold
    
    def check(self, covariates: Dict[str, Dict[str, List]]) -> Dict[str, Dict[str, Any]]:
        """
        Check balance for all covariates.
        
        Args:
            covariates: Dict of {covariate_name: {"treated": [...], "control": [...]}}
            
        Returns:
            Dict of {covariate_name: {"smd": float, "balanced": bool, ...}}
        """
        results = {}
        
        for name, values in covariates.items():
            treated = np.array(values["treated"])
            control = np.array(values["control"])
            
            smd = calculate_smd(treated, control)
            
            results[name] = {
                "smd": smd,
                "mean_treated": float(np.mean(treated)),
                "mean_control": float(np.mean(control)),
                "balanced": smd < self.threshold
            }
        
        return results
    
    def summary(self, results: Dict[str, Dict]) -> Dict[str, Any]:
        """Generate summary of balance check."""
        smds = [r["smd"] for r in results.values()]
        balanced_count = sum(1 for r in results.values() if r["balanced"])
        
        return {
            "n_covariates": len(results),
            "n_balanced": balanced_count,
            "n_imbalanced": len(results) - balanced_count,
            "max_smd": max(smds) if smds else 0,
            "mean_smd": np.mean(smds) if smds else 0,
            "all_balanced": balanced_count == len(results)
        }


def calculate_balance_table(
    data: "pd.DataFrame",
    treatment_col: str,
    covariate_cols: List[str],
    threshold: float = 0.1
) -> Dict[str, Dict[str, Any]]:
    """
    Calculate balance table from a DataFrame.
    
    Args:
        data: DataFrame with treatment and covariates
        treatment_col: Name of treatment column (0/1)
        covariate_cols: List of covariate column names
        threshold: SMD threshold for balance
        
    Returns:
        Dict of {covariate: {smd, mean_treated, mean_control, balanced}}
    """
    import pandas as pd
    
    results = {}
    treated_mask = data[treatment_col] == 1
    
    for col in covariate_cols:
        treated_vals = data.loc[treated_mask, col].values
        control_vals = data.loc[~treated_mask, col].values
        
        smd = calculate_smd(treated_vals, control_vals)
        
        results[col] = {
            "smd": smd,
            "mean_treated": float(np.mean(treated_vals)) if len(treated_vals) > 0 else 0,
            "mean_control": float(np.mean(control_vals)) if len(control_vals) > 0 else 0,
            "balanced": smd < threshold
        }

    return results


def _weighted_mean(values: np.ndarray, weights: np.ndarray) -> float:
    """Weighted mean."""
    if len(values) == 0 or weights.sum() == 0:
        return 0.0
    return float(np.average(values, weights=weights))


def _weighted_var(values: np.ndarray, weights: np.ndarray) -> float:
    """Reliability-weighted variance (Bessel-corrected)."""
    if len(values) < 2 or weights.sum() == 0:
        return 0.0
    w_mean = np.average(values, weights=weights)
    v1 = weights.sum()
    v2 = (weights ** 2).sum()
    denom = v1 - v2 / v1
    if denom <= 0:
        return 0.0
    return float(np.sum(weights * (values - w_mean) ** 2) / denom)


def calculate_weighted_smd(
    treated_values: np.ndarray,
    control_values: np.ndarray,
    treated_weights: np.ndarray,
    control_weights: np.ndarray,
) -> float:
    """
    Calculate Standardized Mean Difference using IPTW weights.

    Uses weighted means and weighted variances for a fair post-adjustment
    comparison.
    """
    if len(treated_values) < 2 or len(control_values) < 2:
        return 0.0

    mean_t = _weighted_mean(treated_values, treated_weights)
    mean_c = _weighted_mean(control_values, control_weights)

    var_t = _weighted_var(treated_values, treated_weights)
    var_c = _weighted_var(control_values, control_weights)

    pooled_std = np.sqrt((var_t + var_c) / 2)
    if pooled_std == 0 or np.isnan(pooled_std):
        return 0.0

    return abs((mean_t - mean_c) / pooled_std)


def calculate_weighted_balance_table(
    data: "pd.DataFrame",
    treatment_col: str,
    covariate_cols: List[str],
    weights: np.ndarray,
    threshold: float = 0.1,
) -> Dict[str, Dict[str, Any]]:
    """
    Calculate balance table with IPTW weights.

    Args:
        data: DataFrame with treatment and covariates
        treatment_col: Name of treatment column (0/1)
        covariate_cols: List of covariate column names
        weights: IPTW weight array aligned with data rows
        threshold: SMD threshold for balance

    Returns:
        Dict of {covariate: {smd, mean_treated, mean_control, balanced}}
    """
    import pandas as pd

    results = {}
    treated_mask = data[treatment_col] == 1
    t_weights = weights[treated_mask.values]
    c_weights = weights[~treated_mask.values]

    for col in covariate_cols:
        t_vals = data.loc[treated_mask, col].values.astype(float)
        c_vals = data.loc[~treated_mask, col].values.astype(float)

        smd = calculate_weighted_smd(t_vals, c_vals, t_weights, c_weights)

        results[col] = {
            "smd": smd,
            "mean_treated": _weighted_mean(t_vals, t_weights),
            "mean_control": _weighted_mean(c_vals, c_weights),
            "balanced": smd < threshold,
        }
    
    return results
