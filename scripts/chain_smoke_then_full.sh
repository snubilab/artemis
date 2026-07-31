#!/usr/bin/env bash
# Gate the full re-ingest on the smoke's number, not on someone reading a log.
#
# The smoke runs ARISTOTLE alone, which is where Agent 1 dropped
# "ALT or AST > 2X ULN or a Total Bilirubin >= 1.5X ULN" to a bare
# "Liver Enzyme Elevation" label. The deterministic parser reads that sentence as
# two ratio constraints and the prompt now carries its answer, so the smoke either
# shows them in the IR or the annotation is not reaching the model.
#
#   floor    0  ratio constraints on ARISTOTLE today
#   pass     >= 1
#   ceiling  2  what parse_value_constraints extracts from the source text
#
# A pass runs both studies; a fail stops and says so rather than spending the GPU
# to reproduce the same zero twice.
#
#   nohup artemis/scripts/chain_smoke_then_full.sh <smoke-pid> > /tmp/smoke_chain.log 2>&1 &
#
set -uo pipefail

WAIT_PID="${1:?usage: $0 <pid of the smoke run>}"
REPO=/home/bilab/work/projects/Broadsea
SMOKE_STORE=/app/tmp/tte_smoke/studies.json
POLL_S=30
MAX_WAIT_S=$((90 * 60))

log() { echo "[$(TZ=Asia/Seoul date '+%m-%d %H:%M:%S KST')] $*"; }

log "waiting for smoke pid ${WAIT_PID}"
waited=0
while kill -0 "$WAIT_PID" 2>/dev/null; do
  sleep "$POLL_S"
  waited=$((waited + POLL_S))
  if [ "$waited" -ge "$MAX_WAIT_S" ]; then
    log "smoke still running after ${waited}s; not starting the full run"
    exit 1
  fi
done
log "smoke finished after ${waited}s"

# Count what build_measurement_value_filter actually emits. Counting the word "ULN"
# in a description is what reported a working PLATO as a failure earlier today:
# process_eligibility renames the criterion and the constraint survives underneath.
ratio=$(docker exec -i artemis-api python - "$SMOKE_STORE" <<'PY'
import json, sys
sys.path.insert(0, "/app")
from src.services.value_constraint import build_measurement_value_filter as build

try:
    studies = json.load(open(sys.argv[1]))["studies"]
except Exception:
    print(-1); raise SystemExit(0)

study = next((s for s in studies if s["id"] == 3), None)
if study is None:
    print(-1); raise SystemExit(0)

eligibility = study.get("eligibility") or {}
count = 0
for key in ("inclusionCriteria", "exclusionCriteria"):
    for criterion in eligibility.get(key) or []:
        fragment = build(criterion.get("valueConstraint"))
        if "RangeHighRatio" in fragment or "RangeLowRatio" in fragment:
            count += 1
print(count)
PY
)
log "smoke result: ARISTOTLE ratio constraints = ${ratio}  (floor 0, pass >=1, ceiling 2)"

if [ "${ratio:-0}" -lt 1 ]; then
  log "SMOKE FAILED — the annotation did not reach the IR. Not running the full pass."
  log "  look at /tmp/reingest_run.log for the prompt the model actually received"
  exit 1
fi

log "── smoke passed; running both studies ──"
cd "$REPO" || exit 1
REINGEST_STORE_DIR=/app/tmp/tte_annotated \
REINGEST_RESULT_ROOT=/app/tmp/model_benchmarks_annotated \
  artemis/scripts/reingest_protocol_pdfs.sh > /tmp/reingest_annotated.log 2>&1
log "full run exit=$?"

grep -E '^\s*(===|\[before\]|\[after\]|generate_from_nct:|!)' /tmp/reingest_run.log 2>/dev/null | sed 's/^/  /'
log "done"
