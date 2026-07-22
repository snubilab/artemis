# 2026-03-22 Generated Gold / SQL Translation Current State

## Purpose

This note consolidates the current state that was previously scattered across:

- `artemis/docs/daily_notes/2026-03-18_generated_gold_eval_handoff.md`
- `artemis/docs/debugging/2026-03-18_generated_gold_10k_eval_log.md`
- `artemis/docs/rfc/RFC-013_SqlRender_PostgreSQL_Bypass.md`

The goal is to make three things explicit:

1. how SQL generation actually works in the current Broadsea/OHDSI stack
2. what the per-study generated-gold status is now
3. what the remaining gap is for ARISTOTLE and for the generated-gold execution path

## SQL Path Split

There are two different SQL paths in play.

### 1. Raw WebAPI SQL endpoint

`POST /WebAPI/cohortdefinition/sql`

Current live behavior on this Broadsea stack:

- returns `templateSql`
- does not return a separate `sql` field
- this was confirmed directly against the live `WebAPI 2.15.1-SNAPSHOT` instance

Important implication:

- the response is still template-oriented SQL
- it can contain placeholders and non-Postgres-native constructs such as:
  - `@cdm_database_schema`
  - `#Codesets`
  - `UPDATE STATISTICS`
  - `DATEADD(...)`

### 2. Atlas UI SQL tab

Atlas does not stop at `/cohortdefinition/sql`.

It uses a two-step flow:

1. fetch `templateSql` from `cohortdefinition/sql`
2. call `POST /WebAPI/sqlrender/translate` to render dialect-specific SQL

Confirmed in:

- `atlas-dev/js/services/CohortDefinition.js`
- `atlas-dev/js/components/utilities/sql/sqlExportPanel.js`

This is why the Atlas `PostgreSQL` tab appears to "work correctly":

- `#Codesets` becomes `CREATE TEMP TABLE Codesets`
- `UPDATE STATISTICS` becomes `ANALYZE`
- `DATEADD(...)` becomes interval arithmetic

### 3. Generated-gold attrition path

The generated-gold attrition/debug path currently diverges from Atlas.

Current behavior:

- calls `cohortdefinition/sql`
- if live response has no `sql`, falls back to repo-local `python_fallback`
- this happens in `artemis/scripts/trace_cohort_attrition.py`

Current conclusion:

- the mismatch is not "Atlas works but OHDSI cannot translate"
- the mismatch is:
  - Atlas path: `templateSql -> sqlrender/translate`
  - generated-gold path: `templateSql -> python_fallback`

## Per-Study Status

## PLATO

Current state:

- generated data: confirmed
- ETL: confirmed
- WebAPI/nonzero cohort extraction: confirmed

Strongest visible runs:

- `20260318_plato_10k_cachefixfinal`
  - `L00 EntryOnly = 436`
  - final `L05 Rule1to5 = 436`
- `20260318_plato_25k_cachefix`
  - `L00 EntryOnly = 1068`
  - final `L05 Rule1to5 = 1068`

Interpretation:

- PLATO is operationally in the "success / effectively closed" bucket
- the remaining question is attrition shape realism, not zero-patient failure

Note:

- some stored artifacts under PLATO paths still carry `cohort_name = "[ATTRITION] Gold LEADER ..."`
- current interpretation is naming mismatch, not run identity mismatch

Gold JSON naming note:

- a separate naming sweep across:
  - `EMPA_REG_GOLD.json`
  - `LEADER_GOLD.json`
  - `PLATO_GOLD.json`
  did not reveal the same stale study-prefix concept-set naming issue
- the stale-prefix cleanup in this pass was therefore limited to:
  - `ARISTOTLE_GOLD.json`

## LEADER

Current state:

- generated data: confirmed
- ETL: confirmed on retry
- nonzero full attrition execution: confirmed

Strongest visible run:

- `20260318_leader_10k_cachefix_retry`
  - `L00 EntryOnly = 1378`
  - latest visible final record `L17 Rule1to17 = 1222`

Interpretation:

- LEADER is also in the "success / effectively closed" bucket
- unlike PLATO, LEADER shows a more trial-like attrition drop before flattening

## ARISTOTLE

ARISTOTLE has been validated more broadly than a single failed retry summary.

### Confirmed

- generator path: validated repeatedly
- ETL path: validated repeatedly
- entry-level viability: validated repeatedly

Confirmed evidence includes:

- scripted retry summary exists:
  - `20260318_aristotle_10k_cachefix_retry`
  - summary ends as `study_error` because automated attrition trace timed out
- separate manual attrition rerun exists:
  - `L00 EntryOnly = 43`
  - `L01 = 41`
  - `L02 = 41`
  - `L03 = 0`
- patched direct validation in handoff notes:
  - patched `1k`: `EntryOnly = 107`
  - patched `20k`: `EntryOnly = 2308`
- dry-run artifact exists through full `L15` SQL/payload generation:
  - `artemis/output/aristotle_attrition_dryrun/20260318_aristotle_full_dryrun/results.jsonl`

### Current live benchmark state

The current benchmark DB was checked against the documented patched `20k` ARISTOTLE state:

- `person = 20000`
- `visit_occurrence = 197780`
- `condition_occurrence = 9044`
- `drug_exposure = 5885`
- `drug_era = 5885`

### Remaining open problem

The remaining unresolved question is not "can ARISTOTLE generate eligible patients?"

That part is already supported by repeated entry-level validation.

The remaining unresolved question is:

- can the full ARISTOTLE `L15` execution complete at acceptable cost on the current benchmark stack?

Observed reproduction on the current patched `20k` DB:

- direct execution of saved `L15 translated.sql` was attempted
- ad hoc compatibility fixes were needed for the repo-local fallback SQL:
  - remove `UPDATE STATISTICS`
  - rewrite `YEAR(date)` to `EXTRACT(YEAR FROM date)`
- after those fixes, the query entered real execution
- observed long-running stage:
  - `SELECT ... INTO TEMP temp_qualified_events`
- during the observed run, `cohort_definition_id = 15` remained `0`

Interpretation:

- the current ARISTOTLE blocker is execution cost in the full SQL path
- the blocker is not absence of generated patients

### 2026-03-22 execute-path verification update

After aligning generated-gold translation with the Atlas path, a real execute-mode
verification was started:

- run id:
  - `20260322T_aristotle_sqlrender_exec`
- level:
  - `L00 EntryOnly`
- translation artifact:
  - `translation_method = sqlrender_translate`
- live generation:
  - WebAPI cohort definition id `483`
  - WebAPI logs showed fresh calculation rather than cache reuse

Current observed state during this verification:

- job status remained `RUNNING`
- observed elapsed time reached about `35 minutes`
- active DB stage remained:
  - `CREATE TEMP TABLE qualified_events AS ...`
- `synthea_cdm_benchmark_results.cohort where cohort_definition_id = 483`
  remained `0` during the observation window

Interpretation:

- this confirms that the new sqlrender-aligned path does reach real WebAPI
  cohort generation
- the unresolved issue is still runtime cost for ARISTOTLE `L00`
- the current state should be read as:
  - **still running / not yet materialized**
  - not **completed zero-patient result**

## Current Architecture Recommendation

For generated-gold cohort evaluation, the SQL path should be aligned with the Atlas UI path.

Recommended direction:

1. prefer `/WebAPI/sqlrender/translate` over repo-local `python_fallback`
2. keep repo-local fallback only as an explicit debug-only path, or remove it from production-like flows
3. make the failure mode explicit when translated SQL cannot be obtained

Rationale:

- Atlas already proves the intended production-like SQL translation path
- the current local fallback created a misleading divergence in behavior and in responsibility boundaries

## Current One-Line Summary

- `PLATO`: success
- `LEADER`: success
- `ARISTOTLE`: generator/ETL/entry viability confirmed, full final execution still limited by SQL execution cost
- SQL architecture mismatch:
  - Atlas uses `sqlrender/translate`
  - generated-gold attrition path still uses repo-local `python_fallback`
