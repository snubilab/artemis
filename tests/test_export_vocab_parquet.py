"""Tests for export_vocab_parquet script."""
import os
import sys

import pytest
from unittest.mock import patch, MagicMock

# Follow the same import pattern as test_spark_executor.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.export_vocab_parquet import export_vocab_tables  # noqa: E402


def test_export_writes_parquet_files(tmp_path):
    """export_vocab_tables creates one .parquet file per requested table."""
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq

    with patch("scripts.export_vocab_parquet.psycopg2.connect") as mock_connect:
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        with patch("scripts.export_vocab_parquet.pd.read_sql") as mock_sql:
            # Return an iterator of one chunk
            mock_sql.return_value = iter([pd.DataFrame({"concept_id": [1, 2]})])
            export_vocab_tables(
                pg_host="localhost",
                pg_dbname="postgres",
                pg_user="postgres",
                pg_password="pass",
                vocab_schema="synthea23m",
                output_dir=str(tmp_path),
                tables=["concept"],
            )

    assert (tmp_path / "concept.parquet").exists()


def test_export_skips_existing_files(tmp_path):
    """export_vocab_tables skips tables whose .parquet already exists."""
    # Pre-create the file to simulate a previous export
    (tmp_path / "concept.parquet").write_bytes(b"dummy")

    with patch("scripts.export_vocab_parquet.psycopg2.connect") as mock_connect:
        export_vocab_tables(
            pg_host="localhost",
            pg_dbname="postgres",
            pg_user="postgres",
            pg_password="pass",
            vocab_schema="synthea23m",
            output_dir=str(tmp_path),
            tables=["concept"],
        )
        mock_connect.assert_not_called()


def test_export_all_tables_by_default(tmp_path):
    """export_vocab_tables exports all 5 vocab tables when tables=None."""
    import pandas as pd

    with patch("scripts.export_vocab_parquet.psycopg2.connect"):
        with patch("scripts.export_vocab_parquet.pd.read_sql") as mock_sql:
            mock_sql.return_value = iter([pd.DataFrame({"id": [1]})])
            export_vocab_tables(
                pg_host="localhost",
                pg_dbname="postgres",
                pg_user="postgres",
                pg_password="pass",
                vocab_schema="synthea23m",
                output_dir=str(tmp_path),
                tables=None,
            )

    expected = {"concept", "concept_ancestor", "concept_relationship", "vocabulary", "drug_strength"}
    created = {p.stem for p in tmp_path.glob("*.parquet")}
    assert created == expected
