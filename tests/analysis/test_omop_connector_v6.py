"""
TDD Tests for OMOPConnector Cohort Overlap Metrics (Task 01)
Usage: pytest -m integration tests/analysis/test_omop_connector_v6.py
"""
import pytest
from src.analysis.omop_connector import OMOPConnector
from sqlalchemy import text

@pytest.fixture(scope="module")
def setup_test_data():
    """Create a temporary schema and table for testing cohort overlap."""
    connector = OMOPConnector()
    if not connector.test_connection():
        pytest.skip("No DB connection")

    schema = "test_results_schema"
    
    with connector.engine.begin() as conn:
        # Create schema
        conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {schema}"))
        
        # Create cohort table
        conn.execute(text(f"""
            CREATE TABLE {schema}.cohort (
                cohort_definition_id integer NOT NULL,
                subject_id integer NOT NULL,
                cohort_start_date date NOT NULL,
                cohort_end_date date NOT NULL
            )
        """))
        
        # Insert test data
        # Gold Cohort (ID: 100): Patients 1, 2, 3, 4, 5
        values_gold = [(100, i, '2020-01-01', '2020-12-31') for i in [1, 2, 3, 4, 5]]
        
        # Agent Cohort (ID: 200): Patients 3, 4, 5, 6, 7 (Overlap: 3, 4, 5)
        values_agent = [(200, i, '2020-01-01', '2020-12-31') for i in [3, 4, 5, 6, 7]]
        
        # Agent Cohort Empty (ID: 300): No patients
        
        # Insert
        for vals in [values_gold, values_agent]:
            for v in vals:
                conn.execute(
                    text(f"INSERT INTO {schema}.cohort VALUES (:cid, :sid, :sd, :ed)"),
                    {"cid": v[0], "sid": v[1], "sd": v[2], "ed": v[3]}
                )

    yield {"schema": schema, "gold_id": 100, "agent_id": 200, "empty_id": 300}
    
    # Teardown
    with connector.engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))

@pytest.mark.integration
def test_cohort_overlap_exact_match(setup_test_data):
    """Test Case A: Exact exact match (gold_id == agent_id) -> Jaccard 1.0"""
    connector = OMOPConnector()
    schema = setup_test_data["schema"]
    gold_id = setup_test_data["gold_id"]
    
    metrics = connector.get_cohort_overlap_metrics(
        gold_cohort_id=gold_id,
        agent_cohort_id=gold_id,  # Same ID
        results_schema=schema
    )
    
    assert metrics["gold_total"] == 5
    assert metrics["agent_total"] == 5
    assert metrics["intersection_count"] == 5
    assert metrics["gold_only_count"] == 0
    assert metrics["agent_only_count"] == 0

@pytest.mark.integration
def test_cohort_overlap_partial_match(setup_test_data):
    """Test Case B: Partial match -> Correct overlap counts"""
    connector = OMOPConnector()
    schema = setup_test_data["schema"]
    gold_id = setup_test_data["gold_id"]
    agent_id = setup_test_data["agent_id"]
    
    metrics = connector.get_cohort_overlap_metrics(
        gold_cohort_id=gold_id,
        agent_cohort_id=agent_id,
        results_schema=schema
    )
    
    # Gold: 1, 2, 3, 4, 5. Agent: 3, 4, 5, 6, 7
    # Intersection: 3, 4, 5 (count = 3)
    # Gold only: 1, 2 (count = 2)
    # Agent only: 6, 7 (count = 2)
    assert metrics["gold_total"] == 5
    assert metrics["agent_total"] == 5
    assert metrics["intersection_count"] == 3
    assert metrics["gold_only_count"] == 2
    assert metrics["agent_only_count"] == 2

@pytest.mark.integration
def test_cohort_overlap_empty_agent(setup_test_data):
    """Test Case C: Empty agent cohort -> 0 true positives, Jaccard 0.0"""
    connector = OMOPConnector()
    schema = setup_test_data["schema"]
    gold_id = setup_test_data["gold_id"]
    empty_id = setup_test_data["empty_id"]
    
    metrics = connector.get_cohort_overlap_metrics(
        gold_cohort_id=gold_id,
        agent_cohort_id=empty_id,
        results_schema=schema
    )
    
    assert metrics["gold_total"] == 5
    assert metrics["agent_total"] == 0
    assert metrics["intersection_count"] == 0
    assert metrics["gold_only_count"] == 5
    assert metrics["agent_only_count"] == 0
