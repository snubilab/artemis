#!/usr/bin/env bash
# Fast-forward a branch into the main checkout in the gap between two models.
#
# Python imports a module once, so a commit landing while a benchmark process runs
# never reaches it. That has silently decided three results this week -- one model
# was immune to a broken commit because it imported first, the next was corrupted by
# it, and a third predated a fix by five minutes. Landing the merge in the gap means
# the next process imports it from its first call and ARTEMIS_GIT_REV records the
# revision that actually ran.
#
# The boundary is between a "benchmark exit=" line and the next "benchmark start",
# roughly the 130s a server takes to load. This waits for it rather than making one:
# stopping the queue to create a window would cost more than it saves.
#
#   nohup artemis/scripts/merge_at_model_boundary.sh fix/codex-adversarial-findings \
#     > /tmp/boundary_merge.log 2>&1 &
#
set -uo pipefail

BRANCH="${1:?usage: $0 <branch>}"
REPO=/home/bilab/work/projects/Broadsea/artemis
QUEUE_LOG=/tmp/model_queue.log
POLL_S=20
MAX_WAIT_S=$((6 * 3600))

log() { echo "[$(TZ=Asia/Seoul date '+%m-%d %H:%M:%S KST')] $*"; }

cd "$REPO" || exit 1

if ! git rev-parse --verify "$BRANCH" >/dev/null 2>&1; then
  log "no such branch: $BRANCH"; exit 1
fi
if ! git merge-base --is-ancestor HEAD "$BRANCH"; then
  log "REFUSING: $BRANCH does not fast-forward onto $(git rev-parse --short HEAD)."
  log "  Something moved underneath. A merge commit is the wrong response here --"
  log "  re-verify the branch instead."
  exit 1
fi

log "waiting for a boundary; $BRANCH is $(git rev-list --count HEAD.."$BRANCH") commits ahead"

# A boundary has arrived when the LAST interesting line is an exit rather than a
# start. Tracking the last line rather than counting avoids firing on an old exit.
waited=0
while [ "$waited" -lt "$MAX_WAIT_S" ]; do
  last=$(grep -E 'benchmark (start|exit=)' "$QUEUE_LOG" 2>/dev/null | tail -1)
  case "$last" in
    *"benchmark exit="*)
      log "boundary: $last"
      break
      ;;
  esac
  sleep "$POLL_S"
  waited=$((waited + POLL_S))
done

if [ "$waited" -ge "$MAX_WAIT_S" ]; then
  log "gave up after ${MAX_WAIT_S}s without a boundary; nothing merged"
  exit 1
fi

# The queue owns this tree. A dirty tree means someone else is mid-edit and a merge
# would tangle with it.
dirty=$(git status --short | grep -v '^??' | wc -l)
if [ "$dirty" -ne 0 ]; then
  log "REFUSING: working tree has $dirty tracked modifications"
  git status --short | grep -v '^??' | sed 's/^/  /'
  exit 1
fi

before=$(git rev-parse --short HEAD)
if git merge --ff-only "$BRANCH" >/dev/null 2>&1; then
  log "merged $before -> $(git rev-parse --short HEAD)"
else
  log "REFUSING: fast-forward failed at merge time"
  exit 1
fi

log "verifying"
.venv/bin/python -m pytest \
  tests/test_reasoning_extraction.py \
  tests/test_cache_keys_carry_critic_config.py \
  tests/test_tte_service_comparator_hitl.py \
  tests/test_value_constraint.py \
  -q --no-header -p no:randomly 2>&1 | tail -3 | sed 's/^/  /'

# Worth saying out loud: the cache-key change invalidates every existing entry, so
# the next model re-maps instead of replaying. Its wall clock will be longer than
# medgemma's for a reason that is not the model.
log "note: cache keys changed — the next model re-maps; do not read its wall clock as a model difference"
log "done"
