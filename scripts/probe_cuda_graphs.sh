#!/usr/bin/env bash
# Does --enforce-eager cost us throughput on the GB10?
#
# Under --enforce-eager there are no CUDA graphs, so every kernel is launched
# individually from the engine's Python loop. Measured under load, that loop sat
# at 98.2% of one core while the GPU drew 55.4 W and reported 96% "utilisation" --
# a busy launch path in front of an idle accelerator. This model has 24 of 32
# layers as linear attention, which is exactly the shape that produces many small
# kernels.
#
# Same model, same prompt, idle server, one variable. Two server starts.
#
#   nohup artemis/scripts/probe_cuda_graphs.sh > /tmp/cuda_graph_probe.log 2>&1 &
#
set -uo pipefail

VLLM_PY=/home/bilab/work/projects/vllm/venv/bin/python
MODEL="${1:-snuh/hari-q3-8b}"
PORT=8000
UTIL=0.55
OUT=/tmp/cuda_graph_probe.json

VLLM_PATTERNS=('vllm.entrypoints.openai.api_server' 'VLLM::EngineCore' 'VLLM::Worker')

log() { echo "[$(TZ=Asia/Seoul date '+%H:%M:%S KST')] $*"; }

stop_server() {
  for sig in TERM KILL; do
    for pat in "${VLLM_PATTERNS[@]}"; do
      pkill --signal "$sig" -f "$pat" 2>/dev/null
    done
    sleep 6
  done
  # The engine core holds the whole allocation; free() does not see it.
  for _ in $(seq 1 30); do
    local held; held=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | wc -l)
    [ "${held:-0}" -eq 0 ] && { sleep 3; return 0; }
    sleep 3
  done
  log "  WARNING: GPU still held after stop"
}

start_server() {
  local eager="$1" tag="$2"
  local extra=""
  [ "$eager" = "yes" ] && extra="--enforce-eager"
  setsid "$VLLM_PY" -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" --served-model-name "$MODEL" \
    --host 0.0.0.0 --port "$PORT" \
    --max-model-len 16384 --dtype auto $extra \
    --gpu-memory-utilization "$UTIL" \
    > "/tmp/vllm_probe_${tag}.log" 2>&1 < /dev/null &
  local t0=$SECONDS
  for _ in $(seq 1 300); do
    if curl -sf --max-time 5 "http://127.0.0.1:${PORT}/v1/models" >/dev/null 2>&1; then
      log "  [${tag}] server up in $((SECONDS - t0))s"
      return 0
    fi
    sleep 5
  done
  log "  [${tag}] SERVER FAILED — see /tmp/vllm_probe_${tag}.log"
  return 1
}

# Critic-shaped: ~50 candidates in, one object per candidate out. That output
# volume is what the run actually spends its time on.
probe() {
  local tag="$1"
  "$VLLM_PY" - "$MODEL" "$tag" <<'PY'
import json, sys, time, urllib.request
model, tag = sys.argv[1], sys.argv[2]
cands = "\n".join(
    f"- ID: {4000000+i} | Name: Anastomosis of artery variant {i} | Domain: Procedure"
    for i in range(50)
)
body = {
    "model": model, "temperature": 0, "response_format": {"type": "json_object"},
    "messages": [
        {"role": "system", "content":
         "You are an expert clinical informaticist. Evaluate the candidates and return "
         "JSON {\"selected_concepts\":[{\"concept_id\":int,\"relevant\":bool,\"reasoning\":str}]} "
         "with one entry per candidate."},
        {"role": "user", "content": f"Query: kidney transplant\n\nCandidates:\n{cands}"},
    ],
}
url = "http://127.0.0.1:8000/v1/chat/completions"
runs = []
for i in range(2):                      # second run avoids first-call warmup
    t = time.time()
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        d = json.load(urllib.request.urlopen(req, timeout=3600))
        el = time.time() - t
        u = d["usage"]
        runs.append({"s": round(el, 1), "out": u["completion_tokens"],
                     "tok_s": round(u["completion_tokens"] / el, 2)})
    except Exception as e:
        runs.append({"s": None, "error": type(e).__name__})
print(json.dumps({"tag": tag, "runs": runs}))
PY
}

: > "$OUT"
log "model=${MODEL} util=${UTIL}"

for variant in eager graph; do
  eager=$([ "$variant" = eager ] && echo yes || echo no)
  log "=== ${variant} (--enforce-eager=${eager}) ==="
  stop_server
  if ! start_server "$eager" "$variant"; then
    echo "{\"tag\":\"${variant}\",\"error\":\"start-failed\"}" >> "$OUT"
    continue
  fi
  sleep 10
  result=$(probe "$variant")
  log "  ${result}"
  echo "$result" >> "$OUT"
  # Sample the launch path while it is the only thing running.
  cpu=$(ps -eo pcpu,args --no-headers 2>/dev/null | grep 'VLLM::EngineCore' | grep -v grep | awk '{print $1}' | head -1)
  pw=$(nvidia-smi --query-gpu=power.draw --format=csv,noheader 2>/dev/null)
  log "  [${variant}] EngineCore cpu=${cpu:-?}% gpu_power=${pw:-?}"
done

log "done — results in $OUT"
