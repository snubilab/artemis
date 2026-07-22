# Decision Log — 2026-04-01

## PRIMARY GOAL (최우선 목표)

**30일 사망률 생존 분석 (30-day mortality survival analysis)**

현재 설정과 목표 설정:

| 파라미터 | 현재 | 목표 |
|----------|------|------|
| `followUpDuration` | 365일 | **30일** |
| outcome `timeAtRisk` | 0~365일 | **0~30일** |
| outcome cohort 정의 | 전체 기간 사망 | **30일 이내 사망** |

이 변경이 이루어져야 나머지 분석 결과가 임상적으로 유효하다.

---

## Decision 1: treatment_vs_rest 비교군 설계

**상태**: ✅ 구현 완료

**결정**: comparator = CDM 전체 인구 - 치료군 (treatment_vs_rest 모드)

**배경 및 이유**:
- PLATO, ARISTOTLE 스터디는 active comparator (예: 다른 항혈소판제) 코호트가 CDM 데이터에 존재하지 않음
- Active comparator 없이 분석하려면 REST population (치료군을 제외한 나머지 전체 CDM 인구)을 비교군으로 사용하는 것이 현실적 대안
- 임상 연구에서 "real-world evidence" 맥락에서는 REST 비교군이 허용되는 설계

**구현 위치**:
- `artemis/src/services/tte_service.py`: `is_derived_rest` guard — derived row이면 `comparator_ref=None` 전달하여 REST path 활성화
- `artemis/src/connectors/omop_connector.py`: CDM REST path에서 전체 인구에서 치료군 제외 로직

**결과**:
| 스터디 | Before (전체 CDM) | After (REST cap 적용) |
|--------|------------------|----------------------|
| PLATO | 9,925 | 750 ✅ |
| ARISTOTLE | 9,605 | 3,950 ✅ |

**트레이드오프**:
- REST 비교군은 indication bias가 있을 수 있음 (치료를 받지 않은 이유가 건강 상태 차이일 수 있음)
- PSM/IPTW로 공변량 균형을 맞추어 보정 필요

---

## Decision 2: Comparator 비율 캡 설계 (10:1)

**상태**: ✅ 구현 완료

**결정**: `comparatorN = treatmentN × 10` 상한 캡 적용

**이유**:
- 원시 REST population 비율이 치료군 대비 극단적으로 불균형 (PLATO: 75 : 9,925 = 1:132)
- PSM을 수행하려면 매칭 풀이 너무 커도 문제 (계산 시간, 메모리)
- 통계적으로 10:1 비율이면 power 손실이 미미 (Cochran 1954, Austin 2011)
- 10:1 비율은 PSM caliper 튜닝 시 매칭 성공률에도 유리

**구현**:
```
comparator_cap = treatment_n * 10
sampled_rest = random_sample(rest_population, min(len(rest_population), comparator_cap))
```

**트레이드오프**:
- 일부 CDM 인구가 무작위 제외됨 → 재현성을 위해 random seed 고정 필요
- 10:1 캡이 너무 낮을 경우 희귀 event 분석에서 검정력 부족 가능

---

## Decision 3: PSM → IPTW Fallback 전략

**상태**: ✅ 완료 — 10 new tests, 25/25 passing (`artemis/src/agents/agent5/workflow.py`)

**결정**: PSM caliper=0.2 실패 → caliper=0.5 재시도 → IPTW 자동 전환

**문제 상황**:
- PLATO 스터디: 치료군 75명, PSM caliper=0.2에서 0 matched pairs 반환
- 소규모 치료군에서 propensity score 분포가 좁아 caliper 내 매칭 불가

**전략 설계**:
```
1단계: PSM caliper=0.2 시도
   → matched_pairs > 0: 성공, 분석 진행
   → matched_pairs == 0: 2단계로

2단계: PSM caliper=0.5 재시도
   → matched_pairs > 0: 경고 로그 후 진행
   → matched_pairs == 0: 3단계로

3단계: IPTW (Inverse Probability of Treatment Weighting)
   → 매칭 없이 전체 코호트에 가중치 적용
   → ATE (Average Treatment Effect) 추정
```

**이유**:
- IPTW는 매칭 불가 상황에서도 공변량 균형을 달성할 수 있는 대안
- 소규모 연구에서 PSM보다 통계적 효율성이 높음
- causalml / lifelines 라이브러리 모두 IPTW 지원

**주의사항**:
- IPTW는 extreme weights (very small propensity scores) 문제 발생 가능 → weight trimming (1~99 percentile) 필요
- 결과 해석 시 PSM과 IPTW가 다른 estimand (ATT vs ATE)임을 명시해야 함

---

## Decision 4: CV Event 주입 전략

**상태**: 🔄 진행 중

**결정**: Synthea CDM에 MI event (concept_id=4329847) 직접 주입

**문제 상황**:
- PLATO, ARISTOTLE에서 events=0 → HR=1.0 (분석 의미 없음)
- Synthea 합성 데이터는 CV event (심근경색, 뇌졸중)가 거의 생성되지 않음
- LEADER 스터디는 events=130/0으로 treatment arm에만 event가 있는 비정상 상태

**주입 방법**:
```sql
-- condition_occurrence 테이블에 MI event 삽입
-- 조건: index_date AFTER 주입 (followup 기간 내 event)
INSERT INTO cdm.condition_occurrence (
    condition_occurrence_id,
    person_id,
    condition_concept_id,  -- 4329847 (Myocardial Infarction)
    condition_start_date,
    condition_type_concept_id
)
SELECT ...
FROM treatment_cohort
WHERE condition_start_date BETWEEN index_date AND index_date + INTERVAL '30 days';
```

**30일 분석 목표에 맞춘 주입 규칙**:
- index_date 이후 0~30일 범위 내 날짜로만 주입
- 치료군/비교군 각각 현실적인 비율로 주입 (예: 치료군 5%, 비교군 8%)
- 주입 전 CDM 백업 또는 별도 스키마 사용 권장

**주의**: 프로덕션 CDM 오염 방지를 위해 반드시 벤치마크 전용 스키마에만 적용

---

## Decision 5: 벤치마크 데이터셋 교체

**상태**: ✅ 결정 완료 (구현 대기)

**결정**: `atlas_cohorts` → `ohdsi_studies` criteria-level 기반으로 교체

**문제 상황**:
- `atlas_cohorts` 데이터셋에 비임상 도메인이 혼재:
  - Geography (지역 코드)
  - Revenue Code (청구 코드)
  - Claim Source (청구 출처)
- 이런 도메인은 OMOP 임상 mapping 평가에 부적합

**새 벤치마크 (`ohdsi_criteria_benchmark.json`) 통계**:
| 도메인 | 개수 | 비율 |
|--------|------|------|
| Condition | ~4,270 | 52% |
| Drug | ~2,053 | 25% |
| Procedure | ~900 | 11% |
| Measurement | ~600 | 7% |
| Observation | ~387 | 5% |
| **전체** | **8,210** | 100% |

**이유**:
- OHDSI 공식 연구의 eligibility criteria는 임상적으로 검증된 concept mapping
- 도메인 분포가 실제 TTE 파이프라인 사용 패턴에 더 근접
- Gold standard로서 신뢰성 높음

---

## Decision 6: 벤치마크 메트릭 설계

**상태**: ✅ 결정 완료

**결정**: Precision / Recall / F1 (set-based) + Hit@K + Latency 측정

**명시적 제외**: SQL Execution Accuracy (사용자 명시적 제외)

**메트릭 정의**:

```
Set-based Precision = |predicted ∩ gold| / |predicted|
Set-based Recall    = |predicted ∩ gold| / |gold|
F1                  = 2 × (P × R) / (P + R)

Hit@1  = gold concept_id가 top-1 결과에 포함되는 비율
Hit@5  = gold concept_id가 top-5 결과에 포함되는 비율
Hit@10 = gold concept_id가 top-10 결과에 포함되는 비율

Latency = criterion당 평균 처리 시간 (ms)
```

**이유**:
- 1개 `concept_set_name`이 여러 `concept_id`에 매핑되는 set retrieval 문제
- SQL Execution Accuracy는 CDM 스키마 의존성이 높아 범용 벤치마크에 부적합
- Hit@K는 RAG retrieval quality를 측정하는 표준 지표

**비교 대상**:
1. **Agent2 (현재 파이프라인)**: UMLS + ChromaDB + KG + Critic
2. **RAG baseline**: ChromaDB 직접 검색 (query → top-K)
3. **LLM baseline**: GPT-4o에 직접 질의 (프롬프트 only)

---

## Decision 7: 동시성 이슈 대응

**상태**: ⚠️ 임시 대응 완료, 영구 수정 대기

**문제**: `PUT /tte/studies/{id}` 동시 호출로 study 데이터 덮어쓰기 발생

**발생 맥락**:
- PLATO 스터디 (ID: 432) 분석 중 두 개의 병렬 에이전트가 동시에 study를 수정
- 후발 write가 선발 write의 결과를 overwrite

**임시 대응**:
- artifact history에서 수동으로 이전 상태 복원
- 향후 동시 write를 유발하는 작업 순차 실행으로 임시 회피

**필요한 영구 수정** (`artemis/src/services/tte_store.py`):
```python
# Option A: asyncio.Lock per study_id
_study_locks: dict[int, asyncio.Lock] = {}

async def update_study(study_id: int, ...):
    lock = _study_locks.setdefault(study_id, asyncio.Lock())
    async with lock:
        # read-modify-write
        ...

# Option B: Optimistic locking with version field
# study에 version 필드 추가, PUT 시 version 불일치면 409 Conflict 반환
```

**우선순위**: P3 (분석 정확성 이슈 해결 후)

현재 테스트 파일: `artemis/tests/test_tte_store_concurrency.py`

---

## Benchmark Code Issues Found (Codex Review)

**날짜**: 2026-04-01

### BUG 1: `domain_hint` not passed to Agent2

**파일**: `quick_concept_benchmark.py`

**문제**: `domain_hint` 파라미터가 Agent2 `recommend()` 호출 시 전달되지 않음 → Drug 도메인 recall이 인위적으로 낮음

**수정**: `recommend()` 호출에 `domain_hint=domain` 추가

### BUG 2: `top_k=10` hardcoded — structural recall ceiling

**문제**: GT(Ground Truth) set이 35개 items인 경우 `top_k=10`이면 최대 recall = 10/35 = **0.286**이 상한
→ 실제 Agent2 성능을 과소평가

**수정**: `top_k=max(20, len(gt_ids))`로 동적 설정

**상태**: Fix in progress

---

### Benchmark Results (10-item, ohdsi_criteria, WITH BUGS)

> Note: Agent2 Recall이 가장 높으나 위 버그로 인해 **과소 추정됨**. 버그 수정 후 결과가 더 높아질 것으로 예상.

| Mapper | Precision | Recall | F1 | Hit@1 | Latency |
|--------|-----------|--------|----|-------|---------|
| RAG | 0.030 | 0.056 | 0.026 | 0.100 | 1.7s |
| LLM Direct | 0.040 | 0.161 | 0.061 | 0.200 | 1.7s |
| Agent2 | 0.048 | 0.206 | 0.058 | 0.100 | 6.1s |

---

## Current Study Status

| 스터디 | Study ID | Treatment N | Comparator N | HR | Events (T/C) | 상태 |
|--------|----------|-------------|--------------|-----|--------------|------|
| LEADER | 431 | ~387 | 557 | 15.9 | 130 / 0 | ✅ 분석 완료 (events 불균형) |
| PLATO | 432 | 75 | 750 | - | 0 / 0 | ❌ PSM 실패, events=0 |
| ARISTOTLE | 424 | ~395 | 3,950 | 1.0 | 0 / 0 | ⚠️ events=0 |

**LEADER 이슈**: Treatment arm에만 event가 130건, Control arm에 0건 → HR이 극단적으로 높음. 30일 outcome 재정의 후 재분석 필요.

---

## Next Steps (Priority Order)

### [P0] 30일 분석 설정 변경 (IN PROGRESS 🔄)
- [ ] `followUpDuration` → 30일 변경 (UI 및 backend 파라미터)
- [ ] outcome cohort → "index_date + 30일 이내 사망" 재정의
- [ ] `timeAtRisk` window → `[0, 30]` 변경
- [ ] 세 스터디 (LEADER 431, PLATO 432, ARISTOTLE 424) 전체 재분석

### [P1-A] CV Event 주입
- [ ] `synthea_cdm_plato`, `synthea_cdm_aristotle`에 MI event 주입
- [ ] 30일 followup 기간 내 날짜로 주입 (index_date + 1~30일)
- [ ] 치료군/비교군 현실적 이벤트 비율 설정 후 재분석
- [ ] CV event injection 결과 검증

### [P1-B] PSM → IPTW Fallback — ✅ COMPLETED
- [x] `workflow.py` caliper=0.5 재시도 로직 추가
- [x] IPTW fallback 구현 (10 new tests, all 25 passing)
- [x] weight trimming (1~99 percentile) 적용

### [P2] ohdsi_criteria_benchmark 재벤치마크
- [ ] **Fix benchmark bugs first** (domain_hint, top_k dynamic)
- [ ] Re-run with bugs fixed, compare before/after
- [ ] Agent2 vs RAG baseline vs LLM baseline 비교 실행
- [ ] Precision / Recall / F1 / Hit@K / Latency 측정
- [ ] 결과 문서화

### [P3] tte_store.py Concurrency Guard
- [ ] `asyncio.Lock` per study_id 구현 (Option A)
- [ ] `test_tte_store_concurrency.py` 테스트 통과 확인
- [ ] 또는 optimistic locking + 409 Conflict 응답 설계

### Next Sessions TODO (updated 2026-04-01)
- [ ] Re-run benchmark with bugs fixed (domain_hint + top_k)
- [ ] 30-day re-analysis results (all 3 studies)
- [ ] CV event injection results
- [ ] tte_store.py concurrency guard

---

## Technical Debt 기록

| 항목 | 파일 | 설명 | 우선순위 |
|------|------|------|----------|
| PSM fallback | `agent5/workflow.py` | ✅ 완료 — caliper 확장 + IPTW, 25 tests passing | P1 |
| Concurrency guard | `tte_store.py` | write lock 없음 | P3 |
| CV event injection | `scripts/inject_cv_events.py` | 미작성 | P1 |
| Random seed 고정 | `omop_connector.py` | REST 10:1 샘플링 재현성 | P2 |

---

## References

- `artemis/src/services/tte_service.py` — `is_derived_rest` guard
- `artemis/src/connectors/omop_connector.py` — CDM REST path, 10:1 cap
- `artemis/src/agents/agent5/workflow.py` — PSM logic (line 203)
- `artemis/src/services/tte_store.py` — concurrency issue location
- `artemis/tests/test_tte_store_concurrency.py` — concurrency test (pending)
- `artemis/docs/daily_notes/2026-03-31_analysis_comparator_handoff.md` — comparator 설계 상세
- `docs/tte_agent/06_backend_atomic_todo_plan.md` — backend 구현 계획
- `docs/tte_agent/07_current_status.md` — 현재 진행 상태
