"""Startup validation for the PySpark cohort executor.

Call validate_spark_prerequisites() during application startup when
COHORT_ENGINE=spark. Fails fast with actionable error messages rather
than at first cohort generation request.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

REQUIRED_PARQUET_TABLES = [
    "concept",
    "concept_ancestor",
    "concept_relationship",
    "vocabulary",
    "drug_strength",
]


def validate_spark_prerequisites(
    jdbc_jar_path: str | None = None,
    parquet_dir: str | None = None,
) -> None:
    """Raise RuntimeError if Spark execution prerequisites are not met.

    Checks (in order):
      1. pyspark is importable
      2. PostgreSQL JDBC jar exists at the configured path
      3. All required vocab Parquet files are present

    Args:
        jdbc_jar_path: Override path to JDBC jar. Defaults to SPARK_JDBC_JAR
                       env var or /app/jdbc/postgresql-42.7.3.jar.
        parquet_dir: Override Parquet directory. Defaults to SPARK_PARQUET_DIR
                     env var or /app/tmp/parquet. Must match spark_executor.py.

    Raises:
        RuntimeError: With actionable message describing what is missing.
    """
    jar = jdbc_jar_path or os.environ.get("SPARK_JDBC_JAR", "/app/jdbc/postgresql-42.7.3.jar")
    pq_dir = parquet_dir or os.environ.get("SPARK_PARQUET_DIR", "/app/tmp/parquet")

    # 1. pyspark importable
    try:
        import pyspark  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            f"pyspark not installed. Rebuild Docker image or run: pip install pyspark\n{e}"
        ) from e

    # 2. JDBC jar present
    if not Path(jar).exists():
        raise RuntimeError(
            f"JDBC jar not found at {jar}. "
            "Rebuild Docker image (Dockerfile.tte-api downloads it at build time)."
        )

    # 3. Vocab Parquet files present
    missing = [
        t for t in REQUIRED_PARQUET_TABLES
        if not (Path(pq_dir) / f"{t}.parquet").exists()
    ]
    if missing:
        raise RuntimeError(
            f"Parquet vocab files missing in {pq_dir}: {missing}. "
            "Run inside container: python -m scripts.export_vocab_parquet"
        )

    logger.info(
        "Spark prerequisites validated — JDBC jar and all Parquet vocab files present in %s.",
        pq_dir,
    )
