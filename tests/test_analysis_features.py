"""
Unit tests for Phase 3.1: Covariate Definitions & Feature Extraction.
TDD: Tests written BEFORE implementation.
"""
import pytest
from datetime import date, timedelta


class TestCovariateDefinition:
    """Tests for covariate group definitions."""
    
    def test_covariate_groups_defined(self):
        """Covariate groups should be defined."""
        from src.analysis.covariates import COVARIATE_GROUPS
        
        expected_groups = ["Condition", "Drug", "Procedure", "Demographics"]
        for group in expected_groups:
            assert group in COVARIATE_GROUPS
    
    def test_covariate_window_default(self):
        """Default covariate window should be 365 days prior."""
        from src.analysis.covariates import CovariateSettings
        
        settings = CovariateSettings()
        assert settings.lookback_days == 365
    
    def test_covariate_settings_custom_window(self):
        """Custom covariate window should be configurable."""
        from src.analysis.covariates import CovariateSettings
        
        settings = CovariateSettings(lookback_days=180)
        assert settings.lookback_days == 180


class TestFeatureExtraction:
    """Tests for SQL-based feature extraction."""
    
    def test_generate_condition_sql(self):
        """Generate SQL for condition covariates."""
        from src.analysis.feature_extraction import FeatureExtractor
        
        extractor = FeatureExtractor()
        sql = extractor.generate_sql("Condition", cohort_table="target_cohort")
        
        assert "condition_occurrence" in sql.lower()
        assert "person_id" in sql.lower()
        assert "concept_id" in sql.lower()
    
    def test_generate_drug_sql(self):
        """Generate SQL for drug covariates."""
        from src.analysis.feature_extraction import FeatureExtractor
        
        extractor = FeatureExtractor()
        sql = extractor.generate_sql("Drug", cohort_table="target_cohort")
        
        assert "drug_exposure" in sql.lower()
    
    def test_generate_procedure_sql(self):
        """Generate SQL for procedure covariates."""
        from src.analysis.feature_extraction import FeatureExtractor
        
        extractor = FeatureExtractor()
        sql = extractor.generate_sql("Procedure", cohort_table="target_cohort")
        
        assert "procedure_occurrence" in sql.lower()


class TestSurvivalRecord:
    """Tests for survival analysis data structures."""
    
    def test_survival_record_creation(self):
        """SurvivalRecord should be creatable with required fields."""
        from src.analysis.survival import SurvivalRecord
        
        record = SurvivalRecord(
            person_id=12345,
            treatment_group="target",
            time=180.0,
            event=1,
            covariates={"age": 65, "gender": 1}
        )
        
        assert record.person_id == 12345
        assert record.treatment_group == "target"
        assert record.time == 180.0
        assert record.event == 1
    
    def test_time_to_event_calculation(self):
        """Calculate time from index to event."""
        from src.analysis.survival import calculate_time_to_event
        
        index_date = date(2020, 1, 1)
        event_date = date(2020, 7, 1)
        
        time_days = calculate_time_to_event(index_date, event_date)
        assert time_days == 182  # ~6 months
    
    def test_censoring_applies_tar_end(self):
        """Censoring should respect time-at-risk window."""
        from src.analysis.survival import apply_censoring
        
        index_date = date(2020, 1, 1)
        event_date = date(2021, 6, 1)  # After TAR
        tar_days = 365
        
        censored_time, is_event = apply_censoring(
            index_date, event_date, tar_days
        )
        
        assert censored_time == 365  # Capped at TAR
        assert is_event == 0  # Censored, not event
