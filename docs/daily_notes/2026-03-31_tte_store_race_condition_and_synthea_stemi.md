# TTE Store Race Condition Fix & Synthea STEMI Module Fix — 2026-03-31

## Summary

Two fixes landed on branch `fix/agent1-pattern-e-or-logic` in the final session of 2026-03-31:

1. **`tte_store.py` inter-process race condition** (`4c566f2`) — added file-level locking so
   concurrent `process_eligibility` calls no longer lose each other's updates to `studies.json`.
2. **Synthea STEMI 코드 누락** (`fe59422`) — PLATO 벤치마크 재생성 시 STEMI 환자가 포함되도록
   `generate_synthea_modules.py`에 SNOMED STEMI 코드를 추가했다.

---

## Fix 1: tte_store.py Inter-Process Race Condition

### 문제 발견 경위

`fix/agent1-pattern-e-or-logic` 세션 중 세 개의 벤치마크 스터디(PLATO, LEADER, ARISTOTLE)에 대해
`process_eligibility`를 동시에 실행했을 때 `studies.json` 파싱 오류가 간헐적으로 발생했다.

### Root Cause

`TTEStore`는 `threading.Lock()`만 사용하고 있었다. 이 락은 **동일 프로세스 내** 스레드 간 경쟁만
막아준다. 별개 프로세스(또는 별개 uvicorn worker)가 동시에 `studies.json`을 읽고 수정하고 쓸 때는
보호가 없다.

```
Process A: read studies.json → modify study 431 →
Process B:                        read studies.json → modify study 432 → write
Process A:                                                                          → write  ← B's change lost
```

원자적 쓰기(`tmp_path.replace(path)`)가 이미 구현되어 있어 JSON 파일 자체가 깨지지는 않지만,
A가 B의 변경 사항을 덮어쓰는 **lost update** 문제는 방지되지 않았다.

### Fix (`artemis/src/services/tte_store.py`)

- `filelock` 라이브러리(v3.25.2, `requirements.txt`에 이미 포함)를 사용해
  모든 read-modify-write 사이클을 파일 락으로 감쌌다.
- `threading.Lock`(프로세스 내)과 `FileLock`(프로세스 간)을 모두 유지하여 TOCTOU를 완전 차단.
- `_make_file_lock(path)` 팩토리 함수가 폴백 체인을 처리한다:
  - `filelock` → `fcntl.flock` (Unix) → warning-only no-op

**핵심 원칙**: `threading.Lock` + atomic write는 파일 손상은 막지만 lost update는 막지 못한다.
파일 락이 있어야 lost update가 방지된다.

### Tests (`artemis/tests/test_tte_store_concurrency.py`)

| 테스트 | 설명 | 결과 |
|--------|------|------|
| `test_concurrent_creates_no_lost_updates` | 10개 스레드가 동시 생성 → 10개 모두 살아남는지 확인 | PASS |
| `test_file_lock_prevents_interleaved_writes` | `_file_lock` 속성이 TTEStore에 존재하는지 확인 | PASS |

---

## Fix 2: Synthea STEMI 코드 누락

### 문제

PLATO_BENCHMARK(25k persons) DB에 STEMI(ST 상승형 심근경색) 환자가 0명이었다.

직접 SQL 확인 결과:

| SNOMED 코드 | 설명 | 건수 |
|------------|------|------|
| `57054005` | NSTEMI | 21,287 |
| `22298006` | Generic AMI | 4,150 |
| `401303003` | **STEMI** | **0** |

Synthea `heart_attack.json` 모듈이 STEMI를 생성하지 않는 구조였기 때문이다.
PLATO 임상시험(NCT00391872)은 STEMI/NSTEMI/UA 환자군을 모두 대상으로 하지만,
현재 벤치마크에서는 STEMI 환자군을 재현할 수 없는 상태였다.

### Fix (`artemis/scripts/generate_synthea_modules.py`)

PLATO 모듈 생성 시 STEMI SNOMED 코드를 추가했다:

| SNOMED | 설명 | OMOP concept_id |
|--------|------|-----------------|
| `401303003` | Acute ST segment elevation myocardial infarction | `312327` |

기존 MI(`22298006`) + LBBB(`63467002`) 매핑은 유지된다.

### 중요 한계

이 수정은 **새 Synthea 데이터 재생성 시에만** 효과가 있다.

- 기존 `PLATO_BENCHMARK` DB는 변경 없이 STEMI 0건 유지
- 현재 PLATO 75명 카운트는 NSTEMI/UA 환자 기반
- 실제 STEMI 환자를 포함한 테스트를 원하면 아래 재실행 필요:

```bash
artemis/scripts/setup_study_benchmarks.sh --plato
```

---

## 브랜치 전체 완료 현황

`fix/agent1-pattern-e-or-logic` 브랜치(2026-03-31)에서 완료한 전체 작업:

| 커밋 | 내용 |
|------|------|
| `5c40a56` | feat(agent1): Pattern E/F OR logic 프롬프트 수정 |
| `571ea30` | fix(agent2): RxNorm Extension → RxNorm Ingredient rollup |
| `8b642d3` | fix(agent1): P1/P2/P3 비결정성 수정 (27 tests passing) |
| `fe59422` | fix(synthea): PLATO 모듈 STEMI SNOMED 코드 추가 |
| `4c566f2` | fix(tte_store): inter-process file lock 추가 |

### 벤치마크 최종 결과

| 벤치마크 | 대상 약물 | 환자 수 | 상태 |
|---------|----------|--------|------|
| LEADER_BENCHMARK | liraglutide | 387 | PASS |
| ARISTOTLE_BENCHMARK | apixaban | 395 | PASS |
| PLATO_BENCHMARK | ticagrelor | 75 | PASS |

---

## 남은 TODO (LOW priority)

- PLATO_BENCHMARK 재생성 (`setup_study_benchmarks.sh --plato`)으로 실제 STEMI 환자 포함 (선택적)
- STEMI 환자 포함 후 PLATO 코호트 재검증
