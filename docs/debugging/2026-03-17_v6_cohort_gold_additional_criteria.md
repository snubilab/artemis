# 🚨 Debugging Log: Gold 166 0-Patient Attrition & AdditionalCriteria

**Date**: 2026-03-17
**Issue**: WebAPI consistently returned 0 patients for the Gold LEADER cohort (ID 166), despite manual SQL queries and simpler cohort definitions yielding significant patient counts (1,093).

## 1. Initial Hypotheses (Debunked)
* **SqlRender Version:** Suspected the bundled `SqlRender-1.19.1.jar` could not translate SQL Server date functions (`DATEADD`).
  * **Result**: False. When WebAPI bypasses the cache and executes SQL internally, it correctly translates to PostgreSQL syntax (e.g., `INTERVAL`).
* **Silent Failure due to Huge SQL (113KB):** Suspected WebAPI could not handle the 49 ConceptSets, leading to execution failure.
  * **Result**: Partially True, but not the root cause. Large SQL executes successfully when bypassed via R `DatabaseConnector` directly to PostgreSQL.

## 2. The Great Deception: WebAPI Generation Cache
During our initial testing, removing ConceptSets yielded different results, leading us to believe the *number* of ConceptSets was the issue. 

**However, we discovered WebAPI's `GenerationCacheHelper` was trapping us.**
* WebAPI caches 0-patient results indefinitely in the `webapi.generation_cache` table.
* Even if we `TRUNCATE` the `synthea_cdm_benchmark_results.cohort_cache` tables, WebAPI checks the central `generation_cache` metadata table first.
* Finding: `SELECT * FROM webapi.generation_cache WHERE design_hash = 1327408681` showed `result_checksum='0'`, forcing WebAPI to skip SQL execution entirely.

**Resolution**: To force a fresh run, we must delete from **both**:
```sql
DELETE FROM webapi.generation_cache WHERE design_hash = 1327408681;
TRUNCATE synthea_cdm_benchmark_results.cohort_cache CASCADE;
```

## 3. The True Root Cause: AdditionalCriteria Hidden in Entry SQL
Once we forced a fresh generation, the result was **genuinely 0 patients**.
We bypassed WebAPI and ran the 113KB Circe SQL directly via R `DatabaseConnector`. Execution succeeded in 24 seconds, but returned 0 patients.
* We analyzed the `cohort_inclusion_stats`.
* Result: **ALL rules had `person_total = 0`**. 
* This meant the cohort failed at the **Entry level**, not inside the 18 Inclusion Rules.

But our manual Entry SQL (DrugEra liraglutide + EraLength + PriorDays) returned 1,093 patients. Why the discrepancy?

**Finding the discrepancy in `qualified_events`:**
Circe's generated SQL for `qualified_events` included an `INNER JOIN` to a `Correlated Criteria` subquery:
```sql
-- Circe SQL inside qualified_events
JOIN Codesets cs on (co.condition_concept_id = cs.concept_id and cs.codeset_id = 91)
...
AND A.START_DATE >= (P.START_DATE + -180*INTERVAL'1 day')
```

We inspected the Gold 166 JSON:
```json
  "PrimaryCriteria": {
    "CriteriaList": [ ... DrugEra ... ],
    "ObservationWindow": { ... }
  },
  "AdditionalCriteria": {
    "Type": "ANY",
    "CriteriaList": [
      {
        "Criteria": { "ConditionOccurrence": { "CodesetId": 91 } },
        "StartWindow": { "Start": { "Days": 180, "Coeff": -1 } ... }
      }
    ]
  }
```

* **Codeset 91**: `[TROY] Type 2 Diabetes Mellitus`
* **Translation**: The patient must have a T2DM condition occurrence *within 180 days prior to the liraglutide prescription*.

### The Bug in Data Generation
Our parsing script (`generate_synthea_from_gold.py`) only looked at `PrimaryCriteria -> CriteriaList`. It **completely ignored `AdditionalCriteria`**.
Because Synthea didn't generate T2DM condition records for these patients, the SQL correctly returned 0 patients.

## 4. Fix Implemented
1. Updated `_extract_primary_criteria_reqs()` in `generate_synthea_from_gold.py` to recursively parse `PrimaryCriteria -> AdditionalCriteria` using the existing `_extract_requirements_from_node` function.
2. Rebuilt the Synthea module (`artemis_leader.json`) and the FAT JAR.
3. Reran the 10-parallel Synthea generation and ETL pipeline.

## 5. Lessons Learned
1. **Never trust WebAPI 0-patient results without clearing metadata cache.** Delete from `webapi.generation_cache` to ensure fresh execution.
2. **PrimaryCriteria is more than just CriteriaList.** `AdditionalCriteria` acts as an entry-level gatekeeper. The data generator must satisfy *all* root conditions, not just the DrugEra.
3. **When Circe returns 0 but manual SQL returns N, manual SQL is incomplete.** Always inspect the translated `qualified_events` CTE in the `SqlRender` output to find the hidden conditions.
