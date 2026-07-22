# Outcome Eligibility Bridge & Execute Blocker — Handoff

**Date**: 2026-03-30
**Branch**: `feat/agent2-mapping-accuracy`
**Study**: 428 (apixaban vs warfarin, LEADER benchmark)

---

## Completed Today

### A. Cohort Name Sanitization

| Commit | Description |
|--------|-------------|
| subagent | `_sanitize_cohort_name()` — strips Atlas-forbidden chars (`: ; \ [ ]`) |
| subagent | `_seeded_cohort_definition_name()` — `:` → ` - `, 255 char limit |
| `0f6c0b1` | 13 tests in `test_cohort_name_sanitization.py` |

### B. Outcome Eligibility Bridge (core feature)

| Commit | Description |
|--------|-------------|
| `6dc1c70` | `_extract_eligibility_concept_ids_for_outcome` helper + threading through call chain |
| `0f6c0b1` | mock signature fix in `test_seeded_outcome_cohort.py` |

**What it does:**
- When generating outcome cohorts, the system now looks up the latest
  `eligibility_processing` artifact to get `criterionMappingMetadata`
- Extracts `selectedConceptIds` from eligibility criteria that match the
  outcome label (fuzzy substring match, splitting by `or`/`and`/`,`/`;`)
- Passes matched concept IDs as `pre_fetched_candidates` to Agent2
- Also forwards the outcome `domain` (from IR) as `expected_domain`

**Expected effect:**
- Outcome cohort concept count should increase significantly (from ~8 to
  many more, depending on eligibility overlap)
- Agent2 gets a head start with already-mapped concepts from eligibility

**Test results:** 32/32 passing (12 bridge + 13 sanitize + 7 seeded outcome)

### C. Previous Commits (from earlier session)

| Commit | Description |
|--------|-------------|
| `b4f0da5` | orphan dict bug fix in `_materialize_seeded_outcome_cohorts` |
| `5991a8c` | hide manual selection UI elements on outcomes tab |
| `616199f` | resolve remaining outcomes tab UI issues |
| `1c5ade4` | hide entire outcomes status banner container |

---

## OPEN ISSUE: Execute Study 400 Error

### Symptom

```
POST /tte/studies/428/execute → 400 Bad Request
{"detail": "Validation artifact is required before execution."}
```

### Root Cause

`_assert_execute_ready` (`tte_service.py:4509`) requires a
`design_validation` artifact before allowing execution. This artifact is
created by `triggerValidation()` in `tte-manager.js:3406`.

**However:** The Validate Design button does NOT exist in the HTML template.
`triggerValidation()` is defined in JS but never bound to any UI element in
`tte-manager.html`. There is no `data-bind="click: triggerValidation"` anywhere.

### Evidence

```bash
# Method exists in JS:
grep -n "triggerValidation" tte-manager.js
# → 3406: triggerValidation() {

# But NO binding in HTML:
grep -rn "triggerValidation" tte-manager.html
# → (no results)
```

### Options to Fix

**Option 1: Add Validate Design button to Execute Study tab**
- Add a button with `data-bind="click: triggerValidation, enable: canTriggerValidation"`
- Place it before the Execute Study button
- The validation gating already exists in `canTriggerExecuteStudy` — it checks
  `canExecute()` which likely requires the validation artifact

**Option 2: Auto-validate before execution**
- Modify `executeAnalysis()` to call `triggerValidation()` first if no
  validation artifact exists
- Chain: validate → execute in one click

**Option 3: Remove validation gate temporarily**
- For development/testing, skip `_assert_execute_ready` check
- NOT recommended for production

### Relevant Code

| File | Location | Description |
|------|----------|-------------|
| `tte-manager.js:3406` | `triggerValidation()` | JS method (exists, no UI binding) |
| `tte-manager.js:1142` | `canTriggerValidation` | Computed observable for enabling button |
| `tte-manager.js:3893` | `executeAnalysis()` | Execute button handler |
| `tte-manager.html:1399` | Execute Study button | Has `click: executeAnalysis` binding |
| `TTEService.js:113` | `validateDesign()` | API call to backend |
| `tte_service.py:4509` | `_assert_execute_ready` | Backend validation gate |
| `tte.py:397` | `POST /execute` endpoint | Catches ValueError → 400 |

---

## State of Study 428

- Import: done
- Process Eligibility: done (has eligibility_processing artifact)
- Generate Seeded Cohorts: done (has seeded_cohort_generation artifact)
  - Now includes eligibility bridge (pre_fetched_candidates)
- Validate Design: **BLOCKED** — no UI button to trigger
- Execute Study: **BLOCKED** — depends on validation artifact

---

## Files Changed (Unstaged/Untracked)

Key files touched in this session:

| File | Status |
|------|--------|
| `artemis/src/services/tte_service.py` | Modified (sanitize + bridge) |
| `artemis/tests/test_outcome_eligibility_bridge.py` | New (12 tests) |
| `artemis/tests/test_cohort_name_sanitization.py` | New (13 tests) |
| `artemis/tests/test_seeded_outcome_cohort.py` | Modified (mock fix) |

---

## Plans Reference

- `docs/superpowers/plans/2026-03-30-outcome-cohort-eligibility-bridge.md`
- `docs/superpowers/plans/2026-03-30-outcome-cohortid-orphan-fix.md`
- `docs/superpowers/plans/2026-03-30-outcome-tab-simplify.md`
