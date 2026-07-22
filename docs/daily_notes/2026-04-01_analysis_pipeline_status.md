# Analysis Pipeline Status — 2026-04-01

## Summary

오늘은 comparatorN 과대 계산 버그를 수정하고, 개념 매핑 벤치마크 인프라를 구축했다.
LEADER/ARISTOTLE/PLATO 3개 스터디의 현황을 검증했으며, PLATO에서 PSM 실패 및 outcome events=0 문제를 새로 발견했다.

---

## Completed Today

### 1. comparatorN Fix (`is_derived_rest` + cap)

**문제**: REST 비교군(derived) 환자 수가 실제보다 훨씬 크게 계산됨
- ARISTOTLE: 9,605 → 3,950 ✅
- PLATO: 9,925 → 750 ✅

**수정 내용**:

| File | Line | Change |
|------|------|--------|
| `artemis/src/services/tte_service.py` | ~4453 | `is_derived_rest` guard — derived REST 행은 `comparator_ref`를 건너뜀 → OMOPConnector가 CDM REST 경로 사용 |
| `artemis/src/analysis/omop_connector.py` | ~760 | REST comparatorN cap: `treatmentN × 10` 상한 적용 |

**커밋**: `929edd0`, `ac0eeae`

---

### 2. Benchmark Infrastructure 구축

새 벤치마크 스크립트 및 데이터:

- `artemis/scripts/quick_concept_benchmark.py` — 50-item 빠른 벤치마크
- `artemis/scripts/extract_criteria_benchmark.py` — `ohdsi_studies`에서 criteria 쌍 추출
- `artemis/data/benchmark_data/ohdsi_criteria_benchmark.json` — 8,210 items

**도메인 분포**:
| Domain | 비율 |
|--------|------|
| Condition | 52% |
| Drug | 25% |
| Procedure | 11% |
| Measurement | 8% |
| Observation | 3% |

**atlas_cohorts 벤치마크 (비임상 도메인 혼재 → 부적합 판정)**:

| Mapper | F1 | Hit@1 | Latency |
|--------|-----|-------|---------|
| RAG (MedCPT+ChromaDB) | 0.026 | 0.100 | 1,693ms |
| LLM Direct (GPT-4o) | 0.061 | 0.200 | 1,672ms |
| Agent2 | 진행 중 | - | - |

**ohdsi_criteria_benchmark 10-item 결과**:

| Mapper | Precision | Recall | F1 | Hit@1 |
|--------|-----------|--------|----|-------|
| RAG | 0.030 | 0.056 | 0.026 | 0.100 |
| LLM Direct | 0.040 | 0.161 | 0.061 | 0.200 |
| Agent2 | 진행 중 | - | - |

> Agent2 전체 벤치마크 미완료 — 내일 계속

---

## Current Study Status

| Study | DB ID | treatmentN | comparatorN | matchedPairs | HR | Events (T/C) | 상태 |
|-------|-------|-----------|------------|-------------|-----|-------------|------|
| LEADER | 431 | 387 | 557 | - | 15.9 | 130 / 0 | ✅ 정상 (IPTW) |
| PLATO | 432 | 75 | 750 | None | None | 0 / 0 | ❌ PSM 실패 |
| ARISTOTLE | 424 | 395 | 3,950 | 34 | 1.0 | 0 / 0 | ⚠️ events=0 |

---

## New Problems Discovered

### Problem 1: PLATO PSM caliper too tight

**증상**: `PSM produced 0 matched pairs — caliper may be too tight`

**근본 원인**:
- `artemis/src/agents/agent5/workflow.py` line ~203에 `caliper=0.2` 하드코딩
- Treatment 75명 vs REST 750명 — 인구 구성이 이질적이어서 caliper 0.2 내 매칭 불가

**수정 옵션**:
- Option A: caliper 완화 (`0.2 → 0.5` 또는 `None`)
- Option B: PLATO도 IPTW로 전환 (LEADER와 동일하게)

**추천**: Option B (IPTW) — 비율 불균형(1:10)이 심각하여 PSM 자체가 부적절할 수 있음

---

### Problem 2: HR=1.0 / outcome events=0

**원인**: PLATO, ARISTOTLE Synthea 합성 데이터에 CV outcome event(MI/Stroke/Death)가 없음

**수정 방법**: `condition_occurrence`에 CV event 직접 주입
```sql
-- Myocardial Infarction
concept_id = 4329847
-- Stroke
concept_id = 375557
```
- index_date 이후 날짜에 삽입
- 백업 존재: `artemis/data/backups/synthea_cdm_{leader,plato,aristotle}_20260331.sql`

---

### Problem 3: 동시성 이슈 (Study 432 덮어쓰기)

**증상**: `PUT /tte/studies/432` 동시 호출로 study가 `version=1`로 리셋됨

**임시 조치**: artifact history에서 수동 복원 완료

**근본 수정 필요**: `tte_store.py`에 optimistic locking 또는 write guard 추가

---

## Pending Tasks

- [ ] Agent2 벤치마크 결과 확인 (진행 중)
- [ ] PLATO PSM caliper 수정 또는 IPTW 전환 (`agent5/workflow.py`)
- [ ] PLATO/ARISTOTLE `condition_occurrence`에 CV event 주입
- [ ] `artemis/.env`에 새 API 키 추가 후 container recreate
  - AWS Bedrock
  - GCP
  - Azure EastUS2
- [ ] `tte_store.py` 동시성 guard 구현

---

## Infrastructure

| Item | Value |
|------|-------|
| Branch | `fix/agent1-pattern-e-or-logic` |
| Container | `477b3f1664ed_artemis-api` (running, new code loaded) |
| DB | `broadsea-atlasdb` (running) |
| Backups | `artemis/data/backups/synthea_cdm_{leader,plato,aristotle}_20260331.sql` |

---

## Next Session Priorities

1. **PLATO PSM fix** — `agent5/workflow.py` caliper 수정 or IPTW 전환
2. **CV event injection** — ARISTOTLE/PLATO Synthea DB에 MI/Stroke event 주입
3. **Agent2 benchmark** — 진행 중인 벤치마크 완료 및 결과 분석
4. **Concurrency guard** — `tte_store.py` write 동시성 보호 구현
5. **API key rotation** — `.env` 업데이트 + container recreate (not restart)
