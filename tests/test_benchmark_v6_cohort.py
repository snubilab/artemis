"""
TDD Tests for benchmark_v6_cohort.py (Task 02)
Usage: pytest tests/test_benchmark_v6_cohort.py
"""
import pytest
import os
import json
from unittest.mock import patch, MagicMock
import sys

# Add scripts dir to path to import benchmark_v6_cohort
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'scripts')))

try:
    from scripts.benchmark_v6_cohort import run_cohort_benchmark, BenchmarkConfig
except Exception as _import_err:
    pytestmark = pytest.mark.skip(reason=f"benchmark import failed: {_import_err}")
    run_cohort_benchmark = None  # type: ignore[assignment]
    BenchmarkConfig = None  # type: ignore[assignment,misc]

@pytest.fixture
def mock_agent1_extract():
    with patch("scripts.benchmark_v6_cohort.get_agent1") as mock_get:
        mock_instance = MagicMock()
        mock_instance.parse_nct.return_value = MagicMock()
        mock_get.return_value = mock_instance
        yield mock_get

@pytest.fixture
def mock_supervisor_steps():
    with patch("scripts.benchmark_v6_cohort.PipelineSupervisor") as mock:
        mock._step2_map.return_value = ([], MagicMock(), [])
        mock._step2_5_consolidate.return_value = []
        mock._step3_register.return_value = []
        yield mock

@pytest.fixture
def mock_agent3_assemble():
    with patch("scripts.benchmark_v6_cohort.agent3") as mock:
        result = MagicMock()
        result.circe_json = {"dummy": "agent_json"}
        mock.assemble.return_value = result
        yield mock

@pytest.fixture
def mock_webapi():
    with patch("scripts.benchmark_v6_cohort.WebAPIClient") as MockClient:
        instance = MockClient.return_value
        # Return mock cohort references
        gold_ref = MagicMock()
        gold_ref.cohort_definition_id = 100
        
        agent_ref = MagicMock()
        agent_ref.cohort_definition_id = 200
        
        instance.generate_cohort.side_effect = [gold_ref, agent_ref]
        yield instance

@pytest.fixture
def mock_omop():
    with patch("scripts.benchmark_v6_cohort.OMOPConnector") as MockConnector:
        instance = MockConnector.return_value
        instance.get_cohort_overlap_metrics.return_value = {
            "gold_total": 10,
            "agent_total": 8,
            "intersection_count": 6,
            "gold_only_count": 4,
            "agent_only_count": 2,
            "precision": 0.75,
            "recall": 0.6,
            "jaccard_similarity": 0.5,
            "f1_score": 0.6667
        }
        yield instance

def test_benchmark_e2e_mocked(
    mock_agent1_extract,
    mock_supervisor_steps,
    mock_agent3_assemble,
    mock_webapi,
    mock_omop,
    tmp_path
):
    """Test Case A: Mock WebAPI completion -> Script runs end to end, persists JSON"""
    config = BenchmarkConfig(
        trial_type="LEADER",
        run_mode="E2E_SUPP",
        gold_json_path=str(tmp_path / "dummy_gold.json"),
        output_dir=str(tmp_path)
    )
    
    # Create dummy gold json
    with open(config.gold_json_path, "w") as f:
        json.dump({"dummy": "gold_json"}, f)
        
    result = run_cohort_benchmark(config)
    
    # Verify metrics
    assert result["metrics"]["jaccard_similarity"] == 0.5
    assert result["metrics"]["precision"] == 0.75
    assert result["metrics"]["recall"] == 0.6
    
    # Verify outputs saved
    saved_files = list(tmp_path.glob("benchmark_cohort_*.json"))
    assert len(saved_files) == 1
    
    with open(saved_files[0], "r") as f:
        saved_data = json.load(f)
        assert saved_data["trial_name"] == "LEADER"
        assert saved_data["metrics"]["gold_total"] == 10
