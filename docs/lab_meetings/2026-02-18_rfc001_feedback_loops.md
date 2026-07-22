# Lab Meeting: RFC-001 Pipeline Feedback Loops 타당성 검토

**날짜**: 2026-02-18  
**참여 모델**: Claude, Gemini (gemini-3-pro-preview), Codex (gpt-5.3-codex-spark)  
**검증 모드**: 2-모델 교차검증 (Gemini 리뷰 phase API 오류로 제외)

## 안건
RFC-001이 제안하는 5개 Feedback Loop (Mapping Sub-Supervisor 3개 + Extraction Agent 2개)가 기술적으로 타당한지, 그리고 구현 시 어떤 순서와 전략이 적절한지 결정한다.

## 제안 요약

| 모델 | 핵심 제안 | 주요 근거 |
|------|----------|----------|
| Claude | Loop 4의 SoC 위반 수정 필요. Partial success 지지. Loop 5 범위 축소 | Extraction에서 concept 확장은 Mapping의 책임. Circe JSON 일관성 |
| Gemini | **Agent 3 Silent Drop이 Loop 1 작동을 원천 차단**. Agent 3가 `failed_entities`를 명시적으로 반환해야 함 | `_has_valid_criteria()`가 CodesetId=0인 rule을 JSON에서 제거하므로 Agent 4가 감지 불가 |
| Codex | Loop 1/5 동시 1순위. MAX_RETRY 단계별 분리. BLOCKER/non-BLOCKER 실패 분류 | exponential backoff + jitter. severity 3단계 분류 |

## 교차 검증에서 발견된 문제점

### 1. 🔴 Agent 3 Silent Drop — Loop 1의 근본적 장애물 (Gemini 발견, Codex 검증)
- **현황**: `assembler.py`의 `_has_valid_criteria()`가 `CodesetId=0`인 inclusion rule을 JSON에서 **삭제**
- **결과**: Agent 4에 도달하는 JSON에는 실패한 rule이 없음 → Loop 1 트리거 불가
- **예외**: Primary Criteria는 필터링되지 않아 Loop 1 작동 가능

> [!CAUTION]
> **RFC-001 구현 전 반드시 Agent 3의 Silent Drop 로직을 수정해야 합니다.**
> 방안 A (합의): Agent 3가 `failed_entities` 리스트를 별도 반환하여 Pipeline 레벨에서 Loop 1 진입 판단

### 2. 🟡 세 제안 모두 현재 코드에 즉시 통합 불가 (Codex 리뷰)
- `cohort_pipeline` ↔ `cohort_executor` ↔ `agent3` 인터페이스 변경이 핵심 병목
- `RetryState`, `LoopResult` 등 새 모델이 `ir.py`에 부재
- `orchestrator.py`가 validation 실패 시에도 분석으로 진행하는 문제

### 3. 🟡 Claude의 `process_batch` 제안 — 이미 존재 (Codex 지적)
- `src/agents/agent2/workflow.py`에 `process_batch()` 이미 구현
- 다만 반환 형태가 엔티티-단위 정합성 보존에 부족 → 반환값 개선 필요

### 4. 🟡 Synthetic Fallback 제거 전략
- **합의**: 즉시 완전 제거 반대. `fallback_mode=always|never|on_debug` 정책형 플래그 도입
- 운영 기본값: `never` (정확한 실패 반환)
- 개발/테스트: `on_debug` 허용

## 최종 합의

### 결정 1: RFC-001 방향성 — ✅ 채택 (조건부)
5개 Loop의 전체 방향은 타당하나, **Agent 3 Silent Drop 수정이 선행 조건**.

### 결정 2: 구현 우선순위

| 순위 | 항목 | 근거 |
|------|------|------|
| **0** | **Agent 3 Silent Drop → Explicit Failure Report** | Loop 1의 전제 조건. 이것 없이는 Loop 1 작동 불가 |
| **1** | Loop 1 (Agent 4 → Agent 2 재매핑) | 가장 빈번한 오류 (CodesetId=0 ~20%), 최고 ROI |
| **2** | Loop 2 (Agent 4 → Agent 3 재조립) | Loop 1과 함께 구현하면 비용 최소 |
| **3** | Loop 4 수정안 (진단만, 확장은 Mapping) | Claude SoC 의견 + Codex severity 분류 적용 |
| **4** | Loop 3 (HITL stub: Gap Report) | 기존 `GapReport` 모델 재활용. LangGraph 전환 대비 |
| **5** | Loop 5 (에러 분류 + 로깅) | CDM 버전 차이는 현재 의미 제한적 (Codex 지적) |

### 결정 3: Retry 전략 — 단계별 분리
- Mapping 재매핑 (Loop 1): MAX_RETRY=2 (총 3회)
- Extraction 재시도 (Loop 4): MAX_RETRY=1 (총 2회)
- 동일 에러 반복 시 즉시 중단 (동형 반복 감지)

### 결정 4: Partial Success — 채택
- 실패 rule이 전체의 30% 미만이면 partial JSON 반환
- BLOCKER 유형 (스키마 정합성 붕괴, primary criteria 실패)은 전체 실패
- `PipelineResult`에 `completeness: float`, `skipped_rules: List[str]` 추가

### 결정 5: Loop 4 설계 수정
- Extraction Agent에서 concept 확장 **금지** (SoC 위반)
- Extraction은 **진단만** 수행 → 결과를 Mapping Sub-Supervisor에 피드백
- 이 피드백은 `orchestrator.py` 레벨에서 관리

### 결정 6: 신규 모델 정의 필요
```python
# ir.py에 추가할 모델
class HealResult(BaseModel):
    """Agent 3 self-heal 결과"""
    action: Literal["KEEP", "PARTIAL", "SKIP"]
    rule_name: str
    reason: str
    healed_rule: Optional[Dict] = None

class ExtractionDiagnostic(BaseModel):
    """Loop 4 진단 결과"""
    target_exists_in_db: bool
    target_patient_count: int
    comparator_exists_in_db: bool
    comparator_patient_count: int
    suggested_action: Literal["EXPAND_DESCENDANTS", "RELAX_EXPOSURE", "REMAP", "FAIL"]

class LoopResult(BaseModel):
    """재시도 루프 결과 추적"""
    status: Literal["SUCCESS", "PARTIAL", "FAILED"]
    attempts: int
    last_error: Optional[str] = None
    severity: Literal["BLOCKER", "RETRYABLE", "DEGRADED"] = "RETRYABLE"
```

## 반대 의견 기록

1. **Codex**: Loop 5를 1순위로 제안했으나, Codex 자체 리뷰에서도 CDM 버전 메타데이터가 현재 없다고 지적 → 5순위로 하향 합의
2. **Claude**: Loop 4에서 Extraction이 concept 확장하는 것을 SoC 위반으로 반대했으나, Codex는 "현재 구조에서 cohort_executor는 추출 시점의 역할이라 Circe JSON에 개입하지 않는다"고 반박 → 진단만 수행하되, 피드백은 orchestrator가 관리하는 절충안으로 합의

## 실행 계획
- [x] RFC-001 방향성 합의 완료
- [ ] **Phase 0**: Agent 3 `_has_valid_criteria()` → Explicit Failure Report 수정
- [ ] **Phase A**: `ir.py`에 `HealResult`, `ExtractionDiagnostic`, `LoopResult` 모델 추가
- [ ] **Phase B**: Loop 1 + 2 구현 (`cohort_pipeline.py` retry loop)
- [ ] **Phase C**: Loop 4 수정안 (진단 쿼리 + orchestrator 피드백)
- [ ] **Phase D**: Loop 3 HITL stub (GapReport → PipelineResult 연결)
- [ ] **Phase E**: Loop 5 에러 분류 로깅
- [ ] **Phase F**: Synthetic fallback → `fallback_mode` 정책 전환

## 부록: 원본 제안 및 리뷰
> 상세 내용은 `tmp/lab_meeting/20260218_rfc001_feedback_loops/` 참조
> - `proposal_claude.md`, `proposal_gemini.md`, `proposal_codex.md`
> - `review_codex.md` (Gemini 리뷰는 API 오류로 미수집)
