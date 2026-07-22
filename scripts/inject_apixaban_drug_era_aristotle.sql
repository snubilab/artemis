-- inject_apixaban_drug_era_aristotle.sql
-- Inject apixaban drug_era + drug_exposure for ~800 AF patients who have NO drug records.
-- Uses INJECTED_ID_BASE = 100_000_000 to avoid collision (max existing drug_era_id ~ 5885).
--
-- Apixaban concept_id: 43013024
-- Drug type concept_id: 32838 (EHR prescription)
-- Pattern: 7-day duration, exposure_count=1, gap_days=0

BEGIN;

-- Materialize the ~800 AF patients without any drug_era, with their AF diagnosis date
CREATE TEMP TABLE _af_no_drug AS
SELECT
    p.person_id,
    MIN(co.condition_start_date) AS first_af_date,
    op.observation_period_start_date,
    op.observation_period_end_date
FROM synthea_cdm_aristotle.person p
JOIN synthea_cdm_aristotle.condition_occurrence co
    ON co.person_id = p.person_id
JOIN omop_vocab.concept_ancestor ca
    ON ca.descendant_concept_id = co.condition_concept_id
JOIN synthea_cdm_aristotle.observation_period op
    ON op.person_id = p.person_id
WHERE ca.ancestor_concept_id IN (313217, 314665)  -- AF / Atrial flutter
  AND p.person_id NOT IN (SELECT person_id FROM synthea_cdm_aristotle.drug_era)
GROUP BY p.person_id, op.observation_period_start_date, op.observation_period_end_date;

-- Assign row numbers and compute injection dates
-- drug_era_start = first_af_date + 1..30 days (deterministic via person_id mod)
-- drug_era_end   = start + 7 days (matching existing pattern)
-- Select 800 patients ordered by person_id for reproducibility
CREATE TEMP TABLE _inject AS
SELECT
    person_id,
    100000000 + ROW_NUMBER() OVER (ORDER BY person_id) AS new_id,
    first_af_date + ((person_id % 30) + 1) AS drug_start_date,
    first_af_date + ((person_id % 30) + 1) + 7 AS drug_end_date
FROM _af_no_drug
ORDER BY person_id
LIMIT 800;

-- Ensure drug dates fall within observation period
-- (first_af_date is always within obs period, +38 days max should be fine,
--  but clip just in case)
UPDATE _inject i
SET drug_end_date = LEAST(
    i.drug_end_date,
    (SELECT op.observation_period_end_date
     FROM synthea_cdm_aristotle.observation_period op
     WHERE op.person_id = i.person_id
     LIMIT 1)
);

-- Insert into drug_exposure
INSERT INTO synthea_cdm_aristotle.drug_exposure (
    drug_exposure_id,
    person_id,
    drug_concept_id,
    drug_exposure_start_date,
    drug_exposure_start_datetime,
    drug_exposure_end_date,
    drug_exposure_end_datetime,
    verbatim_end_date,
    drug_type_concept_id,
    stop_reason,
    refills,
    quantity,
    days_supply,
    sig,
    route_concept_id,
    lot_number,
    provider_id,
    visit_occurrence_id,
    visit_detail_id,
    drug_source_value,
    drug_source_concept_id,
    route_source_value,
    dose_unit_source_value
)
SELECT
    new_id::int,
    person_id::int,
    43013024,                              -- apixaban
    drug_start_date,
    drug_start_date::timestamp,
    drug_end_date,
    drug_end_date::timestamp,
    drug_end_date,                         -- verbatim_end_date
    32838,                                 -- EHR prescription
    '',                                    -- stop_reason
    0,                                     -- refills
    0,                                     -- quantity
    (drug_end_date - drug_start_date),     -- days_supply
    '',                                    -- sig
    0,                                     -- route_concept_id
    '0',                                   -- lot_number
    0,                                     -- provider_id (dummy)
    NULL,                                  -- visit_occurrence_id
    NULL,                                  -- visit_detail_id
    '1364430',                             -- drug_source_value (apixaban NDC)
    43013024,                              -- drug_source_concept_id
    '',                                    -- route_source_value
    ''                                     -- dose_unit_source_value
FROM _inject;

-- Insert into drug_era
INSERT INTO synthea_cdm_aristotle.drug_era (
    drug_era_id,
    person_id,
    drug_concept_id,
    drug_era_start_date,
    drug_era_end_date,
    drug_exposure_count,
    gap_days
)
SELECT
    new_id::int,
    person_id::int,
    43013024,                              -- apixaban
    drug_start_date,
    drug_end_date,
    1,                                     -- drug_exposure_count
    0                                      -- gap_days
FROM _inject;

-- Cleanup temp tables
DROP TABLE _af_no_drug;
DROP TABLE _inject;

COMMIT;
