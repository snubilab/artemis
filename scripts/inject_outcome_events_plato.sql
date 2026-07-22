-- PLATO: Inject incident outcome events (Acute MI, concept 312327)
-- Treatment (ticagrelor 40241186): ~10% event rate
-- Comparator (ACS without ticagrelor): ~14% event rate
-- Real trial HR ≈ 0.84 (ticagrelor protective)

BEGIN;

-- Clean up any previous outcome injections (ID >= 200_000_000)
DELETE FROM synthea_cdm_plato.condition_occurrence
WHERE condition_occurrence_id >= 200000000;

-- Treatment arm: ticagrelor patients, ~10% get outcome event
WITH treatment_patients AS (
    SELECT DISTINCT ON (person_id)
        person_id,
        drug_era_start_date AS index_date
    FROM synthea_cdm_plato.drug_era
    WHERE drug_concept_id = 40241186
    ORDER BY person_id, drug_era_start_date
),
treatment_selected AS (
    SELECT person_id, index_date,
           ROW_NUMBER() OVER (ORDER BY random()) AS rn,
           COUNT(*) OVER () AS total
    FROM treatment_patients
),
treatment_events AS (
    SELECT person_id, index_date
    FROM treatment_selected
    WHERE rn <= CEIL(total * 0.10)  -- 10% event rate
)
INSERT INTO synthea_cdm_plato.condition_occurrence (
    condition_occurrence_id,
    person_id,
    condition_concept_id,
    condition_start_date,
    condition_start_datetime,
    condition_end_date,
    condition_end_datetime,
    condition_type_concept_id,
    condition_status_concept_id,
    stop_reason,
    provider_id,
    visit_occurrence_id,
    visit_detail_id,
    condition_source_value,
    condition_source_concept_id,
    condition_status_source_value
)
SELECT
    200000000 + ROW_NUMBER() OVER (ORDER BY person_id) AS condition_occurrence_id,
    person_id,
    312327,  -- Acute MI
    (index_date + (30 + floor(random() * 336))::int)::date,
    (index_date + (30 + floor(random() * 336))::int)::date + TIME '12:00:00',
    (index_date + (30 + floor(random() * 336))::int + 1)::date,
    (index_date + (30 + floor(random() * 336))::int + 1)::date + TIME '12:00:00',
    32817,  -- EHR
    0,
    NULL, NULL, NULL, NULL,
    'INJECTED_OUTCOME_PLATO_TX',
    0,
    NULL
FROM treatment_events;

-- Comparator arm: ACS patients (312327 or 4329847) without ticagrelor, ~14% get outcome
WITH comparator_patients AS (
    SELECT DISTINCT ON (co.person_id)
        co.person_id,
        co.condition_start_date AS index_date
    FROM synthea_cdm_plato.condition_occurrence co
    WHERE co.condition_concept_id IN (312327, 4329847)
      AND co.person_id NOT IN (
          SELECT person_id FROM synthea_cdm_plato.drug_era WHERE drug_concept_id = 40241186
      )
      AND co.condition_occurrence_id < 200000000  -- exclude injected records
    ORDER BY co.person_id, co.condition_start_date
),
comparator_selected AS (
    SELECT person_id, index_date,
           ROW_NUMBER() OVER (ORDER BY random()) AS rn,
           COUNT(*) OVER () AS total
    FROM comparator_patients
),
comparator_events AS (
    SELECT person_id, index_date
    FROM comparator_selected
    WHERE rn <= CEIL(total * 0.14)  -- 14% event rate
),
max_id AS (
    SELECT COALESCE(MAX(condition_occurrence_id), 200000000) AS max_val
    FROM synthea_cdm_plato.condition_occurrence
    WHERE condition_occurrence_id >= 200000000
)
INSERT INTO synthea_cdm_plato.condition_occurrence (
    condition_occurrence_id,
    person_id,
    condition_concept_id,
    condition_start_date,
    condition_start_datetime,
    condition_end_date,
    condition_end_datetime,
    condition_type_concept_id,
    condition_status_concept_id,
    stop_reason,
    provider_id,
    visit_occurrence_id,
    visit_detail_id,
    condition_source_value,
    condition_source_concept_id,
    condition_status_source_value
)
SELECT
    m.max_val + ROW_NUMBER() OVER (ORDER BY ce.person_id) AS condition_occurrence_id,
    ce.person_id,
    312327,  -- Acute MI
    (ce.index_date + (30 + floor(random() * 336))::int)::date,
    (ce.index_date + (30 + floor(random() * 336))::int)::date + TIME '12:00:00',
    (ce.index_date + (30 + floor(random() * 336))::int + 1)::date,
    (ce.index_date + (30 + floor(random() * 336))::int + 1)::date + TIME '12:00:00',
    32817,  -- EHR
    0,
    NULL, NULL, NULL, NULL,
    'INJECTED_OUTCOME_PLATO_CMP',
    0,
    NULL
FROM comparator_events ce, max_id m;

-- Verify
SELECT
    condition_source_value AS arm,
    COUNT(*) AS events
FROM synthea_cdm_plato.condition_occurrence
WHERE condition_occurrence_id >= 200000000
GROUP BY condition_source_value;

COMMIT;
