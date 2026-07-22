#!/usr/bin/env bash
# Multi-Trial Benchmark: LEADER / PLATO / ARISTOTLE
# Runs benchmark_v5.py for each trial and aggregates R/P/F1.
#
# Usage:
#   PIPELINE_MODE=benchmark conda run -n artemis bash scripts/run_multi_trial_benchmark.sh
#
# Prerequisites:
#   - PostgreSQL OMOP CDM running (DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASS)
#   - LLM API keys configured
#   - conda env 'artemis' activated

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

export PIPELINE_MODE="${PIPELINE_MODE:-benchmark}"

# TROY files (v3.4 — latest available)
declare -A TRIALS=(
    ["LEADER"]="data/sample/LEADER/[TROY] Liraglutide (LEADER) v3.4.json"
    ["PLATO"]="data/sample/PLATO/[TROY] Ticagrelor (PLATO) v3.4.json"
    ["ARISTOTLE"]="data/sample/ARISTOTLE/[TROY] Apixaban (ARISTOTLE) v3.4.json"
)

TIMESTAMP=$(date "+%Y%m%d_%H%M")
REPORT_DIR="output/multi_trial_${TIMESTAMP}"
mkdir -p "$REPORT_DIR"

echo "═══════════════════════════════════════════════════════════"
echo "  Multi-Trial Benchmark — $(date '+%Y-%m-%d %H:%M')"
echo "  Mode: $PIPELINE_MODE"
echo "  Trials: ${!TRIALS[*]}"
echo "  Output: $REPORT_DIR"
echo "═══════════════════════════════════════════════════════════"
echo

SUMMARY_FILE="$REPORT_DIR/summary.txt"
: > "$SUMMARY_FILE"

for trial in LEADER PLATO ARISTOTLE; do
    troy="${TRIALS[$trial]}"
    echo "────────────────────────────────────────"
    echo "  [$trial] $troy"
    echo "────────────────────────────────────────"

    if [[ ! -f "$troy" ]]; then
        echo "  ⚠ TROY file not found: $troy — SKIPPING"
        echo "$trial: SKIPPED (file not found)" >> "$SUMMARY_FILE"
        echo
        continue
    fi

    python scripts/benchmark_v5.py \
        --troy "$troy" \
        --report-dir "$REPORT_DIR" \
        2>&1 | tee "$REPORT_DIR/${trial}_stdout.txt"

    echo
done

# Aggregate results from JSON reports
echo "═══════════════════════════════════════════════════════════"
echo "  AGGREGATE SUMMARY"
echo "═══════════════════════════════════════════════════════════"

# Find all benchmark JSON files in report dir
JSON_FILES=$(find "$REPORT_DIR" -name "benchmark_v5_*.json" -type f | sort)

if command -v jq &> /dev/null && [[ -n "$JSON_FILES" ]]; then
    printf "%-12s %8s %8s %8s %6s %6s %6s %6s\n" \
        "Trial" "Recall" "Prec" "F1" "Full" "Part" "Wrong" "Empty"
    echo "────────────────────────────────────────────────────────"

    for jf in $JSON_FILES; do
        trial_name=$(basename "$jf" | sed 's/benchmark_v5_.*//; s/_$//')
        recall=$(jq -r '.metrics.avg_recall' "$jf")
        precision=$(jq -r '.metrics.avg_precision' "$jf")
        f1=$(jq -r '.metrics.avg_f1' "$jf")
        full=$(jq -r '.totals.full' "$jf")
        partial=$(jq -r '.totals.partial' "$jf")
        wrong=$(jq -r '.totals.wrong' "$jf")
        empty=$(jq -r '.totals.empty' "$jf")
        troy_path=$(jq -r '.troy_path' "$jf")

        # Extract trial name from TROY path
        trial_label=$(echo "$troy_path" | grep -oP '(?<=sample/)[^/]+' || basename "$troy_path" | head -c 12)

        printf "%-12s %7.1f%% %7.1f%% %7.1f%% %6d %6d %6d %6d\n" \
            "$trial_label" \
            "$(echo "$recall * 100" | bc)" \
            "$(echo "$precision * 100" | bc)" \
            "$(echo "$f1 * 100" | bc)" \
            "$full" "$partial" "$wrong" "$empty"
    done
    echo "────────────────────────────────────────────────────────"
else
    echo "  (install jq for automatic summary, or inspect JSON files in $REPORT_DIR)"
fi

echo
echo "💾 Reports saved in: $REPORT_DIR"
echo "   JSON files: $(ls "$REPORT_DIR"/benchmark_v5_*.json 2>/dev/null | wc -l | tr -d ' ')"
echo "   Stdout logs: $(ls "$REPORT_DIR"/*_stdout.txt 2>/dev/null | wc -l | tr -d ' ')"
