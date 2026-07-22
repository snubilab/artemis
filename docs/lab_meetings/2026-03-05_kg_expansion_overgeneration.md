# Lab Meeting: KG Expansion 과잉 확장 해결

**날짜**: 2026-03-05
**참여 모델**: Claude, Codex (gpt-5.3-codex-spark)
**Gemini**: CLI 오류로 불참 (2-모델 검증)

## 안건

Agent 2의 KG Expansion이 descendants를 직접 나열하여 concept 수가 6x 폭발 (GOLD ~217 → Agent 2 ~1,300). Precision 저하 + WebAPI Timeout (1800초 초과) 유발.

## 제안 요약

| 모델   | 핵심 제안                                                                                      | 주요 근거                                                    |
| ------ | ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| Claude | `ancestor_only` 모드 도입. descendants 나열 제거, ancestor/ingredient만 반환. Critic 불필요화. | TROY 방식과 일치. includeDescendants에 위임.                 |
| Codex  | 4-phase 접근: anchor 모드 + includeDesc 정책 + relation-level caps + aggressive consolidator.  | 단계적 롤아웃으로 리스크 최소화. 환경변수로 A/B 테스트 가능. |

## 합의 (✅ 2/2 동의)

### 핵심 결정

1. **KG Expansion → Anchor-Only 모드 도입** (✅ 합의)
   - descendants를 직접 나열하지 않음
   - ancestor, sibling, maps_to 후보만 반환 (seed + 3-8개 anchors)
   - `includeDescendants: true`로 WebAPI에 descendant 확장 위임

2. **역할 분담 재정의** (✅ 합의)
   - KG Expander = "어떤 concept을 seed로 쓸지" (semantic recall)
   - Circe `includeDescendants` = "실행 시 descendants 펼치기" (SQL-level)

3. **Domain-aware concept cap** (✅ 합의)
   - Condition/Procedure: max 50 (seed ≤ 2일 때), 30 (seed > 2)
   - Drug: max 20
   - Measurement/Device: max 15
   - Hard global cap: 120
   - Relation-level: ancestors=8, siblings=6, maps_to=4

4. **Consolidator aggressive LCA** (✅ 합의, Phase 2)
   - Agent 2 전용 `max_separation=8` aggressive 모드
   - pairwise/clustered merge 허용
   - 너무 generic한 ancestor (IC < 6.0) 머지 방지

### 환경변수 (Rollout 제어)

| 변수                         | 기본값            | 설명                                         |
| ---------------------------- | ----------------- | -------------------------------------------- |
| `KG_EXPAND_MODE`             | `clinical_anchor` | `clinical_anchor` (신규) / `clinical` (기존) |
| `KG_CONSOLIDATOR_AGGRESSIVE` | `false`           | Agent 2 전용 aggressive merge                |

## 예상 효과

| 메트릭             | Before         | After (예상)                      |
| ------------------ | -------------- | --------------------------------- |
| 전체 concept 수    | ~1,300         | ~100-200                          |
| hypertension       | 104            | 1-3                               |
| Stroke             | 100            | 2-5                               |
| WebAPI cohort 시간 | >1800s timeout | < 120s                            |
| Recall             | 83.1%          | ≥ 83.1% (includeDescendants 커버) |
| Precision          | 낮음           | 대폭 개선                         |
| Critic LLM 호출    | 56회           | 0-10회                            |

## 리스크 및 완화 방안

| 리스크                                             | 완화                                           |
| -------------------------------------------------- | ---------------------------------------------- |
| Ancestor가 너무 generic (e.g., "Clinical Finding") | IC > 8.0 하한 + concept_class_id 필터 유지     |
| 벤치마크 Recall 변화                               | includeDescendants 시뮬레이션 포함한 비교 필요 |
| Edge case: ancestor 없는 concept                   | seed 그대로 반환 (기존 fallback 유지)          |
| 기존 파이프라인 호환                               | `KG_EXPAND_MODE` env var로 즉시 rollback 가능  |

## 실행 계획

- [ ] Phase 1: `kg_expander.py`에 `clinical_anchor` 모드 추가 (descendants 제거)
- [ ] Phase 1: `workflow.py` 라우팅 변경 (`KG_EXPAND_MODE` env var)
- [ ] Phase 1: Critic skip 로직 (anchor 수 ≤ 10이면 skip)
- [ ] Phase 2: domain-aware `includeDescendants` 정책 (`RegisteredConcept` 확장)
- [ ] Phase 3: relation-level caps + global hard cap 120
- [ ] Phase 4: Consolidator aggressive LCA (Agent 2 전용)
- [ ] 검증: GOLD remap 재실행 → concept 수 + WebAPI 실행 시간 확인
- [ ] 검증: 벤치마크 Recall 유지 확인 (M-TROY ≥ 83.1%)

## 부록: 원본 제안 및 리뷰

> 상세 내용은 `tmp/lab_meeting/20260305_kg_expansion_overgeneration/` 참조
