"""
Report data models for PDF generation.
Phase 4.2.2: Pydantic models for report data.
"""
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime


class HazardRatioSummary(BaseModel):
    """Summary of hazard ratio results."""
    hr: float
    ci_lower: float
    ci_upper: float
    p_value: float
    
    def is_significant(self, alpha: float = 0.05) -> bool:
        return self.p_value < alpha
    
    def format(self) -> str:
        return f"{self.hr:.2f} (95% CI: {self.ci_lower:.2f}-{self.ci_upper:.2f})"


class CovariateBalance(BaseModel):
    """Balance statistics for a single covariate."""
    name: str
    smd_before: float
    smd_after: float
    mean_treated: float
    mean_control: float


class ReportData(BaseModel):
    """Complete data for generating a TTE report."""
    # Study identification
    study_title: str
    generated_at: datetime = None
    
    # Cohort information
    target_cohort_size: int
    comparator_cohort_size: int
    target_name: str = "Target"
    comparator_name: str = "Comparator"
    
    # Analysis results (optional, may not be available yet)
    hazard_ratio: Optional[HazardRatioSummary] = None
    median_followup_days: Optional[float] = None
    
    # Comparative validation (vs published RCT)
    rct_reference_hr: Optional[float] = None
    rct_reference_ci: Optional[tuple] = None  # (lower, upper)
    rct_study_name: Optional[str] = None
    
    # Balance information
    balance_summary: Optional[List[CovariateBalance]] = None
    n_covariates_balanced: Optional[int] = None
    
    # Plot paths
    km_plot_path: Optional[str] = None
    forest_plot_path: Optional[str] = None
    love_plot_path: Optional[str] = None
    ps_dist_plot_path: Optional[str] = None

    # Base64-encoded plot images (data URIs for self-contained HTML)
    km_plot_base64: Optional[str] = None
    forest_plot_base64: Optional[str] = None
    love_plot_base64: Optional[str] = None
    ps_dist_plot_base64: Optional[str] = None

    # Additional metadata
    analysis_method: str = "IPTW"  # PSM or IPTW
    outcome_name: str = "Primary Outcome"
    
    def __init__(self, **data):
        if 'generated_at' not in data or data['generated_at'] is None:
            data['generated_at'] = datetime.now()
        super().__init__(**data)


class StudyProtocol(BaseModel):
    """Target trial protocol information."""
    research_question: str
    target_population: str
    comparator_population: str
    outcome_definition: str
    time_at_risk: str
    confounders_controlled: List[str] = []
