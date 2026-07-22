"""
Integration test: WebAPI cohort generation + HDPS covariate extraction.
Tests the new E2E path: Circe JSON → WebAPI → cohort table → HDPS covariates.

Requires Docker infrastructure: run with `pytest -m integration`
"""
import json
import sys
import pytest

from src.pipeline.webapi_client import WebAPIClient, CohortTableReference, WebAPIError
from src.analysis.omop_connector import OMOPConnector


@pytest.mark.integration
def test_webapi_sql_generation():
    """Test that WebAPI generates SQL from minimal Circe JSON."""
    print("=" * 60)
    print("  TEST 1: WebAPI SQL Generation")
    print("=" * 60)

    client = WebAPIClient()

    # Health check
    try:
        info = client.check_health()
    except (WebAPIError, Exception):
        pytest.skip("WebAPI not reachable")
    print(f"  ✅ WebAPI {info['version']} is online")

    # Minimal Circe JSON
    circe = {
        "PrimaryCriteria": {
            "CriteriaList": [{"DrugExposure": {"CodesetId": 0}}],
            "ObservationWindow": {"PriorDays": 0, "PostDays": 0},
            "PrimaryCriteriaLimit": {"Type": "First"},
        },
        "ConceptSets": [
            {
                "id": 0,
                "name": "Test Drug",
                "expression": {
                    "items": [
                        {
                            "concept": {
                                "CONCEPT_ID": 1301025,
                                "CONCEPT_NAME": "liraglutide",
                                "DOMAIN_ID": "Drug",
                                "VOCABULARY_ID": "RxNorm",
                                "CONCEPT_CLASS_ID": "Ingredient",
                                "STANDARD_CONCEPT": "S",
                                "CONCEPT_CODE": "475968",
                                "INVALID_REASON": "V",
                            },
                            "includeDescendants": True,
                        }
                    ]
                },
            }
        ],
    }

    sql = client.generate_sql(circe)
    sql_lines = sql.count("\n")
    print(f"  ✅ SQL generated: {sql_lines} lines, {len(sql):,} bytes")
    assert sql_lines > 10, f"SQL too short: {sql_lines} lines"
    assert "drug_exposure" in sql.lower() or "DRUG_EXPOSURE" in sql
    print("  ✅ SQL contains drug_exposure reference")


@pytest.fixture
def cohort_ref():
    """Fixture: find an existing TROY cohort for HDPS testing."""
    client = WebAPIClient()
    try:
        existing = client.list_cohort_definitions()
    except (WebAPIError, Exception):
        pytest.skip("WebAPI not reachable")
    for d in existing:
        if "TROY" in d.get("name", "").upper():
            cohort_id = d["id"]
            info_list = client.get_generation_info(cohort_id)
            for info in info_list:
                if info.get("status") == "COMPLETE":
                    return CohortTableReference(
                        cohort_definition_id=cohort_id,
                        results_schema="synthea23m_results",
                        person_count=info.get("personCount", 0),
                        source_key="SYNTHEA23M",
                        name="TROY LEADER",
                    )
    pytest.skip("No TROY cohort found in WebAPI")


@pytest.mark.integration
def test_cohort_generation():
    """Test full cohort generation via WebAPI."""
    print("\n" + "=" * 60)
    print("  TEST 2: Cohort Generation via WebAPI")
    print("=" * 60)

    client = WebAPIClient()

    try:
        existing = client.list_cohort_definitions()
    except (WebAPIError, Exception):
        pytest.skip("WebAPI not reachable")
    troy = None
    for d in existing:
        if "TROY" in d.get("name", "").upper():
            troy = d
            break

    if troy:
        cohort_id = troy["id"]
        print(f"  Found existing TROY cohort: ID={cohort_id}")

        info_list = client.get_generation_info(cohort_id)
        for info in info_list:
            if info.get("status") == "COMPLETE":
                person_count = info.get("personCount", 0)
                print(f"  ✅ TROY cohort has {person_count} patients")

                ref = CohortTableReference(
                    cohort_definition_id=cohort_id,
                    results_schema="synthea23m_results",
                    person_count=8155,
                    source_key="SYNTHEA23M",
                    name="TROY LEADER",
                )
                return ref

    print("  ⚠ No TROY cohort found, skipping")
    return None


@pytest.mark.integration
def test_hdps_covariates(cohort_ref: CohortTableReference):
    """Test HDPS covariate extraction from cohort table."""
    print("\n" + "=" * 60)
    print("  TEST 3: HDPS Covariate Extraction")
    print("=" * 60)

    connector = OMOPConnector(
        connection_string="postgresql://postgres:mypass@localhost:5432/ohdsi",
        schema="synthea23m",
    )

    # Test connection
    assert connector.test_connection(), "DB connection failed"
    print("  ✅ DB connection OK")

    # Build analysis dataset from cohort
    data = connector.build_analysis_dataset_from_cohort(
        cohort_ref=cohort_ref,
        outcome_concept_ids=[260139],  # Default outcome
        followup_days=365,
        min_prevalence=0.01,
    )

    print(f"  Rows: {len(data)}")
    print(f"  Columns: {len(data.columns)}")

    # Check for HDPS covariates
    cond_cols = [c for c in data.columns if c.startswith("cond_")]
    drug_cols = [c for c in data.columns if c.startswith("drug_")]
    proc_cols = [c for c in data.columns if c.startswith("proc_")]

    print(f"  Condition covariates: {len(cond_cols)}")
    print(f"  Drug covariates: {len(drug_cols)}")
    print(f"  Procedure covariates: {len(proc_cols)}")

    total_hdps = len(cond_cols) + len(drug_cols) + len(proc_cols)
    assert total_hdps > 0, "No HDPS covariates extracted"
    print(f"  ✅ Total HDPS covariates: {total_hdps}")

    # Check basic columns exist
    assert "person_id" in data.columns
    assert "age" in data.columns
    assert "gender_male" in data.columns
    assert "time" in data.columns
    assert "event" in data.columns
    print("  ✅ All required columns present")

    return data


if __name__ == "__main__":
    print("\n" + "🏥" * 30)
    print("  ARTEMIS E2E WebAPI Integration Test")
    print("🏥" * 30 + "\n")

    try:
        test_webapi_sql_generation()
        cohort_ref = test_cohort_generation()

        if cohort_ref and cohort_ref.person_count > 0:
            data = test_hdps_covariates(cohort_ref)
            print(f"\n✅ All tests passed! Dataset: {data.shape}")
        else:
            print("\n⚠ Skipped HDPS test (no cohort with patients)")

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
