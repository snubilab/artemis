#!/bin/bash
# setup_study_benchmarks.sh
# Permanently set up LEADER, PLATO, ARISTOTLE benchmark CDM schemas.
# Schemas survive Docker restarts (stored in broadsea-atlasdb volume).
#
# Usage:
#   bash artemis/scripts/setup_study_benchmarks.sh [leader|plato|aristotle|all]

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
DB="${ARTEMIS_DB_NAME:?ARTEMIS_DB_NAME must be set (e.g. ARTEMIS_DB_NAME=postgres)}"
JDBC_DIR="/Users/kyh/Workspace/Broadsea/jdbc"

LEADER_CSV="$REPO_DIR/artemis/output/generated_gold_eval/20260318_leader_10k_cachefix/leader/synthea_output/csv"
PLATO_CSV="$REPO_DIR/artemis/output/generated_gold_eval/20260318_plato_10k_cachefixfinal/plato/synthea_output/csv"
ARISTOTLE_CSV="$REPO_DIR/artemis/output/aristotle_patch_scale20_20k/csv"

psql() { docker exec -i -u postgres broadsea-atlasdb psql "$DB" "$@"; }

setup_study() {
  local STUDY="$1"
  local CDM="$2"
  local NATIVE="$3"
  local RESULTS="$4"
  local CSV="$5"

  echo ""
  echo "══════════════════════════════════════════════════════"
  echo "  $STUDY  →  CDM: $CDM  |  native: $NATIVE"
  echo "══════════════════════════════════════════════════════"

  if [ ! -f "$CSV/patients.csv" ]; then
    echo "ERROR: CSV not found: $CSV/patients.csv"; exit 1
  fi
  echo "  patients.csv: $(( $(wc -l < "$CSV/patients.csv") - 1 )) rows"

  # ── 1. Schemas ──────────────────────────────────────────
  echo "[1/5] Creating schemas..."
  psql -c "
    SELECT pg_terminate_backend(pid) FROM pg_stat_activity
    WHERE state='active' AND pid!=pg_backend_pid()
    AND (query ILIKE '%$CDM%' OR query ILIKE '%$NATIVE%');
  " 2>/dev/null || true
  sleep 1
  psql -c "
    DROP SCHEMA IF EXISTS $CDM     CASCADE;
    DROP SCHEMA IF EXISTS $NATIVE  CASCADE;
    DROP SCHEMA IF EXISTS $RESULTS CASCADE;
    CREATE SCHEMA $CDM;
    CREATE SCHEMA $NATIVE;
    CREATE SCHEMA $RESULTS;
  "

  # ── 2. Create CDM + native tables via R ─────────────────
  echo "[2/5] Creating CDM and native tables..."
  CDM_SCHEMA="$CDM" NATIVE_SCHEMA="$NATIVE" ARTEMIS_DB_NAME="$DB" \
  Rscript - <<'REOF'
.libPaths(c("~/R/library", .libPaths()))
library(ETLSyntheaBuilder); library(DatabaseConnector)
cd <- DatabaseConnector::createConnectionDetails(
  dbms="postgresql", server=paste0("localhost/", Sys.getenv("ARTEMIS_DB_NAME","ohdsi")),
  user="postgres", password="mypass", port=5432,
  pathToDriver="/Users/kyh/Workspace/Broadsea/jdbc")
cdm    <- Sys.getenv("CDM_SCHEMA")
native <- Sys.getenv("NATIVE_SCHEMA")
ETLSyntheaBuilder::CreateCDMTables(connectionDetails=cd, cdmSchema=cdm, cdmVersion="5.4")
ETLSyntheaBuilder::CreateSyntheaTables(connectionDetails=cd, syntheaSchema=native, syntheaVersion="3.3.0")
cat("Tables created.\n")
REOF

  # ── 3. Load CSVs ─────────────────────────────────────────
  echo "[3/5] Loading CSVs into $NATIVE..."
  docker exec broadsea-atlasdb rm -rf /tmp/sc_csv
  docker cp "$CSV" broadsea-atlasdb:/tmp/sc_csv

  psql <<SQL
\copy $NATIVE.patients      FROM '/tmp/sc_csv/patients.csv'      WITH (FORMAT csv, HEADER true);
\copy $NATIVE.encounters    FROM '/tmp/sc_csv/encounters.csv'    WITH (FORMAT csv, HEADER true);
\copy $NATIVE.conditions    FROM '/tmp/sc_csv/conditions.csv'    WITH (FORMAT csv, HEADER true);
\copy $NATIVE.medications   FROM '/tmp/sc_csv/medications.csv'   WITH (FORMAT csv, HEADER true);
\copy $NATIVE.procedures    FROM '/tmp/sc_csv/procedures.csv'    WITH (FORMAT csv, HEADER true);
\copy $NATIVE.observations  FROM '/tmp/sc_csv/observations.csv'  WITH (FORMAT csv, HEADER true);
\copy $NATIVE.organizations FROM '/tmp/sc_csv/organizations.csv' WITH (FORMAT csv, HEADER true);
\copy $NATIVE.providers     FROM '/tmp/sc_csv/providers.csv'     WITH (FORMAT csv, HEADER true);
SQL

  # ── 4. Vocabulary views + OMOP ETL ───────────────────────
  echo "[4/5] Vocab views + OMOP ETL (20-40 min)..."
  local LOG="/tmp/etl_${STUDY}.log"
  CDM_SCHEMA="$CDM" NATIVE_SCHEMA="$NATIVE" ARTEMIS_DB_NAME="$DB" \
  Rscript "$REPO_DIR/artemis/scripts/run_etl_study.R" > "$LOG" 2>&1 && \
    echo "  ETL complete." || { echo "ETL FAILED. See $LOG"; tail -30 "$LOG"; exit 1; }

  # ── 5. Verify ────────────────────────────────────────────
  echo "[5/5] Verification:"
  psql -c "
    SELECT 'person'             AS tbl, count(*) FROM $CDM.person
    UNION ALL SELECT 'drug_exposure'    , count(*) FROM $CDM.drug_exposure
    UNION ALL SELECT 'condition_occ'    , count(*) FROM $CDM.condition_occurrence
    UNION ALL SELECT 'visit_occurrence' , count(*) FROM $CDM.visit_occurrence;
  "
  echo "  Done: $STUDY"
}

TARGET="${1:-all}"

case "$TARGET" in
  leader)
    setup_study LEADER synthea_cdm_leader synthea_native_leader synthea_cdm_leader_results "$LEADER_CSV"
    ;;
  plato)
    setup_study PLATO synthea_cdm_plato synthea_native_plato synthea_cdm_plato_results "$PLATO_CSV"
    ;;
  aristotle)
    setup_study ARISTOTLE synthea_cdm_aristotle synthea_native_aristotle synthea_cdm_aristotle_results "$ARISTOTLE_CSV"
    ;;
  all)
    setup_study LEADER    synthea_cdm_leader    synthea_native_leader    synthea_cdm_leader_results    "$LEADER_CSV"
    setup_study PLATO     synthea_cdm_plato     synthea_native_plato     synthea_cdm_plato_results     "$PLATO_CSV"
    setup_study ARISTOTLE synthea_cdm_aristotle synthea_native_aristotle synthea_cdm_aristotle_results "$ARISTOTLE_CSV"
    echo ""
    echo "All 3 benchmark schemas are permanently set up."
    ;;
  *)
    echo "Usage: $0 [leader|plato|aristotle|all]"
    exit 1
    ;;
esac
