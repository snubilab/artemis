#!/usr/bin/env bash
# Start/stop vLLM servers for the local-model benchmark on the GB10 box.
#
# Why a script: `snuh/hari-q3-8b` on :8000 is shared with other work. Any
# benchmark swap must be short, reversible, and end with hari healthy. The
# `restore` verb is the default final state and is what you run if anything
# goes wrong.
#
# GB10 is unified memory: `nvidia-smi` reports "Not Supported" for memory, and
# vLLM's --gpu-memory-utilization is a fraction of the whole 119.7 GiB pool
# shared with the OS. /proc/meminfo is therefore the authoritative free-memory
# source here; `status` prints it.
#
#   ./vllm_serve.sh status
#   ./vllm_serve.sh serve Qwen/Qwen3.5-4B 8003 0.15 16384
#   ./vllm_serve.sh stop 8003
#   ./vllm_serve.sh restore          # ensure hari is up on :8000
set -euo pipefail

VLLM_PY="${VLLM_PY:-/home/bilab/work/projects/vllm/venv/bin/python}"
HARI_PORT=8000
HARI_MODEL="snuh/hari-q3-8b"
HARI_UTIL=0.35
HARI_MAXLEN=16384
LOG_DIR="${LOG_DIR:-/tmp/vllm-bench}"
READY_TIMEOUT="${READY_TIMEOUT:-1800}"

mkdir -p "$LOG_DIR"

mem_gib() { awk -v k="$1" '$1==k":"{printf "%.1f", $2/1048576}' /proc/meminfo; }

# MemAvailable, not MemFree: page cache is reclaimable and vLLM will evict it.
free_gib() { mem_gib MemAvailable; }

port_model() {
    curl -s -m 3 "http://localhost:$1/v1/models" 2>/dev/null \
        | "$VLLM_PY" -c 'import json,sys
try: print(json.load(sys.stdin)["data"][0]["id"])
except Exception: pass' 2>/dev/null
}

status() {
    printf 'unified pool : %s GiB total, %s GiB available (MemAvailable)\n' \
        "$(mem_gib MemTotal)" "$(free_gib)"
    printf 'swap         : %s GiB free of %s GiB\n' \
        "$(mem_gib SwapFree)" "$(mem_gib SwapTotal)"
    echo "served:"
    for p in 8000 8001 8002 8003 8004; do
        m=$(port_model "$p")
        [ -n "$m" ] && printf '  :%s  %s\n' "$p" "$m"
    done
    return 0
}

# Block until /v1/models answers. vLLM loads weights for minutes on the big
# models, so callers must not assume the port is live when the process starts.
wait_ready() {
    local port=$1 start deadline
    start=$(date +%s)
    deadline=$((start + READY_TIMEOUT))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        if [ -n "$(port_model "$port")" ]; then
            echo "READY :$port after $(( $(date +%s) - start ))s"
            return 0
        fi
        # Fail fast if the server died instead of waiting out the full timeout.
        tmux has-session -t "vllm-$port" 2>/dev/null || {
            echo "FAILED :$port — session gone, see $LOG_DIR/$port.log" >&2
            return 1
        }
        sleep 5
    done
    echo "TIMEOUT :$port after ${READY_TIMEOUT}s" >&2
    return 1
}

serve() {
    local model=$1 port=${2:-8003} util=${3:-0.15} maxlen=${4:-16384}
    if [ -n "$(port_model "$port")" ]; then
        echo "refusing: :$port already serves $(port_model "$port")" >&2
        return 1
    fi
    echo "serving $model on :$port (util=$util maxlen=$maxlen), ${$(free_gib)} GiB available"
    tmux new-session -d -s "vllm-$port" \
        "$VLLM_PY -m vllm.entrypoints.openai.api_server \
            --model '$model' --served-model-name '$model' \
            --host 0.0.0.0 --port $port \
            --max-model-len $maxlen --dtype auto --enforce-eager \
            --gpu-memory-utilization $util 2>&1 | tee '$LOG_DIR/$port.log'"
    wait_ready "$port"
}

stop() {
    local port=$1
    [ "$port" = "$HARI_PORT" ] && echo "note: stopping the shared hari port; run 'restore' when done" >&2
    tmux kill-session -t "vllm-$port" 2>/dev/null || true
    # tmux kill-session leaves the EngineCore child alive often enough to matter;
    # an orphan keeps its whole --gpu-memory-utilization slice reserved.
    pkill -f "api_server.*--port $port" 2>/dev/null || true
    for _ in $(seq 60); do
        [ -z "$(port_model "$port")" ] && break
        sleep 1
    done
    pkill -9 -f "api_server.*--port $port" 2>/dev/null || true
    sleep 2
    echo "stopped :$port, $(free_gib) GiB available"
}

restore() {
    if [ "$(port_model $HARI_PORT)" = "$HARI_MODEL" ]; then
        echo "hari already healthy on :$HARI_PORT"
        return 0
    fi
    stop "$HARI_PORT"
    # Flags mirror the long-running production invocation: tool-calling is
    # enabled there and callers depend on it.
    tmux new-session -d -s "vllm-$HARI_PORT" \
        "$VLLM_PY -m vllm.entrypoints.openai.api_server \
            --model $HARI_MODEL --served-model-name $HARI_MODEL \
            --host 0.0.0.0 --port $HARI_PORT \
            --max-model-len $HARI_MAXLEN --dtype auto --enforce-eager \
            --gpu-memory-utilization $HARI_UTIL \
            --enable-auto-tool-choice --tool-call-parser qwen3_xml \
            2>&1 | tee '$LOG_DIR/hari.log'"
    wait_ready "$HARI_PORT"
}

case "${1:-status}" in
    status)  status ;;
    serve)   shift; serve "$@" ;;
    stop)    shift; stop "$@" ;;
    restore) restore ;;
    *) echo "usage: $0 {status|serve MODEL [PORT] [UTIL] [MAXLEN]|stop PORT|restore}" >&2; exit 2 ;;
esac
