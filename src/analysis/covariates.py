"""
Covariate definitions for HDPS-style feature extraction.
Phase 3.1: High-Dimensional Propensity Score covariates.
"""
from dataclasses import dataclass, field
from typing import Dict, List


# Covariate group definitions
COVARIATE_GROUPS = {
    "Condition": {
        "table": "condition_occurrence",
        "concept_column": "condition_concept_id",
        "date_column": "condition_start_date"
    },
    "Drug": {
        "table": "drug_exposure",
        "concept_column": "drug_concept_id",
        "date_column": "drug_exposure_start_date"
    },
    "Procedure": {
        "table": "procedure_occurrence",
        "concept_column": "procedure_concept_id",
        "date_column": "procedure_date"
    },
    "Demographics": {
        "table": "person",
        "columns": ["year_of_birth", "gender_concept_id", "race_concept_id"]
    }
}


@dataclass
class CovariateSettings:
    """Settings for covariate extraction."""
    lookback_days: int = 365
    min_prevalence: float = 0.01  # Minimum 1% prevalence to include
    max_covariates: int = 10000  # Maximum number of covariates
    included_groups: List[str] = field(
        default_factory=lambda: ["Condition", "Drug", "Procedure", "Demographics"]
    )
    
    def get_date_range_sql(self, index_date_col: str = "cohort_start_date") -> str:
        """Generate SQL for date range filter."""
        return f"""
            BETWEEN ({index_date_col} - INTERVAL '{self.lookback_days} days')
            AND {index_date_col}
        """


@dataclass
class Covariate:
    """A single covariate for analysis."""
    covariate_id: int
    covariate_name: str
    group: str
    concept_id: int = 0
    analysis_id: int = 0
