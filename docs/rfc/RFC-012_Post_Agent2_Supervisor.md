# RFC-012: Post-Agent2 Supervisor Quality Gate

**상태**: ✅ 구현 완료 (Phase 1)  
**날짜**: 2026-03-11  
**제안자**: @kyh  
**관련**: [RFC-005 Pipeline Feedback Loops](./RFC-005_Pipeline_Feedback_Loops.md)

## 1. 가설 및 목표

### RFC-005와의 관계

RFC-005는 **Agent 4 validation 이후** 실패한 entity를 재매핑하는 Feedback Loop을 정의한다 (Loop 1-3).
그러나 Agent 4에 도달하기 전, **Agent 2 직후**에 품질을 검사하면 더 빨리 문제를 잡을 수 있다.

| 위치                | RFC-005 (기존)        | RFC-012 (신규)                                     |
| ------------------- | --------------------- | -------------------------------------------------- |
| **시점**            | Agent 4 validation 후 | Agent 2 mapping 직후                               |
| **검사 대상**       | Circe JSON 유효성     | 매핑 품질 (seed count, domain)                     |
| **재시도 방법**     | 동일 query 재매핑     | **Query rewrite** (domain prefix, broadening)      |
| **파이프라인 위치** | Step 4-5 retry loop   | **Step 2.1** (Agent 2 → Supervisor → Consolidator) |

### 핵심 가설

> Post-Agent2 quality gate로 seed count < 2인 entity를 query rewrite로 재매핑하면,
> Agent 3/4 retry 없이도 매핑 성공률이 향상된다.

### 성공 측정 기준

| 지표                         | Baseline (E2E v1) | 목표 |
| ---------------------------- | ----------------- | ---- |
| LEADER E2E Recall            | 72.5%             | 75%+ |
| Empty mapping → retry 성공률 | —                 | 30%+ |
| 파이프라인 regression        | —                 | 0    |

## 2. 제안 설계 (Proposed Design)

### 2.1 아키텍처

```
Agent 1 → Agent 2 → [Step 2.1: Supervisor] → Consolidator → Agent 3 → Agent 4
                          │                        ↑
                          │  (retry weak entities)  │
                          └────────────────────────┘
```

### 2.2 Quality Gates (규칙 기반, No LLM)

| Gate                | 조건                                           | 동작                  |
| ------------------- | ---------------------------------------------- | --------------------- |
| **Empty**           | concept_ids = []                               | Query rewrite + retry |
| **Low Seeds**       | len(concept_ids) < MIN_SEED_COUNT (default: 2) | Query rewrite + retry |
| **Domain Mismatch** | 매핑 결과의 >50% domain ≠ domain_hint          | Query rewrite + retry |

### 2.3 Query Rewrite 전략

| 시도 | Rewrite                             | 예시                            |
| ---- | ----------------------------------- | ------------------------------- |
| 1차  | Domain prefix: `"{domain}: {text}"` | `"Procedure: organ transplant"` |
| 2차  | Broadening: `"types of {text}"`     | `"types of organ transplant"`   |

### 2.4 구현 파일

| 파일                              | 변경                                             |
| --------------------------------- | ------------------------------------------------ |
| `src/pipeline/supervisor.py`      | **[NEW]** PipelineSupervisor, SupervisorReport   |
| `src/pipeline/cohort_pipeline.py` | Step 2.1 추가, `_map_all_entities()` return 확장 |

### 2.5 환경 변수

| 변수                          | 기본값 | 설명                        |
| ----------------------------- | ------ | --------------------------- |
| `ENABLE_SUPERVISOR`           | `1`    | 0이면 비활성화              |
| `SUPERVISOR_MIN_SEEDS`        | `2`    | 최소 seed 수                |
| `SUPERVISOR_MAX_RETRIES`      | `2`    | entity당 최대 재시도        |
| `SUPERVISOR_DOMAIN_THRESHOLD` | `0.5`  | domain mismatch 비율 임계값 |

## 3. 검증 결과

### E2E LEADER Benchmark (2026-03-11)

| Version                    | R         | P         | F1        | Full   |
| -------------------------- | --------- | --------- | --------- | ------ |
| E2E v1 (before)            | 72.5%     | 61.5%     | 57.3%     | 10     |
| E2E v2 (+ domain_hint)     | 77.4%     | 59.7%     | 56.1%     | 11     |
| E2E v3 (+ hier. expansion) | 74.9%     | 64.2%     | 60.2%     | 10     |
| **E2E v4 (+ supervisor)**  | **77.6%** | **64.2%** | **60.5%** | **11** |

> Regression 없음. Supervisor 통합으로 F1 60.5% (최고 기록).

## 4. 향후 계획

| Phase   | 내용                                                  | 상태    |
| ------- | ----------------------------------------------------- | ------- |
| Phase 1 | Empty + Low Seeds gate + query rewrite retry          | ✅ 완료 |
| Phase 2 | Domain mismatch gate (concept metadata 기반)          | 🔜 예정 |
| Phase 3 | RFC-005 Loop 1-3과 통합 (LangGraph conditional edges) | ❌ W7+  |

## 5. 예상되는 리스크

| 리스크                          | 대응                                    |
| ------------------------------- | --------------------------------------- |
| Query rewrite가 noise 추가      | Retry 결과도 MIN_SEED_COUNT 검사        |
| Agent 2 호출 증가 (비용)        | 실패 entity만 선별 retry, MAX_RETRIES=2 |
| Supervisor 오판 (정상을 weak로) | MIN_SEEDS=2는 보수적 임계값             |
