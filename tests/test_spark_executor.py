"""
Tests for spark_executor module.

render_spark_sql tests do not require a live Spark session.
SparkCohortExecutor tests mock the SparkSession to avoid Spark startup overhead.
"""
import sys
import os
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from pipeline.spark_executor import render_spark_sql, SparkCohortExecutor  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_SQL = (
    "SELECT * FROM @cdm_database_schema.person p "
    "JOIN @vocabulary_database_schema.concept c ON p.gender_concept_id = c.concept_id "
    "INSERT INTO @target_database_schema.@target_cohort_table "
    "(cohort_definition_id, subject_id) "
    "SELECT @target_cohort_id, p.person_id FROM @cdm_database_schema.person p; "
    "CREATE TABLE @temp_database_schema.tmpTable USING DELTA AS SELECT 1 AS x"
)


# ---------------------------------------------------------------------------
# TestRenderSparkSql
# ---------------------------------------------------------------------------


class TestRenderSparkSql:
    def test_cdm_schema_substituted(self):
        """@cdm_database_schema placeholder is replaced in all occurrences."""
        result = render_spark_sql(_SAMPLE_SQL, "my_cdm", "results", 42)
        assert "@cdm_database_schema" not in result
        assert "my_cdm.person" in result

    def test_vocab_schema_substituted(self):
        """@vocabulary_database_schema placeholder uses the cdm_schema value."""
        result = render_spark_sql(_SAMPLE_SQL, "vocab_cdm", "results", 1)
        assert "@vocabulary_database_schema" not in result
        assert "vocab_cdm.concept" in result

    def test_target_schema_substituted(self):
        """@target_database_schema and @target_cohort_table are replaced."""
        result = render_spark_sql(_SAMPLE_SQL, "cdm", "my_results", 5)
        assert "@target_database_schema" not in result
        assert "my_results" in result

    def test_cohort_id_substituted(self):
        """@target_cohort_id is replaced with the integer value as a string."""
        result = render_spark_sql(_SAMPLE_SQL, "cdm", "results", 99)
        assert "@target_cohort_id" not in result
        assert "99" in result

    def test_temp_schema_substituted(self):
        """@temp_database_schema defaults to 'spark_temp' and is replaced."""
        result = render_spark_sql(_SAMPLE_SQL, "cdm", "results", 1)
        assert "@temp_database_schema" not in result
        assert "spark_temp.tmpTable" in result

    def test_temp_schema_custom_value(self):
        """Custom temp_schema overrides the default."""
        result = render_spark_sql(_SAMPLE_SQL, "cdm", "results", 1, temp_schema="my_tmp")
        assert "my_tmp.tmpTable" in result

    def test_rejects_invalid_schema(self):
        """Schema names containing SQL injection characters raise ValueError."""
        with pytest.raises(ValueError, match="Invalid schema"):
            render_spark_sql(_SAMPLE_SQL, "bad; DROP TABLE--", "results", 1)

    def test_delta_removed(self):
        """USING DELTA is stripped so plain Spark managed tables are used."""
        result = render_spark_sql(_SAMPLE_SQL, "cdm", "results", 1)
        assert "USING DELTA" not in result
        # Table creation syntax should still be present without DELTA keyword
        assert "CREATE TABLE" in result


# ---------------------------------------------------------------------------
# TestSparkCohortExecutor
# ---------------------------------------------------------------------------


class TestSparkCohortExecutor:
    def test_jdbc_url_property(self):
        """pg_jdbc_url is constructed from host, port, and dbname."""
        executor = SparkCohortExecutor(
            pg_host="db-host",
            pg_port=5432,
            pg_dbname="mydb",
            pg_user="user",
            pg_password="pass",
        )
        assert executor.pg_jdbc_url == "jdbc:postgresql://db-host:5432/mydb"

    def test_default_config(self):
        """SparkCohortExecutor stores configuration with sensible defaults."""
        executor = SparkCohortExecutor(pg_host="localhost")
        assert executor.pg_port == 5432
        assert executor.pg_dbname == "postgres"
        assert executor.jdbc_jar_path == "/app/jdbc/postgresql-42.7.3.jar"
        assert executor._spark is None  # session not yet created

    def test_render_then_execute_flow(self):
        """render_spark_sql output can be passed to execute_cohort_sql; Spark calls are mocked."""
        executor = SparkCohortExecutor(
            pg_host="localhost",
            pg_port=5432,
            pg_dbname="postgres",
            pg_user="postgres",
            pg_password="secret",
        )

        # Build a minimal rendered SQL (already processed by render_spark_sql)
        rendered = render_spark_sql(
            "SELECT 1 AS x; INSERT INTO results.cohort SELECT 1, 1",
            "cdm",
            "results",
            7,
        )

        # Mock the SparkSession and its sql method
        mock_spark = MagicMock()
        mock_count_df = MagicMock()
        mock_count_df.collect.return_value = [{"cnt": 42}]
        mock_spark.sql.return_value = mock_count_df
        mock_spark.read.jdbc.return_value = MagicMock()
        mock_spark.catalog.setCurrentDatabase = MagicMock()

        executor._spark = mock_spark

        with patch.object(executor, "_register_cdm_tables") as mock_register, \
             patch.object(executor, "_write_cohort_to_pg") as mock_write:
            mock_register.return_value = None
            mock_write.return_value = None

            count = executor.execute_cohort_sql(rendered, "cdm", "results", 7)

        # Verify CDM registration and write-back were called
        mock_register.assert_called_once_with(mock_spark, "cdm")
        mock_write.assert_called_once()

        # Count should come from the mocked Spark SQL result
        assert count == 42
