#!/usr/bin/env python3
"""Load pre-built Synthea 100K OMOP dataset into PostgreSQL."""
import subprocess
import sys
import os

DATA_DIR = "/Users/kyh/Workspace/Broadsea/data/synthea_omop_100k"
CONTAINER = "broadsea-atlasdb"
SCHEMA = "synthea100k"
RESULTS_SCHEMA = "synthea100k_results"

# Table definitions matching the CSV headers exactly (OMOP CDM v5.4)
TABLES = {
    "person": """
        person_id INTEGER, gender_concept_id INTEGER, year_of_birth INTEGER,
        month_of_birth INTEGER, day_of_birth INTEGER, birth_datetime TIMESTAMP,
        race_concept_id INTEGER, ethnicity_concept_id INTEGER,
        location_id INTEGER, provider_id INTEGER, care_site_id INTEGER,
        person_source_value VARCHAR(50), gender_source_value VARCHAR(50),
        gender_source_concept_id INTEGER, race_source_value VARCHAR(50),
        race_source_concept_id INTEGER, ethnicity_source_value VARCHAR(50),
        ethnicity_source_concept_id INTEGER
    """,
    "observation_period": """
        observation_period_id INTEGER, person_id INTEGER,
        observation_period_start_date DATE, observation_period_end_date DATE,
        period_type_concept_id INTEGER
    """,
    "visit_occurrence": """
        visit_occurrence_id INTEGER, person_id INTEGER, visit_concept_id INTEGER,
        visit_start_date DATE, visit_start_datetime TIMESTAMP,
        visit_end_date DATE, visit_end_datetime TIMESTAMP,
        visit_type_concept_id INTEGER, provider_id INTEGER, care_site_id INTEGER,
        visit_source_value VARCHAR(50), visit_source_concept_id INTEGER,
        admitting_source_concept_id INTEGER, admitting_source_value VARCHAR(50),
        discharge_to_concept_id INTEGER, discharge_to_source_value VARCHAR(50),
        preceding_visit_occurrence_id INTEGER
    """,
    "condition_occurrence": """
        condition_occurrence_id INTEGER, person_id INTEGER,
        condition_concept_id INTEGER, condition_start_date DATE,
        condition_start_datetime TIMESTAMP, condition_end_date DATE,
        condition_end_datetime TIMESTAMP, condition_type_concept_id INTEGER,
        stop_reason VARCHAR(20), provider_id INTEGER,
        visit_occurrence_id INTEGER, visit_detail_id INTEGER,
        condition_source_value VARCHAR(50), condition_source_concept_id INTEGER,
        condition_status_source_value VARCHAR(50), condition_status_concept_id INTEGER
    """,
    "drug_exposure": """
        drug_exposure_id INTEGER, person_id INTEGER, drug_concept_id INTEGER,
        drug_exposure_start_date DATE, drug_exposure_start_datetime TIMESTAMP,
        drug_exposure_end_date DATE, drug_exposure_end_datetime TIMESTAMP,
        verbatim_end_date DATE, drug_type_concept_id INTEGER,
        stop_reason VARCHAR(20), refills INTEGER, quantity NUMERIC,
        days_supply INTEGER, sig TEXT, route_concept_id INTEGER,
        lot_number VARCHAR(50), provider_id INTEGER,
        visit_occurrence_id INTEGER, visit_detail_id INTEGER,
        drug_source_value VARCHAR(50), drug_source_concept_id INTEGER,
        route_source_value VARCHAR(50), dose_unit_source_value VARCHAR(50)
    """,
    "measurement": """
        measurement_id INTEGER, person_id INTEGER, measurement_concept_id INTEGER,
        measurement_date DATE, measurement_datetime TIMESTAMP,
        measurement_time VARCHAR(10), measurement_type_concept_id INTEGER,
        operator_concept_id INTEGER, value_as_number NUMERIC,
        value_as_concept_id INTEGER, unit_concept_id INTEGER,
        range_low NUMERIC, range_high NUMERIC, provider_id INTEGER,
        visit_occurrence_id INTEGER, visit_detail_id INTEGER,
        measurement_source_value VARCHAR(50), measurement_source_concept_id INTEGER,
        unit_source_value VARCHAR(50), value_source_value VARCHAR(50)
    """,
    "observation": """
        observation_id INTEGER, person_id INTEGER, observation_concept_id INTEGER,
        observation_date DATE, observation_datetime TIMESTAMP,
        observation_type_concept_id INTEGER, value_as_number NUMERIC,
        value_as_string VARCHAR(60), value_as_concept_id INTEGER,
        qualifier_concept_id INTEGER, unit_concept_id INTEGER,
        provider_id INTEGER, visit_occurrence_id INTEGER, visit_detail_id INTEGER,
        observation_source_value VARCHAR(50), observation_source_concept_id INTEGER,
        unit_source_value VARCHAR(50), qualifier_source_value VARCHAR(50)
    """,
    "procedure_occurrence": """
        procedure_occurrence_id INTEGER, person_id INTEGER,
        procedure_concept_id INTEGER, procedure_date DATE,
        procedure_datetime TIMESTAMP, procedure_type_concept_id INTEGER,
        modifier_concept_id INTEGER, quantity INTEGER,
        provider_id INTEGER, visit_occurrence_id INTEGER, visit_detail_id INTEGER,
        procedure_source_value VARCHAR(50), procedure_source_concept_id INTEGER,
        modifier_source_value VARCHAR(50)
    """,
    "condition_era": """
        condition_era_id INTEGER, person_id INTEGER,
        condition_concept_id INTEGER, condition_era_start_date DATE,
        condition_era_end_date DATE, condition_occurrence_count INTEGER
    """,
    "drug_era": """
        drug_era_id INTEGER, person_id INTEGER, drug_concept_id INTEGER,
        drug_era_start_date DATE, drug_era_end_date DATE,
        drug_exposure_count INTEGER, gap_days INTEGER
    """,
}


def run(cmd: str, check: bool = True) -> str:
    """Run a shell command and return stdout."""
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and r.returncode != 0:
        print(f"  ❌ {cmd[:80]}...")
        print(f"     {r.stderr.strip()[:200]}")
        sys.exit(1)
    return r.stdout.strip()


def docker_psql(sql: str) -> str:
    """Execute SQL inside the Docker PostgreSQL container."""
    escaped = sql.replace("'", "'\\''")
    return run(f"docker exec {CONTAINER} psql -U postgres -d ohdsi -c '{escaped}'")


def main():
    print("=" * 60)
    print("  Loading Synthea 100K OMOP Dataset")
    print("=" * 60)

    # 1. Create tables
    print("\n📋 Step 1: Creating tables...")
    for table, cols in TABLES.items():
        docker_psql(f"DROP TABLE IF EXISTS {SCHEMA}.{table} CASCADE;")
        docker_psql(f"CREATE TABLE {SCHEMA}.{table} ({cols});")
        print(f"  ✅ {SCHEMA}.{table}")

    # 2. Create vocab views (reuse from synthea_cdm)
    print("\n📚 Step 2: Creating vocabulary views...")
    vocab_tables = [
        "concept", "concept_ancestor", "concept_relationship",
        "concept_synonym", "vocabulary", "domain", "concept_class",
        "relationship", "drug_strength"
    ]
    for vt in vocab_tables:
        docker_psql(f"DROP VIEW IF EXISTS {SCHEMA}.{vt} CASCADE;")
        result = run(
            f"docker exec {CONTAINER} psql -U postgres -d ohdsi -c "
            f"\"SELECT 1 FROM information_schema.tables WHERE table_schema='synthea_cdm' AND table_name='{vt}' LIMIT 1;\"",
            check=False
        )
        if "1" in result:
            docker_psql(f"CREATE VIEW {SCHEMA}.{vt} AS SELECT * FROM synthea_cdm.{vt};")
            print(f"  ✅ {SCHEMA}.{vt} (view)")
        else:
            print(f"  ⚠  synthea_cdm.{vt} not found, skipping")

    # 3. Create results tables
    print("\n📊 Step 3: Creating results schema tables...")
    results_sql = f"""
        DROP TABLE IF EXISTS {RESULTS_SCHEMA}.cohort CASCADE;
        CREATE TABLE {RESULTS_SCHEMA}.cohort (
            cohort_definition_id int NOT NULL, subject_id bigint NOT NULL,
            cohort_start_date date NOT NULL, cohort_end_date date NOT NULL
        );
        DROP TABLE IF EXISTS {RESULTS_SCHEMA}.cohort_inclusion CASCADE;
        CREATE TABLE {RESULTS_SCHEMA}.cohort_inclusion (
            cohort_definition_id int, design_hash int, rule_sequence int,
            name varchar(255), description varchar(1000)
        );
        DROP TABLE IF EXISTS {RESULTS_SCHEMA}.cohort_inclusion_result CASCADE;
        CREATE TABLE {RESULTS_SCHEMA}.cohort_inclusion_result (
            cohort_definition_id int, mode_id int DEFAULT 0,
            inclusion_rule_mask bigint, person_count bigint
        );
        DROP TABLE IF EXISTS {RESULTS_SCHEMA}.cohort_inclusion_stats CASCADE;
        CREATE TABLE {RESULTS_SCHEMA}.cohort_inclusion_stats (
            cohort_definition_id int, rule_sequence int, mode_id int DEFAULT 0,
            person_count bigint, gain_count bigint, person_total bigint
        );
        DROP TABLE IF EXISTS {RESULTS_SCHEMA}.cohort_summary_stats CASCADE;
        CREATE TABLE {RESULTS_SCHEMA}.cohort_summary_stats (
            cohort_definition_id int, mode_id int DEFAULT 0,
            base_count bigint, final_count bigint
        );
        DROP TABLE IF EXISTS {RESULTS_SCHEMA}.cohort_censor_stats CASCADE;
        CREATE TABLE {RESULTS_SCHEMA}.cohort_censor_stats (
            cohort_definition_id int, lost_count bigint
        );
    """
    for stmt in results_sql.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            docker_psql(stmt + ";")
    print(f"  ✅ {RESULTS_SCHEMA} tables created")

    # 4. Copy CSV files to Docker and load
    print("\n📦 Step 4: Copying CSVs to Docker container...")
    run(f"docker exec {CONTAINER} rm -rf /tmp/synthea100k", check=False)
    run(f"docker exec {CONTAINER} mkdir -p /tmp/synthea100k")

    for table in TABLES:
        csv_file = f"{table}.csv"
        csv_path = os.path.join(DATA_DIR, csv_file)
        if not os.path.exists(csv_path):
            print(f"  ⚠  {csv_file} not found, skipping")
            continue

        size_mb = os.path.getsize(csv_path) / (1024 * 1024)
        print(f"  📤 Copying {csv_file} ({size_mb:.0f} MB)...")
        run(f"docker cp {csv_path} {CONTAINER}:/tmp/synthea100k/{csv_file}")

    # 5. Bulk load with \copy
    print("\n🔄 Step 5: Loading data into PostgreSQL...")
    for table in TABLES:
        csv_file = f"/tmp/synthea100k/{table}.csv"
        print(f"  ⏳ Loading {table}...", end="", flush=True)
        result = run(
            f"docker exec {CONTAINER} psql -U postgres -d ohdsi -c "
            f"\"\\copy {SCHEMA}.{table} FROM '{csv_file}' CSV HEADER\"",
        )
        # Extract row count
        count_result = docker_psql(f"SELECT COUNT(*) FROM {SCHEMA}.{table};")
        # Parse count
        lines = count_result.strip().split("\n")
        count = "?"
        for line in lines:
            line = line.strip()
            if line.isdigit():
                count = f"{int(line):,}"
                break
        print(f" ✅ {count} rows")

    # 6. Summary
    print("\n" + "=" * 60)
    print("  ✅ Loading Complete!")
    print("=" * 60)
    for table in TABLES:
        count_result = docker_psql(f"SELECT COUNT(*) FROM {SCHEMA}.{table};")
        lines = count_result.strip().split("\n")
        for line in lines:
            line = line.strip()
            if line.isdigit():
                print(f"  {table:30s} {int(line):>12,}")
                break


if __name__ == "__main__":
    main()
