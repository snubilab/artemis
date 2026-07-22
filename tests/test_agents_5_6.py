"""
Tests for Agent 5 (Analysis Agent) and Agent 6 (Reporting Agent).
TDD: Tests written BEFORE implementation.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
import numpy as np
import pandas as pd


class TestAgent5AnalysisAgent:
    """Tests for Agent 5: Analysis Agent."""
    
    def test_agent5_initialization(self):
        """Agent 5 should initialize with analysis config."""
        from src.agents.agent5.workflow import Agent5Workflow
        
        agent = Agent5Workflow()
        assert agent is not None
    
    def test_agent5_accepts_cohort_ids(self):
        """Agent 5 should accept target and comparator cohort IDs."""
        from src.agents.agent5.workflow import Agent5Workflow
        
        agent = Agent5Workflow()
        result = agent.configure(
            target_cohort_id=1,
            comparator_cohort_id=2,
            outcome_definition={"concept_ids": [4329847], "window_days": 365}
        )
        
        assert agent.target_cohort_id == 1
        assert agent.comparator_cohort_id == 2
    
    def test_agent5_runs_analysis_pipeline(self):
        """Agent 5 should run the full analysis pipeline with provided data."""
        from src.agents.agent5.workflow import Agent5Workflow
        import pandas as pd
        
        # Create test data directly
        test_data = pd.DataFrame({
            "person_id": [1, 2, 3, 4, 5, 6, 7, 8],
            "treatment": [1, 1, 1, 1, 0, 0, 0, 0],
            "age": [60, 55, 62, 58, 61, 54, 63, 57],
            "time": [100, 200, 150, 180, 120, 90, 160, 140],
            "event": [1, 0, 1, 0, 1, 1, 0, 0]
        })
        
        agent = Agent5Workflow()
        agent.configure(target_cohort_id=1, comparator_cohort_id=2)
        result = agent.run(data=test_data)
        
        assert "hazard_ratio" in result
        assert "balance" in result

    def test_agent5_runs_psm_pipeline_on_fake_data(self):
        """Agent 5 should execute the PSM path on fake data and return survival outputs."""
        from src.agents.agent5.workflow import Agent5Workflow
        import pandas as pd

        test_data = pd.DataFrame({
            "person_id": [1, 2, 3, 4, 5, 6, 7, 8],
            "treatment": [1, 1, 1, 1, 0, 0, 0, 0],
            "age": [60, 61, 62, 63, 60, 61, 62, 63],
            "gender": [0, 1, 0, 1, 0, 1, 0, 1],
            "time": [120, 200, 150, 180, 122, 198, 148, 176],
            "event": [1, 0, 1, 0, 1, 0, 1, 0],
        })

        agent = Agent5Workflow()
        agent.configure(
            target_cohort_id=1,
            comparator_cohort_id=2,
            outcome_definition={"concept_ids": [4329847], "window_days": 365},
            analysis_method="PSM",
        )
        result = agent.run(data=test_data)

        assert result["analysis_method"] == "PSM"
        assert result["n_matched_pairs"] > 0
        assert "hazard_ratio" in result
        assert "survival_data" in result


class TestAgent6ReportingAgent:
    """Tests for Agent 6: Reporting Agent."""
    
    def test_agent6_initialization(self):
        """Agent 6 should initialize properly."""
        from src.agents.agent6.workflow import Agent6Workflow
        
        agent = Agent6Workflow()
        assert agent is not None
    
    def test_agent6_accepts_analysis_results(self):
        """Agent 6 should accept analysis results from Agent 5."""
        from src.agents.agent6.workflow import Agent6Workflow
        from src.reporting.models import HazardRatioSummary
        
        hr = HazardRatioSummary(hr=0.85, ci_lower=0.72, ci_upper=0.99, p_value=0.038)
        
        agent = Agent6Workflow()
        agent.set_results(
            study_title="Test Study",
            hazard_ratio=hr,
            target_n=1000,
            comparator_n=1000
        )
        
        assert agent.results is not None
    
    def test_agent6_generates_report(self, tmp_path):
        """Agent 6 should generate a report (HTML only to avoid WeasyPrint)."""
        from src.agents.agent6.workflow import Agent6Workflow
        from src.reporting.models import HazardRatioSummary
        
        hr = HazardRatioSummary(hr=0.85, ci_lower=0.72, ci_upper=0.99, p_value=0.038)
        
        agent = Agent6Workflow()
        agent.set_results(
            study_title="Test Study",
            hazard_ratio=hr,
            target_n=1000,
            comparator_n=1000
        )
        
        output_path = tmp_path / "report.html"
        agent.generate_html_report(str(output_path))
        
        assert output_path.exists()


class TestE2EPipeline:
    """Integration tests for full E2E pipeline."""
    
    @pytest.mark.skip(reason="Requires full database and dependencies")
    def test_e2e_pipeline_execution(self):
        """Full pipeline from NL query to report should execute."""
        from src.pipeline.e2e import run_e2e_pipeline
        
        result = run_e2e_pipeline(
            query="Patients on metformin vs sulfonylurea with cardiovascular outcome",
            output_dir="/tmp/artemis_output"
        )
        
        assert result["status"] == "success"
        assert "report_path" in result
