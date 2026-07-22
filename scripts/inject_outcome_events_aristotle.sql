-- ARISTOTLE: Inject incident outcome events (Cerebral infarction, concept 443454)
-- Treatment (apixaban 43013024): ~8% event rate
-- Comparator (AF without apixaban): ~12% event rate
-- Real trial HR ≈ 0.79 (apixaban protective)

BEGIN;

-- Clean up any previous outcome injections (ID >= 200_000_000)
DELETE FROM synthea_cdm_aristotle.condition_occurrence
WHERE condition_occurrence_id >= 200000000;

-- Treatment arm: apixaban patients, ~8% get outcome event
WITH treatment_patients AS (
    SELECT DISTINCT ON (person_id)
        person_id,
        drug_era_start_date AS index_date
    FROM synthea_cdm_aristotle.drug_era
    WHERE drug_concept_id = 43013024
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
    WHERE rn <= CEIL(total * 0.08)  -- 8% event rate
)
INSERT INTO synthea_cdm_aristotle.condition_occurrence (
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
    443454,  -- Cerebral infarction (stroke)
    (index_date + (30 + floor(random() * 336))::int)::date,
    (index_date + (30 + floor(random() * 336))::int)::date + TIME '12:00:00',
    (index_date + (30 + floor(random() * 336))::int + 1)::date,
    (index_date + (30 + floor(random() * 336))::int + 1)::date + TIME '12:00:00',
    32817,  -- EHR
    0,
    NULL, NULL, NULL, NULL,
    'INJECTED_OUTCOME_ARISTOTLE_TX',
    0,
    NULL
FROM treatment_events;

-- Comparator arm: AF patients (313217) without apixaban, ~12% get outcome
WITH comparator_patients AS (
    SELECT DISTINCT ON (co.person_id)
        co.person_id,
        co.condition_start_date AS index_date
    FROM synthea_cdm_aristotle.condition_occurrence co
    WHERE co.condition_concept_id = 313217
      AND co.person_id NOT IN (
          SELECT person_id FROM synthea_cdm_aristotle.drug_era WHERE drug_concept_id = 43013024
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
    WHERE rn <= CEIL(total * 0.12)  -- 12% event rate
),
max_id AS (
    SELECT COALESCE(MAX(condition_occurrence_id), 200000000) AS max_val
    FROM synthea_cdm_aristotle.condition_occurrence
    WHERE condition_occurrence_id >= 200000000
)
INSERT INTO synthea_cdm_aristotle.condition_occurrence (
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
    443454,  -- Cerebral infarction (stroke)
    (ce.index_date + (30 + floor(random() * 336))::int)::date,
    (ce.index_date + (30 + floor(random() * 336))::int)::date + TIME '12:00:00',
    (ce.index_date + (30 + floor(random() * 336))::int + 1)::date,
    (ce.index_date + (30 + floor(random() * 336))::int + 1)::date + TIME '12:00:00',
    32817,  -- EHR
    0,
    NULL, NULL, NULL, NULL,
    'INJECTED_OUTCOME_ARISTOTLE_CMP',
    0,
    NULL
FROM comparator_events ce, max_id m;

-- Verify
SELECT
    condition_source_value AS arm,
    COUNT(*) AS events
FROM synthea_cdm_aristotle.condition_occurrence
WHERE condition_occurrence_id >= 200000000
GROUP BY condition_source_value;

COMMIT;
