# Synthea Regeneration & Analysis Fix Handoff — 2026-03-31

## 한 줄 요약
comparator fix 완료, Synthea CDM 재생성 백그라운드 진행 중 (CV event 없어서 HR=1.0 문제 해결 목적).

---

## 오늘 완료된 작업

### 코드 수정 (커밋됨)

| 커밋 | 내용 |
|------|------|
| `087e5b9` | OMOPConnector: localhost 하드코딩 → DATABASE_URL env var |
| `fc15c34` | `build_analysis_dataset_from_generated_cohorts`: `comparator_ref=None`이면 CDM 전체 person - treatment로 REST comparator 구성 |
| `8ae7f38` | `_run_agent5_analysis_wrapper`: post-PSM n_target/n_comparator Agent5 output 기반 |
| `83b4b3c` | n_target/n_comparator = 원래 투입 코호트 크기, matchedPairs = PSM 매칭 결과 별도 |

### 테스트
- `artemis/tests/analysis/test_omop_connector_rest_comparator.py` — 4개 TDD 케이스 GREEN
- 기존 22개 tests 모두 통과

### 백업 완료
위치: `artemis/data/backups/`
```
synthea_cdm_leader_20260331.sql     2.5GB
synthya_cdm_plato_20260331.sql      2.5GB
synthea_cdm_aristotle_20260331.sql  2.5GB
backup_synthea_cdm_leader_results.sql   4.9MB
backup_synthea_cdm_plato_results.sql    505KB
backup_synthea_cdm_aristotle_results.sql 1.4MB
```

---

## 현재 진행 중 (백그라운드 에이전트 `a2ca03f68f6626d9d`)

1. ✅ CDM 3개 백업 완료
2. ✅ results schema 3개 백업 완료
3. 🔄 WebAPI 불필요 코호트 삭제 (217개 cohort_definition_id 중 현재 3개 스터디에서 사용 중인 것만 유지)
4. 🔄 Synthea 재생성 (`setup_study_benchmarks.sh all`)
5. ⏳ WebAPI 캐시 클리어 후 재실행

에이전트 완료 후: `SendMessage(to: 'a2ca03f68f6626d9d')` 또는 완료 알림 확인.

---

## 근본 원인 (오늘 발견)

### comparator_n=0 문제
```
현재: comparator = CIRCE cohort(target - treatment) = 0명
수정: comparator_ref.personCount==0이면 comparator_ref=None
      → omop_connector에서 CDM 전체 person - treatment = REST population
```

### HR=1.0 문제
```
원인 1: outcome cohort의 cohort_start_date ≤ treatment index_date
        → extract_outcome_from_cohort에서 event_date > index_date 실패 → event=0

원인 2: Synthea 합성 데이터에 cardiovascular event (MI/stroke/death)가 거의 없음
        → PSM matched 10쌍 중 outcome event 보유자 0명

임시 대응: condition_occurrence 테이블에 MI event(concept_id=4329847) SQL 직접 주입
          → 그러나 REST comparator의 index_date 기준 타이밍 문제로 comparatorEvents=0 지속

근본 해결: Synthea 재생성 (현재 진행 중)
```

### n_target=10 문제 (수정됨)
```
잘못: workflow_result.get("n_target") = PSM matched pairs = 10
수정: dataset_treatment_n = 원래 투입 환자 수 = 75
      matchedPairs = 10 (별도 필드)
```

---

## 현재 스터디 상태

| 스터디 | ID | sourceKey | n_target | n_comparator | matchedPairs | HR | 상태 |
|--------|-----|-----------|----------|--------------|--------------|-----|------|
| LEADER | 431 | LEADER_BENCHMARK | 387 | 2,875 | - | 3.23 | ✅ (IPTW, 이전 세션) |
| PLATO | 432 | PLATO_BENCHMARK | 75 | 9,925 | 10 | 1.0 | ⚠️ events=0 |
| ARISTOTLE | 424 | ARISTOTLE_BENCHMARK | 395 | 9,605 | 55 | 1.0 | ⚠️ events=0 |

LEADER는 이미 유의미한 HR=3.23 (Synthea liraglutide 사용자에 high CV risk 시뮬레이션됨).
PLATO/ARISTOTLE은 Synthea 재생성 후 재분석 필요.

---

## 다음 세션 TODO

### P0: Synthea 재생성 완료 확인
```bash
# 에이전트 완료 확인
tail -c 2000 "/private/tmp/claude-501/.../tasks/a2ca03f68f6626d9d.output"

# 재생성 후 각 CDM person count 확인
docker exec broadsea-atlasdb psql -U postgres -d postgres -c "
SELECT schemaname, COUNT(*) as person_count
FROM (
  SELECT 'leader' as schemaname, person_id FROM synthea_cdm_leader.person
  UNION ALL SELECT 'plato', person_id FROM synthea_cdm_plato.person
  UNION ALL SELECT 'aristotle', person_id FROM synthea_cdm_aristotle.person
) t GROUP BY 1;
"
```

### P1: 재생성된 데이터로 condition_occurrence 확인
```bash
# CV event 존재 여부 확인
docker exec broadsea-atlasdb psql -U postgres -d postgres -c "
SELECT COUNT(*) as mi_count
FROM synthea_cdm_leader.condition_occurrence
WHERE condition_concept_id = 4329847;  -- Myocardial infarction
"
```

### P2: WebAPI 캐시 클리어 후 3개 스터디 재실행
```bash
# 캐시 클리어
docker exec broadsea-atlasdb psql -U postgres -d postgres -c "
DELETE FROM webapi.generation_cache
WHERE type = 'COHORT'
  AND source_id IN (
    SELECT source_id FROM webapi.source
    WHERE source_key IN ('LEADER_BENCHMARK','PLATO_BENCHMARK','ARISTOTLE_BENCHMARK')
  );
"

# 각 스터디 validate → execute → apply → run-analysis
for id in 431 432 424; do
  curl -s -X POST "http://localhost/artemis-api/tte/studies/$id/validate"
done
```

### P3: Gold 비교
재생성 데이터로 의미있는 HR 나오면 Gold JSON과 비교:
```
artemis/data/gold/{LEADER,PLATO,ARISTOTLE}/
```

---

## 인프라 상태

- artemis-api: 정상 실행 중 (`477b3f1664ed_artemis-api`)
- broadsea-atlasdb: 정상 (`broadsea-atlasdb`)
- 코드: `fix/agent1-pattern-e-or-logic` 브랜치, 아직 미푸시

## 참고 커밋 이력
```
83b4b3c fix(analysis): treatment_vs_rest uses CDM REST population as comparator
8ae7f38 fix(analysis): use post-PSM/IPTW n_target/n_comparator from Agent5 output
fc15c34 fix(analysis): use CDM REST population as comparator in treatment_vs_rest mode
087e5b9 fix(analysis): use DATABASE_URL env var in OMOPConnector default connection
```
