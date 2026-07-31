#!/usr/bin/env bash
# Re-ingest ARISTOTLE and PLATO now that their protocol PDFs are on disk, then
# count how many RangeHighRatio constraints reach the Circe.
#
# Both trials scored 0 RangeHighRatio because their study records were built from
# ClinicalTrials.gov summaries -- 421 and 523 characters -- which carry no lab
# thresholds. The documents that do were added to data/papers on 2026-07-31:
#
#   NCT00412984/nejmoa1107039_protocol.pdf   exclusion 20) ALT or AST > 2X ULN
#                                              or a Total Bilirubin >= 1.5X ULN
#   NCT00391872/plato_design_ahj2009.pdf     inclusion Table I: Troponin I or T
#                                              or CK-MB greater than the ULN
#
# The text stage was dry-run before writing this (no GPU): _discover_pdfs assigns
# protocol=1 and appendix=2, the protocol yields 29 exclusion criteria including
# the ULN one, and the ARISTOTLE appendix yields zero -- so its
# "supplement_priority" strategy, which would otherwise overwrite the protocol's
# criteria, never fires because _enrich_from_pdf returns early on an empty result.
# PLATO's three PDFs all classify as "main" and merge in name order, which puts
# the design paper (24 inclusion / 12 exclusion) last.
#
#   floor    0   both trials today
#   ceiling  7   gold per cohort: ARISTOTLE 3 + PLATO 4
#
# Isolated store: this MUTATES study records. The canonical store must keep
# meaning "as ingested from CT.gov" so the before/after stays interpretable, and
# a benchmark reading it must not silently pick up re-ingested criteria.
#
#   nohup artemis/scripts/reingest_protocol_pdfs.sh > /tmp/reingest.log 2>&1 &
#
set -uo pipefail

VLLM_PY=/home/bilab/work/projects/vllm/venv/bin/python
HOST_IP=100.66.233.6
PORT=8000
MODEL="google/gemma-4-E4B-it"     # 74/85 on the capability probe; 350s, the best practical rate

# 16384 -- the value every other harness here uses -- truncated Agent 1's IR JSON
# on the first run. agent1/parser.py calls get_llm() without max_tokens, so vLLM's
# output budget is max_model_len minus the prompt; ARISTOTLE's protocol yields 52
# criteria and the response died at ~39 KB with
# "Expecting property name enclosed in double quotes ... (char 38835)".
# PLATO's 45 criteria parsed at the same setting, so the ceiling sits between them
# and 16384 is not a safe default for protocol-scale input. The checkpoint declares
# max_position_embeddings=131072; 65536 stays well inside it and inside the 0.55
# memory share on 119 GB unified memory.
MAX_MODEL_LEN=65536
# Overridable so a second attempt starts from a clean copy of the canonical store.
# The first attempt left ARISTOTLE with zero criteria -- a heuristic placeholder
# applied over real ones -- and `cp -n` below would preserve that wreckage as if it
# were a resume.
STORE_DIR="${REINGEST_STORE_DIR:-/app/tmp/tte_reingest}"
CANONICAL=/app/tmp/tte/studies.json
# A separate root on purpose. The harness resumes per study file, and
# tmp/model_benchmarks/vllm__google__gemma-4-E4B-it__stored-criteria already holds
# six results from the CT.gov-only run -- writing there would make every study
# "already written, skipping" and the run would exit 0 having measured nothing.
RESULT_ROOT="${REINGEST_RESULT_ROOT:-/app/tmp/model_benchmarks_reingest}"

log() { echo "[$(TZ=Asia/Seoul date '+%m-%d %H:%M:%S KST')] $*"; }

VLLM_PATTERNS=('vllm.entrypoints.openai.api_server' 'VLLM::EngineCore' 'VLLM::Worker')

stop_server() {
  for sig in TERM KILL; do
    for pat in "${VLLM_PATTERNS[@]}"; do
      pkill --signal "$sig" -f "$pat" 2>/dev/null
    done
    for _ in $(seq 1 30); do
      alive=0
      for pat in "${VLLM_PATTERNS[@]}"; do
        pgrep -f "$pat" >/dev/null && alive=1
      done
      [ "$alive" -eq 0 ] && break
      sleep 2
    done
  done
  for _ in $(seq 1 30); do
    held=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | wc -l)
    [ "${held:-0}" -eq 0 ] && { sleep 3; return 0; }
    sleep 3
  done
  log "  WARNING: a process still holds GPU memory after stop_server"
}

start_server() {
  safe=$(echo "$MODEL" | tr '/:' '__')
  setsid "$VLLM_PY" -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" --served-model-name "$MODEL" \
    --host 0.0.0.0 --port "$PORT" \
    --max-model-len "$MAX_MODEL_LEN" --dtype auto --enforce-eager \
    --gpu-memory-utilization 0.55 \
    > "/tmp/vllm_${safe}.log" 2>&1 < /dev/null &
  for i in $(seq 1 240); do
    if curl -sf --max-time 5 "http://127.0.0.1:${PORT}/v1/models" >/dev/null 2>&1; then
      log "  server up after ${i}0s"; return 0
    fi
    sleep 10
  done
  log "  SERVER FAILED TO START — see /tmp/vllm_${safe}.log"
  return 1
}

stop_server
log "re-ingest — ${MODEL}; floor 0, ceiling 7 (ARISTOTLE 3 + PLATO 4)"
start_server || exit 1

docker exec artemis-api sh -c "mkdir -p ${STORE_DIR} && cp -n ${CANONICAL} ${STORE_DIR}/studies.json && echo '  store isolated'"

rev=$(git -C "$(dirname "$0")/.." rev-parse --short HEAD 2>/dev/null || echo unknown)

log "  re-ingest start"
docker exec \
  -e LLM_MODEL="vllm/${MODEL}" \
  -e VLLM_BASE_URL="http://${HOST_IP}:${PORT}/v1" \
  -e TTE_STORE_PATH="${STORE_DIR}/studies.json" \
  -e ARTEMIS_GIT_REV="$rev" \
  -e PYTHONUNBUFFERED=1 \
  artemis-api python /app/scripts/reingest_protocol_pdfs.py > /tmp/reingest_run.log 2>&1
rc=$?
log "  re-ingest exit=${rc}"
tail -30 /tmp/reingest_run.log

if [ "$rc" -eq 0 ]; then
  log "  arms benchmark on studies 2,3"
  docker exec \
    -e LLM_MODEL="vllm/${MODEL}" \
    -e VLLM_BASE_URL="http://${HOST_IP}:${PORT}/v1" \
    -e TTE_STORE_PATH="${STORE_DIR}/studies.json" \
    -e ARTEMIS_GIT_REV="$rev" \
    -e PYTHONUNBUFFERED=1 \
    artemis-api python /app/scripts/benchmark_value_constraint_arms.py \
    --studies "3,2" --output-root "$RESULT_ROOT" > /tmp/reingest_bench.log 2>&1
  log "  benchmark exit=$?"
fi

stop_server
log "done"
