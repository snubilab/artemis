# Lab Meeting: Benchmark Evaluation Strategy

**날짜**: 2026-03-02  
**참여 모델**: Claude, Codex (gpt-5.3-codex-spark)  
**Gemini**: 2회 실패 (exit code 1) → 2-모델 검증으로 전환

## 안건
ARTEMIS 벤치마크 평가 전략: Exp A (순수 매핑 테스트) vs Exp D (E2E 테스트) — 어느 것이 올바른 primary benchmark인가?

## 제안 요약

| 모델 | 핵심 제안 | 주요 근거 |
|------|----------|----------|
| Claude | **2-Tier 분리 운영**: Tier 1 = Exp A (mapping), Tier 2 = Exp D (emulation) | Construct validity: 각 tier가 하나의 측정 대상만 평가. Agent 1 noise 제거. |
| Codex | **동일 구조**: `A_map_direct` (mapping primary) + `Exp D` (emulation secondary) 분리 | 혼합하면 construct validity 파괴. ADR-017과 일관. |

## 합의 (✅ 2/2 동의)

### Decision 1: Primary Benchmark = Exp A 계열 (Mapping Accuracy)
- TROY rule name/entity_text를 **Agent 1 없이** 직접 Agent 2에 전달
- 새 실험명: **`Exp A_direct`** (기존 A/A'와 구분)
- 측정 대상: Agent 2의 순수 concept mapping 품질
- 매칭 방식: **1:1** (TROY rule 하나당 Agent 2 결과 하나)

### Decision 2: Secondary Benchmark = Exp D 계열 (Emulation Accuracy)
- NCT + PDF → Agent 1 (캐시) → Agent 2 → TROY 비교
- 측정 대상: 전체 파이프라인의 실제 작동 성능
- 매칭 방식: **N:1** (여러 Agent 1 rules → 하나의 TROY rule)
- 용도: 시스템 성능 보고, 개선 효과 추적

### Decision 3: prior CV disease 평가
- **Mapping (1:1)**: 구성 entity별 개별 평가 (MI, Stroke, Revascularization 등 각각)
- **Emulation (N:1)**: 현재 방식 유지 (union recall)
- 두 값을 **동시 보고**하여 병목 식별

### Decision 4: 지표 체계

| | Tier 1 (Mapping) | Tier 2 (Emulation) |
|---|---|---|
| **실험** | `Exp A_direct` | `Exp D v5+` |
| **입력** | TROY entity_text 직접 | NCT + PDF |
| **Agent 1** | ❌ 미사용 | ✅ 사용 (IR 캐시) |
| **매칭** | 1:1 (atomic) | N:1 (union) |
| **주요 지표** | Recall, Precision, F1 per rule | Avg Recall, Full/Partial/Wrong |
| **용도** | Agent 2 개선 방향 도출 | 시스템 성능 보고 |
| **결정성** | ✅ 완전 결정적 | ✅ 캐시로 결정적 |

## 반대 의견 기록
없음 — 2개 모델 완전 합의.

## 실행 계획
- [ ] `Exp A_direct` 벤치마크 스크립트 작성 (TROY entity_text → Agent 2 직접 매핑)
- [ ] prior CV disease 하위 entity 분해 평가 구현
- [ ] `BENCHMARK_CONSOLIDATED_REPORT.md`에 2-Tier 체계 반영
- [ ] 기존 A/A'는 부가 지표로 유지

## 부록: 원본 제안 및 리뷰
> 상세 내용은 `tmp/lab_meeting/20260302_benchmark_evaluation_strategy/` 참조
