"""Export OMOP vocabulary tables from PostgreSQL to Parquet.

concept_ancestor (75M rows) and concept_relationship (39M rows) cannot be
read by Spark JDBC without OOM. This script exports them once to Parquet
for Spark to read directly via SPARK_PARQUET_DIR.

Usage (inside container):
    python -m scripts.export_vocab_parquet
Or with args:
    python -m scripts.export_vocab_parquet --pg-host broadsea-atlasdb
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
from typing import Optional

import pandas as pd
import psycopg2
import pyarrow as pa
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

VOCAB_TABLES: dict[str, str] = {
    "concept": "SELECT * FROM {schema}.concept",
    "concept_ancestor": "SELECT * FROM {schema}.concept_ancestor",
    "concept_relationship": "SELECT * FROM {schema}.concept_relationship",
    "vocabulary": "SELECT * FROM {schema}.vocabulary",
    "drug_strength": "SELECT * FROM {schema}.drug_strength",
}

CHUNK_SIZE = 500_000  # rows per read chunk — limits peak RAM to ~2GB per chunk


def export_vocab_tables(
    pg_host: str,
    pg_dbname: str,
    pg_user: str,
    pg_password: str,
    vocab_schema: str,
    output_dir: str,
    tables: Optional[list[str]] = None,
    pg_port: int = 5432,
) -> None:
    """Export vocab tables to Parquet. Skip tables whose file already exists.

    Uses chunked PyArrow writer to avoid loading full 75M-row tables into RAM
    simultaneously (would require ~6GB for concept_ancestor).
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    target_tables = tables if tables is not None else list(VOCAB_TABLES.keys())
    to_export = [t for t in target_tables if not (out / f"{t}.parquet").exists()]

    if not to_export:
        logger.info("All vocab Parquet files already exist in %s — skipping.", output_dir)
        return

    conn_str = (
        f"host={pg_host} port={pg_port} dbname={pg_dbname} "
        f"user={pg_user} password={pg_password}"
    )
    conn = psycopg2.connect(conn_str)

    try:
        for table in to_export:
            out_path = out / f"{table}.parquet"
            sql = VOCAB_TABLES[table].format(schema=vocab_schema)
            logger.info("Exporting %s → %s ...", table, out_path)

            writer = None
            total_rows = 0
            try:
                for chunk in pd.read_sql(sql, conn, chunksize=CHUNK_SIZE):
                    arrow_table = pa.Table.from_pandas(chunk, preserve_index=False)
                    if writer is None:
                        writer = pq.ParquetWriter(str(out_path), arrow_table.schema)
                    writer.write_table(arrow_table)
                    total_rows += len(chunk)
            finally:
                if writer is not None:
                    writer.close()
                elif not out_path.exists():
                    # No chunks returned (empty table) — write an empty parquet file
                    # so the skip-existing logic works correctly on reruns.
                    empty = pa.table({})
                    pq.write_table(empty, str(out_path))

            logger.info("  %d rows → %s", total_rows, out_path)
    finally:
        conn.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Export OMOP vocab tables to Parquet.")
    parser.add_argument("--pg-host", default=os.environ.get("OMOP_DB_HOST", "broadsea-atlasdb"))
    parser.add_argument("--pg-port", type=int, default=5432)
    parser.add_argument("--pg-dbname", default=os.environ.get("OMOP_DB_NAME", "postgres"))
    parser.add_argument("--pg-user", default=os.environ.get("OMOP_DB_USER", "postgres"))
    parser.add_argument("--pg-password", default=os.environ.get("OMOP_DB_PASSWORD", "mypass"))
    parser.add_argument("--vocab-schema", default=os.environ.get("VOCAB_SCHEMA", "synthea23m"))
    parser.add_argument(
        "--output-dir",
        default=os.environ.get("SPARK_PARQUET_DIR", "/app/tmp/parquet"),
    )
    parser.add_argument("--tables", nargs="*")
    args = parser.parse_args()

    export_vocab_tables(
        pg_host=args.pg_host,
        pg_port=args.pg_port,
        pg_dbname=args.pg_dbname,
        pg_user=args.pg_user,
        pg_password=args.pg_password,
        vocab_schema=args.vocab_schema,
        output_dir=args.output_dir,
        tables=args.tables,
    )


if __name__ == "__main__":
    main()
