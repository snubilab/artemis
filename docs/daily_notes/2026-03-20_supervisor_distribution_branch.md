# 2026-03-20: Supervisor distribution branch 정리 및 staged domain correction 고정

## 오늘 완료

- [x] `main`/`feat/distribution`를 로컬 전용 브랜치로 정리
  - `origin/main` 추적을 끊고 로컬 브랜치로만 관리되도록 복구
  - 현재 작업 브랜치는 `feat/distribution`
- [x] Supervisor register wiring 버그 수정
  - `supervisor_agent.py`에서 `_step3_register()` 호출 시 registry 의존성 누락 수정
  - 관련 회귀 테스트 추가
- [x] `force_slow_path` 실제 동작 수정
  - `map_single_entity()`가 Agent 2 workflow가 읽는 `FORCE_SLOW_PATH`를 사용하도록 변경
  - slow-path 강제 회귀 테스트 추가
- [x] selective retry audit 계약 보강
  - `too_few_concepts` producer key와 retry planner consumer key 정합성 수정
  - domain mismatch audit에 concept domain 빈도 보존
- [x] Option C 구현
  - `domain_mismatch` 1차는 원래 `domain_hint` 유지 + `force_slow_path`
  - 2차부터 strong evidence가 있을 때만 corrected `domain_hint` 허용
  - `domain_mismatch:{entity_key}` 전용 retry count 추가
- [x] domain correction threshold env/config 노출
  - `SUPERVISOR_DOMAIN_CORRECTION_*` 변수로 stage/ratio/count 조건 조정 가능하게 변경
- [x] `ESCALATE` 종료 경로 비활성화
  - 현재 distribution 브랜치에서는 `escalate_reason`만 state에 남기고 파이프라인은 계속 진행
- [x] 관련 문서 최신화
  - Supervisor flow / selective retry / distribution branch 운영 규칙 반영

## 진행중

- [/] distribution 브랜치 운영 규칙 명문화 진행
  - 코드/테스트/문서 기준선은 맞췄고, 이후 README급 실행 가이드가 추가로 필요할 수 있음

## 핵심 변경사항

### 1. Supervisor routing semantics

- `ESCALATE`는 더 이상 `END`로 가지 않음
- 현재 동작:
  - `review_trial()`에서 `ESCALATE`여도 `mapping`으로 진행
  - `review_mapping()`에서 `ESCALATE`여도 `assembly`로 진행
  - `review_assembly()`에서 `ESCALATE`여도 `extraction`으로 진행
  - `review_extraction()`에서 `ESCALATE`여도 `analysis`로 진행
- 의미:
  - escalation은 즉시 종료가 아니라 **상태 기록용 경고 신호**
  - 종료/HITL interrupt는 future phase에서 별도 설계 필요

### 2. Domain mismatch remediation 정책

- 기본 원칙:
  - Agent 1의 `domain_hint`를 우선 존중
  - 첫 mismatch 재시도는 domain을 바꾸지 않고 slow path만 강제
- corrected domain 허용 조건:
  - `expected_domain_count == 0`
  - `dominant_non_expected_count >= threshold`
  - `dominant_non_expected_ratio >= threshold`
  - `unknown_domain_count == 0`
- retry telemetry:
  - `entity:{entity_key}`
  - `domain_mismatch:{entity_key}`

### 3. Configurable env

- `SUPERVISOR_DOMAIN_CORRECTION_AFTER_RETRIES` (default `1`)
- `SUPERVISOR_DOMAIN_CORRECTION_MIN_COUNT` (default `3`)
- `SUPERVISOR_DOMAIN_CORRECTION_MIN_RATIO` (default `0.8`)
- `SUPERVISOR_DOMAIN_CORRECTION_REQUIRE_ZERO_EXPECTED` (default `true`)
- `SUPERVISOR_DOMAIN_CORRECTION_REQUIRE_KNOWN_ONLY` (default `true`)

## 오늘 수정/추가한 주요 파일

### 코드

- `artemis/src/pipeline/supervisor_agent.py`
- `artemis/src/pipeline/mapping_retry.py`
- `artemis/src/agents/agent2/map_entity.py`

### 테스트

- `artemis/tests/test_supervisor_agent.py`
- `artemis/tests/test_mapping_retry.py`
- `artemis/tests/test_map_entity.py`

### 문서

- `artemis/docs/architecture/agent_reference.md`
- `artemis/docs/TODO_mapping_quality.md`
- `artemis/docs/lab_meetings/2026-03-15_supervisor_selective_retry.md`

## 오늘 생성한 커밋

- `645324f` `chore: checkpoint v6 cohort eval worktree`
- `17a70de` `fix: wire supervisor agent register dependencies`
- `99d62f2` `fix: honor force slow path in map entity`
- `9954d80` `fix: preserve supervisor retry audit signals`
- `7148913` `fix: align supervisor action type contract`
- `22063ba` `fix: stage supervisor domain correction behind retry`
- `ec8804a` `feat: make supervisor domain correction configurable`
- `f35fbbb` `fix: keep supervisor flow running after escalate`
- `87f44ec` `docs: update supervisor distribution flow`

## 검증

실행:

```bash
cd /Users/kyh/Workspace/Broadsea/artemis
PYTHONPATH=. pytest tests/test_map_entity.py tests/test_mapping_retry.py tests/test_supervisor_agent.py -q
```

결과:

- `69 passed`

## 현재 브랜치 상태

- `main`: 로컬 통합 브랜치
- `feat/distribution`: distribution 실험/정책 브랜치
- `origin/main`과의 브랜치 추적은 해제

## 다음 작업 후보

1. distribution 실행 가이드 문서 추가
2. `.env` 또는 실행 스크립트에 `SUPERVISOR_DOMAIN_CORRECTION_*` 예시 반영
3. 실제 benchmark/e2e에서 Option C threshold sweep 수행
