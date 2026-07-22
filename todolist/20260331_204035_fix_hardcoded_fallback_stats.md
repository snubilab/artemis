# Fix Remaining Hardcoded Fallback Stats - 2026-03-31

## Requirements Analysis
- [x] Understand current _run_agent5_analysis_wrapper except block behavior
- [x] Understand _build_placeholder_results (hardcoded HR=0.83, pValue=0.005, etc.)
- [x] Understand cohort_executor.py synthetic rows with patient_count=0
- [x] Understand _generate_fallback_data usage

## Implementation Plan

### Fix A - _run_agent5_analysis_wrapper error payload
- [x] Write RED test: wrapper returns error payload (no HR/CI/p-value) on exception
- [x] Implement GREEN: replace placeholder stats with null metrics + status="error"

### Fix B - cohort_executor synthetic rows with patient_count=0
- [x] Write RED test: empty cohort returns data=None, used_fallback=False, error field
- [x] Implement GREEN: separate empty cohort path from fallback

### Fix C - reject used_fallback=True cohorts in agent5 dataset builder
- [x] Write RED test: wrapper catches RuntimeError from dataset builder when fallback detected
- [x] Implement GREEN: error propagates through wrapper returning error payload

### Fix D - _generate_fallback_data docstring and warning
- [x] Add docstring with WARNING
- [x] Add logger.warning() at top of function body

## Progress Tracking
- [x] Started at: 20:40
- [x] Current status: COMPLETE - commit 33e1c3c
- [x] Blockers: none
- [x] Tests: 12 new TDD tests (all pass), 2 existing tests updated
