# Spark Cohort Executor Setup

## System Requirements

- **Colima: 18GB+ memory** — Spark loads 75M-row concept_ancestor into RAM
- Docker image must be rebuilt after this integration (includes JDK 17 + pyspark)

## First-time setup

### 1. Start Colima with enough memory

```bash
colima start --memory 18 --cpu 4
```

Default Colima memory (7.7GB) causes OOM when loading concept_ancestor.
To make this permanent, add to your shell profile:

```bash
# ~/.zshrc
alias colima-broadsea='colima start --memory 18 --cpu 4'
```

### 2. Build and start the stack

```bash
docker-compose build artemis-api
docker-compose up -d
```

### 3. Export vocabulary Parquet files (one-time, ~10 minutes)

```bash
docker exec artemis-api python -m scripts.export_vocab_parquet
```

Exports to `/app/tmp/parquet/` (volume-mounted, persists across restarts):
- `concept.parquet` (~5MB)
- `concept_ancestor.parquet` (~3GB, 75M rows)
- `concept_relationship.parquet` (~1.5GB, 39M rows)
- `vocabulary.parquet`, `drug_strength.parquet`

Subsequent restarts skip the export if files already exist.

### 4. Activate Spark engine

Add to `artemis/.env`:

```
COHORT_ENGINE=spark
```

Restart: `docker-compose restart artemis-api`

The API will validate prerequisites on startup and fail fast if anything is missing.

## Verification

```bash
docker exec artemis-api python -c "
from src.pipeline.spark_startup import validate_spark_prerequisites
validate_spark_prerequisites()
print('All Spark prerequisites met.')
"
```

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Container OOM (exit 137) | Colima memory < 18GB | `colima stop && colima start --memory 18` |
| `pyspark not installed` | Old image | `docker-compose build artemis-api` |
| `JDBC jar not found` | Old image | `docker-compose build artemis-api` |
| `Parquet vocab files missing` | First-time or volume lost | Re-run export (Step 3) |
| WebAPI 2000s+ timeout | PostgreSQL stuck query | `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state='active' AND now()-query_start > interval '5 minutes';` |

## Architecture

```
CIRCE JSON
  → WebAPI /cohortdefinition/sql (OHDSI SQL)
  → WebAPI /sqlrender/translate  (Spark dialect)
  → render_spark_sql()           (placeholder substitution)
  → SparkCohortExecutor          (PySpark local[*])
    ├── CDM tables: PostgreSQL JDBC  (person, condition_occurrence, …)
    └── Vocab tables: Parquet        (concept_ancestor, concept, …)
  → cohort results → PostgreSQL writeback
```

Activation env var: `COHORT_ENGINE=spark` (default: WebAPI)

## Validated performance (10K patient cohorts)

| Study    | Patients | WebAPI | Spark | Speedup |
|----------|----------|--------|-------|---------|
| LEADER   | 1,222    | 479s   | 48s   | 10x     |
| PLATO    | 436      | 14s    | 15s   | ~1x*    |
| ARISTOTLE| 1,219    | ~2100s | 19s   | 111x    |

*Small cohorts: Spark startup overhead exceeds query savings. Spark excels on large cohorts.
