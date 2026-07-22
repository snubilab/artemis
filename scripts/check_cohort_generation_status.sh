#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  check_cohort_generation_status.sh COHORT_DEFINITION_ID [--watch SECONDS]

Examples:
  artemis/scripts/check_cohort_generation_status.sh 483
  artemis/scripts/check_cohort_generation_status.sh 483 --watch 10

Optional environment variables:
  WEBAPI_URL           Default: http://127.0.0.1/WebAPI
  ATLASDB_CONTAINER    Default: broadsea-atlasdb
  OHDSI_DB             Default: ohdsi
  RESULTS_SCHEMA       Default: synthea_cdm_benchmark_results
EOF
}

if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

COHORT_ID="$1"
shift

WATCH_INTERVAL=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --watch)
      WATCH_INTERVAL="${2:-}"
      if [[ -z "$WATCH_INTERVAL" ]]; then
        echo "--watch requires a seconds value" >&2
        exit 1
      fi
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

WEBAPI_URL="${WEBAPI_URL:-http://127.0.0.1/WebAPI}"
ATLASDB_CONTAINER="${ATLASDB_CONTAINER:-broadsea-atlasdb}"
OHDSI_DB="${OHDSI_DB:-ohdsi}"
RESULTS_SCHEMA="${RESULTS_SCHEMA:-synthea_cdm_benchmark_results}"

print_webapi_info() {
  python - "$WEBAPI_URL" "$COHORT_ID" <<'PY'
import json
import sys
import urllib.request

base_url, cohort_id = sys.argv[1], sys.argv[2]
url = f"{base_url.rstrip('/')}/cohortdefinition/{cohort_id}/info"

try:
    with urllib.request.urlopen(url, timeout=30) as resp:
        body = json.loads(resp.read().decode())
except Exception as exc:
    print(f"webapi_error: {exc}")
    sys.exit(0)

if not body:
    print("status: <no info>")
    sys.exit(0)

info = body[0]
print(f"status: {info.get('status')}")
print(f"executionDuration: {info.get('executionDuration')}")
print(f"personCount: {info.get('personCount')}")
print(f"recordCount: {info.get('recordCount')}")
print(f"failMessage: {info.get('failMessage')}")
print(f"isValid: {info.get('isValid')}")
print(f"isCanceled: {info.get('isCanceled')}")
PY
}

print_row_count() {
  docker exec "$ATLASDB_CONTAINER" \
    psql -U postgres -d "$OHDSI_DB" -Atqc \
    "select count(*) from ${RESULTS_SCHEMA}.cohort where cohort_definition_id = ${COHORT_ID};"
}

print_activity() {
  docker exec "$ATLASDB_CONTAINER" \
    psql -U postgres -d "$OHDSI_DB" -Atqc \
    "select pid, state, now()-query_start as runtime, left(query,180)
     from pg_stat_activity
     where datname='${OHDSI_DB}'
       and pid <> pg_backend_pid()
       and state <> 'idle'
     order by query_start;"
}

render_once() {
  echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
  echo "cohort_definition_id: ${COHORT_ID}"
  echo
  echo "=== webapi info ==="
  print_webapi_info
  echo
  echo "=== results row count ==="
  print_row_count
  echo
  echo "=== active ohdsi queries ==="
  local activity
  activity="$(print_activity)"
  if [[ -n "$activity" ]]; then
    echo "$activity"
  else
    echo "<none>"
  fi
}

if [[ -n "$WATCH_INTERVAL" ]]; then
  while true; do
    clear
    render_once
    sleep "$WATCH_INTERVAL"
  done
else
  render_once
fi
