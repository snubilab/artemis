#!/usr/bin/env bash
# Re-extract eligibility with the model, then assemble both ADR-031 arms on top.
#
# Scoped to EMPA-REG (8) and CARMELINA (9) on purpose. Gold names 32 RangeHighRatio
# across the six studies, but a pre-run probe of the study store found that PLATO,
# ARISTOTLE and CAROLINA -- 20 of those 32 -- carry no "x ULN" / "upper limit of
# normal" text at all, neither in their criterion descriptions nor in their source
# artifacts. --extract cannot recover a bound its input never contained, so those
# four studies would return a guaranteed zero for every model, cost GPU hours, and
# read as model failure. They are an upstream ingestion question, not an extraction
# one.
#
# What --extract actually does, stated because the name oversells it:
#   run_study(extract=True) -> process_eligibility(study_id)
#     -> _study_to_provisional_ir(study)
#       -> fragments built from study["eligibility"][...]["description"]
# That is the ALREADY-EXTRACTED text, not the protocol. So this measures
# re-extraction quality on text that does contain the bound (EMPA-REG and CARMELINA
# have 4 such sentences each), which is exactly the 6-of-12 the pipeline currently
# gets.
#
# Floor and ceiling are already known, so the result needs no extra run to read:
#   floor    3 + 3 = 6   (the stored-criteria arms result -- model adds nothing)
#   ceiling  6 + 6 = 12  (gold)
#
#   nohup artemis/scripts/run_extract_arms.sh > /tmp/extract_arms.log 2>&1 &
#
set -uo pipefail

VLLM_PY=/home/bilab/work/projects/vllm/venv/bin/python
HOST_IP=100.66.233.6
PORT=8000
STUDIES="8,9"
RESULT_ROOT=/app/tmp/model_benchmarks
STATE=/tmp/extract_arms.state

# --extract WRITES the re-extracted criteria back into the study store. The harness
# reuses bench_{model}.json, which is the same file the stored-criteria runs read,
# so running in place would overwrite the canonical criteria with one model's
# extraction and silently change what "stored-criteria" means for every later run.
# An isolated store directory keeps the two experiments from touching.
EXTRACT_STORE_DIR=/app/tmp/tte_extract
CANONICAL_STORE=/app/tmp/tte/studies.json

MODELS=("google/gemma-4-E2B-it" "google/gemma-4-E4B-it")

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
  model="$1"; util="${2:-0.55}"
  safe=$(echo "$model" | tr '/:' '__')
  # Do not put comments between these continuation lines -- a "#" after a trailing
  # backslash comments out the rest of the joined command and bash -n does not
  # catch it. That silently dropped three flags once already.
  setsid "$VLLM_PY" -m vllm.entrypoints.openai.api_server \
    --model "$model" --served-model-name "$model" \
    --host 0.0.0.0 --port "$PORT" \
    --max-model-len 16384 --dtype auto --enforce-eager \
    --gpu-memory-utilization "$util" \
    > "/tmp/vllm_${safe}.log" 2>&1 < /dev/null &
  for i in $(seq 1 240); do
    if curl -sf --max-time 5 "http://127.0.0.1:${PORT}/v1/models" >/dev/null 2>&1; then
      log "  server up after ${i}0s"
      return 0
    fi
    sleep 10
  done
  log "  SERVER FAILED TO START — see /tmp/vllm_${safe}.log"
  return 1
}

# ── wait for the GPU ─────────────────────────────────────────────────────────
# One GPU. The model benchmark queue owns it until it prints "finished".
QUEUE_LOG=/tmp/model_queue.log
waited=0
while pgrep -f 'run_model_benchmark_queue.sh' >/dev/null 2>&1; do
  if [ "$waited" -eq 0 ]; then log "waiting for the model benchmark queue to finish"; fi
  sleep 60
  waited=$((waited + 60))
  if [ "$waited" -ge $((14 * 3600)) ]; then
    log "gave up after ${waited}s waiting for the queue; nothing run"
    exit 1
  fi
done
[ "$waited" -gt 0 ] && log "queue finished after ${waited}s of waiting"
stop_server

# ── isolated store ───────────────────────────────────────────────────────────
docker exec artemis-api sh -c "mkdir -p ${EXTRACT_STORE_DIR} && \
  if [ ! -f ${EXTRACT_STORE_DIR}/studies.json ]; then \
    cp ${CANONICAL_STORE} ${EXTRACT_STORE_DIR}/studies.json; \
    echo '  store copied'; else echo '  store already present'; fi"

log "extract arms — studies ${STUDIES}, ${#MODELS[@]} models"
log "  floor (stored-criteria, model adds nothing) = 6 ; ceiling (gold) = 12"

rev=$(git -C "$(dirname "$0")/.." rev-parse --short HEAD 2>/dev/null || echo unknown)

for model in "${MODELS[@]}"; do
  log "=== ${model} ==="
  stop_server
  start_server "$model" 0.55 || { echo "${model}|start|failed" >> "$STATE"; continue; }
  safe=$(echo "$model" | tr '/:' '__')
  log "  extract benchmark start"
  docker exec \
    -e LLM_MODEL="vllm/${model}" \
    -e VLLM_BASE_URL="http://${HOST_IP}:${PORT}/v1" \
    -e TTE_STORE_PATH="${EXTRACT_STORE_DIR}/studies.json" \
    -e ARTEMIS_GIT_REV="$rev" \
    -e PYTHONUNBUFFERED=1 \
    artemis-api python /app/scripts/benchmark_value_constraint_arms.py \
    --extract --studies "$STUDIES" \
    --output-root "$RESULT_ROOT" > "/tmp/extract_${safe}.log" 2>&1
  rc=$?
  lf="/tmp/extract_${safe}.log"
  skips=$(grep -c 'rollup skipped' "$lf" 2>/dev/null || echo 0)
  typeerrs=$(grep -c 'unexpected keyword argument\|TypeError' "$lf" 2>/dev/null || echo 0)
  fallbacks=$(grep -c 'falling back\|Reranking failed' "$lf" 2>/dev/null || echo 0)
  log "  exit=${rc} rev=${rev} rollup_skips=${skips} typeerrors=${typeerrs} fallbacks=${fallbacks}"
  echo "${model}|extract|rc=${rc}|rev=${rev}|skips=${skips}|typeerrs=${typeerrs}|fallbacks=${fallbacks}" >> "$STATE"

  # The first model is the smoke test. If it came back degraded or empty there is
  # no point spending the second model's GPU hours on the same broken instrument.
  if [ "$model" = "${MODELS[0]}" ]; then
    if [ "$rc" -ne 0 ] || [ "$typeerrs" -gt 0 ] || [ "$fallbacks" -gt 0 ] || [ "$skips" -gt 0 ]; then
      log "SMOKE FAILED — stopping before the second model. See ${lf}"
      exit 1
    fi
    log "  smoke ok — continuing to the next model"
  fi
done

stop_server
log "done — results under artemis/tmp/model_benchmarks/vllm__*__extracted/"
log "read against floor 6 / ceiling 12; a value of exactly 6 means re-extraction changed nothing"
