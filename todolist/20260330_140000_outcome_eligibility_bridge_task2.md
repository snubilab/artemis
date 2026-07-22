# Task 2: Thread Eligibility Data into Outcome Cohort Generation - 2026-03-30

## Requirements Analysis
- [x] Understand the 4 method changes needed
- [x] Read current code at each change site

## Implementation Plan
- [x] Change 1: _build_seeded_condition_circe - add expected_domain + pre_fetched_candidates params
- [x] Change 2: _build_seeded_single_codeset_circe - add pre_fetched_candidates param
- [x] Change 3: _materialize_seeded_outcome_cohorts - add eligibility + criterion_mapping_metadata params
- [x] Change 4: _build_seeded_cohort_artifact_payload - add criterion mapping metadata lookup + pass to call
- [x] Add signature-verification tests
- [x] Run tests and verify all pass (12/12 passed)
- [x] Verify no existing callers break

## Progress Tracking
- [x] Completed
- [x] Blockers: None
