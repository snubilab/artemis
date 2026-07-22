# RFC-004: Multi-Concept Expansion Strategy

**상태**: 검토 중
**날짜**: 2026-02-11
**제안자**: @kyh + Antigravity + Perplexity

## 1. 가설 및 목표
Agent 2의 12건 Wrong 중 5건은 "TROY가 10-46개 descendant 코드를 기대하는데 Agent 2가 1개 parent 개념만 반환"하는 문제. 이 문제를 해결하면 Wrong 12→7건으로 개선 가능.

**핵심 발견:** 이 문제는 Agent 2 (매핑)이 아니라 **Agent 3 (Circe JSON 조립)**에서 해결해야 한다.

## 2. 비판적 분석 (Options A-E)

### ❌ Option A: CONCEPT_ANCESTOR 자동 확장 (All descendants)
**Fatal flaw:** 잘못된 레이어에서 해결. Agent 2가 46개 ID를 직접 반환할 이유가 없음.
**Breaking edge case:** "Surgical procedure" → 수천 개 descendants로 폭발.

### ❌ Option B: Domain-constrained 확장
**Fatal flaw:** A와 동일. 잘못된 레이어.
**Breaking edge case:** Condition-Procedure 교차 개념 (예: "transplant"은 condition이자 procedure)

### ❌ Option C: LLM-guided 선택적 확장
**Fatal flaw:** 비용 (LLM 호출), 비결정적, 임상시험 재현성 위반.
**Breaking edge case:** 같은 쿼리를 두 번 돌리면 다른 결과.

### ⚠️ Option D: Concept class별 확장 깊이 설정
**거의 정답이지만 reframe 필요.** 확장 계산이 아닌 **includeDescendants 플래그 결정**으로 전환해야 함.

### ❌ Option E: TROY 참조 학습
**Fatal flaw:** TROY에 과적합. 다른 코호트 정의에 일반화 불가.

## 3. 제안 설계: `includeDescendants` Rule Engine in Agent 3

### 핵심 인사이트
OHDSI 표준 관행은 **parent concept + `includeDescendants=true`** 플래그 설정. ATLAS가 쿼리 시점에 자동 확장함.

```
TROY "Revascularization" = { conceptId: 4336464, includeDescendants: true }
  → ATLAS resolves → 46 specific procedure codes
```

따라서 Agent 2는 이미 올바른 parent를 찾고 있고, Agent 3가 Circe JSON 생성 시 includeDescendants를 설정하면 됨.

### Circe JSON Concept Set Expression
```json
{
  "items": [{
    "concept": { "CONCEPT_ID": 4336464, "CONCEPT_NAME": "Revascularization" },
    "includeDescendants": true,
    "includeMapped": true,
    "isExcluded": false
  }]
}
```

### includeDescendants 결정 규칙

| domain_id | concept_class_id | includeDescendants | 근거 |
|-----------|-----------------|-------------------|------|
| Procedure | Procedure | **true** (항상) | 시술은 하위 분류가 많음 |
| Condition | Clinical Finding | **true** (비-leaf일 때) | 진단 계층 구조 활용 |
| Drug | Ingredient | **true** | 성분 → 제품/조합 확장 |
| Drug | Clinical Drug | **false** | 이미 구체적 |
| Measurement | Lab Test | **false** | LOINC은 너무 specific |
| Device | - | **true** | 디바이스 계층 활용 |

### 안전장치 (Over-expansion 방지)
1. descendant 수 > 500일 경우 경고 플래그
2. domain_id 교차 필터링
3. non-standard concept 제외

## 4. 예상되는 리스크
- "Surgical procedure" 같은 극도로 넓은 부모 개념 → 무의미한 확장
  - **완화**: concept_class_id level 체크 + descendant count threshold
- Condition의 leaf vs non-leaf 판단 오류
  - **완화**: `CONCEPT_ANCESTOR`에서 descendant 수 0이면 leaf로 판단

## 5. 벤치마크 수정 필요

> [!IMPORTANT]
> 현재 `diagnose_agent2_gaps.py`는 Agent 2의 raw output과 TROY의 resolved (확장된) output을 비교 중.
> 공정한 비교를 위해 Agent 2 output도 includeDescendants 적용 후 비교해야 함.

## 6. 타임라인
- Agent 3 includeDescendants 룰 엔진 구현
- 벤치마크 스크립트를 resolved set 비교로 수정
- 수정 후 벤치마크 재실행
