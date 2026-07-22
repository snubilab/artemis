# Valid Gold vs AI HR Comparison — Injection Design (2026-04-01)

## 왜 이 문서가 필요한가

Synthea 합성 데이터로 임상 RCT를 벤치마킹할 때 CV outcome 이벤트가 자연적으로 거의 없다.
이벤트를 수동 주입해야 하는데, **주입 방식이 잘못되면 gold vs AI 비교 자체가 무의미해진다.**

이 문서는 "어떻게 주입해야 공정한 비교가 되는가"의 설계 근거를 기록한다.

---

## 핵심 통찰: Cohort-Blind Population Injection

### 문제: cohort-specific injection의 함정

이전 방식 (잘못된 방법):
```
AI cohort 75명에게만 이벤트 주입
→ gold-only 362명은 이벤트 0건
→ gold HR analysis: 362명이 모두 comparator rate를 받음
→ gold HR = 1.0 (무의미)
```

### 해결: Gold ∪ AI union을 "treated"로 분류

```
모든 CDM person
  ├─ gold ∪ AI cohort에 속하는 사람 → 25% event rate
  └─ 나머지 CDM population (REST) → 12.5% event rate
```

**왜 union인가?**
- gold 분석 시: gold patients가 treated(25%) rate 받음 → HR ≠ 1.0
- AI 분석 시: AI patients가 treated(25%) rate 받음 → HR ≠ 1.0
- 두 분석 모두 **동일한 condition_occurrence 테이블** 위에서 실행
- Gold HR vs AI HR 비교가 공정해짐

**목표는 published HR 재현이 아님:** Gold HR ≈ AI HR이면 AI가 gold와 비슷한 환자를 선택했다는 의미.
차이가 크면 AI cohort의 covariate profile이 다르다는 신호.

---

## 기술적 설계 결정사항

### 1. REST comparator의 index_date 처리

`omop_connector.py:822`:
```python
comp_index_date = target_df["cohort_start_date"].min()
```

REST comparator 환자들은 모두 **동일한 index_date** (treatment 중 가장 이른 날짜)를 가짐.
따라서 untreated 환자에게 이벤트를 주입할 때도 이 `min_treatment_index_date`를 기준으로 해야
followup window (365일) 안에 이벤트가 들어감.

### 2. Event 날짜 범위: [index_date + 30, index_date + 330]

- Day 0 제외: `extract_outcome_from_cohort`이 `cohort_start_date > index_date` (strict greater-than)
- 30일 시작: 너무 이른 이벤트는 baseline condition과 혼동 가능
- 330일 상한: 365일 followup window 내 확실히 포함되도록 30일 버퍼

### 3. INJECTED_ID_BASE = 100_000_000 (100M)

실제 max condition_occurrence_id:
- LEADER: 10,000,338
- PLATO: 10,000,317
- ARISTOTLE: 12,001,374

1M base 사용 시 충돌. 100M으로 안전하게 분리.
Idempotent clean: `DELETE WHERE condition_occurrence_id >= 100_000_000`

### 4. Event rates: 25% treated / 12.5% untreated

이론적 HR ≈ 2.0. IPTW 조정 후 실제 HR은 달라지지만, non-degenerate하고
gold vs AI HR 비교에 충분한 분산을 만들어냄.

### 5. Outcome cohort 재생성 필수

이벤트를 condition_occurrence에 넣어도 WebAPI의 outcome cohort (results.cohort)는
자동으로 업데이트되지 않음. `generate_existing_cohort(force_regenerate=True)` 호출 필요.

---

## 스크립트 위치

```
artemis/scripts/inject_cv_events.py
```

**사용법:**
```bash
python3 artemis/scripts/inject_cv_events.py \
  --seed 42 \
  --treatment-rate 0.25 \
  --comparator-rate 0.125 \
  --studies LEADER PLATO ARISTOTLE
```

---

## Cohort ID 참조표

| Study | CDM Schema | AI Treatment | Gold Treatment | Outcome | Source Key |
|-------|-----------|--------------|----------------|---------|------------|
| LEADER | synthea_cdm_leader | 840 | 1136 | 841 | LEADER_BENCHMARK |
| PLATO | synthea_cdm_plato | 941 | 1137 | 943 | PLATO_BENCHMARK |
| ARISTOTLE | synthea_cdm_aristotle | 1127 | 1138 | 1128 | ARISTOTLE_BENCHMARK |

---

## 실행 순서

1. `inject_cv_events.py` (~30초 INSERT + 2-5분 WebAPI regeneration)
2. `run_gold_vs_ai_comparison.py` 재실행
3. Gold HR vs AI HR 비교표 확인

## 이전 실패 사례 요약

| 시도 | 문제 | 교훈 |
|------|------|------|
| Campaign 1 (results schema 직접 주입) | WebAPI가 cohort execute 시 results 덮어씀 | CDM에 주입해야 함 |
| Campaign 2 (index_date+90일) | 30일 followup window 밖 | 30-330일 범위 사용 |
| Campaign 3 (AI cohort만) | gold-only 환자 이벤트 0 → gold HR=1.0 | Gold∪AI union 사용 |
| Campaign 3 (treatment 53.5%) | 의도한 20% 초과 | 명시적 seed+rate 사용 |
