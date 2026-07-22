# Agent2 Pipeline 분석: T1DM Case Study

## Case: E-1 "No Type 1 Diabetes Mellitus"

GOLD Recall = **19%** — 왜 낮은가?

---

## Pipeline Overview

```
Query: "Type 1 diabetes mellitus"

┌─────────────────────────────────────────────────┐
│  Step 1. Vector Search (ChromaDB)               │
│  query → OMOP concept 임베딩 유사도 검색        │
│  결과: 20 candidates                            │
│  435216 (Disorder due to T1DM) → rank 6 ✅      │
└──────────────────────┬──────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────┐
│  Step 2. UMLS Synonym Expansion                 │
│  query → local MRCONSO DB → CUI → 동의어       │
│  "Insulin-dependent diabetes mellitus" 등 3개   │
│  각 동의어로 추가 Vector Search → merge         │
│  결과: 20 + 8 = 28 candidates                   │
│  435216 여전히 position 6 ✅                     │
└──────────────────────┬──────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────┐
│  Step 3. LLM Reranker (top-3 선택)              │
│  "Select up to 3 concepts that best match       │
│   the user's clinical intent"                   │
│                                                 │
│  LLM 선택:                                      │
│    ✅ [201254] Type 1 diabetes mellitus          │
│    ✅ [4047906] IDDM type 1A                     │
│    ✅ [4102018] IDDM type 1B                     │
│    ❌ [435216] Disorder due to T1DM → 탈락!      │
└──────────────────────┬──────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────┐
│  Step 4. KG Expansion (Neo4j, clinical)         │
│  seed concepts → descendants<=3 + siblings +    │
│  maps_to + ancestors<=2 확장                    │
│  + (Condition/Procedure) ancestor_climb(IC>8)   │
│  그러나 435216은 seed 경로 밖(cross-branch)로   │
│  이번 case에서 최종 후보에 미포함                │
└──────────────────────┬──────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────┐
│  Step 5. LLM Critic (최종 필터링)               │
│  최종 concept 목록 확정                          │
│  435216 미포함 → Recall 저하                     │
└─────────────────────────────────────────────────┘
```

---

## 왜 Reranker가 435216을 탈락시키는가?

### OMOP 계층 구조

```
              Diabetes mellitus (201820)
             ╱                          ╲
   Type 1 DM (201254)          Complication due to DM (442793)
    ↓ 24 descendants                     ↓
   • IDDM type 1A               Disorder due to T1DM (435216)
   • IDDM type 1B                        ↑
   • Fulminant T1DM             ⚠️ 다른 가지 (cross-branch)
```

- `435216`은 201254의 **descendant가 아님**
- 부모가 다름: `201820` vs `442793` → **sibling도 아님**
- LLM 판단: "Disorder **due to** T1DM ≠ T1DM 자체" → 제외

### Reranker 프롬프트

```
System: You are an expert medical terminologist.
        Select up to 3 OMOP Concept IDs that
        best match the user's clinical intent.

User:   Clinical term: Type 1 diabetes mellitus
        Candidates: [20개 목록]
```

- **"best match"** → 정확 매칭 우선 → subtype(1A, 1B) 선택
- **top_n=3** → 3개 slot 소진 → 435216은 4번째로 밀림
- **exclusion context 없음** → "배제 조건이니 넓게 잡아라" 정보 부재

---

## UMLS Expansion 상세

```
입력: "Type 1 diabetes mellitus"

  ① get_cuis()
     MRCONSO exact match → CUI: C0011854

  ② get_synonyms_for_cui(C0011854)
     우선순위: ISPREF='Y' → 선호 vocabulary (SNOMED, MeSH, NCI...)
     결과:
       • "Insulin-dependent diabetes mellitus"
       • "Diabetes Mellitus, Insulin Dependent"
       • "Insulin Dependent Diabetes Mellitus"
                    ↓
  ③ 각 동의어로 ChromaDB 재검색 (병렬)
       • 7개 신규 concept 추가
       • 1개 신규 concept 추가
       • 0개 (중복)
```

**한계**: 동일 CUI의 동의어만 확장 → **cross-branch concept은 다른 CUI** → 도달 불가

---

## 개선 방안 (RFC-010)

| 방안                     | 변경                             | 효과             | 리스크         |
| ------------------------ | -------------------------------- | ---------------- | -------------- |
| **A. top_n 증가**        | `top_n=3 → 5`                    | 435216 포함 가능 | Precision 하락 |
| **B. Exclusion context** | query에 "배제 조건" 맥락 추가    | LLM이 넓게 선택  | 분기 로직 필요 |
| **C. 프롬프트 수정**     | "Include complications" 추가     | 전역 적용        | 과도한 확장    |
| **D. Agent1 세분화**     | "T1DM" + "Complications of T1DM" | 근본 해결        | 대규모 수정    |

**권장**: **B + A 조합** (exclusion context 전달 + top_n=5)
