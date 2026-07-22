"""
Agent 5: Analysis Agent.
Phase 4.3: Orchestrates feature extraction, propensity scoring, and outcome modeling.
"""
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class AnalysisConfig:
    """Configuration for Agent 5 analysis."""
    target_cohort_id: int = 0
    comparator_cohort_id: int = 0
    outcome_concept_ids: List[int] = field(default_factory=list)
    outcome_window_days: int = 365
    analysis_method: str = "IPTW"  # PSM or IPTW
    ps_model_covariates: List[str] = field(default_factory=lambda: ["age", "gender"])


class Agent5Workflow:
    """
    Analysis Agent - orchestrates the causal inference pipeline.

    Steps:
    1. Extract features from database for both cohorts
    2. Fit propensity score model
    3. Apply matching (PSM) or weighting (IPTW)
    4. Check covariate balance (before & after)
    5. Fit outcome model (Cox regression)
    6. Return results
    """

    def __init__(self, connector: Optional[Any] = None):
        self.config: Optional[AnalysisConfig] = None
        self.target_cohort_id: Optional[int] = None
        self.comparator_cohort_id: Optional[int] = None
        self.connector = connector
        self.data: Optional[pd.DataFrame] = None
        self.results: Dict[str, Any] = {}

    def configure(
        self,
        target_cohort_id: int,
        comparator_cohort_id: int,
        outcome_definition: Optional[Dict] = None,
        analysis_method: str = "IPTW"
    ) -> "Agent5Workflow":
        """Configure the analysis agent."""
        outcome_definition = outcome_definition or {}
        window_days_raw = outcome_definition.get("window_days")
        outcome_window_days = int(window_days_raw) if window_days_raw is not None else 365

        self.target_cohort_id = target_cohort_id
        self.comparator_cohort_id = comparator_cohort_id

        self.config = AnalysisConfig(
            target_cohort_id=target_cohort_id,
            comparator_cohort_id=comparator_cohort_id,
            outcome_concept_ids=outcome_definition.get("concept_ids", []),
            outcome_window_days=outcome_window_days,
            analysis_method=analysis_method
        )
        return self

    def run(self, data: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
        """
        Run the analysis pipeline.

        Args:
            data: Optional DataFrame with features. If None, will extract from DB.

        Returns:
            Dictionary with analysis results
        """
        from src.analysis.propensity import (
            PropensityScoreModel, PropensityMatcher, MahalanobisMatcher,
            calculate_iptw_weights,
        )
        from src.analysis.balance import (
            calculate_balance_table, calculate_weighted_balance_table,
        )
        from src.analysis.cox import CoxModel

        # Use provided data or extract from DB
        if data is not None:
            self.data = data
        else:
            self.data = self._extract_features()

        # Prepare covariates
        covariate_cols = [c for c in self.data.columns
                         if c not in ["person_id", "treatment", "time", "event"]]

        # Drop zero-variance AND near-zero-variance covariates
        variances = self.data[covariate_cols].var()
        low_var = variances[variances < 0.001].index.tolist()
        if low_var:
            logger.warning(
                f"Dropping {len(low_var)} low-variance covariates: "
                f"{low_var[:5]}{'...' if len(low_var) > 5 else ''}"
            )
            covariate_cols = [c for c in covariate_cols if c not in low_var]

        X = self.data[covariate_cols].values
        treatment = self.data["treatment"].values

        # Fit PS model
        ps_model = PropensityScoreModel()
        ps_model.fit(X, treatment)
        ps_scores = ps_model.predict(X)

        # Balance BEFORE adjustment
        balance_before = calculate_balance_table(
            self.data,
            treatment_col="treatment",
            covariate_cols=covariate_cols
        )

        method = self.config.analysis_method if self.config else "IPTW"

        if method == "PSM":
            self.results = self._run_psm(
                ps_scores, treatment, covariate_cols,
                balance_before, ps_model
            )
        elif method == "MAHALANOBIS":
            self.results = self._run_mahalanobis(
                ps_scores, treatment, covariate_cols,
                balance_before, ps_model
            )
        else:
            self.results = self._run_iptw(
                ps_scores, treatment, covariate_cols,
                balance_before, ps_model
            )

        return self.results

    # ------------------------------------------------------------------
    # IPTW path
    # ------------------------------------------------------------------
    def _run_iptw(
        self,
        ps_scores: np.ndarray,
        treatment: np.ndarray,
        covariate_cols: List[str],
        balance_before: Dict,
        ps_model: Any,
    ) -> Dict[str, Any]:
        from src.analysis.propensity import calculate_iptw_weights, trim_weights
        from src.analysis.balance import calculate_weighted_balance_table
        from src.analysis.cox import CoxModel

        weights = calculate_iptw_weights(ps_scores, treatment, stabilized=True)
        # Trim extreme weights to reduce variance and avoid singular matrix
        weights = trim_weights(weights, percentile=99)

        # Balance AFTER weighting (weighted SMD)
        balance_after = calculate_weighted_balance_table(
            self.data,
            treatment_col="treatment",
            covariate_cols=covariate_cols,
            weights=weights,
        )

        balance = self._merge_balance(covariate_cols, balance_before, balance_after)

        # Weighted Cox regression — use treatment only (IPTW already balances covariates)
        cox = CoxModel()
        cox_df = self.data[["time", "event", "treatment"]].copy()
        cox_df["_weights"] = weights
        cox.fit(cox_df, duration_col="time", event_col="event", weights_col="_weights")
        hr_result = cox.get_hazard_ratio("treatment")

        treated_mask = treatment == 1
        return {
            "hazard_ratio": hr_result,
            "balance": balance,
            "ps_scores": ps_scores,
            "weights": weights,
            "treatment": treatment,
            "analysis_method": "IPTW",
            "survival_data": self._build_survival_data(treated_mask),
            "n_target": int(treated_mask.sum()),
            "n_comparator": int((~treated_mask).sum()),
        }

    # ------------------------------------------------------------------
    # PSM path
    # ------------------------------------------------------------------
    def _run_psm(
        self,
        ps_scores: np.ndarray,
        treatment: np.ndarray,
        covariate_cols: List[str],
        balance_before: Dict,
        ps_model: Any,
    ) -> Dict[str, Any]:
        from src.analysis.propensity import PropensityMatcher
        from src.analysis.balance import calculate_balance_table
        from src.analysis.cox import CoxModel

        treated_mask = treatment == 1
        matched_pairs = []
        selected_caliper = None

        for caliper in (0.2, 0.5):
            try:
                matcher = PropensityMatcher(caliper=caliper, ratio=1)
                matched_pairs = matcher.match(
                    ps_scores[treated_mask],
                    ps_scores[~treated_mask],
                )
            except Exception as exc:
                if caliper == 0.2:
                    logger.warning(
                        "[Agent5] PSM caliper=0.2 failed (%s) — widening to caliper=0.5",
                        exc,
                    )
                    continue
                logger.warning(
                    "[Agent5] PSM caliper=0.5 failed (%s) — falling back to IPTW",
                    exc,
                )
                matched_pairs = []
            else:
                if len(matched_pairs) > 0:
                    selected_caliper = caliper
                    break
                if caliper == 0.2:
                    logger.warning(
                        "[Agent5] PSM caliper=0.2 produced 0 pairs — widening to caliper=0.5"
                    )
                    continue
                logger.warning(
                    "[Agent5] PSM caliper=0.5 still 0 pairs — falling back to IPTW"
                )

        if selected_caliper is None:
            result = self._run_iptw(ps_scores, treatment, covariate_cols, balance_before, ps_model)
            result["analysis_method"] = "IPTW (PSM fallback)"
            return result

        # Build matched subset
        treated_indices = np.where(treated_mask)[0]
        control_indices = np.where(~treated_mask)[0]

        matched_t_idx = [treated_indices[mp.treated_idx] for mp in matched_pairs]
        matched_c_idx = [control_indices[mp.control_idx] for mp in matched_pairs]
        matched_idx = matched_t_idx + matched_c_idx
        matched_data = self.data.iloc[matched_idx].copy()

        # Balance AFTER matching (unweighted on matched subset)
        balance_after = calculate_balance_table(
            matched_data,
            treatment_col="treatment",
            covariate_cols=covariate_cols,
        )

        balance = self._merge_balance(covariate_cols, balance_before, balance_after)

        # Unweighted Cox on matched subset — drop near-zero-variance
        # covariates that can cause ConvergenceError in lifelines.
        cox = CoxModel()
        safe_covs = self._safe_cox_covariates(matched_data, covariate_cols)
        cox_df = matched_data[["time", "event", "treatment"] + safe_covs].copy()
        cox.fit(cox_df, duration_col="time", event_col="event")
        hr_result = cox.get_hazard_ratio("treatment")

        matched_treatment = matched_data["treatment"].values
        matched_treated_mask = matched_treatment == 1
        return {
            "hazard_ratio": hr_result,
            "balance": balance,
            "ps_scores": ps_scores,
            "weights": np.ones(len(matched_data)),
            "treatment": matched_treatment,
            "analysis_method": "PSM",
            "n_matched_pairs": len(matched_pairs),
            "survival_data": self._build_survival_data(
                matched_treated_mask, data=matched_data
            ),
            "n_target": int(matched_treated_mask.sum()),
            "n_comparator": int((~matched_treated_mask).sum()),
        }

    def _run_mahalanobis(
        self,
        ps_scores: np.ndarray,
        treatment: np.ndarray,
        covariate_cols: List[str],
        balance_before: Dict,
        ps_model: Any,
    ) -> Dict[str, Any]:
        from src.analysis.propensity import MahalanobisMatcher
        from src.analysis.balance import calculate_balance_table
        from src.analysis.cox import CoxModel

        treated_mask = treatment == 1
        matcher = MahalanobisMatcher(caliper=0.2, ratio=1)
        matched_pairs = matcher.match(
            self.data.loc[treated_mask, covariate_cols].values,
            self.data.loc[~treated_mask, covariate_cols].values,
            ps_scores[treated_mask],
            ps_scores[~treated_mask],
        )

        if len(matched_pairs) == 0:
            raise ValueError("MAHALANOBIS produced 0 matched pairs — caliper may be too tight.")

        treated_indices = np.where(treated_mask)[0]
        control_indices = np.where(~treated_mask)[0]

        matched_t_idx = [treated_indices[mp.treated_idx] for mp in matched_pairs]
        matched_c_idx = [control_indices[mp.control_idx] for mp in matched_pairs]
        matched_idx = matched_t_idx + matched_c_idx
        matched_data = self.data.iloc[matched_idx].copy()

        balance_after = calculate_balance_table(
            matched_data,
            treatment_col="treatment",
            covariate_cols=covariate_cols,
        )

        balance = self._merge_balance(covariate_cols, balance_before, balance_after)

        cox = CoxModel()
        safe_covs = self._safe_cox_covariates(matched_data, covariate_cols)
        cox_df = matched_data[["time", "event", "treatment"] + safe_covs].copy()
        cox.fit(cox_df, duration_col="time", event_col="event")
        hr_result = cox.get_hazard_ratio("treatment")

        matched_treatment = matched_data["treatment"].values
        matched_treated_mask = matched_treatment == 1
        return {
            "hazard_ratio": hr_result,
            "balance": balance,
            "ps_scores": ps_scores,
            "weights": np.ones(len(matched_data)),
            "treatment": matched_treatment,
            "analysis_method": "MAHALANOBIS",
            "n_matched_pairs": len(matched_pairs),
            "survival_data": self._build_survival_data(
                matched_treated_mask, data=matched_data
            ),
            "n_target": int(matched_treated_mask.sum()),
            "n_comparator": int((~matched_treated_mask).sum()),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _safe_cox_covariates(
        df: pd.DataFrame,
        covariate_cols: List[str],
        min_variance: float = 0.005,
    ) -> List[str]:
        """Drop covariates with near-zero variance or complete separation.

        After PSM/Mahalanobis matching the subset may have different
        variance characteristics than the full dataset, causing lifelines
        ConvergenceError ('delta contains nan').
        """
        if not covariate_cols:
            return []
        variances = df[covariate_cols].var()
        safe = variances[variances >= min_variance].index.tolist()
        dropped = len(covariate_cols) - len(safe)
        if dropped:
            logger.warning(
                "Dropped %d near-zero-variance covariates before Cox fit "
                "(matched subset): %s",
                dropped,
                [c for c in covariate_cols if c not in safe][:10],
            )
        return safe

    @staticmethod
    def _merge_balance(
        covariate_cols: List[str],
        before: Dict,
        after: Dict,
    ) -> Dict[str, Dict[str, Any]]:
        """Combine before/after balance dicts."""
        return {
            col: {
                "smd_before": before[col]["smd"],
                "smd_after": after[col]["smd"],
                "mean_treated": before[col]["mean_treated"],
                "mean_control": before[col]["mean_control"],
                "balanced": after[col]["balanced"],
            }
            for col in covariate_cols
        }

    def _build_survival_data(
        self,
        treated_mask: np.ndarray,
        data: Optional[pd.DataFrame] = None,
    ) -> Dict[str, list]:
        df = data if data is not None else self.data
        return {
            "times_treated": df.loc[treated_mask, "time"].tolist(),
            "events_treated": df.loc[treated_mask, "event"].tolist(),
            "times_control": df.loc[~treated_mask, "time"].tolist(),
            "events_control": df.loc[~treated_mask, "event"].tolist(),
        }

    def _extract_features(self) -> pd.DataFrame:
        """Extract features from OMOP CDM via connector."""
        if self.connector is None:
            raise RuntimeError(
                "No OMOPConnector provided. Pass data directly via run(data=df) "
                "or provide a connector at init."
            )
        if self.config is None:
            raise RuntimeError("Call configure() before run().")

        return self.connector.build_analysis_dataset(
            target_drug_ids=[],  # populated from cohort definition
            comparator_drug_ids=[],
            outcome_concept_ids=self.config.outcome_concept_ids,
            followup_days=self.config.outcome_window_days,
        )
