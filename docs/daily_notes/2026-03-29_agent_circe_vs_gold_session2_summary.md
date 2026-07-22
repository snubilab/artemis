# Agent CIRCE vs Gold LEADER — Session 2 Summary (2026-03-29)

## Goal
Agent가 생성한 CIRCE로 Gold LEADER(1222명)에 근사하는 코호트 추출

## Data
- LEADER_BENCHMARK: synthea_cdm_leader (10k persons, liraglutide 1403 drug_era)
- Gold CIRCE: 17 rules, 75 concept sets, final=1222
- Agent CIRCE: 18 rules, 79 concept sets

---

## Bugs Found & Fixed

### BUG-1: artemis/data/ Volume Mount Missing (FIXED)
- **Symptom**: Agent1이 supplement PDF를 읽지 못해 NCT 텍스트만 파싱
- **Cause**: compose/artemis-api.yml에 data/ 마운트 누락
- **Fix**: `- ../artemis/data:/app/data` 추가 + 컨테이너 재시작
- **Impact**: CV conditions 세분화 불가 → 수정 후 20 inc + 61 exc 정상 파싱

### BUG-2: HbA1c Concept Mapping Error (FIXED by SPEC-MAP-001)
- **Symptom**: Rule 3 (HbA1c >= 7.0%) → 0명 전멸
- **Cause**: Agent2가 SNOMED 37171451 매핑 (LOINC 3004410이 정답)
- **Root cause**: Measurement 도메인에서 LOINC-SNOMED vocab preference gap이 0.25로 부족
- **Fix**: SPEC-MAP-001 — LOINC: -0.30, SNOMED: +0.20 (gap 0.50)
- **Result**: 0명 → 1132명 통과

### BUG-3: Age Rule AND Structure (SPEC-INFRA-002 작성 완료)
- **Symptom**: "Age>=50+CVD OR Age>=60+risk" 가 두 개의 AND rule로 분리
- **Cause**: CIRCE builder가 Demographics를 별도 추출하면서 groupId를 무시
- **Key finding**: Agent1 IR은 정확 (group_type=ANY), CIRCE builder에서 손실
- **Fix**: _build_seeded_target_circe에서 Demographics도 groupId로 그룹핑
- **Impact**: 수동 수정 시 0명 → 253명

### BUG-4: CV Concept Set Too Narrow (SPEC-MAP-002 작성 중)
- **Symptom**: Rule 8 (CV composite) → 346/1132 (31%)만 통과
- **Cause**: Agent2 concept set이 Gold보다 좁음 (개별 concept만, descendant 부족)
- **Impact**: 253명 vs Gold 1222명의 주요 gap 원인

---

## Attrition Progression

| Stage | Final Count | Key Change |
|-------|-------------|------------|
| Initial (session 1) | 0 | L03 CV risk factors 전원 탈락 |
| After re-parse (supplement) | 0 | 18 rules/79 CS, but HbA1c wrong |
| After HbA1c fix (manual) | 0 | R3 fixed, but R0+R1 AND blocks |
| After HbA1c + Age OR fix | **253** | Two main bugs resolved |
| Target (Gold) | **1222** | Gap: CV concept breadth |

## Attrition Breakdown (After Manual Fix)

```
Base (liraglutide drug_era):  1132 (100%)
R0: Age criteria (OR merged):  1097 (97%)  -- fixed from AND to OR
R1: HbA1c >= 7.0%:             1132 (100%) -- fixed from SNOMED to LOINC
R2: Type 2 diabetes:           1132 (100%)
R3: Type 1 diabetes (excl):    1132 (100%)
R4: CHF NYHA IV (excl):        1047 (93%)
R5: Renal replacement (excl):  1132 (100%)
R6: Anti-diabetic drugs:       1132 (100%)
R7: CV disease composite:       346 (31%)  <-- MAIN GAP
R8-R16: Other exclusions:     ~1132 each
Final:                           253
```

---

## SPECs Created

| SPEC | Title | Status | Priority |
|------|-------|--------|----------|
| SPEC-PERF-001 | Agent2 Performance Optimization | **Implemented** (5 commits) | Done |
| SPEC-MAP-001 | Vocab Preference & Standard Concept | **Implemented** (1 commit) | Done |
| SPEC-INFRA-002 | CIRCE Builder Demographics Grouping | **Spec written** | High |
| SPEC-MAP-002 | Concept Set Breadth (CV) | **Spec writing** | High |

### SPEC-PERF-001 Implementation

| Env Var | Default | Purpose |
|---------|---------|---------|
| AGENT2_MAX_WORKERS | 16 | Thread pool concurrency (was 4) |
| AGENT2_KG_CLIMB_LIMIT | 40 | Ancestor climb cap (was 100) |
| AGENT2_MAX_CRITIC_CANDIDATES | 30 | Pre-filter before Critic |
| AGENT2_CRITIC_MODEL_TIER | auto | gpt-4o-mini for Condition/Drug/Measurement |
| AGENT2_CRITIC_CACHE_TTL_HOURS | 24 | Critic result cache TTL |

### SPEC-MAP-001 Implementation

| Domain | Old Gap | New Gap |
|--------|---------|---------|
| Measurement (LOINC vs SNOMED) | 0.25 | **0.50** |
| Drug (RxNorm vs ATC) | 0.05 | **0.25** |
| Condition (SNOMED vs ICD10CM) | 0.05 | **0.15** |
| Procedure (SNOMED vs CPT4) | 0.02 | **0.10** |
| Standard concept S bonus | none | **-0.10** |

---

## Key Lessons Learned

1. **data/ 마운트 누락이 cascade failure의 시작** — supplement PDF 없으면 파싱 품질 급락
2. **Measurement 도메인에서 LOINC이 CDM 표준** — SNOMED measurement는 standard이지만 데이터에 안 쓰임
3. **Gold CIRCE도 non-standard concept 포함** — 232개 중 13개 NULL (의도적)
4. **WebAPI cohort_inclusion rule name varchar(255) 제한** — composite rule 이름 truncation 필요
5. **CIRCE builder의 Demographics 특별 처리가 grouping을 깨뜨림** — Agent1 IR은 정확했음
6. **seeded cohort generation이 eligibility CIRCE를 재매핑** — 성능 최적화 필요 (캐시 재사용)

---

## Next Steps

1. **SPEC-INFRA-002 구현** — Demographics groupId 보존 → Age OR 구조 수정
2. **SPEC-MAP-002 구현** — CV concept set 확장 → 346명 → ~1000+ 목표
3. **Gold vs Agent 전체 비교** (진행 중) — rule별 concept/환자 수 차이 파악
4. **통합 테스트** — 모든 수정 반영 후 attrition 재실행 → Gold 1222 근사 확인
5. **Dockerfile 재빌드** — bookworm + poppler-utils 영구 반영
