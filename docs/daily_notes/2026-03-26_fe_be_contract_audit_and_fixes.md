# 2026-03-26: TTE Frontend-Backend Contract Audit and Fixes

## Summary

Full audit of all 6 TTE modules for frontend-backend field contract violations,
followed by implementation of all critical fixes.

## Audit Results (6 modules)

| Module | Critical | Important | Minor |
|--------|----------|-----------|-------|
| Eligibility Criteria | 2 | 3 | 3 |
| Treatment Arms | 0 | 0 | 2 |
| Outcomes | 1 | 3 | 3 |
| Structured Expression / Editor | 2 (+2 test) | 7 | 2 |
| Study Spec / Metadata | 0 | 4 | 5 |
| Concept Sets | 2 | 3 | 3 |
| **Total** | **7** | **20** | **18** |

## Critical Fixes Implemented

### 1. Composite Criteria (groupId/groupType)
- IR `sub_criteria` + `group_type` were flattened and lost in `_criteria_from_ir`
- Added `groupId`/`groupType` fields to `Criterion` model
- `_criteria_from_ir` now preserves grouping metadata (UUID groupId, ANY/ALL groupType)
- `_build_seeded_target_circe` merges grouped criteria into single CIRCE InclusionRules
- FE adapter handles composite rules bidirectionally (build + read)
- 10 new adapter tests, all passing

### 2. logicType (ABSENCE/PRESENCE)
- IR `logic_type` was dropped during conversion, making ABSENCE criteria indistinguishable
- Added `logicType` to Criterion model, propagated through full pipeline
- ABSENCE criteria now correctly produce `Occurrence: {Type: 0, Count: 0}`
- Sub-criteria inherit parent's logic_type with override capability
- 9 new backend tests

### 3. Outcome timeAtRisk + domain
- IR `CohortOutcome.time_at_risk` and `domain` were parsed by Agent1 but dropped
- Added both fields to `Outcome` model
- New `_outcome_dict_from_ir` helper extracts and preserves all fields
- Outcome domain no longer defaults to ConditionOccurrence

### 4. ConceptSet items preservation
- `createConceptSet()` always returned empty items on rebuild path
- Now accepts existing expression and preserves concept items via ID/name lookup

### 5. Domain-based criteria key
- `createRuleExpression()` hardcoded ConditionOccurrence for all domains
- Added `DOMAIN_TO_CRITERIA_KEY` mapping (8 domains: Condition, Drug, Measurement,
  Procedure, Observation, Device, Visit, Death)
- FE adapter now produces correct CIRCE criteria keys per domain

### 6. DemographicCriteriaList round-trip
- Backend demographic rules (Age, Gender) were destroyed on adapter re-generation
- Added `buildDemographicExpression()` for proper CIRCE demographic rules
- Read path recognizes DemographicCriteriaList and reconstructs valueConstraint

### 7. CIRCE sync on criteria remove
- `removeCriterionFromExpression()` surgically removes ConceptSet + InclusionRule
- Handles standalone, grouped (partial/full removal), and demographic criteria
- ConceptSet refCount guard prevents removal when shared by other rules
- Save-time orphan cleanup in `buildStudyData()`
- `_isProcessed` tracking with "pending" badge for unprocessed criteria

## Other Fixes

- ConceptSet ID numbering aligned to 1-based (matching backend)
- `getEligibilitySummaryData()` now includes all metadata fields
- `version` included in `buildStudyData()` for optimistic concurrency
- `eligibilityObservationWindow` converted to ko.observable
- NCT `trialMetadata` added to TTEStudy model with back-fill on apply
- logicType/window/conceptSetName badges in criteria template
- Groups/EndWindow/Gender/EndStrategy pass-through tests added

## DB Tuning

- Container memory: 2GB -> 4GB, shm_size: 256m -> 512m
- shared_buffers: 2GB -> 1GB (was exceeding container memory)
- work_mem: 256MB -> 128MB (prevents OOM on concurrent queries)
- Parallel workers enabled: max_parallel_workers_per_gather = 4
- concept_ancestor materialized as table with indexes (was VIEW)

## Gold Validation (LEADER NCT01179048)

- IR sub_criteria correctly preserved: 4 composite groups (ANY)
- Adapter generates correct CIRCE: 37 ConceptSets, 18 InclusionRules (4 composite)
- WebAPI SQL generation: 61,887 chars, correct domain keys
- SYNTHEA 11.7K: T2DM + composite (MI OR Stroke) = 14 persons
- SYNTHEA100K: same cohort = 16 persons (no OOM crash)
- BENCHMARK 10K (LEADER data): Gold CIRCE = base 1,363 -> final 1,228 persons

## Test Summary

- Backend: 29 tests passing (20 existing + 9 new)
- Frontend adapter: 52 tests passing (18 original + 34 new)

## Files Changed

- `artemis/src/api/models/tte.py` — Criterion: groupId, groupType, logicType; Outcome: domain, timeAtRisk; TTEStudy: trialMetadata
- `artemis/src/services/tte_service.py` — _criteria_from_ir, _build_seeded_target_circe, _outcome_dict_from_ir, _fetch_nct_trial_metadata
- `artemis/tests/test_tte_ir_pipeline.py` — 9 new test classes
- `atlas-dev/js/.../eligibility-expression-adapter.js` — composite rules, domain mapping, demographics, removeCriterionFromExpression
- `atlas-dev/js/.../tte-manager.js` — groupId/groupType/logicType model, CIRCE sync, _isProcessed, version, observationWindow
- `atlas-dev/js/.../tte-manager.html` — NOT/pending/window/conceptSetName badges
- `atlas-dev/tests/.../eligibility-expression-adapter.test.js` — 34 new tests
- `docker-compose.yml` — DB memory tuning

## Remaining (DEFERRED)

- Description/domain edit sync to InclusionRule name (low priority refinement)
- Secondary outcome cohort selection UI (stub)
- OHDSI WebAPI SQL generation performance (~400s for complex Gold CIRCE, structural limit)

## References

- Full audit: `todolist/20260326_010000_tte_fe_be_contract_audit.md`
- Pipeline doc: `artemis/docs/synthea_benchmark_data_pipeline.md`
