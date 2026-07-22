"""
SQL-based feature extraction for OMOP CDM.
Phase 3.1: Generate extraction SQL for each covariate domain.
"""
from typing import Optional
from src.analysis.covariates import COVARIATE_GROUPS, CovariateSettings


class FeatureExtractor:
    """Generates SQL for extracting features from OMOP CDM."""
    
    def __init__(self, settings: Optional[CovariateSettings] = None):
        self.settings = settings or CovariateSettings()
    
    def generate_sql(self, group: str, cohort_table: str = "cohort") -> str:
        """
        Generate SQL for extracting covariates from specified group.
        
        Args:
            group: One of COVARIATE_GROUPS keys
            cohort_table: Name of cohort temp table
            
        Returns:
            SQL string for extraction
        """
        if group not in COVARIATE_GROUPS:
            raise ValueError(f"Unknown covariate group: {group}")
        
        config = COVARIATE_GROUPS[group]
        
        if group == "Demographics":
            return self._generate_demographics_sql(cohort_table)
        
        return self._generate_event_sql(
            table=config["table"],
            concept_column=config["concept_column"],
            date_column=config["date_column"],
            cohort_table=cohort_table
        )
    
    def _generate_event_sql(
        self, 
        table: str, 
        concept_column: str, 
        date_column: str,
        cohort_table: str
    ) -> str:
        """Generate SQL for event-based covariates (conditions, drugs, procedures)."""
        return f"""
            SELECT 
                c.person_id,
                e.{concept_column} as concept_id,
                1 as feature_value
            FROM {cohort_table} c
            JOIN {table} e ON c.person_id = e.person_id
            WHERE e.{date_column} BETWEEN 
                (c.cohort_start_date - INTERVAL '{self.settings.lookback_days} days')
                AND c.cohort_start_date
            GROUP BY c.person_id, e.{concept_column}
        """
    
    def _generate_demographics_sql(self, cohort_table: str) -> str:
        """Generate SQL for demographic covariates."""
        return f"""
            SELECT 
                c.person_id,
                p.year_of_birth,
                p.gender_concept_id,
                p.race_concept_id,
                EXTRACT(YEAR FROM c.cohort_start_date) - p.year_of_birth as age
            FROM {cohort_table} c
            JOIN person p ON c.person_id = p.person_id
        """
    
    def generate_all_sql(self, cohort_table: str = "cohort") -> dict:
        """Generate SQL for all covariate groups."""
        return {
            group: self.generate_sql(group, cohort_table)
            for group in self.settings.included_groups
        }
