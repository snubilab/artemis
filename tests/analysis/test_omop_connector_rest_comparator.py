"""
TDD Tests: build_analysis_dataset_from_generated_cohorts - treatment_vs_rest mode.

When comparator_ref=None, the connector should use all CDM persons minus
treatment IDs as the comparator group (treatment_vs_rest semantics).

Tests:
  A - comparator_ref=None yields comparator rows in output (n_comparator > 0)
  B - comparator persons get treatment=0, treatment persons get treatment=1
  C - comparator_ref=None with empty CDM returns empty DataFrame
  D - explicit comparator_ref still works as before (no regression)
"""
import pytest
import pandas as pd
from datetime import date
from unittest.mock import patch, MagicMock
from sqlalchemy import text

from src.analysis.omop_connector import OMOPConnector
from src.pipeline.webapi_client import CohortTableReference


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ref(cohort_id: int, schema: str = "test_results", n: int = 3) -> CohortTableReference:
    return CohortTableReference(
        cohort_definition_id=cohort_id,
        results_schema=schema,
        person_count=n,
        source_key="TEST",
        name="test cohort",
    )


def _make_connector_with_mock_db(
    treatment_persons: list[int],
    all_cdm_persons: list[int],
    outcome_persons: list[int],
    results_schema: str = "test_results",
) -> OMOPConnector:
    """
    Patch OMOPConnector.engine so DB calls return controlled DataFrames.
    Returns a configured connector instance.
    """
    connector = OMOPConnector.__new__(OMOPConnector)
    connector.connection_string = "mock://"
    connector.schema = "cdm"
    connector._engine = None

    start = date(2020, 1, 1)
    end = date(2020, 12, 31)

    treatment_cohort_df = pd.DataFrame([
        {"person_id": pid, "cohort_definition_id": 10, "cohort_start_date": start, "cohort_end_date": end}
        for pid in treatment_persons
    ])
    all_person_df = pd.DataFrame({"person_id": all_cdm_persons})
    outcome_df = pd.DataFrame([
        {"person_id": pid, "cohort_definition_id": 20, "cohort_start_date": start, "cohort_end_date": end}
        for pid in outcome_persons
    ])

    call_count = {"n": 0}

    def mock_read_sql(query_or_text, conn, params=None):
        call_count["n"] += 1
        q = str(query_or_text) if not hasattr(query_or_text, "text") else query_or_text.text
        # Cohort table queries are parametrized
        if params and params.get("cohort_id") == 10:
            return treatment_cohort_df
        if params and params.get("cohort_id") == 20:
            return outcome_df
        # CDM person query (treatment_vs_rest fallback)
        if "person" in q.lower() and params is None:
            return all_person_df
        return pd.DataFrame()

    def mock_extract_demographics(pids):
        return pd.DataFrame({
            "person_id": pids,
            "age": [50] * len(pids),
            "gender_male": [1] * len(pids),
        })

    def mock_extract_conditions(pids):
        return pd.DataFrame({"person_id": pids})

    def mock_extract_drugs(pids):
        return pd.DataFrame({"person_id": pids})

    def mock_extract_procedures(pids):
        return pd.DataFrame({"person_id": pids})

    def mock_extract_outcome_from_cohort(pids, outcome_ref, index_dates, followup_days):
        return pd.DataFrame({
            "person_id": pids,
            "time": [365] * len(pids),
            "event": [0] * len(pids),
        })

    connector.extract_demographics = mock_extract_demographics
    connector.extract_conditions = mock_extract_conditions
    connector.extract_drugs = mock_extract_drugs
    connector.extract_procedures = mock_extract_procedures
    connector.extract_outcome_from_cohort = mock_extract_outcome_from_cohort

    import contextlib

    class FakeConn:
        def execute(self, *a, **k): return None

    @contextlib.contextmanager
    def fake_connect():
        yield FakeConn()

    mock_engine = MagicMock()
    mock_engine.connect = fake_connect

    connector._engine = mock_engine
    connector._mock_read_sql = mock_read_sql
    connector._results_schema = results_schema

    return connector, mock_read_sql


# ---------------------------------------------------------------------------
# Test A: comparator_ref=None → CDM rest used as comparator
# ---------------------------------------------------------------------------

def test_rest_comparator_produces_nonzero_comparators():
    """Test A: When comparator_ref=None, all CDM non-treatment persons become comparators."""
    treatment_ids = [1, 2, 3]
    all_cdm_ids = [1, 2, 3, 4, 5, 6]  # persons 4,5,6 are "rest"
    outcome_ids = []

    connector, mock_read_sql = _make_connector_with_mock_db(
        treatment_ids, all_cdm_ids, outcome_ids
    )

    target_ref = _make_ref(cohort_id=10, n=3)
    outcome_ref = _make_ref(cohort_id=20, n=0)

    with patch("pandas.read_sql", side_effect=mock_read_sql):
        result = connector.build_analysis_dataset_from_generated_cohorts(
            target_ref=target_ref,
            outcome_ref=outcome_ref,
            comparator_ref=None,
        )

    assert not result.empty, "Result must not be empty when CDM has non-treatment persons"
    n_comparator = (result["treatment"] == 0).sum()
    assert n_comparator == 3, f"Expected 3 comparator rows (persons 4,5,6), got {n_comparator}"


# ---------------------------------------------------------------------------
# Test B: treatment flags are correct
# ---------------------------------------------------------------------------

def test_rest_comparator_treatment_flags():
    """Test B: treatment=1 for treatment persons, treatment=0 for REST persons."""
    treatment_ids = [1, 2]
    all_cdm_ids = [1, 2, 3, 4]
    outcome_ids = []

    connector, mock_read_sql = _make_connector_with_mock_db(
        treatment_ids, all_cdm_ids, outcome_ids
    )

    target_ref = _make_ref(cohort_id=10, n=2)
    outcome_ref = _make_ref(cohort_id=20, n=0)

    with patch("pandas.read_sql", side_effect=mock_read_sql):
        result = connector.build_analysis_dataset_from_generated_cohorts(
            target_ref=target_ref,
            outcome_ref=outcome_ref,
            comparator_ref=None,
        )

    treated = set(result[result["treatment"] == 1]["person_id"].tolist())
    comparator = set(result[result["treatment"] == 0]["person_id"].tolist())

    assert treated == {1, 2}, f"Treatment persons should be {{1,2}}, got {treated}"
    assert comparator == {3, 4}, f"REST comparators should be {{3,4}}, got {comparator}"


# ---------------------------------------------------------------------------
# Test C: Empty CDM returns empty DataFrame
# ---------------------------------------------------------------------------

def test_rest_comparator_empty_cdm_returns_empty():
    """Test C: If CDM has no persons outside treatment, returns empty DataFrame."""
    treatment_ids = [1, 2]
    all_cdm_ids = [1, 2]  # no REST persons
    outcome_ids = []

    connector, mock_read_sql = _make_connector_with_mock_db(
        treatment_ids, all_cdm_ids, outcome_ids
    )

    target_ref = _make_ref(cohort_id=10, n=2)
    outcome_ref = _make_ref(cohort_id=20, n=0)

    with patch("pandas.read_sql", side_effect=mock_read_sql):
        result = connector.build_analysis_dataset_from_generated_cohorts(
            target_ref=target_ref,
            outcome_ref=outcome_ref,
            comparator_ref=None,
        )

    assert result.empty, "Should return empty DataFrame when no REST persons exist"


# ---------------------------------------------------------------------------
# Test D: Explicit comparator_ref still works (no regression)
# ---------------------------------------------------------------------------

def test_explicit_comparator_ref_no_regression():
    """Test D: Explicit comparator_ref with persons still produces dual-arm dataset."""
    treatment_ids = [1, 2]
    all_cdm_ids = [1, 2, 3, 4]  # should NOT be queried when explicit ref given
    comparator_ids_in_db = [5, 6]
    outcome_ids = []

    connector, _ = _make_connector_with_mock_db(
        treatment_ids, all_cdm_ids, outcome_ids
    )

    # Override mock to also handle comparator cohort (id=30)
    start = date(2020, 1, 1)
    end = date(2020, 12, 31)
    comp_df = pd.DataFrame([
        {"person_id": pid, "cohort_definition_id": 30, "cohort_start_date": start, "cohort_end_date": end}
        for pid in comparator_ids_in_db
    ])
    treatment_df = pd.DataFrame([
        {"person_id": pid, "cohort_definition_id": 10, "cohort_start_date": start, "cohort_end_date": end}
        for pid in treatment_ids
    ])
    outcome_df = pd.DataFrame(columns=["person_id", "cohort_definition_id", "cohort_start_date", "cohort_end_date"])

    def read_sql_explicit(query_or_text, conn, params=None):
        if params and params.get("cohort_id") == 10:
            return treatment_df
        if params and params.get("cohort_id") == 30:
            return comp_df
        if params and params.get("cohort_id") == 20:
            return outcome_df
        return pd.DataFrame()

    target_ref = _make_ref(cohort_id=10, n=2)
    outcome_ref = _make_ref(cohort_id=20, n=0)
    comparator_ref = _make_ref(cohort_id=30, n=2)

    with patch("pandas.read_sql", side_effect=read_sql_explicit):
        result = connector.build_analysis_dataset_from_generated_cohorts(
            target_ref=target_ref,
            outcome_ref=outcome_ref,
            comparator_ref=comparator_ref,
        )

    assert not result.empty
    treated = set(result[result["treatment"] == 1]["person_id"].tolist())
    comparator = set(result[result["treatment"] == 0]["person_id"].tolist())
    assert treated == {1, 2}
    assert comparator == {5, 6}


def test_rest_comparator_override_ids_are_used_and_overlap_removed():
    """Override comparator IDs should be used and treatment overlap removed."""
    treatment_ids = [1, 2]
    all_cdm_ids = [1, 2, 3, 4, 5, 6]
    outcome_ids = []

    connector, mock_read_sql = _make_connector_with_mock_db(
        treatment_ids, all_cdm_ids, outcome_ids
    )

    target_ref = _make_ref(cohort_id=10, n=2)
    outcome_ref = _make_ref(cohort_id=20, n=0)

    with patch("pandas.read_sql", side_effect=mock_read_sql):
        result = connector.build_analysis_dataset_from_generated_cohorts(
            target_ref=target_ref,
            outcome_ref=outcome_ref,
            comparator_ref=None,
            comparator_person_ids=[2, 3, 4],  # includes treatment overlap(2)
        )

    comparator = set(result[result["treatment"] == 0]["person_id"].tolist())
    assert comparator == {3, 4}


def test_rest_comparator_override_index_date_is_honored():
    """Comparator index_date should use override date when provided."""
    treatment_ids = [1]
    all_cdm_ids = [1, 2, 3]
    outcome_ids = []

    connector, _ = _make_connector_with_mock_db(
        treatment_ids, all_cdm_ids, outcome_ids
    )
    captured = {}

    def capture_outcome(pids, outcome_ref, index_dates, followup_days):
        captured["index_dates"] = dict(index_dates)
        return pd.DataFrame({
            "person_id": pids,
            "time": [followup_days] * len(pids),
            "event": [0] * len(pids),
        })

    connector.extract_outcome_from_cohort = capture_outcome

    start = date(2020, 1, 1)
    treatment_df = pd.DataFrame([
        {"person_id": 1, "cohort_definition_id": 10, "cohort_start_date": start, "cohort_end_date": start}
    ])
    outcome_df = pd.DataFrame(columns=["person_id", "cohort_definition_id", "cohort_start_date", "cohort_end_date"])

    def read_sql_override(query_or_text, conn, params=None):
        if params and params.get("cohort_id") == 10:
            return treatment_df
        if params and params.get("cohort_id") == 20:
            return outcome_df
        return pd.DataFrame({"person_id": [1, 2, 3]})

    target_ref = _make_ref(cohort_id=10, n=1)
    outcome_ref = _make_ref(cohort_id=20, n=0)
    override_date = date(2015, 6, 1)

    with patch("pandas.read_sql", side_effect=read_sql_override):
        connector.build_analysis_dataset_from_generated_cohorts(
            target_ref=target_ref,
            outcome_ref=outcome_ref,
            comparator_ref=None,
            comparator_person_ids=[2, 3],
            comparator_index_date_override=override_date,
        )

    assert captured["index_dates"][2] == override_date
    assert captured["index_dates"][3] == override_date
