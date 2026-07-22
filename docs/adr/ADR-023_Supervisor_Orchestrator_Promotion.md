# ADR-023: Supervisor를 Pipeline Orchestrator로 승격

**상태**: 승인됨  
**날짜**: 2026-03-11  
**의사결정자**: @kyh

## 컨텍스트

현재 `cohort_pipeline.py`가 Agent 간 결과 전달, 조건부 판단, retry loop 등 **사실상 Supervisor 역할**을 수행 중.
별도로 생성한 `supervisor.py`는 Post-Agent2 quality gate 하나만 담당하는 작은 모듈.

이 구조의 문제:

- `cohort_pipeline.py`가 오케스트레이션 + 비즈니스 로직 모두 담당 (493줄)
- `supervisor.py`라는 이름이 실제 역할(quality gate)과 불일치
- LangGraph 전환 시 pipeline 전체를 재작성해야 함

## 결정

**`supervisor.py`를 진짜 Pipeline Orchestrator로 승격**한다.

1. `cohort_pipeline.py`의 오케스트레이션 로직 (`run()`)을 `supervisor.py`로 이관
2. `cohort_pipeline.py`는 thin wrapper 또는 삭제
3. `supervisor.py`가 Agent 간 결과 전달, 조건부 분기, retry, HITL escalation 전담
4. LangGraph 전환 시 `supervisor.py`의 로직이 StateGraph conditional edges로 자연 변환

## 근거

- `cohort_pipeline.py`가 이미 Supervisor 역할 수행 → 이름과 역할 일치시킴
- RFC-005 Phase E (LangGraph 전환)와 자연스럽게 연결
- Agent Reference 문서상 6개 Agent 명명과 일관성 확보
- 단일 모듈이 오케스트레이션 전담 → 테스트/디버깅 용이

## 영향

### 수정 대상

| 파일                              | 변경                                               |
| --------------------------------- | -------------------------------------------------- |
| `src/pipeline/supervisor.py`      | `run()` 메서드 추가, 전체 오케스트레이션 로직 흡수 |
| `src/pipeline/cohort_pipeline.py` | thin wrapper로 축소 또는 삭제                      |
| `src/pipeline/orchestrator.py`    | supervisor 호출로 변경                             |
| `src/pipeline/__init__.py`        | export 변경                                        |

### 마이그레이션 전략

```
Phase 1 (현재): supervisor.py = quality gate only ✅
Phase 2 (완료): supervisor.py에 run() 추가, pipeline.run() → supervisor.run() 위임 ✅ (2026-03-12)
Phase 3 (W7+): LangGraph StateGraph로 전환, supervisor.py가 graph builder
```

### 하위 호환성

- `pipeline.run()` 인터페이스 유지 (내부적으로 supervisor 호출)
- 벤치마크 스크립트(`benchmark_v5.py`)는 Agent를 직접 호출하므로 영향 없음
