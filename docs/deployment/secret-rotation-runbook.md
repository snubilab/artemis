# Secret Rotation Runbook — .env history exposure

Finding: `secrets-history` (adversarial review, 2026-07-30). Confirmed: commit
`6ffd07c` (repo root) tracked a live `.env` with `AWS_BEARER_TOKEN_BEDROCK`,
`OPENROUTER_API_KEY`, `VLLM_API_KEY`, `OMOP_DB_PASS`. `4bad902` untracked the
file but did not remove it from history. The `main` branch ref still points at
`6ffd07c`, so `git show main:.env` is byte-identical to the leaked blob —
checking out `main` alone reproduces the exposure with no history digging.
No remote is configured on this repo (`git remote -v` is empty), so exposure
today is local-disk only.

This document is instructions only. **Nothing in it has been executed.**
Rotating a credential and rewriting history are both the user's calls — see
the closing note.

## Where these four keys are actually read from

Confirmed 2026-07-30 in this environment (key names only, no values touched):

- Source file: `/home/bilab/work/projects/Broadsea/artemis/.env` (main
  checkout, not this worktree — this worktree's `.env` is untracked and has
  no on-disk copy, which is expected worktree behavior, not remediation).
- Wired into the container via `env_file:` in
  `/home/bilab/work/projects/Broadsea/compose/artemis-api.yml`.
- Live in the running `artemis-api` container's environment right now
  (verified via `docker exec artemis-api env | grep -oE '^(AWS_BEARER_TOKEN_BEDROCK|OPENROUTER_API_KEY|VLLM_API_KEY|OMOP_DB_PASS)='`
  — all four keys present; command intentionally stops at `=` so no value is
  printed).
- `docker restart artemis-api` does **not** re-read `env_file` — it restarts
  the existing process with its already-baked environment. A rotated value
  only takes effect after the container is recreated:
  `docker compose --profile default up -d artemis-api` (from the Broadsea
  root, using the compose fragment that owns this service).

## Rotation steps per credential

For each: revoke the exposed value first, generate a replacement, then update
every consumer before declaring it rotated. A key that is regenerated but not
revoked is not rotated — the old value keeps working.

### AWS_BEARER_TOKEN_BEDROCK

1. AWS Console → Amazon Bedrock → **API keys** (or IAM → access keys, if this
   was issued as a long-term IAM credential rather than a Bedrock API key —
   check which by the key's prefix format).
2. Find the key matching the exposed value, **Delete** (not just deactivate —
   deletion is what stops it from being usable if the leaked value is ever
   read).
3. Create a new key scoped identically (same model access / region).
4. Update `AWS_BEARER_TOKEN_BEDROCK=` in `artemis/.env` on the main checkout.
5. Recreate `artemis-api` (see above) so the container picks it up.
6. Check for the same key in any other `.env` on this machine — this repo has
   at least the main checkout and however many worktrees exist
   (`git worktree list` from `artemis/`).

### OPENROUTER_API_KEY

1. https://openrouter.ai/keys → find the key by name/prefix.
2. **Delete** it from the OpenRouter dashboard.
3. Create a new key with the same rate limit / spend cap.
4. Update `OPENROUTER_API_KEY=` in `artemis/.env`.
5. Recreate `artemis-api`.

### VLLM_API_KEY

This one has no external console — it is a bearer token the local vLLM
server was started with (`--api-key` or equivalent env var read by whatever
launches vLLM on this box; see
`docs/debugging/2026-07-29_gb10_vllm_serving_facts.md` for the GB10 launch
pattern).

1. Generate a new opaque token (e.g. `openssl rand -hex 32`) — do not print
   it to a shell history file; redirect straight into the two places that
   need it.
2. Update the vLLM server's own launch config/env with the new token and
   restart the vLLM process (a full process restart, not a hot-reload — vLLM
   reads its API key once at startup).
3. Update `VLLM_API_KEY=` in `artemis/.env` to match.
4. Recreate `artemis-api`.
5. Confirm the mismatch window is zero-length in practice: if vLLM restarts
   with the new token before `artemis-api` is recreated, every artemis call
   to vLLM 401s until step 4 completes — expected, not a bug.

### OMOP_DB_PASS

Postgres password for the OMOP CDM connection artemis reads from (distinct
from the WebAPI/atlasdb service password, which is set separately in
`compose/artemis-api.yml`; do not conflate the two — rotating one does not
rotate the other).

1. `docker exec -it <the postgres container holding this role> psql -U
   postgres -c "ALTER USER <omop_db_user> WITH PASSWORD '<new password>';"`
   — resolve `<the postgres container>` and `<omop_db_user>` from
   `OMOP_DB_HOST`/`OMOP_DB_USER` in `artemis/.env` first; do not guess.
2. Update `OMOP_DB_PASS=` (and `DATABASE_URL=` if it embeds the password
   inline) in `artemis/.env`.
3. Recreate `artemis-api`.
4. Recreate/restart any other consumer of the same role — check
   `compose/*.yml` for other services pointed at the same Postgres host
   before assuming artemis-api is the only reader.

## Pre-push guard (copy-paste only — not installed by this change)

Two layers: a local pre-push hook (fast, catches it before it leaves the
machine) and a CI check (catches it if the hook was bypassed or the clone
didn't have it installed). Both use the same pattern list so they can't drift
apart.

### `.githooks/pre-push`

```bash
#!/usr/bin/env bash
# Blocks a push if any commit being pushed tracks a file matching a secret
# pattern. Install with: git config core.hooksPath .githooks
set -euo pipefail

SECRET_PATTERNS='^\.env$|^\.env\.[^.]+$|^secrets/|_?[Ss][Ee][Cc][Rr][Ee][Tt].*\.(ya?ml|json|env)$'

remote="$1"
zero=$(git hash-object --stdin </dev/null | tr '[0-9a-f]' '0')

while read -r local_ref local_sha remote_ref remote_sha; do
  [ "$local_sha" = "$zero" ] && continue  # branch deletion, nothing to scan

  range="$local_sha"
  if [ "$remote_sha" != "$zero" ]; then
    range="$remote_sha..$local_sha"
  fi

  hits=$(git diff --name-only --diff-filter=ACMR "$range" -- 2>/dev/null \
    | grep -E "$SECRET_PATTERNS" || true)

  if [ -n "$hits" ]; then
    echo "pre-push: blocked — tracked file(s) match a secret pattern:" >&2
    echo "$hits" >&2
    echo "If this is genuinely safe to track, remove it from SECRET_PATTERNS" >&2
    echo "in .githooks/pre-push with a reviewed reason, don't just force-push." >&2
    exit 1
  fi
done

exit 0
```

```bash
chmod +x .githooks/pre-push
git config core.hooksPath .githooks
```

`core.hooksPath` is per-clone, not per-repo — every clone/worktree needs the
one-time `git config` line. That's exactly the gap the CI check below closes.

### CI check (GitHub Actions form; adapt the trigger to whatever CI runs here)

```yaml
name: secret-file-guard
on: [push, pull_request]
jobs:
  block-tracked-secrets:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Fail if a secret-shaped path is tracked
        run: |
          set -euo pipefail
          PATTERN='^\.env$|^\.env\.[^.]+$|^secrets/|_?[Ss][Ee][Cc][Rr][Ee][Tt].*\.(ya?ml|json|env)$'
          hits=$(git ls-tree -r --name-only HEAD | grep -E "$PATTERN" || true)
          if [ -n "$hits" ]; then
            echo "::error::Tracked file(s) match a secret pattern:"
            echo "$hits"
            exit 1
          fi
```

Both checks are path-pattern only — they do not scan file contents for
high-entropy strings, so a secret pasted inside an otherwise-ordinary file
(a `.md` note, a `.json` fixture) will not be caught. That is a known,
named ceiling: content-scanning (gitleaks/trufflehog in CI) is the upgrade
path if that pattern of leak shows up.

## Measured cost of a history rewrite

Rewriting `6ffd07c` reassigns every SHA in the repo — `git rev-list --all |
wc -l` = 72, single-rooted, so all 72 change across all 3 branches
(`fix/codex-adversarial-findings`, `fix/tte-a-drug-anchored-entry`, `main`).
Every citation of an old SHA in prose (docs, wiki notes, commit trailers)
goes stale simultaneously.

Counted 2026-07-30 in this worktree, cross-checked against the real 72-commit
SHA list (not a raw hex-token grep — this codebase also has 7-40 char hex
strings that are OMOP concept IDs, hashes, and fingerprints, e.g.
`concept_id: 45774751`, which a naive grep cannot tell apart from a commit
SHA):

```bash
# 1. Ground truth: every SHA reachable from any ref, this repo only
git rev-list --all > /tmp/all_full_shas.txt   # 72 lines, 2026-07-30

# 2. Candidate hex tokens, each root grepped separately since omx_wiki/ is
#    NOT part of this git repo — it lives at the Broadsea root, a separate
#    non-git directory (per CLAUDE.md), a sibling of this checkout, not a
#    subdirectory of it.
grep -rEoi '\b[0-9a-f]{7,40}\b' docs/ 2>/dev/null > /tmp/candidates_docs.txt
grep -rEoi '\b[0-9a-f]{7,40}\b' /home/bilab/work/projects/Broadsea/omx_wiki/ \
  2>/dev/null > /tmp/candidates_omx.txt

# 3. Filter candidates to real prefixes of an actual commit SHA (python,
#    because grep alone can't do "is this a prefix of a SHA in file 1")
python3 - <<'PY'
full = [l.strip() for l in open('/tmp/all_full_shas.txt') if l.strip()]
def is_sha(tok):
    tok = tok.lower()
    return 7 <= len(tok) <= 40 and any(s.startswith(tok) for s in full)
for label, path in [("docs", "/tmp/candidates_docs.txt"), ("omx_wiki", "/tmp/candidates_omx.txt")]:
    hits = [ln for ln in open(path) if is_sha(ln.split(':',1)[1].strip())]
    print(label, len(hits))
PY

# 4. Commit-message self-references need the same filter applied to
#    `git log --all --format='%H %B'` bodies instead of file content —
#    see the worked version that produced row 3 below; omitted here since
#    it needs the same is_sha() helper against a different input stream.
```

Result, measured on the pre-existing corpus (everything except this runbook
file, since a document about the citation count is itself a citation the
moment it names a SHA — see caveat below):

| Location | Files | Citations |
|---|---:|---:|
| `docs/` (all file types — `.md`, `.json`) | 8 | 37 |
| `omx_wiki/` (all file types — Broadsea root, outside this git repo) | 6 | 22 |
| Commit-message self-references (`git log --all --format='%H %B'`, same filter) | — | 14 |
| **Total** | | **73** |

Caveat, stated once rather than re-measured every edit: this file itself
names `6ffd07c` and `4bad902` (`grep -c` on this file will show the current
count). Each of those is a genuine citation by the same definition used
above, so the true total is the 73 above plus however many this file
currently has — a number that changes with every edit to this file and
isn't worth chasing to convergence. Treat 73 as the baseline the rest of the
repository owes, independent of this runbook's own existence.

All of them would need hand-fixing after a `filter-repo`/BFG rewrite — a
rewrite does not update prose, it only changes what the SHA refers to
underneath the now-wrong text.

## What is true right now

This runbook exists and the finding is otherwise unchanged: the four
credentials are still live and unrotated, `main` still has `.env` tracked at
its tip, and no pre-push guard is installed anywhere in this repo — closing
this finding requires a human to actually run the rotation steps above and
decide, separately, whether the history rewrite is worth its 73-plus-citation
cost.
