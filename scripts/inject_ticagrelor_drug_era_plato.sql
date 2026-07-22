-- Inject ticagrelor drug_era records for ACS patients without ticagrelor in PLATO CDM
-- Purpose: Increase treatment pool for E2E benchmark
-- Existing pattern: drug_concept_id=40241186, 30-day duration, exposure_count=1, gap_days=0
-- ID base: 100_000_000 (existing max ~300M, use 400M+ to avoid collision)

BEGIN;

-- Insert ~800 ticagrelor drug_era records for randomly selected ACS patients
-- who currently have NO ticagrelor exposure
WITH acs_no_tica AS (
    SELECT DISTINCT co.person_id,
           MIN(co.condition_start_date) AS first_acs_date
    FROM synthea_cdm_plato.condition_occurrence co
    JOIN omop_vocab.concept_ancestor ca
        ON ca.descendant_concept_id = co.condition_concept_id
    WHERE ca.ancestor_concept_id IN (312327, 314666, 315296, 434376, 438170, 444406)
      AND co.person_id NOT IN (
          SELECT DISTINCT de.person_id
          FROM synthea_cdm_plato.drug_era de
          WHERE de.drug_concept_id = 40241186
      )
    GROUP BY co.person_id
),
candidates AS (
    SELECT person_id,
           first_acs_date,
           ROW_NUMBER() OVER (ORDER BY random()) AS rn
    FROM acs_no_tica
)
INSERT INTO synthea_cdm_plato.drug_era
    (drug_era_id, person_id, drug_concept_id, drug_era_start_date, drug_era_end_date, drug_exposure_count, gap_days)
SELECT
    400000000 + rn AS drug_era_id,
    person_id,
    40241186 AS drug_concept_id,
    first_acs_date AS drug_era_start_date,
    first_acs_date + INTERVAL '30 days' AS drug_era_end_date,
    1 AS drug_exposure_count,
    0 AS gap_days
FROM candidates
WHERE rn <= 800;

COMMIT;
