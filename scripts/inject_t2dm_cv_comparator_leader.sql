-- inject_t2dm_cv_comparator_leader.sql
-- Inject ~800 T2DM+CV patients WITHOUT any drug_era into LEADER CDM
-- to increase the comparator pool for TTE analysis.
--
-- INJECTED_ID_BASE = 100_000_000 for person_id
-- condition_occurrence_id starts at 200_000_000
-- observation_period_id starts at 100_000_000
--
-- Each injected person gets:
--   - person record (age 50-80, mixed gender/race)
--   - observation_period (2010-2015 start, 2024-2025 end)
--   - T2DM condition (concept_id = 201826)
--   - Acute MI condition (concept_id = 312327, most common CV in this CDM)
--   - NO drug_era records

BEGIN;

-- ============================================================
-- 1. Insert 800 persons (IDs 100_000_001 .. 100_000_800)
-- ============================================================
INSERT INTO synthea_cdm_leader.person (
    person_id, gender_concept_id, year_of_birth, month_of_birth, day_of_birth,
    birth_datetime, race_concept_id, ethnicity_concept_id,
    location_id, provider_id, care_site_id,
    person_source_value, gender_source_value, gender_source_concept_id,
    race_source_value, race_source_concept_id,
    ethnicity_source_value, ethnicity_source_concept_id
)
SELECT
    100000000 + i                                AS person_id,
    CASE WHEN i % 2 = 0 THEN 8507 ELSE 8532 END AS gender_concept_id,  -- 50/50 M/F
    1946 + (i % 31)                              AS year_of_birth,      -- age 49-80 in 2026
    1 + (i % 12)                                 AS month_of_birth,
    1 + (i % 28)                                 AS day_of_birth,
    make_timestamp(1946 + (i % 31), 1 + (i % 12), 1 + (i % 28), 0, 0, 0) AS birth_datetime,
    -- Race distribution matching existing CDM (~74.5% White, 8.4% Hispanic, 7.2% Black, 5.4% Asian, 2.3% Other)
    CASE
        WHEN i % 100 < 75 THEN 8527   -- White
        WHEN i % 100 < 83 THEN 8516   -- Black
        WHEN i % 100 < 89 THEN 8515   -- Asian
        ELSE 0                          -- Unknown/Other
    END                                          AS race_concept_id,
    CASE
        WHEN i % 100 >= 75 AND i % 100 < 83 THEN 38003563  -- Hispanic
        ELSE 38003564                                        -- Not Hispanic
    END                                          AS ethnicity_concept_id,
    NULL, NULL, NULL,
    'INJECTED_COMPARATOR_' || i,
    CASE WHEN i % 2 = 0 THEN 'M' ELSE 'F' END,
    0, NULL, 0, NULL, 0
FROM generate_series(1, 800) AS s(i);

-- ============================================================
-- 2. Insert observation_period for each person
-- ============================================================
INSERT INTO synthea_cdm_leader.observation_period (
    observation_period_id, person_id,
    observation_period_start_date, observation_period_end_date,
    period_type_concept_id
)
SELECT
    100000000 + i                                AS observation_period_id,
    100000000 + i                                AS person_id,
    ('2010-01-01'::date + (i % 1826 || ' days')::interval)::date AS observation_period_start_date,  -- 2010-2014
    ('2024-06-01'::date + (i % 365  || ' days')::interval)::date AS observation_period_end_date,    -- 2024-2025
    32827                                        AS period_type_concept_id  -- EHR
FROM generate_series(1, 800) AS s(i);

-- ============================================================
-- 3. Insert T2DM condition for each person
-- ============================================================
INSERT INTO synthea_cdm_leader.condition_occurrence (
    condition_occurrence_id, person_id, condition_concept_id,
    condition_start_date, condition_start_datetime,
    condition_end_date, condition_end_datetime,
    condition_type_concept_id, condition_status_concept_id,
    stop_reason, provider_id, visit_occurrence_id, visit_detail_id,
    condition_source_value, condition_source_concept_id,
    condition_status_source_value
)
SELECT
    200000000 + i                                AS condition_occurrence_id,
    100000000 + i                                AS person_id,
    201826                                       AS condition_concept_id,  -- Type 2 diabetes mellitus
    ('2011-01-01'::date + (i % 1461 || ' days')::interval)::date AS condition_start_date,  -- 2011-2014
    make_timestamp(2011 + (i % 4), 1 + (i % 12), 1 + (i % 28), 0, 0, 0) AS condition_start_datetime,
    NULL, NULL,
    32827, 0,
    NULL, NULL, NULL, NULL,
    '44054006', 0,  -- SNOMED source for T2DM
    NULL
FROM generate_series(1, 800) AS s(i);

-- ============================================================
-- 4. Insert Acute MI condition for each person
-- ============================================================
INSERT INTO synthea_cdm_leader.condition_occurrence (
    condition_occurrence_id, person_id, condition_concept_id,
    condition_start_date, condition_start_datetime,
    condition_end_date, condition_end_datetime,
    condition_type_concept_id, condition_status_concept_id,
    stop_reason, provider_id, visit_occurrence_id, visit_detail_id,
    condition_source_value, condition_source_concept_id,
    condition_status_source_value
)
SELECT
    200000800 + i                                AS condition_occurrence_id,
    100000000 + i                                AS person_id,
    312327                                       AS condition_concept_id,  -- Acute myocardial infarction
    ('2012-01-01'::date + (i % 1096 || ' days')::interval)::date AS condition_start_date,  -- 2012-2014
    make_timestamp(2012 + (i % 3), 1 + (i % 12), 1 + (i % 28), 0, 0, 0) AS condition_start_datetime,
    NULL, NULL,
    32827, 0,
    NULL, NULL, NULL, NULL,
    '57054005', 0,  -- SNOMED source for acute MI
    NULL
FROM generate_series(1, 800) AS s(i);

COMMIT;
