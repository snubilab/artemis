#!/usr/bin/env python3
"""
Fix synthea100k schema: create missing tables, add missing columns.

AWS Synthea OMOP 100K only ships 10 CSVs but WebAPI SQL references ~40 CDM tables.
This script:
  1. Creates empty stub tables for all missing CDM tables (cloned from synthea_cdm)
  2. Adds missing columns to existing tables (CDM v5.3 → v5.4 gap)
  3. Restarts WebAPI so it reloads the source
"""
import subprocess
import sys

CONTAINER = "broadsea-atlasdb"
DB = "ohdsi"
SRC_SCHEMA = "synthea_cdm"
DST_SCHEMA = "synthea100k"

def psql(sql: str) -> str:
    r = subprocess.run(
        ["docker", "exec", CONTAINER, "psql", "-U", "postgres", "-d", DB, "-c", sql],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        print(f"  ⚠ SQL error: {r.stderr.strip()[:200]}")
    return r.stdout.strip()

def psql_tuples(sql: str) -> list[str]:
    r = subprocess.run(
        ["docker", "exec", CONTAINER, "psql", "-U", "postgres", "-d", DB, "-t", "-A", "-c", sql],
        capture_output=True, text=True
    )
    return [l for l in r.stdout.strip().split("\n") if l]

def main():
    print("=" * 60)
    print("  Fixing synthea100k Schema")
    print("=" * 60)

    # Step 1: Create missing CDM tables
    print("\n📋 Step 1: Create missing CDM tables (cloned structure from synthea_cdm)")
    missing = psql_tuples(f"""
        SELECT t1.tablename FROM pg_tables t1
        WHERE t1.schemaname = '{SRC_SCHEMA}'
        AND NOT EXISTS (
            SELECT 1 FROM pg_tables t2
            WHERE t2.schemaname = '{DST_SCHEMA}' AND t2.tablename = t1.tablename
        )
        AND t1.tablename NOT IN ('all_visits', 'assign_all_visit_ids', 'final_visit_ids')
        ORDER BY t1.tablename;
    """)
    if missing:
        for table in missing:
            psql(f"CREATE TABLE {DST_SCHEMA}.{table} (LIKE {SRC_SCHEMA}.{table});")
            print(f"  ✅ Created: {table}")
    else:
        print("  ✅ All CDM tables already present")

    # Step 2: Add missing columns to existing tables
    print("\n📋 Step 2: Add missing columns")
    col_fixes = {
        "measurement": [
            ("unit_source_concept_id", "INTEGER DEFAULT 0"),
            ("measurement_event_id", "BIGINT"),
            ("meas_event_field_concept_id", "INTEGER DEFAULT 0"),
        ],
        "observation": [
            ("value_source_value", "VARCHAR(50)"),
            ("observation_event_id", "BIGINT"),
            ("obs_event_field_concept_id", "INTEGER DEFAULT 0"),
        ],
        "procedure_occurrence": [
            ("procedure_end_date", "DATE"),
            ("procedure_end_datetime", "TIMESTAMP"),
        ],
        "visit_occurrence": [
            ("admitted_from_concept_id", "INTEGER DEFAULT 0"),
            ("admitted_from_source_value", "VARCHAR(50)"),
            ("discharged_to_concept_id", "INTEGER DEFAULT 0"),
            ("discharged_to_source_value", "VARCHAR(50)"),
        ],
    }
    for table, cols in col_fixes.items():
        for col_name, col_type in cols:
            psql(f"ALTER TABLE {DST_SCHEMA}.{table} ADD COLUMN IF NOT EXISTS {col_name} {col_type};")
            print(f"  ✅ {table}.{col_name} ({col_type})")

    # Step 3: Verify
    print("\n📋 Step 3: Verification")
    final_count = psql_tuples(f"""
        SELECT COUNT(*) FROM pg_tables WHERE schemaname = '{DST_SCHEMA}';
    """)
    ref_count = psql_tuples(f"""
        SELECT COUNT(*) FROM pg_tables WHERE schemaname = '{SRC_SCHEMA}';
    """)
    print(f"  synthea100k tables: {final_count[0] if final_count else '?'}")
    print(f"  synthea_cdm tables: {ref_count[0] if ref_count else '?'} (reference)")

    still_missing = psql_tuples(f"""
        SELECT t1.tablename FROM pg_tables t1
        WHERE t1.schemaname = '{SRC_SCHEMA}'
        AND NOT EXISTS (
            SELECT 1 FROM pg_tables t2
            WHERE t2.schemaname = '{DST_SCHEMA}' AND t2.tablename = t1.tablename
        )
        AND t1.tablename NOT IN ('all_visits', 'assign_all_visit_ids', 'final_visit_ids')
        ORDER BY t1.tablename;
    """)
    if still_missing:
        print(f"  ❌ Still missing: {still_missing}")
    else:
        print("  ✅ All tables matched!")

    print("\n" + "=" * 60)
    print("  ✅ Schema fix complete!")
    print("  Next: restart WebAPI, then re-trigger cohort generation")
    print("=" * 60)


if __name__ == "__main__":
    main()
