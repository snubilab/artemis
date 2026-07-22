# ARCH_MAP: v6_cohort_benchmark

## 1. Project Goal
Shift ARTEMIS evaluation to Cohort-level Jaccard Similarity (Cohort Overlap) to accurately measure end-to-end performance and bypass the conceptual limits of Concept-ID flat-union metrics.

## 2. Tech Stack
- Language: Python 3.10+
- Orchestration: OMOP WebAPI (Circe-be engine)
- DB: PostgreSQL (OMOP CDM v5.3 / Synthea 23M)
- Caching: Local JSON (`agent2_cache.json` or a new benchmark cache)

## 3. Atomic Sub-tasks
- `01`: Enhance `OMOPConnector` to support direct Cohort overlap queries (Jaccard metrics).
- `02`: Implement `benchmark_v6_cohort.py` orchestrator script.

## 4. Status
- [IN_PROGRESS] `01_omop_connector`
- [PENDING] `02_benchmark_script`
