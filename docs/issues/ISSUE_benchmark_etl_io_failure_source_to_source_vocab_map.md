# ISSUE: Benchmark ETL I/O failure at `create_source_to_source_vocab_map.sql`

## Status

- Open
- First observed: 2026-03-18
- Scope: generated-data benchmark ETL on `synthea_cdm_benchmark`

## Summary

When running the generated Gold benchmark workflow, OMOP ETL can fail during
`CreateMapAndRollupTables`, specifically while executing
`create_source_to_source_vocab_map.sql`.

Observed error:

```text
org.postgresql.util.PSQLException: An I/O error occurred while sending to the backend.
```

This is an infra/runtime stability issue, not yet proven to be a cohort-logic
or data-semantics issue.

## Exact failure point

The captured error report showed failure while executing:

```sql
create index idx_source_vocab_map_source_code
on synthea_cdm_benchmark.source_to_source_vocab_map (source_code)
```

This happened inside ETLSyntheaBuilder Step 5:

- `CreateMapAndRollupTables`
- `CreateVocabMapTables`

## Why this matters

If this failure is not detected correctly, the workflow may continue and report:

- `person = 0`
- `visit_occurrence = 0`
- `WebAPI final = 0`

which can be mistaken for a cohort/data problem even though ETL never completed.

## What changed to reduce confusion

`artemis/scripts/run_etl_full.sh` was updated so that ETL failure now returns a
non-zero exit code instead of silently continuing.

That means future runs should stop at the ETL boundary instead of producing a
misleading downstream `0 patients` interpretation.

## Evidence observed so far

### Failure case

- Study: `ARISTOTLE`
- Run: `20260318_aristotle_10k_cachefix`
- ETL log showed failure in `create_source_to_source_vocab_map.sql`
- WebAPI/direct SQL results from that run are not trustworthy because ETL did
  not finish

### Retry case

- Study: `ARISTOTLE`
- Run: `20260318_aristotle_10k_cachefix_retry`
- Same workflow retried under the same general setup
- ETL completed successfully

Interpretation:

- the I/O failure is not deterministically tied to the ARISTOTLE cohort logic
- it behaves like an intermittent infrastructure/runtime instability

## Operational guidance

If this happens again:

1. Do **not** interpret downstream `0 patients` as a cohort/data failure yet.
2. Check `05_run_etl.log` and `/tmp/run_etl.log` first.
3. Confirm whether ETL stopped in:
   - `create_source_to_source_vocab_map.sql`
   - or another Step 5 mapping/rollup operation
4. Treat the run as infra-failed and retry from ETL / workflow level.
5. Keep the OHDSI/Broadsea core path unchanged unless the failure becomes
   frequent and clearly root-caused.

## Non-goals for now

We are **not** changing core OHDSI / Broadsea ETL SQL for this issue yet.

Reason:

- current priority is portability and reproducibility
- the issue has only been observed intermittently
- one clean retry already completed successfully

## Related documents

- `artemis/docs/debugging/2026-03-18_generated_gold_10k_eval_log.md`
- `artemis/docs/daily_notes/2026-03-18_generated_gold_eval_handoff.md`
- `.agent/workflows/generated-gold-10k-eval.md`
