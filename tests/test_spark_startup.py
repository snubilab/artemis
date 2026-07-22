"""Tests for Spark prerequisite validation."""
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Follow established import pattern from test_spark_executor.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from pipeline.spark_startup import validate_spark_prerequisites  # noqa: E402

REQUIRED_TABLES = ["concept", "concept_ancestor", "concept_relationship", "vocabulary", "drug_strength"]


def _make_parquet_dir(base: Path) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_TABLES:
        (base / f"{name}.parquet").write_bytes(b"fake")
    return base


def test_validate_passes_when_all_present(tmp_path):
    """No exception raised when JDBC jar and all Parquet files exist."""
    jdbc_jar = tmp_path / "pg.jar"
    jdbc_jar.write_bytes(b"fake")
    parquet_dir = _make_parquet_dir(tmp_path / "parquet")

    # Patch pyspark import to succeed without needing it installed
    with patch.dict("sys.modules", {"pyspark": object()}):
        validate_spark_prerequisites(
            jdbc_jar_path=str(jdbc_jar),
            parquet_dir=str(parquet_dir),
        )
    # No exception = pass


def test_validate_fails_missing_jdbc_jar(tmp_path):
    """RuntimeError raised when JDBC jar is absent."""
    with patch.dict("sys.modules", {"pyspark": object()}):
        with pytest.raises(RuntimeError, match="JDBC jar not found"):
            validate_spark_prerequisites(
                jdbc_jar_path=str(tmp_path / "missing.jar"),
                parquet_dir=str(tmp_path),
            )


def test_validate_fails_missing_parquet(tmp_path):
    """RuntimeError raised when Parquet vocab files are absent."""
    jdbc_jar = tmp_path / "pg.jar"
    jdbc_jar.write_bytes(b"fake")

    with patch.dict("sys.modules", {"pyspark": object()}):
        with pytest.raises(RuntimeError, match="Parquet vocab files missing"):
            validate_spark_prerequisites(
                jdbc_jar_path=str(jdbc_jar),
                parquet_dir=str(tmp_path / "empty"),
            )


def test_validate_fails_pyspark_not_installed(tmp_path):
    """RuntimeError raised when pyspark cannot be imported."""
    jdbc_jar = tmp_path / "pg.jar"
    jdbc_jar.write_bytes(b"fake")
    parquet_dir = _make_parquet_dir(tmp_path / "parquet")

    # Remove pyspark from sys.modules to simulate not installed
    with patch.dict("sys.modules", {"pyspark": None}):
        with pytest.raises(RuntimeError, match="pyspark not installed"):
            validate_spark_prerequisites(
                jdbc_jar_path=str(jdbc_jar),
                parquet_dir=str(parquet_dir),
            )
