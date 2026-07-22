# Task: 02_benchmark_script

## 1. Specification (Strict)

- Input: `--trial LEADER`, `--mode E2E_SUPP`
- Output: Output to console and `output/benchmark_cohort_{timestamp}.json`
- Logic:
  1. Orchestrate Agent 1 -> Agent 2 -> Agent 3 to get `agent_circe`
  2. Load `gold_circe` from `gold_standard/`
  3. Generate both in WebAPI asynchronously. Cache the `gold_cohort_id` based on `hash(gold_circe)` to avoid re-running identical queries.
  4. Wait for WebAPI completion.
  5. Call `OMOPConnector` overlap metric method.
  6. Calculate Precision, Recall, Jaccard, F1.
  7. Print results and save to JSON.

## 2. TDD Strategy

- [x] Test Case A: Mock WebAPI completion -> Script runs end to end, persists JSON
- [x] Test Case B: Real run on lightweight query -> Confirm cache hit on 2nd run
- [x] Test Case C: Handle WebAPI timeout -> Graceful failure and logging

## 3. Implementation Log

- 2026-03-16T17:35: Test Created (Fail)
- 2026-03-16T17:38: Implementation Code Written
- 2026-03-16T17:40: Test Passed

## 4. Final Status

- [DONE]
