BEGIN;

-- ============================================================
-- Inject 1,000 AF-only patients into ARISTOTLE CDM
-- INJECTED_ID_BASE = 100,000,000 for person/obs_period
-- condition_occurrence starts at 100,100,000 (above max 100,001,833)
-- ============================================================

-- 1. Insert 1,000 persons
INSERT INTO synthea_cdm_aristotle.person (
  person_id, gender_concept_id, year_of_birth, month_of_birth, day_of_birth,
  birth_datetime, race_concept_id, ethnicity_concept_id,
  location_id, provider_id, care_site_id,
  person_source_value, gender_source_value,
  gender_source_concept_id, race_source_value, race_source_concept_id,
  ethnicity_source_value, ethnicity_source_concept_id
)
SELECT
  100000000 + g AS person_id,
  CASE WHEN g % 2 = 0 THEN 8507 ELSE 8532 END AS gender_concept_id,
  1941 + (g * 37 + g / 7) % 68 AS year_of_birth,
  1 + g % 12 AS month_of_birth,
  1 + g % 28 AS day_of_birth,
  make_timestamp(
    1941 + (g * 37 + g / 7) % 68,
    1 + g % 12,
    1 + g % 28,
    0, 0, 0
  ) AS birth_datetime,
  CASE
    WHEN g % 20 < 15 THEN 8527
    WHEN g % 20 < 17 THEN 8516
    WHEN g % 20 < 19 THEN 8515
    ELSE 0
  END AS race_concept_id,
  CASE WHEN g % 20 < 17 THEN 38003564 ELSE 38003563 END AS ethnicity_concept_id,
  NULL, NULL, NULL,
  'INJECTED_AF_COMPARATOR_' || g AS person_source_value,
  CASE WHEN g % 2 = 0 THEN 'M' ELSE 'F' END AS gender_source_value,
  0,
  CASE
    WHEN g % 20 < 15 THEN 'white'
    WHEN g % 20 < 17 THEN 'black'
    WHEN g % 20 < 19 THEN 'asian'
    ELSE 'other'
  END AS race_source_value,
  0,
  CASE WHEN g % 20 < 17 THEN 'nonhispanic' ELSE 'hispanic' END AS ethnicity_source_value,
  0
FROM generate_series(1, 1000) AS g;

-- 2. Insert observation_periods
INSERT INTO synthea_cdm_aristotle.observation_period (
  observation_period_id, person_id,
  observation_period_start_date, observation_period_end_date,
  period_type_concept_id
)
SELECT
  100000000 + g AS observation_period_id,
  100000000 + g AS person_id,
  ('2010-01-01'::date + ((g * 41) % 2922)::int) AS observation_period_start_date,
  ('2025-06-01'::date + (g % 274)::int) AS observation_period_end_date,
  32882 AS period_type_concept_id
FROM generate_series(1, 1000) AS g;

-- 3. Insert condition_occurrence for AF (313217)
INSERT INTO synthea_cdm_aristotle.condition_occurrence (
  condition_occurrence_id, person_id,
  condition_concept_id, condition_start_date, condition_start_datetime,
  condition_end_date, condition_end_datetime,
  condition_type_concept_id, condition_status_concept_id,
  stop_reason, provider_id, visit_occurrence_id, visit_detail_id,
  condition_source_value, condition_source_concept_id, condition_status_source_value
)
SELECT
  100100000 + g AS condition_occurrence_id,
  100000000 + g AS person_id,
  313217 AS condition_concept_id,
  ('2024-06-01'::date + (g % 550)::int) AS condition_start_date,
  make_timestamp(2024, 6, 1, 0, 0, 0) + ((g % 550)::int || ' days')::interval AS condition_start_datetime,
  ('2024-06-01'::date + (g % 550)::int + 1) AS condition_end_date,
  make_timestamp(2024, 6, 1, 0, 0, 0) + (((g % 550) + 1)::int || ' days')::interval AS condition_end_datetime,
  32827 AS condition_type_concept_id,
  0 AS condition_status_concept_id,
  NULL, NULL, NULL, NULL,
  '49436004' AS condition_source_value,
  313217 AS condition_source_concept_id,
  NULL
FROM generate_series(1, 1000) AS g;

COMMIT;
