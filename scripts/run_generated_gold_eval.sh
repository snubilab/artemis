#!/bin/bash
set -euo pipefail

ROOT_DIR="/Users/kyh/Workspace/Broadsea"
ARTEMIS_DIR="$ROOT_DIR/artemis"

STUDIES="${1:-LEADER,PLATO,ARISTOTLE,EMPA-REG}"
PATIENTS="${PATIENTS:-10000}"
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)_generated_gold_eval}"

cd "$ROOT_DIR"

echo "Running generated Gold evaluation"
echo "  studies  : $STUDIES"
echo "  patients : $PATIENTS"
echo "  run_id   : $RUN_ID"

python "$ARTEMIS_DIR/scripts/evaluate_generated_gold_studies.py" \
  --studies "$STUDIES" \
  --patients "$PATIENTS" \
  --run-id "$RUN_ID"
