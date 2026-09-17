#!/usr/bin/env bash
# End-to-end check that committed fixes reach a freshly extracted and exported delivery.
#
#   scripts/run_fix_verification.sh <run-dir>
#
# Steps, each stopping the run on failure:
#   0  .venv matches requirements.txt          (drift returns wrong numbers, not crashes)
#   1  vLLM serves exactly LLM_MODEL           (a mismatch silently falls back to OpenRouter)
#   2  seed a COPY of the store + PROVENANCE   (TTE_STORE_PATH is always explicit)
#   3  cold re-extraction of the delivery studies, waited on by PID
#   4  export_seeded_cohorts.py -> <run-dir>/DELIVERY, log kept for step 5
#   5  verify_fix_reflection.py against the unfixed baseline delivery
#   6  delivery-side gates: Atlas renderability, entry/exclusion conflict
#
# START_AT=export skips steps 2-3 and exports from an existing <run-dir>/store, which is
# what to use when only export-time fixes changed -- cold re-extraction costs ~2 hours for
# the three delivery studies (6 studies took 3h47m on 2026-09-12).
#
# Environment overrides:
#   SEED_STORE   default output/site_gap/2026-09-14/store/studies.json
#                (the store the 2026-09-12 delivery's run started from)
#   BASELINE     default deliveries/2026-09-12 (the unfixed sent payload)
#   START_AT     extract (default) | export
set -euo pipefail

ART="$(cd "$(dirname "$0")/.." && pwd)"
RUN="${1:?usage: run_fix_verification.sh <run-dir>}"
mkdir -p "$RUN"
RUN="$(cd "$RUN" && pwd)"
SEED_STORE="${SEED_STORE:-$ART/output/site_gap/2026-09-14/store/studies.json}"
BASELINE="${BASELINE:-$ART/deliveries/2026-09-12}"
START_AT="${START_AT:-extract}"
PY="$ART/.venv/bin/python"
STUDIES="8,9,10"
SLUGS="8=empa-reg,9=carmelina,10=carolina"
cd "$ART"

step() { printf '\n== %s\n' "$*"; }

step "0 environment gate"
"$PY" -m pytest -q tests/test_environment_matches_requirements.py

step "1 LLM backend"
LLM_MODEL="$(rg -N '^LLM_MODEL=' .env | cut -d= -f2-)"
VLLM_BASE_URL="$(rg -N '^VLLM_BASE_URL=' .env | cut -d= -f2-)"
served="$(curl -s --max-time 10 "$VLLM_BASE_URL/models" | "$PY" -c 'import json,sys; print(" ".join(m["id"] for m in json.load(sys.stdin)["data"]))')"
case "$LLM_MODEL" in
  vllm/*) want="${LLM_MODEL#vllm/}" ;;
  *) echo "FAIL: LLM_MODEL=$LLM_MODEL has no vllm/ prefix and would route to OpenRouter"; exit 1 ;;
esac
[[ " $served " == *" $want "* ]] || { echo "FAIL: vLLM serves [$served], LLM_MODEL wants $want"; exit 1; }
echo "vLLM serves $want"

if [[ "$START_AT" == "extract" ]]; then
  step "2 seed store"
  mkdir -p "$RUN/store"
  cp "$SEED_STORE" "$RUN/store/studies.json"
  chmod u+w "$RUN/store/studies.json"
  {
    echo "# fix-verification run"
    echo "- artemis HEAD: $(git rev-parse --short HEAD) ($(git branch --show-current))"
    echo "- seed store: $SEED_STORE md5 $(md5sum "$SEED_STORE" | cut -d' ' -f1)"
    echo "- studies: $STUDIES"
    echo "- LLM: $LLM_MODEL @ $VLLM_BASE_URL"
    echo "- baseline: $BASELINE"
    echo "- started: $(date '+%Y-%m-%d %H:%M:%S')"
  } > "$RUN/PROVENANCE.md"

  step "3 cold re-extraction (studies $STUDIES)"
  PYTHONPATH="$ART" TTE_STORE_PATH="$RUN/store/studies.json" REINGEST_STUDIES="$STUDIES" \
    nohup "$PY" scripts/reingest_protocol_pdfs.py > "$RUN/reingest.log" 2>&1 &
  pid=$!
  echo "$pid" > "$RUN/reingest.pid"
  echo "pid $pid, log $RUN/reingest.log"
  while kill -0 "$pid" 2>/dev/null; do sleep 60; done
  wait "$pid" || { echo "FAIL: re-extraction exited non-zero; see $RUN/reingest.log"; exit 1; }
  echo "finished: $(date '+%Y-%m-%d %H:%M:%S')" >> "$RUN/PROVENANCE.md"
fi

[[ -s "$RUN/store/studies.json" ]] || { echo "FAIL: no store at $RUN/store/studies.json"; exit 1; }

step "4 export"
# The export's own gate rejects on pre-existing criterion-loss categories (0/12 PASS since
# 2026-09-11); that is not this check's question, so its exit code is recorded, not fatal.
set +e
PYTHONPATH="$ART" TTE_STORE_PATH="$RUN/store/studies.json" "$PY" scripts/export_seeded_cohorts.py \
  --store "$RUN/store/studies.json" --out "$RUN/DELIVERY" \
  --study-id 8 --study-id 9 --study-id 10 --slug-map "$SLUGS" > "$RUN/export.log" 2>&1
echo "export exit $?" | tee -a "$RUN/PROVENANCE.md"
set -e
ls "$RUN/DELIVERY"/*.circe.json >/dev/null

step "5 are the fixes reflected?"
set +e
"$PY" scripts/verify_fix_reflection.py --baseline "$BASELINE" --candidate "$RUN/DELIVERY" \
  --export-log "$RUN/export.log" | tee "$RUN/fix_reflection.txt"
reflection=${PIPESTATUS[0]}

step "6 delivery gates"
python3 scripts/verify_atlas_renderable.py "$RUN/DELIVERY" | tee "$RUN/atlas_renderable.txt"
atlas=${PIPESTATUS[0]}
"$PY" scripts/verify_entry_exclusion_conflict.py "$RUN/DELIVERY" | tee "$RUN/entry_exclusion.txt"
entry=${PIPESTATUS[0]}
set -e

step "summary"
echo "fix reflection exit $reflection  (0 all PASS / 1 FAIL or CONTROL-BROKEN / 3 UNVERIFIABLE)"
echo "atlas renderable exit $atlas"
echo "entry-exclusion exit $entry"
{ echo "fix_reflection=$reflection atlas=$atlas entry_exclusion=$entry"; } >> "$RUN/PROVENANCE.md"
[[ $reflection -eq 0 && $atlas -eq 0 && $entry -eq 0 ]]
