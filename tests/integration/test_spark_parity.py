"""Integration test: Spark cohort executor produces same count as WebAPI.

Requires:
  - COHORT_ENGINE=spark env var set
  - Parquet vocab files in SPARK_PARQUET_DIR
  - Running Docker stack (docker-compose up -d)
  - LEADER data loaded in synthea_cdm_leader schema

Run with:
  docker exec -e COHORT_ENGINE=spark artemis-api \
    pytest /app/tests/integration/test_spark_parity.py -v -m integration

Skip entirely with: pytest -m "not integration"
"""
import os
import sys

import pytest

pytestmark = pytest.mark.integration

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


@pytest.fixture(scope="module", autouse=True)
def require_spark_env():
    if os.environ.get("COHORT_ENGINE") != "spark":
        pytest.skip("COHORT_ENGINE != spark — set env var to run Spark integration tests")
    parquet_dir = os.environ.get("SPARK_PARQUET_DIR", "/app/tmp/parquet")
    ancestor_path = os.path.join(parquet_dir, "concept_ancestor.parquet")
    if not os.path.exists(ancestor_path):
        pytest.skip(f"Parquet vocab not found at {ancestor_path} — run export script first")


def test_leader_spark_matches_webapi_count():
    """Spark executor produces 1,222 patients for LEADER cohort (ID 534).

    This cohort uses synthea_cdm_leader schema with LEADER Gold data
    (liraglutide, 10K patients, 54 ConceptSets, 17 InclusionRules).
    """
    from pipeline.webapi_client import WebAPIClient

    # Correct constructor: base_url, source_key, results_schema
    client = WebAPIClient(
        base_url=os.environ.get("WEBAPI_URL", "http://ohdsi-webapi:8080/WebAPI"),
        source_key="SYNTHEA_CDM_LEADER",
        results_schema="synthea_cdm_leader_results",
    )

    # Fetch cohort definition (private method — used internally)
    cohort_def = client._get_cohort_definition(534)
    circe_json = cohort_def.get("expression", cohort_def)

    result = client.generate_cohort_spark(circe_json, cohort_id=534, name="LEADER Spark parity test")

    assert result["person_count"] == 1222, (
        f"Expected 1222 patients, got {result['person_count']}. "
        "Check that synthea_cdm_leader has LEADER Gold data loaded."
    )
