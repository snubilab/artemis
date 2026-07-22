# Task: 01_omop_connector

## 1. Specification (Strict)
- Input: `gold_cohort_id` (int), `agent_cohort_id` (int), `results_schema` (str)
- Output: Dictionary containing `intersection_count`, `gold_only_count`, `agent_only_count`, `gold_total`, `agent_total`
- Logic:
  1. Construct a SQL query to compare `person_id` sets for both cohort IDs in `{results_schema}.cohort`.
  2. Use `OMOPConnector.engine.connect()` to execute the query.
  3. Return the aggregated counts to compute Jaccard Similarity and F1 over patient IDs.

## 2. TDD Strategy
- [x] Test Case A: Exact exact match (gold_id == agent_id) -> Jaccard 1.0
- [x] Test Case B: Partial match -> Correct overlap counts
- [x] Test Case C: Empty agent cohort -> 0 true positives, Jaccard 0.0

## 3. Implementation Log
- 2026-03-16T17:35: Test Created (Fail)
- 2026-03-16T17:36: Implementation Code Written
- 2026-03-16T17:36: Test Passed

## 4. Final Status
- [DONE]
