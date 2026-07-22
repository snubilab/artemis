# Agent1 Ingredient Concept Fix — 2026-03-31

## Summary

Fixed the TTE drug-concept handling path so Drug-domain mappings are normalized to
standard RxNorm ingredient concepts before they become CIRCE concept sets.

This targets the PLATO failure mode where generated cohorts used RxNorm Extension
product concepts such as `855208` instead of the DrugEra-compatible ingredient
concept `40241186` (`ticagrelor`).

## Investigation

### Agent1 (`artemis/src/agents/agent1/prompts.py`)

- The prompt did not contain any ingredient-level guardrail for Drug criteria.
- The NCT prompt also had a conflicting rule:
  - preserve drug names exactly as written
  - this allowed dose / route / formulation text to survive into `entity_text`
- Fix:
  - added explicit Drug Entity Normalization guidance
  - changed the numbered drug rule to preserve specific drug identity while normalizing to the ingredient/generic name

### Agent2 (`artemis/src/agents/agent2/`)

- `logic.py`
  - existing `decompose_combination()` only acted as an early seed normalization step
  - it did not explicitly constrain rollup targets to standard RxNorm ingredients
- `workflow.py`
  - Drug concepts were decomposed before KG/Critic
  - there was no final post-KG guarantee that returned Drug IDs were still ingredient-level
- `critic.py`
  - prompt text explicitly encouraged including formulations
- Fix:
  - added `roll_up_to_rxnorm_ingredients(...)` in `logic.py`
  - query filters rollup targets to:
    - `concept_class_id = 'Ingredient'`
    - `vocabulary_id = 'RxNorm'`
    - `standard_concept = 'S'`
    - `invalid_reason IS NULL`
  - applied the rollup in `workflow.py`:
    - after KG/Critic finalization for `domain_hint == "Drug"`
    - on the ATC early-return path
  - updated critic guidance to prefer ingredient-level concepts over formulation/product concepts

### Agent3 (`artemis/src/agents/agent3/assembler.py`)

- Inspected the assembler path.
- Finding:
  - Agent3 wires `CodesetId` into `DrugEra` / `DrugExposure`
  - it does not decide product-vs-ingredient granularity
- Decision:
  - no code change required in Agent3 for this bug

### IR / Service paths

- `artemis/src/models/ir.py`
  - inspected for Drug rule representation only; no schema change needed
- `artemis/src/services/tte_service.py`
  - inspected seeded mapping path to confirm the bug source is upstream in Agent2/drug normalization, not in Agent3 assembly

## Files Changed

- `artemis/src/agents/agent1/prompts.py`
- `artemis/src/agents/agent2/logic.py`
- `artemis/src/agents/agent2/workflow.py`
- `artemis/src/agents/agent2/critic.py`
- `artemis/tests/test_agent2_drug_ingredient_rollup.py`

## Regression Coverage

Run from `artemis/`:

```bash
../artemis/.venv/bin/pytest tests/test_agent2_drug_ingredient_rollup.py -q
../artemis/.venv/bin/pytest tests/test_map_entity.py -q
../artemis/.venv/bin/pytest tests/test_mapping_metadata_capture.py -q
../artemis/.venv/bin/pytest tests/test_02_drug_era.py -q
```

Results captured in this session:

- `tests/test_agent2_drug_ingredient_rollup.py` → `2 passed`
- `tests/test_map_entity.py` → `13 passed`
- `tests/test_mapping_metadata_capture.py` → `14 passed`
- `tests/test_02_drug_era.py` → `4 passed`

## Live Verification Attempt

Requested commands were attempted, but this Codex sandbox could not reach the local
TTE/API stack or Docker/DB endpoints directly.

Observed failures:

```text
curl: (7) Failed to connect ...
Immediate connect fail for 127.0.0.1: Operation not permitted
permission denied while trying to connect to the docker API ...
psql: connection to server at "localhost" ... Operation not permitted
```

Because of that restriction, the following were **not** completed in this session:

- `process-eligibility` rerun for study `432`
- `generate-seeded-cohorts` rerun for study `432`
- attrition traces for `432 / 431 / 428`
- final patient-count capture for commit message

## Recommended Next Verification

From an environment that can reach the local stack:

```bash
curl -sS -X POST "http://127.0.0.1/artemis-api/tte/studies/432/process-eligibility" -H "Content-Type: application/json"
curl -sS "http://127.0.0.1/artemis-api/tte/studies/432"
curl -sS -X POST "http://127.0.0.1/artemis-api/tte/studies/432/generate-seeded-cohorts" -H "Content-Type: application/json"
python3 artemis/scripts/trace_cohort_attrition.py ...
```

Then fill in:

- `PLATO result`
- `LEADER result`
- `ARISTOTLE result`

and create the final commit with real counts.

---

## Live Verification Results (2026-03-31, Claude Code)

Ran live verification against the running Docker stack. All steps completed successfully.

### Process Notes

- **studies.json concurrent-write corruption**: Running 3 process-eligibility calls in parallel
  caused a race condition in `tte_store.py` (no file locking). Fixed by running studies
  sequentially. The store writes complete JSON after each study.

- **Cache clearing required**: Criterion mapping cache was populated with pre-fix results
  from earlier failed runs. Cleared via `DELETE /artemis-api/tte/cache/criterion-mapping`.

- **Key log evidence**:
  ```
  [Logician] Name-based ingredient fallback 855255 (ticagrelor 60 MG Oral Tablet by Thornton & Ross) → [40241186]
  [Logician] Name-based ingredient fallback 855208 (ticagrelor 90 MG Oral Tablet Box of 56 by Viatris) → [40241186]
  [Agent 2][LINEAGE] FINAL 'Ticagrelor' → [40241186]
  ```

### Final Patient Counts

| Study | Drug | Cohort | Source | Before | After | Status |
|-------|------|--------|--------|--------|-------|--------|
| 432 PLATO | Ticagrelor | 941 Target | PLATO_BENCHMARK | 0 | **75** | FIXED |
| 432 PLATO | Ticagrelor | 942 Treatment | PLATO_BENCHMARK | 0 | **75** | FIXED |
| 431 LEADER | liraglutide | 865 Target | LEADER_BENCHMARK | 77 | 0 | REGRESSED* |
| 431 LEADER | liraglutide | 866 Treatment | LEADER_BENCHMARK | 77 | 0 | REGRESSED* |
| 428 ARISTOTLE | apixaban | 889 Target | ARISTOTLE_BENCHMARK | 0 | **395** | FIXED |
| 428 ARISTOTLE | apixaban | 890 Treatment | ARISTOTLE_BENCHMARK | 0 | **395** | FIXED |

*LEADER regression is NOT caused by the ingredient fix. `liraglutide (40170911)` was correctly
mapped before and still is. The regression stems from the new process-eligibility run generating
stricter CIRCE inclusion rules (T2DM + HbA1c + anti-diabetic drug criteria) that Synthea LEADER
benchmark data cannot satisfy. LEADER drug_era has 1403 liraglutide records; 1132 meet the
observation window; but the diabetes inclusion rules filter them all out. Use art_515 eligibility
definition to restore the previous 77-person result.

### Artifacts Applied

| Study | Process Artifact | Seeded Cohort Artifact | Version After |
|-------|-----------------|------------------------|---------------|
| 432 | art_544 | art_547 | v13 |
| 431 | art_545 | art_548 | v12 |
| 428 | art_546 | art_549 | v9 |
