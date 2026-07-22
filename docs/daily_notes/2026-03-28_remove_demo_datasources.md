# 2026-03-28: Demo Data Source Removal

## Summary

Removed 3 unused data sources from Broadsea, keeping EUNOMIA (demo) and SYNTHEA23M (primary).

## Removed Sources

| Source Key | Schema | Patients | Purpose |
|-----------|--------|----------|---------|
| SYNTHEA | synthea_cdm | 11,771 | Legacy small dataset |
| SYNTHEA100K | synthea100k | 235,222 | Mid-size test dataset |
| SYNTHEA_CDM_BENCHMARK | synthea_cdm_benchmark | ~1,200 | Benchmark evaluation |

## Kept Sources

| Source Key | Schema | Patients | Purpose |
|-----------|--------|----------|---------|
| EUNOMIA | demo_cdm | 2,694 | OHDSI demo database |
| SYNTHEA23M | synthea23m | 2,700,000 | Primary production dataset |

## Changes Made

### Deleted Files (10 scripts)

```
artemis/scripts/load_synthea_benchmark.sql
artemis/scripts/create_benchmark_vocab.sql
artemis/scripts/run_etl_full.sh
artemis/scripts/run_etl_benchmark.R
artemis/scripts/setup_all_benchmark_sources.sh
artemis/scripts/setup_benchmark_native_tables.R
artemis/scripts/run_etl_per_study.R
artemis/scripts/load_synthea100k.py
artemis/scripts/fix_synthea100k_schema.py
artemis/scripts/diagnose_synthea100k.py
```

### Modified Files — Default Values (synthea_cdm/synthea_cdm_benchmark -> synthea23m)

**Docker/Config:**
- `compose/artemis-api.yml`: CDM_SCHEMA default

**Scripts (11):**
- `execute_webapi_payload.py`, `evaluate_generated_gold_studies.py`, `trace_cohort_attrition.py`: DEFAULT_SOURCE_KEY
- `check_cohort_generation_status.sh`: RESULTS_SCHEMA default
- `neo4j_csv_import.sh`, `load_omop_to_neo4j.py`: SCHEMA default
- `benchmark_v4.py`, `benchmark_exp_d.py`: SCHEMA default
- `diagnose_hierarchy.py`, `diagnose_agent2_gaps.py`, `generate_concept_stats.py`: SCHEMA default

**Other Scripts (comments/docstrings):**
- `monitor_generation.py`: SQL schema refs
- `trigger_cohort_generation.py`, `simplified_troy_artemis_compare.py`: docstrings
- `achilles/run_achilles_synthea.R`: schema params and search_path

**Application Code (docstrings only):**
- `artemis/src/analysis/omop_connector.py`: docstring

**Tests (3):**
- `test_trace_cohort_attrition.py`: fixture schemas
- `test_evaluate_generated_gold_studies.py`: source key refs
- `tests/integration/test_spark_parity.py`: source key and schema

### Documentation Updated

~60 markdown files across `docs/`, `artemis/docs/`, `.moai/project/`, `CLAUDE.md`, `AGENTS.md`, `GEMINI.md` had schema/source key references updated.

## Not Changed

- **PostgreSQL schemas**: The actual DB schemas (synthea_cdm, synthea100k, synthea_cdm_benchmark) were NOT dropped. Only code references were removed.
- **`artemis/output/`**: Generated evaluation result files were left as-is (historical artifacts).
- **EUNOMIA (demo_cdm)**: All demo_cdm references preserved.

## Verification

- `grep` for removed source keys/schemas in code files: **0 matches**
- `pytest`: **132 passed, 1 failed** (pre-existing `test_boot_check` failure due to missing `gobject-2.0-0` system lib)
- Modified tests (24 cases): **all passed**
