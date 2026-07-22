"""
Propensity Score modeling for causal inference.
Phase 3.3: PSM and IPTW implementation.
"""
import numpy as np
from typing import List, Tuple, Optional
from dataclasses import dataclass


class PropensityScoreModel:
    """Propensity score estimation using logistic regression."""
    
    def __init__(self, max_iter: int = 5000, regularization: float = 1.0):
        self.max_iter = max_iter
        self.regularization = regularization
        self.model = None
        self.is_fitted = False
    
    def fit(self, X: np.ndarray, y: np.ndarray) -> 'PropensityScoreModel':
        """
        Fit propensity score model.
        
        Args:
            X: Covariate matrix (n_samples, n_features)
            y: Treatment assignment (0 or 1)
            
        Returns:
            self
        """
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
        
        # Scale covariates for better convergence
        self._scaler = StandardScaler()
        X_scaled = self._scaler.fit_transform(X)
        
        self.model = LogisticRegression(
            max_iter=self.max_iter,
            C=self.regularization,
            solver='lbfgs'
        )
        self.model.fit(X_scaled, y)
        self.is_fitted = True
        return self
    
    def predict(self, X: np.ndarray) -> np.ndarray:
        """Predict propensity scores (probability of treatment)."""
        if not self.is_fitted:
            raise RuntimeError("Model not fitted. Call fit() first.")
        
        # Scale using the same scaler from fit
        X_scaled = self._scaler.transform(X)
        return self.model.predict_proba(X_scaled)[:, 1]


@dataclass
class MatchedPair:
    """A matched pair of treated and control subjects."""
    treated_idx: int
    control_idx: int
    distance: float


class PropensityMatcher:
    """Nearest-neighbor propensity score matching."""
    
    def __init__(self, caliper: float = 0.2, ratio: int = 1):
        """
        Args:
            caliper: Maximum distance for matching (in PS units)
            ratio: Number of controls per treated
        """
        self.caliper = caliper
        self.ratio = ratio
    
    def match(
        self, 
        ps_treated: np.ndarray, 
        ps_control: np.ndarray
    ) -> List[MatchedPair]:
        """
        Match treated subjects to controls based on propensity scores.
        
        Args:
            ps_treated: Propensity scores for treated group
            ps_control: Propensity scores for control group
            
        Returns:
            List of matched pairs
        """
        from sklearn.neighbors import NearestNeighbors
        
        # Reshape for sklearn - use self.ratio for k-nearest neighbors
        control_ps = ps_control.reshape(-1, 1)
        
        # Use ratio for number of potential matches to consider
        k = min(self.ratio * 3, len(ps_control))  # Consider more for flexibility
        nn = NearestNeighbors(n_neighbors=k, metric='manhattan')
        nn.fit(control_ps)
        
        matched_pairs = []
        used_controls = set()
        
        for i, ps in enumerate(ps_treated):
            distances, indices = nn.kneighbors([[ps]])
            matches_for_treated = 0
            for j in range(len(indices[0])):
                if matches_for_treated >= self.ratio:
                    break
                distance = distances[0][j]
                control_idx = indices[0][j]
                
                if distance <= self.caliper and control_idx not in used_controls:
                    matched_pairs.append(MatchedPair(
                        treated_idx=i,
                        control_idx=control_idx,
                        distance=distance
                    ))
                    used_controls.add(control_idx)
                    matches_for_treated += 1
        
        return matched_pairs


class MahalanobisMatcher:
    """Nearest-neighbor Mahalanobis matching within an optional PS caliper."""

    def __init__(self, caliper: float = 0.2, ratio: int = 1):
        self.caliper = caliper
        self.ratio = ratio

    def match(
        self,
        X_treated: np.ndarray,
        X_control: np.ndarray,
        ps_treated: np.ndarray,
        ps_control: np.ndarray,
    ) -> List[MatchedPair]:
        if len(X_treated) == 0 or len(X_control) == 0:
            return []

        combined = np.vstack([X_treated, X_control]).astype(float)
        covariance = np.cov(combined, rowvar=False)
        if covariance.ndim == 0:
            covariance = np.array([[float(covariance)]])
        covariance += np.eye(covariance.shape[0]) * 1e-6
        inverse_covariance = np.linalg.pinv(covariance)

        matched_pairs = []
        used_controls = set()

        for treated_idx, treated_row in enumerate(X_treated):
            eligible_controls = []
            for control_idx, control_row in enumerate(X_control):
                if control_idx in used_controls:
                    continue
                ps_distance = abs(float(ps_treated[treated_idx]) - float(ps_control[control_idx]))
                if self.caliper > 0 and ps_distance > self.caliper:
                    continue
                delta = treated_row - control_row
                distance = float(np.sqrt(delta @ inverse_covariance @ delta.T))
                eligible_controls.append((distance, control_idx))

            if not eligible_controls:
                continue

            eligible_controls.sort(key=lambda item: item[0])
            for distance, control_idx in eligible_controls[: self.ratio]:
                if control_idx in used_controls:
                    continue
                matched_pairs.append(
                    MatchedPair(
                        treated_idx=treated_idx,
                        control_idx=control_idx,
                        distance=distance,
                    )
                )
                used_controls.add(control_idx)

        return matched_pairs


def calculate_iptw_weights(
    ps_scores: np.ndarray, 
    treatment: np.ndarray,
    stabilized: bool = False
) -> np.ndarray:
    """
    Calculate Inverse Probability of Treatment Weights.
    
    Args:
        ps_scores: Propensity scores
        treatment: Treatment indicator (1=treated, 0=control)
        stabilized: Whether to use stabilized weights
        
    Returns:
        IPTW weights array
    """
    # Clip PS to avoid division by zero (common practice: 0.01-0.99)
    eps = 0.01
    ps_clipped = np.clip(ps_scores, eps, 1 - eps)
    
    weights = np.zeros_like(ps_clipped, dtype=float)
    
    # Treated: 1/PS
    treated_mask = treatment == 1
    weights[treated_mask] = 1.0 / ps_clipped[treated_mask]
    
    # Control: 1/(1-PS)
    control_mask = treatment == 0
    weights[control_mask] = 1.0 / (1.0 - ps_clipped[control_mask])
    
    if stabilized:
        # Stabilize by multiplying by marginal probability
        p_treatment = treatment.mean()
        weights[treated_mask] *= p_treatment
        weights[control_mask] *= (1 - p_treatment)
    
    return weights


def trim_weights(weights: np.ndarray, percentile: float = 99) -> np.ndarray:
    """Trim extreme weights to reduce variance."""
    threshold = np.percentile(weights, percentile)
    return np.clip(weights, None, threshold)
