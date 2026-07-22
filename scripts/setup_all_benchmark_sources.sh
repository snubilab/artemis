#!/bin/bash
# ============================================================
# Setup all benchmark CDM sources (one schema per study)
#
# Creates persistent per-study schemas so benchmark data is
# always available without DROP/reload cycles:
#
#   synthea_cdm_leader      + synthea_native_leader
#   synthea_cdm_plato       + synthea_native_plato
#   synthea_cdm_aristotle   + synthea_native_aristotle
#
# Each is registered as a WebAPI source for cohort generation.
#
# Usage:
#   cd artemis && bash scripts/setup_all_benchmark_sources.sh
#
# Prerequisites:
#   - broadsea-atlasdb container running
#   - Generated gold CSVs exist (from evaluate_generated_gold_studies.py)
#   - R with ETLSyntheaBuilder installed
#   - synthea23m schema with vocabulary tables (for VIEWs)
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ARTEMIS_DIR="$(dirname "$SCRIPT_DIR")"
DB_NAME="${ARTEMIS_DB_NAME:-postgres}"
DB_CONTAINER="broadsea-atlasdb"
DB_USER="postgres"
DB_PASS="mypass"

# Study definitions: STUDY_KEY|CSV_DIR
STUDIES=(
  "leader|${ARTEMIS_DIR}/output/generated_gold_eval/20260318_leader_10k_cachefix_retry/leader/synthea_output/csv"
  "plato|${ARTEMIS_DIR}/output/generated_gold_eval/20260318_plato_10k_cachefixfinal/plato/synthea_output/csv"
  "aristotle|${ARTEMIS_DIR}/output/generated_gold_eval/20260318_aristotle_10k_cachefix_retry/aristotle/synthea_output/csv"
)

log() { echo "[$(date +%H:%M:%S)] $*"; }

setup_study() {
  local study_key="$1"
  local csv_dir="$2"
  local cdm_schema="synthea_cdm_${study_key}"
  local native_schema="synthea_native_${study_key}"
  local results_schema="${cdm_schema}_results"

  log "=========================================="
  log "Setting up: $(echo $study_key | tr a-z A-Z)"
  log "  CDM schema:    $cdm_schema"
  log "  Native schema: $native_schema"
  log "  CSV dir:       $csv_dir"
  log "=========================================="

  # Verify CSV directory exists
  if [ ! -d "$csv_dir" ]; then
    log "WARNING: CSV directory not found: $csv_dir — skipping ${study_key}"
    return 1
  fi

  # Step 1: Create schemas
  log "[1/6] Creating schemas..."
  docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c "
    CREATE SCHEMA IF NOT EXISTS ${cdm_schema};
    CREATE SCHEMA IF NOT EXISTS ${native_schema};
    CREATE SCHEMA IF NOT EXISTS ${results_schema};
  "

  # Step 2: Check if data already loaded
  local person_count
  person_count=$(docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -At -c "
    SELECT COUNT(*) FROM information_schema.tables
    WHERE table_schema = '${cdm_schema}' AND table_name = 'person';
  " 2>/dev/null || echo "0")

  if [ "$person_count" = "1" ]; then
    local existing
    existing=$(docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -At -c "
      SELECT COUNT(*) FROM ${cdm_schema}.person;
    " 2>/dev/null || echo "0")
    if [ "$existing" -gt "0" ]; then
      log "Data already loaded ($existing persons). Skipping ETL."
      log "  To force reload, run: docker exec $DB_CONTAINER psql -U $DB_USER -d $DB_NAME -c 'DROP SCHEMA ${cdm_schema} CASCADE; DROP SCHEMA ${native_schema} CASCADE;'"
      return 0
    fi
  fi

  # Step 3: Create native tables via ETLSyntheaBuilder
  log "[2/6] Creating native Synthea tables..."
  ARTEMIS_DB_NAME="$DB_NAME" \
  BENCHMARK_CDM_SCHEMA="$cdm_schema" \
  BENCHMARK_NATIVE_SCHEMA="$native_schema" \
  Rscript "${SCRIPT_DIR}/setup_benchmark_native_tables.R" 2>&1 | tail -3

  # Step 4: Load CSVs into native schema
  log "[3/6] Copying CSVs to container..."
  docker exec "$DB_CONTAINER" rm -rf /tmp/synthea_csv
  docker cp "$csv_dir" "${DB_CONTAINER}:/tmp/synthea_csv"

  log "[4/6] Loading CSVs into native schema..."
  docker exec -i "$DB_CONTAINER" psql -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$DB_NAME" <<SQL
TRUNCATE TABLE ${native_schema}.patients CASCADE;
TRUNCATE TABLE ${native_schema}.encounters CASCADE;
TRUNCATE TABLE ${native_schema}.conditions CASCADE;
TRUNCATE TABLE ${native_schema}.medications CASCADE;
TRUNCATE TABLE ${native_schema}.procedures CASCADE;
TRUNCATE TABLE ${native_schema}.observations CASCADE;
TRUNCATE TABLE ${native_schema}.organizations CASCADE;
TRUNCATE TABLE ${native_schema}.providers CASCADE;

\copy ${native_schema}.patients FROM '/tmp/synthea_csv/patients.csv' WITH (FORMAT csv, HEADER true);
\copy ${native_schema}.encounters FROM '/tmp/synthea_csv/encounters.csv' WITH (FORMAT csv, HEADER true);
\copy ${native_schema}.conditions FROM '/tmp/synthea_csv/conditions.csv' WITH (FORMAT csv, HEADER true);
\copy ${native_schema}.medications FROM '/tmp/synthea_csv/medications.csv' WITH (FORMAT csv, HEADER true);
\copy ${native_schema}.procedures FROM '/tmp/synthea_csv/procedures.csv' WITH (FORMAT csv, HEADER true);
\copy ${native_schema}.observations FROM '/tmp/synthea_csv/observations.csv' WITH (FORMAT csv, HEADER true);
\copy ${native_schema}.organizations FROM '/tmp/synthea_csv/organizations.csv' WITH (FORMAT csv, HEADER true);
\copy ${native_schema}.providers FROM '/tmp/synthea_csv/providers.csv' WITH (FORMAT csv, HEADER true);
SQL

  # Step 5: Run R ETL (vocab views + mapping + event tables)
  log "[5/6] Running ETL (vocab views + mapping + event tables)..."
  ARTEMIS_DB_NAME="$DB_NAME" \
  BENCHMARK_CDM_SCHEMA="$cdm_schema" \
  BENCHMARK_NATIVE_SCHEMA="$native_schema" \
  Rscript "${SCRIPT_DIR}/run_etl_per_study.R" 2>&1 | tail -5

  # Step 6: Verify
  log "[6/6] Verifying..."
  docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c "
    SELECT
      '${study_key}' as study,
      (SELECT COUNT(*) FROM ${cdm_schema}.person) as persons,
      (SELECT COUNT(*) FROM ${cdm_schema}.condition_occurrence) as conditions,
      (SELECT COUNT(*) FROM ${cdm_schema}.drug_era) as drug_eras,
      (SELECT COUNT(*) FROM ${cdm_schema}.measurement) as measurements;
  "

  log "$(echo $study_key | tr a-z A-Z) setup complete!"
}

# Register WebAPI sources
register_webapi_sources() {
  log "=========================================="
  log "Registering WebAPI sources..."
  log "=========================================="

  for entry in "${STUDIES[@]}"; do
    IFS='|' read -r study_key csv_dir <<< "$entry"
    local cdm_schema="synthea_cdm_${study_key}"
    local results_schema="${cdm_schema}_results"
    local source_key="$(echo $study_key | tr a-z A-Z)_BENCHMARK"
    local source_name="Benchmark $(echo $study_key | tr a-z A-Z) (10K patients)"

    # Check if source already exists
    local exists
    exists=$(docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -At -c "
      SELECT COUNT(*) FROM webapi.source WHERE source_key = '${source_key}';
    " 2>/dev/null || echo "0")

    if [ "$exists" = "1" ]; then
      log "Source ${source_key} already registered. Skipping."
      continue
    fi

    log "Registering source: ${source_key}..."
    docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c "
      INSERT INTO webapi.source (source_name, source_key, source_connection, source_dialect)
      VALUES ('${source_name}', '${source_key}', 'jdbc:postgresql://localhost:5432/${DB_NAME}', 'postgresql');
    " 2>/dev/null || log "WARNING: Could not register source ${source_key} (may need manual WebAPI config)"

    # Add CDM and Results daimons
    local source_id
    source_id=$(docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -At -c "
      SELECT source_id FROM webapi.source WHERE source_key = '${source_key}';
    " 2>/dev/null || echo "")

    if [ -n "$source_id" ]; then
      docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c "
        INSERT INTO webapi.source_daimon (source_id, daimon_type, table_qualifier, priority)
        VALUES
          (${source_id}, 0, '${cdm_schema}', 2),
          (${source_id}, 1, '${cdm_schema}', 2),
          (${source_id}, 2, '${results_schema}', 2)
        ON CONFLICT DO NOTHING;
      " 2>/dev/null || true
      log "Registered ${source_key} (source_id=${source_id})"
    fi
  done
}

# Main
log "Setting up all benchmark sources..."
echo ""

for entry in "${STUDIES[@]}"; do
  IFS='|' read -r study_key csv_dir <<< "$entry"
  setup_study "$study_key" "$csv_dir" || true
  echo ""
done

register_webapi_sources
echo ""

log "=========================================="
log "ALL BENCHMARK SOURCES SETUP COMPLETE"
log "=========================================="
log ""
log "Available sources:"
for entry in "${STUDIES[@]}"; do
  IFS='|' read -r study_key csv_dir <<< "$entry"
  log "  $(echo $study_key | tr a-z A-Z)_BENCHMARK → synthea_cdm_${study_key}"
done
log ""
log "Usage: COHORT_ENGINE=spark WEBAPI_SOURCE_KEY=LEADER_BENCHMARK python3 ..."
