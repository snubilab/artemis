# RFC-010: Reranker Cross-Branch Concept Recall 개선

**상태**: 검토 중  
**날짜**: 2026-03-03  
**제안자**: @kyh

## 1. 가설 및 목표

Agent2 파이프라인에서 **Reranker(LLM top-N 선택)가 OMOP cross-branch 관련 concept을 탈락**시키는 문제를 해결한다.

### 발견 경위

TROY GOLD benchmark E-1 (No T1DM) rule에서 Recall=19%로 측정됨. 원인 추적:

```
[Step 1] Vector Search (ChromaDB): 435216 (Disorder due to T1DM) → rank 6 ✅ 발견됨
[Step 2] UMLS Synonym Expansion: 동의어 추가 검색 → candidates 합침
[Step 3] Reranker (LLM top-3):   435216 → ❌ 탈락 (LLM이 top-3에서 제외)
```

Reranker가 선택한 3개:

- `201254` Type 1 diabetes mellitus
- `4047906` Insulin dependent diabetes mellitus type 1A
- `4102018` Insulin dependent diabetes mellitus type 1B

**435216 (Disorder due to T1DM)**은 OMOP 계층상 **다른 가지**(Complication due to DM)에 위치하여, LLM이 "T1DM 자체가 아닌 합병증"으로 판단하고 제외.

```
                Diabetes mellitus (201820)
               ╱                          ╲
     Type 1 DM (201254)           Complication due to DM (442793)
      ↓ descendants만 확장              ↓ Reranker가 무시
     24개 하위 개념              Disorder due to T1DM (435216)
```

### KG Sibling 확장도 불가

기존 KG sibling 로직은 `min_levels_of_separation=1` (같은 부모)만 탐색하므로, 다른 부모 하위의 cross-branch concept은 도달 불가.

### 측정 기준

- E-1 (No T1DM) Recall: 19% → 목표 ≥80%
- 유사 패턴의 다른 rule (E-11 ESLD 등)에도 동일 개선 적용 가능

## 2. 제안 설계 (Proposed Design)

### 방안 A: top_n 증가 (최소 변경)

```python
# 현재: top_n=3
top_concepts = self.reranker.rerank_topn(search_context, candidates, top_n=3)

# 변경: top_n=5~7
top_concepts = self.reranker.rerank_topn(search_context, candidates, top_n=5)
```

- **장점**: 한 줄 변경
- **단점**: 불필요한 concept도 함께 증가 → Precision 하락 가능

### 방안 B: Exclusion context를 Reranker에 전달

현재 query가 `"Type 1 diabetes mellitus"`로만 전달됨. Exclusion 맥락 추가:

```python
# workflow.py에서 context 전달 시
search_context = f"Exclusion criterion: {query_text} — include all related conditions, complications, and subtypes"
```

- **장점**: LLM이 임상적 맥락 이해 → 합병증 계통도 선택
- **단점**: Inclusion과 Exclusion 분기 로직 필요

### 방안 C: Reranker 프롬프트 수정

```python
# 현재 프롬프트
"Select up to {top_n} OMOP Concept IDs from the candidates that best match the user's clinical intent."

# 수정 프롬프트
"Select up to {top_n} OMOP Concept IDs from the candidates that best match the user's clinical intent. "
"Include related complications, subtypes, and causally-related conditions (e.g., 'Disorder due to X' for disease X)."
```

- **장점**: 전체 파이프라인에 적용, 분기 불필요
- **단점**: Precision 하락 가능 (너무 많은 관련 concept 선택)

### 방안 D: Agent1 세분화 (장기)

Agent1이 "No T1DM" → `["Type 1 diabetes mellitus", "Complications of type 1 diabetes"]`로 분해.

- **장점**: 근본적 해결
- **단점**: Agent1 프롬프트 대규모 수정 필요, 다른 rule에도 영향

### 권장: B + A 조합

1. Exclusion/Inclusion context를 reranker에 전달 (B)
2. top_n을 3 → 5로 증가 (A)
3. 결과 측정 후 필요시 프롬프트 수정 (C)

### 왜 Logician/KG Expander가 아닌 Reranker인가

이 문제는 약물 복합제 분해와 **근본적으로 다른 성격**이다.

|          | 약물 분해 (Logician)    | 질환 확장 (이 문제)                     |
| -------- | ----------------------- | --------------------------------------- |
| **관계** | 구조적 (has_ingredient) | 의미적 (임상 판단)                      |
| **정답** | 명확 (성분 = 정답)      | 모호 (어디까지가 T1DM인가?)             |
| **DB**   | RxNorm에 명시적 정의    | OMOP에 cross-branch 관계 없음           |
| **경계** | 분명함                  | exclusion이면 넓게? inclusion이면 좁게? |

- **Logician**: 약물 `has_ingredient`만 조회 → Condition에는 해당 관계 없음
- **KG Expander sibling**: 같은 부모(depth=1)만 탐색 → cross-branch 도달 불가
- **Reranker**: 이미 Vector Search가 435216을 rank 6에서 찾고 있음. **찾은 것을 버리는 문제**이므로 Reranker에서 해결하는 것이 가장 자연스러움

결론: "어디까지 포함할 것인가"는 **LLM이 임상적 맥락(exclusion/inclusion)을 보고 판단**해야 하는 문제이므로, Reranker에 context를 전달하는 방안 B가 문제의 본질에 가장 부합한다.

- **Precision 하락**: top_n 증가 + 넓은 선택 → 무관한 concept 포함 가능
- **다른 rule 퇴행**: T1DM에 맞춘 변경이 다른 rule의 정확도를 떨어뜨릴 수 있음
- **LLM 비결정성**: 프롬프트 변경 시 기존에 잘 작동하던 rule도 결과가 달라질 수 있음

## 4. 해결되지 않은 질문 (Unresolved Questions)

- `40484648 (T1DM uncontrolled)`은 retriever top-30에도 없음 → 인덱싱 누락? 비표준 concept?
- 다른 exclusion rule (E-11 ESLD, E-12 transplant)에도 동일한 cross-branch 패턴이 있는지 체계적 분석 필요
- top_n 증가가 전체 benchmark Avg F1에 미치는 영향 사전 측정 필요

## 5. 타임라인 (Timeline)

- 프로토타이핑: 방안 A (top_n=5) 즉시 테스트 가능
- 방안 B 구현: ~2시간 (context 전달 로직)
- 전체 benchmark 재측정: ~1시간
- 실제 적용: 다음 실험 사이클에서 검증
