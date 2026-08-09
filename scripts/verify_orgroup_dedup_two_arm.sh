#!/usr/bin/env bash
# Two-arm verification: does removing the duplicate top-level rules move the
# ARISTOTLE cohort off zero?
#
#   arm A  ARTEMIS_DISABLE_ORGROUP_DEDUP=1   13 inclusion criteria, 4 of them
#                                            restating an alternative the OR
#                                            group already offers
#   arm B  (unset)                            9 inclusion criteria, 0 restatements
#
# The arms differ in nothing else: same model, same prompt template, same store
# lineage, same CDM source (ARISTOTLE_BENCHMARK), same study (3). Attributing a
# cohort count to the deduplication needs that control -- a single arm cannot
# separate the fix from model or prompt drift.
#
# Recorded prior state, WebAPI definition 3402 on the same source:
#   base 3,100 -> final 0, with three 0-person rules: ECG at enrollment,
#   LVEF, and TIA + Systemic Embolism. The first two have no Synthea data and
#   cannot be cleared on this CDM; the third is the duplicate under test.
#
# PRE-REGISTERED READING (write this down before the numbers exist):
#   success  -> arm B has no standalone TIA/SE rule and no standalone LVEF AND
#               rule; the five risk factors appear as ONE ANY group
#   failure  -> a duplicate survives in arm B
#   null     -> both arms 0 patients because ECG/LVEF have no Synthea data.
#               That is a CDM limitation, not evidence about the fix, and must
#               be reported as such rather than as either success or failure.
#
#   nohup scripts/verify_orgroup_dedup_two_arm.sh > /tmp/twoarm/driver.log 2>&1 &
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT=/tmp/twoarm
mkdir -p "$OUT"
JSONL="$OUT/progress.jsonl"

ts()  { TZ=Asia/Seoul date '+%Y-%m-%d %H:%M:%S KST'; }
log() { echo "[$(ts)] $*"; }
ev()  { printf '{"t":"%s","event":%s}\n' "$(ts)" "$1" >> "$JSONL"; }

log "════ two-arm ARISTOTLE dedup verification ════"
log "  cwd        : $ROOT"
log "  driver pid : $$"
log "  git        : $(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null) on $(git -C "$ROOT" branch --show-current 2>/dev/null)"
log "  dirty      : $(git -C "$ROOT" status --porcelain src/ scripts/ | wc -l) files unstaged"
log "  artifacts  : $OUT/{arm_a,arm_b}.{reingest,circe,cohort}.log, $JSONL"
echo "$$" > "$OUT/driver.pid"
ev "{\"phase\":\"start\",\"pid\":$$}"

run_arm () {
  local arm="$1" disable="$2" store="$3"
  log "──── arm ${arm}: ARTEMIS_DISABLE_ORGROUP_DEDUP='${disable}' store=${store} ────"
  ev "{\"phase\":\"arm_start\",\"arm\":\"${arm}\",\"disable\":\"${disable}\"}"

  # Fresh store every time. reingest uses `cp -n`, so a leftover directory from a
  # failed attempt would be silently treated as a resume and its wreckage kept.
  docker exec artemis-api python -c "
import shutil, os
d = '${store}'
if os.path.isdir(d): shutil.rmtree(d); print('  cleared stale', d)
" 2>&1 | sed 's/^/    /'

  REINGEST_STORE_DIR="${store}" \
  REINGEST_CANONICAL=/app/tmp/tte_six_deliver/studies.json \
  REINGEST_STUDIES=3 \
  REINGEST_SKIP_BENCH=1 \
  REINGEST_RUN_LOG="/tmp/reingest_run_${arm}.log" \
  ARTEMIS_DISABLE_ORGROUP_DEDUP="${disable}" \
    "$ROOT/scripts/reingest_protocol_pdfs.sh" > "$OUT/arm_${arm}.reingest.log" 2>&1
  local rc=$?
  cp -f "/tmp/reingest_run_${arm}.log" "$OUT/arm_${arm}.reingest.inner.log" 2>/dev/null
  log "  arm ${arm} reingest exit=${rc}"
  ev "{\"phase\":\"reingest_done\",\"arm\":\"${arm}\",\"rc\":${rc}}"

  # The gate the handoff prescribes: a Cache HIT means the criteria bytes did not
  # change, so the arm never exercised what it was built to exercise.
  if grep -q 'Cache HIT' "$OUT/arm_${arm}.reingest.inner.log" 2>/dev/null; then
    log "  ABORT arm ${arm}: Cache HIT — the IR was replayed, not regenerated"
    ev "{\"phase\":\"abort\",\"arm\":\"${arm}\",\"reason\":\"cache_hit\"}"
    return 1
  fi
  [ "$rc" -ne 0 ] && return "$rc"

  log "  arm ${arm}: export circe"
  docker exec artemis-api python -c "import os; os.makedirs('/app/tmp/circe_${arm}', exist_ok=True)"
  docker exec artemis-api sh -c "cd /app && python scripts/export_circe_from_store.py \
    --store ${store}/studies.json --out /app/tmp/circe_${arm}" \
    > "$OUT/arm_${arm}.circe.log" 2>&1
  log "  arm ${arm} circe exit=$?"

  log "  arm ${arm}: register + generate cohort"
  docker exec artemis-api sh -c "cd /app && python scripts/register_and_generate_circe.py \
    --studies 3 --circe-dir /app/tmp/circe_${arm}" \
    > "$OUT/arm_${arm}.cohort.log" 2>&1
  log "  arm ${arm} cohort exit=$?"
  ev "{\"phase\":\"arm_done\",\"arm\":\"${arm}\"}"
  tail -25 "$OUT/arm_${arm}.cohort.log" | sed 's/^/    /'
}

# Arm B first: it is the one under test, so a failure surfaces before the control
# has spent an hour of GPU.
run_arm b ""  /app/tmp/tte_arm_b_postfix
run_arm a "1" /app/tmp/tte_arm_a_prefix

log "════ done ════"
ev '{"phase":"done"}'
