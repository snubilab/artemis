-- 아주대 0/6 원인 판별용 집계 쿼리
-- 전부 집계값만 반환하며, 환자 단위 행은 사이트를 떠나지 않는다.
-- @cdm 을 아주대 CDM 스키마 이름으로 바꿔서 실행.

-- ── Q0. 어떤 vocabulary 버전인가 (descendant 해석이 우리 쪽과 같은지)
SELECT vocabulary_id, vocabulary_version
FROM @cdm.vocabulary
WHERE vocabulary_id IN ('None','SNOMED','RxNorm','LOINC','UCUM');

-- ── Q1. drug_era 가 채워져 있는가  ★ 4개 코호트(treatment arm 전부 + CAROLINA comparator)의 entry event
--   0 이면 그 4개는 기준이 아무리 정확해도 0명이다.
SELECT 'drug_era'    AS tbl, COUNT(*) AS rows FROM @cdm.drug_era
UNION ALL SELECT 'condition_era', COUNT(*) FROM @cdm.condition_era
UNION ALL SELECT 'drug_exposure', COUNT(*) FROM @cdm.drug_exposure;

-- ── Q2. entry event 별 인원수
--   201826 = Type 2 diabetes mellitus (comparator arm 2개의 entry)
SELECT 'T2DM condition_occurrence' AS entry, COUNT(DISTINCT co.person_id) AS persons
FROM @cdm.condition_occurrence co
JOIN @cdm.concept_ancestor ca ON ca.descendant_concept_id = co.condition_concept_id
WHERE ca.ancestor_concept_id IN (201826, 44793113)
UNION ALL
-- 40239216 linagliptin / 45774751 empagliflozin / 1597756 glimepiride
SELECT 'linagliptin drug_era', COUNT(DISTINCT de.person_id)
FROM @cdm.drug_era de
JOIN @cdm.concept_ancestor ca ON ca.descendant_concept_id = de.drug_concept_id
WHERE ca.ancestor_concept_id = 40239216
UNION ALL
SELECT 'empagliflozin drug_era', COUNT(DISTINCT de.person_id)
FROM @cdm.drug_era de
JOIN @cdm.concept_ancestor ca ON ca.descendant_concept_id = de.drug_concept_id
WHERE ca.ancestor_concept_id = 45774751
UNION ALL
SELECT 'glimepiride drug_era', COUNT(DISTINCT de.person_id)
FROM @cdm.drug_era de
JOIN @cdm.concept_ancestor ca ON ca.descendant_concept_id = de.drug_concept_id
WHERE ca.ancestor_concept_id = 1597756;

-- ── Q3. HbA1c 단위  ★ 6개 코호트 전부가 통과해야 하는 유일한 공통 규칙
--   우리 정의는 unit_concept_id = 8554 (percent) 를 요구한다.
--   unit_concept_id 가 NULL 이거나 다른 값이면 그 규칙은 0명을 반환하고,
--   inclusion rule 은 AND 로 묶이므로 코호트 전체가 0이 된다.
SELECT COALESCE(CAST(m.unit_concept_id AS VARCHAR),'NULL') AS unit_concept_id,
       c.concept_name                                     AS unit_name,
       COUNT(*)                        AS measurements,
       COUNT(DISTINCT m.person_id)     AS persons,
       SUM(CASE WHEN m.value_as_number IS NOT NULL THEN 1 ELSE 0 END) AS with_value
FROM @cdm.measurement m
LEFT JOIN @cdm.concept c ON c.concept_id = m.unit_concept_id
WHERE m.measurement_concept_id IN (3004410, 3005446, 3007263, 3034639, 4197971, 44793001)
GROUP BY m.unit_concept_id, c.concept_name
ORDER BY measurements DESC;

-- ── Q4. HbA1c 7.0~10.0 % 를 실제로 만족하는 인원 (단위 조건 있음 / 없음 대조)
SELECT 'unit=8554 요구' AS variant, COUNT(DISTINCT person_id) AS persons
FROM @cdm.measurement
WHERE measurement_concept_id IN (3004410,3005446,3007263,3034639,4197971,44793001)
  AND value_as_number BETWEEN 7.0 AND 10.0
  AND unit_concept_id = 8554
UNION ALL
SELECT '단위 조건 없음', COUNT(DISTINCT person_id)
FROM @cdm.measurement
WHERE measurement_concept_id IN (3004410,3005446,3007263,3034639,4197971,44793001)
  AND value_as_number BETWEEN 7.0 AND 10.0;

-- ── Q5. BMI 단위 (CAROLINA 의 presence 규칙)
SELECT COALESCE(CAST(unit_concept_id AS VARCHAR),'NULL') AS unit_concept_id,
       COUNT(*) AS measurements, COUNT(DISTINCT person_id) AS persons
FROM @cdm.measurement
WHERE measurement_concept_id IN (3038553, 36304833, 40762636)
GROUP BY unit_concept_id ORDER BY measurements DESC;

-- ── Q6. range_high 가 채워져 있는가 (ALT/AST/ALP 의 x ULN 배제 규칙이 읽는 컬럼)
--   비어 있어도 코호트를 0으로 만들지는 않는다(배제 규칙이 그냥 통과) — 정확도 확인용.
SELECT COUNT(*) AS measurements,
       SUM(CASE WHEN range_high IS NOT NULL THEN 1 ELSE 0 END) AS with_range_high
FROM @cdm.measurement;

-- ── Q7. observation_period 가 entry 앞 365일을 덮는가
--   우리 정의는 PriorDays = 365 를 요구한다.
SELECT COUNT(DISTINCT person_id) AS persons,
       AVG(DATEDIFF(day, observation_period_start_date, observation_period_end_date)) AS avg_days
FROM @cdm.observation_period;
