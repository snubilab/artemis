#!/usr/bin/env bash
# Wait for the first re-ingest attempt to finish, summarise it, then retry at a
# context length that can actually hold the answer.
#
# Attempt 1 ran at --max-model-len 16384, the value every harness here inherited.
# agent1/parser.py calls get_llm() with no max_tokens, so vLLM's output budget is
# max_model_len minus the prompt. ARISTOTLE's protocol produced 52 criteria and the
# IR JSON died mid-object at ~39 KB; PLATO's 45 parsed. The ceiling sits between
# them, which makes 16384 unsafe for protocol-scale input rather than merely tight.
#
# The retry starts from a clean copy of the canonical store on purpose. Attempt 1
# left ARISTOTLE with zero criteria -- run_generate_from_nct falls back to a
# heuristic placeholder on a parse failure, still returns status="completed", and
# apply_artifact wrote that over 31 real criteria. Resuming from that state would
# measure the wreckage.
#
#   nohup artemis/scripts/chain_reingest_retry.sh <pid> > /tmp/reingest_chain.log 2>&1 &
#
set -uo pipefail

WAIT_PID="${1:?usage: $0 <pid of the running attempt>}"
REPO=/home/bilab/work/projects/Broadsea
POLL_S=60
MAX_WAIT_S=$((4 * 3600))

log() { echo "[$(TZ=Asia/Seoul date '+%m-%d %H:%M:%S KST')] $*"; }

log "waiting for pid ${WAIT_PID}"
waited=0
while kill -0 "$WAIT_PID" 2>/dev/null; do
  sleep "$POLL_S"
  waited=$((waited + POLL_S))
  if [ "$waited" -ge "$MAX_WAIT_S" ]; then
    log "gave up after ${waited}s; attempt 1 still running, nothing retried"
    exit 1
  fi
done
log "attempt 1 finished after ${waited}s of waiting"

log "── attempt 1 result ──"
grep -E '^\s*(===|\[before\]|\[after\]|generate_from_nct:|apply_artifact:|WARNING:)' \
  /tmp/reingest_run.log 2>/dev/null | sed 's/^/  /'

log "── retry at max-model-len 65536, clean store ──"
cd "$REPO" || exit 1
REINGEST_STORE_DIR=/app/tmp/tte_reingest_65k \
REINGEST_RESULT_ROOT=/app/tmp/model_benchmarks_reingest_65k \
  artemis/scripts/reingest_protocol_pdfs.sh > /tmp/reingest_65k.log 2>&1
log "retry exit=$?"

log "── retry result ──"
grep -E '^\s*(===|\[before\]|\[after\]|generate_from_nct:|apply_artifact:|WARNING:)' \
  /tmp/reingest_run.log 2>/dev/null | sed 's/^/  /'
log "done"
