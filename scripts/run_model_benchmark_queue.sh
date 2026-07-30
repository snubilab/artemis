#!/usr/bin/env bash
# Work through the model benchmark matrix one model at a time.
#
# One GPU means one model at a time; this is a queue, not a fan-out. Small models
# first because they are the working set and finish. The 26B+ tail is probed for
# the record and then run regardless of what the probe says.
#
# Resumable: a model whose result directory already holds six study files is
# skipped, so re-running after an interrupt continues rather than restarts.
#
#   nohup artemis/scripts/run_model_benchmark_queue.sh > /tmp/model_queue.log 2>&1 &
#
set -uo pipefail

VLLM_PY=/home/bilab/work/projects/vllm/venv/bin/python
HOST_IP=100.66.233.6            # container reaches the host over Tailscale
PORT=8000
STATE=/tmp/model_queue.state
# /app/output is NOT a mounted volume -- results written there live only inside
# the container and vanish when it is recreated. /app/tmp is mounted at
# artemis/tmp, so everything this queue produces survives.
RESULT_ROOT=/app/tmp/model_benchmarks
HOST_RESULT_ROOT=/home/bilab/work/projects/Broadsea/artemis/tmp/model_benchmarks
PROBE_JSON=/tmp/model_queue_probe.json

# Small first. The tail is probed, not scheduled.
WORKING=(
  # snuh/hari-q3-8b is parked, not dropped. It emitted 14,934 output tokens for one
  # critic call against Qwen3.5-4B's 2,996 -- five times as verbose on the same
  # prompt shape -- which put a single study at three hours and the six-study run
  # at 15-18h. A subagent owns finding out why and whether a json_schema
  # response_format fixes it; put it back once that is settled.
  "Qwen/Qwen2.5-7B-Instruct"
  "google/medgemma-1.5-4b-it"
  "google/gemma-4-E2B-it"
  "google/gemma-4-E4B-it"
)
HEAVY=(
  "google/gemma-4-26B-A4B-it"
  "google/medgemma-27b-text-it"
  "google/gemma-4-31B-it"
  "google/medgemma-27b-it"
  "Jiunsong/supergemma4-26b-abliterated-multimodal"
)
DEFAULT_MODEL="Qwen/Qwen3.5-4B"   # restored when the queue finishes

# Treatment studies first, controls after. hari-q3-8b needed 3h for one study, so
# a model will often be cut off part way; this ordering means the part that ran is
# the part that carries signal. EMPA-REG (8) and CARMELINA (9) hold all six "x ULN"
# inputs between them; ARISTOTLE (3), PLATO (2), CAROLINA (10) and LEADER (1) have
# none and have returned identical zeros in both arms for every model so far.
STUDY_ORDER="8,9,3,2,10,1"

# The probe still runs and is still recorded: knowing a model needs 17 minutes
# for one critic-shaped call is the number that explains its wall clock. It no
# longer gates anything -- every model runs, however long it takes.

log() { echo "[$(TZ=Asia/Seoul date '+%m-%d %H:%M:%S KST')] $*"; }

# vLLM's engine core renames itself to "VLLM::EngineCore", so a pattern matching
# only the api_server entrypoint leaves it alive holding the whole allocation.
# One survivor kept 67,164 MiB and every later model then failed to start with
# "Free memory on device cuda:0 (38.81/119.69 GiB) ... is less than desired GPU
# memory utilization" -- which reads as a config problem rather than a leftover.
# nvidia-smi --query-compute-apps is the only per-process number here that means
# what it says; free/available do not see it.
VLLM_PATTERNS=('vllm.entrypoints.openai.api_server' 'VLLM::EngineCore' 'VLLM::Worker')

stop_server() {
  for sig in TERM KILL; do
    for pat in "${VLLM_PATTERNS[@]}"; do
      pkill --signal "$sig" -f "$pat" 2>/dev/null
    done
    for _ in $(seq 1 30); do
      local alive=0
      for pat in "${VLLM_PATTERNS[@]}"; do
        pgrep -f "$pat" >/dev/null && alive=1
      done
      [ "$alive" -eq 0 ] && break
      sleep 2
    done
  done
  # Confirm the GPU allocation actually came back before starting the next model.
  for _ in $(seq 1 30); do
    local held; held=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | wc -l)
    [ "${held:-0}" -eq 0 ] && { sleep 3; return 0; }
    sleep 3
  done
  log "  WARNING: a process still holds GPU memory after stop_server"
}

start_server() {
  local model="$1" util="${2:-0.55}"
  local safe; safe=$(echo "$model" | tr '/:' '__')
  # setsid so the server outlives the shell that launched it.
  # --enforce-eager is kept deliberately. Measured on snuh/hari-q3-8b against an
  # idle server, two timed critic-shaped calls per variant: eager 10.09/10.04
  # tok/s, CUDA graphs 10.20/10.23 tok/s -- 1.5%, inside noise. Graphs did cut
  # EngineCore from 126% to 102% of a core, so they do reduce launch overhead;
  # throughput did not move, which means the launch path was never the limiter.
  # GPU drew 37.9 W in both. The limiter is raw decode at ~10 tok/s against a
  # 14,934-token critic response.
  #
  # Do not put comments between these continuation lines. A "#" after a trailing
  # backslash comments out the remainder of the joined command, which silently
  # dropped --max-model-len, --enforce-eager and --gpu-memory-utilization; vLLM
  # then used its 0.9 default and refused to start with "Free memory on device
  # cuda:0 (104.05/119.69 GiB) ... less than desired (0.9, 107.72 GiB)" -- an
  # error that reads as a memory problem. bash -n does not catch it.
  setsid "$VLLM_PY" -m vllm.entrypoints.openai.api_server \
    --model "$model" --served-model-name "$model" \
    --host 0.0.0.0 --port "$PORT" \
    --max-model-len 16384 --dtype auto --enforce-eager \
    --gpu-memory-utilization "$util" \
    > "/tmp/vllm_${safe}.log" 2>&1 < /dev/null &
  # Weights stream from disk; a 50GB checkpoint is minutes, not seconds.
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

# Time one critic-shaped call. Prints seconds, or 9999 on failure.
probe_seconds() {
  local model="$1"
  "$VLLM_PY" - "$model" <<'PY' 2>/dev/null || echo 9999
import json, sys, time, urllib.request
model = sys.argv[1]
# ~50 candidates, the shape that dominates a real run.
cands = "\n".join(
    f"- ID: {4000000+i} | Name: Anastomosis of artery variant {i} | Domain: Procedure"
    for i in range(50)
)
body = {
    "model": model, "temperature": 0, "response_format": {"type": "json_object"},
    "messages": [
        {"role": "system", "content":
         "You are an expert clinical informaticist. Evaluate the candidates and "
         "return JSON {\"selected_concepts\":[{\"concept_id\":int,\"relevant\":bool,"
         "\"reasoning\":str}]} with one entry per candidate."},
        {"role": "user", "content": f"Query: kidney transplant\n\nCandidates:\n{cands}"},
    ],
}
t = time.time()
req = urllib.request.Request("http://127.0.0.1:8000/v1/chat/completions",
    data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
try:
    d = json.load(urllib.request.urlopen(req, timeout=1800))
    el = time.time() - t
    print(f"{el:.0f} {d['usage']['completion_tokens']}")
except Exception:
    print("9999 0")
PY
}

PROBE_DIR=/home/bilab/work/projects/Broadsea/artemis/output/classifier_probe

# The six-study benchmark costs hours per model and leaves the informative matrix
# columns blank. This costs ~28 minutes on a 4B and returns a hard number that
# separates models by a factor of three: 75/85 correct MEASUREMENT_VALUE for
# hari-q3-8b against 26/85 for medgemma-1.5-4b. Run while the server is already up,
# so it adds no load time.
run_probe() {
  local model="$1"
  local safe; safe=$(echo "$model" | tr '/:' '__')
  local out="${PROBE_DIR}/${safe}.json"
  if [ -f "$out" ]; then
    log "  probe already recorded: $out"
    return 0
  fi
  mkdir -p "$PROBE_DIR"
  log "  probe start"
  docker exec \
    -e LLM_MODEL="vllm/${model}" \
    -e VLLM_BASE_URL="http://${HOST_IP}:${PORT}/v1" \
    -e ARTEMIS_GIT_REV="$rev" \
    -e PYTHONUNBUFFERED=1 \
    artemis-api python /app/scripts/eval_threshold_classifier.py \
    --max-workers 4 --save "/app/output/classifier_probe/${safe}.json" \
    > "/tmp/probe_${safe}.log" 2>&1
  local rc=$?
  local score; score=$(rg -o 'MEASUREMENT_VALUE\s+\d+\s+\d+' "/tmp/probe_${safe}.log" 2>/dev/null | tail -1)
  log "  probe exit=${rc} ${score:-no-score}"
  echo "${model}|probe|rc=${rc}|${score:-}" >> "$STATE"
}

already_done() {
  local model="$1"
  # The harness names the directory from LLM_MODEL with "/" -> "__", and
  # LLM_MODEL carries the vllm/ prefix.
  local dir="${HOST_RESULT_ROOT}/vllm__${model//\//__}__stored-criteria"
  [ -d "$dir" ] && [ "$(ls "$dir" 2>/dev/null | wc -l)" -ge 6 ]
}

run_benchmark() {
  local model="$1"
  local safe; safe=$(echo "$model" | tr '/:' '__')
  log "  benchmark start"
  # Captured at launch and recorded in the artifact, because a commit landing
  # mid-run cannot reach a process that already imported the module.
  docker exec \
    -e LLM_MODEL="vllm/${model}" \
    -e VLLM_BASE_URL="http://${HOST_IP}:${PORT}/v1" \
    -e ARTEMIS_GIT_REV="$rev" \
    -e PYTHONUNBUFFERED=1 \
    artemis-api python /app/scripts/benchmark_value_constraint_arms.py \
    --studies "$STUDY_ORDER" \
    --output-root "$RESULT_ROOT" > "/tmp/bench_${safe}.log" 2>&1
  local rc=$?
  # Every defect this week produced a well-formed table from a broken stage, and
  # each was caught by counting a log line rather than by an exit code. A run that
  # exits 0 with non-zero counters here is not a result.
  local lf="/tmp/bench_${safe}.log"
  local skips typeerrs fallbacks forced qfail
  skips=$(grep -c 'rollup skipped' "$lf" 2>/dev/null || echo 0)
  typeerrs=$(grep -c 'unexpected keyword argument\|TypeError' "$lf" 2>/dev/null || echo 0)
  fallbacks=$(grep -c 'falling back\|Reranking failed' "$lf" 2>/dev/null || echo 0)
  forced=$(grep -c 'Force-included' "$lf" 2>/dev/null || echo 0)
  qfail=$(grep -c 'query failed' "$lf" 2>/dev/null || echo 0)
  log "  benchmark exit=${rc} rev=${rev} rollup_skips=${skips} typeerrors=${typeerrs} fallbacks=${fallbacks} forced_top1=${forced} query_failures=${qfail}"
  echo "${model}|benchmark|rc=${rc}|rev=${rev}|rollup_skips=${skips}|typeerrors=${typeerrs}|fallbacks=${fallbacks}|forced_top1=${forced}|query_failures=${qfail}" >> "$STATE"
  if [ "${typeerrs}" -gt 0 ] || [ "${fallbacks}" -gt 0 ] || [ "${skips}" -gt 0 ]; then
    log "  WARNING: ${model} exited ${rc} but a stage was degraded — treat this row as unmeasured"
  fi
}

# ── queue ────────────────────────────────────────────────────────────────────
log "queue start — ${#WORKING[@]} working + ${#HEAVY[@]} heavy"
: > "$PROBE_JSON"

for model in "${WORKING[@]}"; do
  log "=== ${model} (working set) ==="
  # Plain assignment: this is the loop body, not a function, and `local` is a
  # function-only builtin -- it aborts the script here rather than warning.
  rev=$(git -C "$(dirname "$0")/.." rev-parse --short HEAD 2>/dev/null || echo unknown)
  # A benchmarked model can still be missing its probe. Serve it once and do both.
  if already_done "$model" && [ -f "${PROBE_DIR}/$(echo "$model" | tr '/:' '__').json" ]; then
    log "SKIP ${model} — benchmark and probe both present"
    continue
  fi
  stop_server
  start_server "$model" 0.55 || { echo "${model}|start|failed" >> "$STATE"; continue; }
  if already_done "$model"; then
    log "  benchmark already present, probe only"
  else
    run_benchmark "$model"
  fi
  run_probe "$model"
done

log "working set complete — probing the heavy tail"

for model in "${HEAVY[@]}"; do
  log "=== ${model} (probe) ==="
  stop_server
  # Bigger share for a 50GB checkpoint; still inside 119GB unified memory.
  start_server "$model" 0.80 || { echo "${model}|start|failed" >> "$STATE"; continue; }
  read -r secs toks <<< "$(probe_seconds "$model")"
  log "  probe ${secs}s ${toks} tokens — recorded, not gating"
  echo "{\"model\":\"${model}\",\"probe_s\":${secs},\"tokens\":${toks}}" >> "$PROBE_JSON"
  echo "${model}|probe|${secs}s|${toks}tok" >> "$STATE"
  run_probe "$model"
  run_benchmark "$model"
done

log "queue done — restoring ${DEFAULT_MODEL}"
stop_server
start_server "$DEFAULT_MODEL" 0.55 || log "  WARNING: default model did not come back up"
log "finished"
