#!/bin/bash
set -euo pipefail

DB_NAME="${ARTEMIS_DB_NAME:-ohdsi}"

# Kill any active queries on benchmark schemas that would block DROP
echo "Terminating blocking queries on benchmark schemas..."
docker exec broadsea-atlasdb psql -v ON_ERROR_STOP=0 -U postgres -d "$DB_NAME" -c "
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE state = 'active'
  AND pid != pg_backend_pid()
  AND (query ILIKE '%synthea_cdm_benchmark%' OR query ILIKE '%synthea_native_benchmark%');
" 2>/dev/null || true
sleep 2

echo "Dropping and recreating benchmark schemas (CDM + native)..."
docker exec broadsea-atlasdb psql -v ON_ERROR_STOP=1 -U postgres -d "$DB_NAME" -c "DROP SCHEMA IF EXISTS synthea_cdm_benchmark CASCADE; DROP SCHEMA IF EXISTS synthea_native_benchmark CASCADE; CREATE SCHEMA synthea_cdm_benchmark; CREATE SCHEMA synthea_native_benchmark;"

echo "Running ETLSyntheaBuilder pipeline..."
if Rscript scripts/run_etl_benchmark.R > /tmp/run_etl.log 2>&1; then
  echo "ETL completely finished. Exit code: 0"
else
  status=$?
  echo "ETL failed. Exit code: $status"
  tail -n 200 /tmp/run_etl.log || true
  exit "$status"
fi
