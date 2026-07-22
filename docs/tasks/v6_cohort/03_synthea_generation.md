# Task: 03_synthea_generation

## 1. Specification (Strict)
- Input: JSON module definitions for LEADER, PLATO, and ARISTOTLE trial eligibility.
- Output: 
  1. Synthea modules `artemis_leader.json`, `artemis_plato.json`, `artemis_aristotle.json`.
  2. Synthea CSV outputs.
  3. ETL to PostgreSQL `$SCHEMA` `synthea_cdm_benchmark`.
- Logic:
  1. Create Python script `scripts/generate_synthea_modules.py` to output valid Synthea GMF v2 JSONs:
     - LEADER: Age >= 50, CVD (MI), T2DM, HbA1c >= 7.0%.
     - PLATO: Age >= 18, Hospitalized for ACS / MI.
     - ARISTOTLE: Age >= 18, Atrial Fibrillation, Risk factors (e.g. prior stroke or Age >= 75).
  2. Put modules in `data/synthea/synthea/src/main/resources/modules/`.
  3. Synthesize using `./run_synthea -p 3000`.
  4. Load using `run_etl.R` or equivalent.

## 2. TDD Strategy
- [ ] Test Case A: JSON parses successfully in Synthea.
- [ ] Test Case B: Synthea output `patients.csv` has ~1000 targeted profiles.
- [ ] Test Case C: OMOP dataset `synthea_cdm_benchmark.person` successfully populated.

## 3. Implementation Log
- {Time}: Test Created (Fail)
- {Time}: Implementation Code Written
- {Time}: Test Passed / Failed (Log Error)

## 4. Final Status
- [PENDING]
