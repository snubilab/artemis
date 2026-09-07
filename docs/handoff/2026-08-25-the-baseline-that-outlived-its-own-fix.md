# Handoff — SPEC-INFRA-004 (restated-cluster generalization) — 2026-08-25

## Goal / context

This session did three things in sequence: (1) fixed a PLATO-specific text-extraction bug in
agent1 (unrelated to the rest), (2) investigated whether it was safe to send TTE cohort
definitions to a hospital for real patient-data extraction (verdict: **No-Go**, several
blockers), and (3) authored, audited, and implemented **SPEC-INFRA-004**, which generalizes
SPEC-INFRA-003's Demographics-only duplicate-criterion fix to the rest of the domain space.
SPEC-INFRA-004 is now merged. One small, well-understood cleanup item from step (1) was never
applied — see Next steps.

## Current state

- Branch: `fix/tte-a-drug-anchored-entry` (in the `artemis/` nested repo — this repo has **no
  git remote**, so there is nothing to push and no PR to open; commit is the terminal action).
- HEAD: `0707b2aa579888e4936c8f7d9ba24ec6b0261c92`
- Uncommitted: clean except one pre-existing untracked file,
  `docs/handoff/2026-08-21-the-number-that-would-not-stay-attached.md` — leave it alone, it is
  not this session's.
- Worktrees: only the two unrelated pre-existing ones remain
  (`artemis-codex-fixes`, `artemis-eval-baseline`); both SPEC-INFRA-004 worktrees were merged
  and removed by `manager-git`.
- No server/build running.

## Done this session (newest first)

- `0707b2a` `09f90f3` `1ccfbba` `aef2986` — SPEC-INFRA-004 implementation (M2/M3+M5/M6/lint),
  merged clean fast-forward onto `fix/tte-a-drug-anchored-entry`. Post-merge test re-run:
  `pytest tests/test_infra_004_*.py tests/test_infra_003_*.py -q` → **260 passed, 0 failed**.
- `3e38b64` — `fix(agent1)`: PLATO's PDF-derived criteria no longer glue a following
  enumerated item onto the previous one (root cause: the numbered-list-marker regex in
  `src/agents/agent1/pubmed_fetcher.py` didn't accept a leading `(` before the marker).
- `506ffaf`/`4d30ddf` — an earlier, unrelated Pattern-G prompt fix (pre-dates this session's
  main thread; already committed when this session picked up).

SPEC-INFRA-004 artifacts: `/home/bilab/work/projects/Broadsea/.moai/specs/SPEC-INFRA-004/`
(`spec.md` v0.3.0, `plan.md`, `acceptance.md`, `progress.md` — note this path is at the
**workspace root** `.moai/specs/`, not `artemis/.moai/`). plan-auditor PASS at 0.94 after 3
iterations (0.75 → 0.84 → 0.94). Run-phase: 15 AC PASS, 1 PASS-WITH-DEBT (AC-014 — see below,
not this SPEC's defect).

## Key decisions & why

- **The generalized collapse path is gated on the *complement* of SPEC-INFRA-003's own
  `is_restatable_demographic()` predicate**, not on `domain != "Demographics"`. The simpler
  domain-exclusion gate was tried first and rejected: it orphans CAROLINA inclusion
  `Age >= 70 years` (a genuine duplicate with a non-null `valueConstraint`, so it fails
  INFRA-003's own gate 2 and neither path would ever collapse it). The complement-of-predicate
  gate gives the same disjointness guarantee with no orphan, no read of `sourceText` state, and
  it stays correct even if a future regeneration flips Demographics `sourceText` from empty to
  populated (this has already happened once in the corpus history — see `spec.md` §2.5/§B-1).
- **The collapse is equivalence-class partitioning, not group-wide reduction to one survivor.**
  Discovered mid-plan: EMPA-REG's "Liver disease (ALT/AST/ALP > 3x ULN)" is emitted as 6
  ungrouped criteria that are really 3 exact duplicate *pairs* (ALT, AST, ALP each appearing
  twice). A naive "one survivor per stem group" design would reduce 6→1 and recreate the exact
  regression SPEC-INFRA-003's AC-004 exists to prevent. The correct behavior — verified live,
  `acceptance.md` AC-006 — is 6→3.
- **3 decision points were resolved as their recommended defaults, confirmed by the user before
  run-phase**: fold in CAROLINA's other sibling duplicate-description groups; do NOT normalize
  `unitConceptId` on the EMPA-REG eGFR pair (strict equality, fail-closed); accept CAROLINA
  `{22,59}` ("Participation in another trial") as a **reported false negative** — it cannot be
  collapsed safely without synonym matching, which SPEC-INFRA-003 already forbade.
- **AC-014 (PLATO corpus-regression test) is PASS-WITH-DEBT, and it is *not* SPEC-INFRA-004's
  to fix.** `tests/test_corpus_regression.py`'s `BASELINE["PLATO"]` still reads `(18, 12, 1)`
  but the true post-`3e38b64` count is `(24, 12, 1)` — verified independently this session via
  `git diff 3e38b64 -- src/agents/ tests/test_corpus_regression.py` (empty — the mismatch
  predates SPEC-INFRA-004 entirely) and by re-counting PLATO's live inclusion criteria. The
  delta (+6) is exactly the (b)–(g) risk-factor items that used to be glued into one corrupted
  string and now correctly split apart — i.e. this is the **correct** consequence of the
  `3e38b64` fix; only the hardcoded baseline tuple never got updated. `pubmed_fetcher.py` is on
  SPEC-INFRA-004's PRESERVE list, so its implementing agent correctly declined to touch this.

## Next steps (ordered, concrete)

1. **Fix the stale PLATO baseline** (small, well-understood, not yet done — this was in
   progress when the session was interrupted):
   `artemis/tests/test_corpus_regression.py:44` — change
   `"PLATO": (18, 12, 1),` → `"PLATO": (24, 12, 1),`
   Then verify: `cd artemis && .venv/bin/python3 -m pytest tests/test_corpus_regression.py -v`
   (expect all pass, including the PLATO case). Commit separately from SPEC-INFRA-004 (it's an
   unrelated follow-up to `3e38b64`) — e.g.
   `fix(agent1): update PLATO corpus-regression baseline for the 3e38b64 split`.
2. **`progress.md`'s branch_note is stale** — it still says "Not committed on
   fix/tte-a-drug-anchored-entry"; the branch section was written before the merge. Update it to
   reflect the actual merged HEAD (`0707b2a`) if/when `§E.4 Sync-phase` gets filled in.
3. **SPEC-INFRA-004 sync-phase has not run** (`§E.4` in `progress.md` is still
   `<pending sync-phase>`). Given this repo has no remote, sync-phase will likely look like
   SPEC-INFRA-003's did — no PR, adapted CHANGELOG handling — check how SPEC-INFRA-003's
   sync-phase was closed out for the precedent before running `/moai sync SPEC-INFRA-004`.
4. **Two non-blocking plan-audit findings remain, explicitly left optional by the auditor**
   (R1/R2, both cosmetic wording precision in `spec.md`, no test/behavior impact) — take or
   leave at will, not worth another SPEC round-trip.
5. **The hospital-readiness No-Go verdict from earlier this session is still active** and
   SPEC-INFRA-004 only closes one of its blockers (the CAROLINA/EMPA-REG harm-confirmed
   clusters — now 2 fixed, 3 correctly identified as non-defects). Still open: (a) a fresh
   concept-set-mapping gold re-evaluation across all 6 studies with the current code (measure
   of record: `artemis/scripts/conceptset_overlap_eval.py --mode closure`, NOT
   `evaluate_generated_gold_studies.py` — that script's own docstring says it is not a quality
   measure), (b) actual clinical review of eligibility criteria by medical staff — out of
   engineering scope entirely, not something any SPEC can close.

## How to verify / run

```bash
cd /home/bilab/work/projects/Broadsea/artemis
git log --oneline -6
.venv/bin/python3 -m pytest tests/test_infra_004_*.py tests/test_infra_003_*.py -q
.venv/bin/python3 -m pytest tests/test_corpus_regression.py -v   # currently 1 known-failing case (PLATO), see Next steps #1
```

No server, no URL — this is a batch pipeline / library repo, not a running service this
session.

## Gotchas / constraints

- `artemis/` has **no git remote** — never attempt `git push`, `git fetch origin`, or open a
  PR here. Commit is the terminal action.
- SPEC artifacts live at the **workspace root** `.moai/specs/`, not `artemis/.moai/` (the
  latter only holds `state/`).
- Docker stack (`artemis-api`, `broadsea-atlasdb`, `ohdsi-webapi`) was up throughout this
  session and used for live-store verification. A generated-IR store used repeatedly for
  fixture verification lives at `/app/tmp/tte_six_hospital_readiness/studies.json` inside the
  `artemis-api` container (all 6 studies, reflects code as of `3e38b64`) — check it is still
  present before trusting any fixture that depends on it; regenerate narrowly if not.
- `pubmed_fetcher.py`, `restated_demographics.py`, `restated_clusters.py`, and
  `tte_service.py`'s `_effective_group_type`/`_build_grouped_inclusion_rule` are all
  cross-SPEC-sensitive — multiple SPECs declare parts of them PRESERVE-listed. Check the
  relevant `spec.md` Out-of-Scope section before editing any of them.
- `ruff format --check` is **not** a project gate here — it rewrites several PRESERVE-listed
  files. Use `ruff check` only.
