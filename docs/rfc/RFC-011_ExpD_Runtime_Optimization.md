# RFC-011: Exp D 실행 시간 단축 전략 (Cache + Parallel + Resolve Optimization)

**상태**: 제안 (수정안 반영)  
**날짜**: 2026-03-04  
**제안자**: @kyh

## 1. 가설 및 목표

`scripts/benchmark_exp_d.py`의 총 실행 시간을 단축한다.

- 기준 실행 시간: 약 `634초` (NCT01179048 / LEADER_GOLD 기준)
- 목표: 정확도 저하 없이 1차로 `50%+` 단축
- 원칙: 개발된 요소(KG/Critic 포함)를 반영한 상태로 성능을 개선하고, 평가 경로를 임의 단축하지 않는다.

## 2. 병목 측정 결과 (Baseline)

### 2.1 전체 구조

- Agent 1: 캐시 HIT 시 수 초 내 완료 (주 병목 아님)
- TROY resolve: 별도 측정 `78.1초` (17 rule)
- Agent 2: 규칙별 단건 직렬 호출 누적으로 최장 구간 형성

### 2.2 핵심 병목

1. Agent2 단건 직렬 호출
- `benchmark_exp_d.py`에서 rule당 순차 호출
- base rules `28`개, drug split 포함 실제 호출 `35`회
- v5 로그 기준 Agent2 1호출 평균 약 `19.9초` (query 편차 큼)

2. TROY resolve DB 반복 쿼리
- `resolve_troy_rule()` 내부에서 concept item 단위 descendant 확장 반복
- 느린 rule 예:
  - `prior CV disease`: `25.3초`
  - `No acute coronary...`: `24.0초`

## 3. 제안 설계 (Proposed Design)

### A. Agent2 결과 캐시를 Exp D에 직접 적용 (즉시)

- 파일: `src/agents/agent2/agent2_cache.py` 재사용
- 키: `(entity_text, domain)` 정규화
- 캐시 HIT 시 Agent2 호출 생략
- 기대 효과: 반복 벤치마크(동일 corpus)에서 대폭 단축

### B. Agent2 호출 병렬화 + 중복 제거 (즉시)

- `evaluate_troy_matching()` 내 Agent2 phase를 worker pool로 실행
- 호출 전 `(rule_type, entity_text, domain, polarity)` 기준으로 중복 질의 제거
- 권장 기본값: `max_workers=4` (CLI 플래그)
- 기대 효과: 단건 직렬 누적 구간을 병렬로 단축

### C. TROY resolve 캐시 추가 (즉시)

- 키: `(troy_path hash, schema, troy_rule_index)` 또는 `(troy rule signature)`
- 캐시 위치: `data/cache/benchmark/`
- 같은 TROY 파일 반복 실행 시 resolve 단계 재사용

### D. 벤치마크 Fast 모드 옵션 (기각)

- 결정: **기각** (2026-03-04)
- 사유: 개발된 요소를 반영한 실제 경로에서 지속 검증해야 하므로, KG/Critic 생략 모드는 본 RFC 목표와 충돌
- 후속: 속도 개선은 캐시/병렬화/쿼리 최적화로만 진행

### E. resolve_troy_rule 배치화 (중기)

- 현재 per-item descendant 조회를 batch SQL로 전환
- include/exclude seed를 한 번에 처리해 DB round-trip 축소
- 구현 난도는 높지만 캐시 없이도 전처리 시간을 구조적으로 절감

## 4. 변경 우선순위 (Impact × Effort)

1. A (Agent2 캐시): **높은 효과 / 낮은 난도**
2. B (병렬화 + dedupe): **높은 효과 / 중간 난도**
3. C (TROY 캐시): **중간 효과 / 낮은 난도**
4. E (resolve 배치화): **중간 효과 / 높은 난도**

## 5. 구현 계획 (최소 변경)

1. `benchmark_exp_d.py` CLI 확장
- `--max-workers` (default: 4)
- `--no-agent2-cache` (default: cache ON)
- `--no-troy-cache` (default: cache ON)

2. Agent2 phase 리팩터
- 단건 loop → 병렬 실행
- dedupe map 구성 후 결과 fan-out

3. 캐시 계층 추가
- Agent2 cache read/write
- TROY resolve cache read/write

4. 리포트 확장
- `timings`: phase별 sec
- `cache_stats`: hit/miss
- `parallelism`: workers, dedupe ratio

## 6. 검증 기준 (Acceptance Criteria)

- 정확도 회귀 없음(기본 모드):
  - Avg Recall/F1 기존 변동 범위 내 유지
- 성능:
  - 1회차: baseline 대비 `30%+` 단축
  - 2회차(캐시 warm): baseline 대비 `50%+` 단축
- 재현성:
  - 동일 입력/동일 캐시에서 결과 JSON 핵심 메트릭 동일

## 7. 리스크 및 대응

- 병렬화로 인한 비결정성
  - 대응: 결과 수집 순서 고정, key 기반 merge
- 캐시 오염(스키마/코드 변경)
  - 대응: cache key에 schema + version + troy hash 포함

## 8. 결론

Exp D 시간 단축의 핵심은 `Agent2 직렬 호출 제거`와 `캐시 재사용`이다.  
즉시 적용 가능한 A+B+C만으로도 반복 벤치마크 시간을 크게 줄일 수 있으며, 중기적으로 E를 적용한다.
