# RFC-006: Vocabulary-Based Drug Class Expansion

**상태**: 검토 중  
**날짜**: 2026-02-28  
**제안자**: @kyh

## 1. 가설 및 목표

Agent 2의 drug class 매핑이 하드코딩 dictionary에 의존하면 **unseen drug class에 일반화 불가**하고, 벤치마크 성능이 dictionary 커버리지에 종속된다. 

OMOP vocabulary의 ATC classification 계층과 `concept_ancestor` 테이블을 활용하면, **모든 약물 클래스를 자동으로 개별 ingredient로 확장**할 수 있다.

### 성공 측정 기준
- V5 벤치마크에서 drug class rule (GLP1-RA, DPP-4, Insulin 등)의 Recall ≥ 80%
- 하드코딩 dictionary 제거 (또는 fallback으로만 유지)
- 5개 이상 unseen drug class에서 정상 동작 확인

### ATC Classification 계층 구조

WHO ATC (Anatomical Therapeutic Chemical) classification은 5단계 계층으로 약물을 분류한다.

```
ATC 1st (14건)  : A — Alimentary tract and metabolism (해부학적 대분류)
 └ ATC 2nd (94건) : A10 — Drugs used in diabetes (치료 소분류)
   └ ATC 3rd (271건): A10B — Blood glucose lowering drugs (약리학적 소분류)
     └ ATC 4th (936건): A10BJ — GLP-1 receptor agonists (화학적 소분류) ← 이 레벨 사용
       └ ATC 5th (5905건): A10BJ01 — exenatide (개별 약물)
                           A10BJ02 — liraglutide
                           A10BJ05 — dulaglutide
                           A10BJ06 — semaglutide
```

**ATC 4th level**이 drug class expansion의 핵심:
- "DPP-4 inhibitor" = ATC 4th `A10BH` → 하위에 sitagliptin, linagliptin 등 8개 ingredient
- "GLP-1 receptor agonist" = ATC 4th `A10BJ` → 하위에 exenatide, liraglutide 등 6개 ingredient
- `concept_ancestor` JOIN으로 ATC 4th → RxNorm Ingredient 자동 확장 가능

## 2. 제안 설계

### 2.1 현재 구조 (dictionary 기반)

```
Agent 1 output: "GLP1-RA"
  → drug_class_expander.detect_drug_class("GLP1-RA")
  → alias lookup → None (미등록)
  → fallback → ChromaDB "GLP1-RA" 검색 → GLPG-3970 (오답)
```

### 2.2 제안 구조 (vocabulary 기반)

```
Agent 1 output: "GLP1-RA"
  → Step 1: ChromaDB 검색 (vocabulary=ATC, class=ATC 4th)
       → "Glucagon-like peptide-1 (GLP-1) analogues" (A10BJ, ID=1123618)
  → Step 2: concept_ancestor 쿼리
       → 6 RxNorm Ingredients: exenatide, liraglutide, dulaglutide, ...
  → Step 3: 각 ingredient에 대해 기존 파이프라인 (descendants 포함)
```

### 2.3 실현 가능성 (검증 완료)

OMOP `synthea_cdm` DB에서 실제 쿼리로 검증:

| Drug Class | ATC Code | ATC 4th Concept | Ingredient 수 |
|---|---|---|:---:|
| GLP-1 receptor agonist | A10BJ | Glucagon-like peptide-1 analogues | 6 |
| DPP-4 inhibitor | A10BH | Dipeptidyl peptidase 4 inhibitors | 8 |
| SGLT2 inhibitor | A10BK | Sodium-glucose co-transporter 2 inhibitors | (확인 필요) |
| Statin | C10AA | HMG CoA reductase inhibitors | (확인 필요) |

쿼리:
```sql
SELECT c2.concept_name, c2.vocabulary_id
FROM concept c1
JOIN concept_ancestor ca ON c1.concept_id = ca.ancestor_concept_id
JOIN concept c2 ON ca.descendant_concept_id = c2.concept_id
WHERE c1.vocabulary_id = 'ATC' AND c1.concept_code = 'A10BJ'
  AND c2.concept_class_id = 'Ingredient'
  AND c2.vocabulary_id IN ('RxNorm', 'RxNorm Extension');
```

### 2.4 구현 위치

`src/agents/agent2/drug_class_expander.py` 수정:

```python
def expand_drug_class_via_vocab(query_text: str, db_conn) -> List[int]:
    """
    1. ChromaDB에서 ATC 4th level concept 검색
    2. concept_ancestor로 하위 RxNorm Ingredient 추출
    3. 각 ingredient의 concept_id 반환
    """
    # Step 1: ATC class 검색
    atc_candidates = retriever.search(
        query_text, 
        n_results=5, 
        domain_hint="Drug",
        vocabulary_filter="ATC",
        class_filter="ATC 4th"
    )
    
    if not atc_candidates:
        return []  # fallback to existing pipeline
    
    atc_concept_id = atc_candidates[0].concept_id
    
    # Step 2: concept_ancestor 쿼리
    cur = db_conn.cursor()
    cur.execute("""
        SELECT c2.concept_id
        FROM concept_ancestor ca
        JOIN concept c2 ON ca.descendant_concept_id = c2.concept_id
        WHERE ca.ancestor_concept_id = %s
          AND c2.concept_class_id = 'Ingredient'
          AND c2.vocabulary_id IN ('RxNorm', 'RxNorm Extension')
    """, (atc_concept_id,))
    
    return [row[0] for row in cur.fetchall()]
```

### 2.5 파이프라인 통합

```
process_with_details(query_text)
  ├─ Step 0a: abbreviation expansion
  ├─ Step 0b: drug class detection
  │   ├─ (현재) dictionary lookup → ingredient list → ChromaDB per ingredient
  │   └─ (제안) ChromaDB ATC search → concept_ancestor → ingredient concept_ids
  ├─ Step 1: complexity routing
  └─ ...
```

**변경 최소화**: `expand_drug_class()` 함수 내부만 교체. workflow.py 호출 코드 변경 없음.

## 3. 예상되는 리스크

| 리스크 | 심각도 | 대응 |
|--------|:---:|------|
| ChromaDB에 ATC concept가 인덱싱 안 됨 | High | ChromaDB 빌드 시 `vocabulary_id='ATC'` 포함 확인 |
| ATC 계층이 불완전 (일부 약물 누락) | Medium | concept_ancestor 외에 `concept_relationship` (Maps to) 병용 |
| "GLP1-RA" → ATC 검색 실패 (이름 불일치) | Medium | LLM reranker로 ATC concept 선택, 또는 UMLS synonym 확장 |
| DB 연결 의존성 추가 | Low | 기존 dictionary를 fallback으로 유지 |

## 4. 검증 결과 (Resolved Questions)

### Q1: ChromaDB에 ATC 포함 여부 → ❌ 포함되지 않음

```
ATC concepts: standard_concept='C' (Classification) → 6,897건
ChromaDB 필터: standard_concept='S' (Standard) → ATC 0건
```

ATC는 **Classification vocabulary**이므로 `standard_concept='S'` 필터에 걸려 ChromaDB에 인덱싱되지 않는다. 따라서 **ChromaDB 경유 불가** — 직접 SQL 검색 필요.

### Q2: ChromaDB에서 drug class 검색 정확도 → ❌ 완전 실패

| 검색어 | ChromaDB Top-1 | 정답 | 판정 |
|--------|---------------|------|:---:|
| `GLP1-RA` | GLPG-3970 (Ingredient) | GLP-1 analogues (ATC) | ❌ |
| `DPP-4` | DW-D-5 (Ingredient) | DPP-4 inhibitors (ATC) | ❌ |
| `GLP-1 receptor agonist` | glyceryl 1 MG | GLP-1 analogues | ❌ |
| `DPP-4 inhibitor` | daprodustat 4 MG | DPP-4 inhibitors | ❌ |
| `statin` | Statin not indicated (SNOMED) | HMG CoA reductase inhibitors | ❌ |
| `ACE inhibitor` | acetoin (Ingredient) | ACE inhibitors | ❌ |

ChromaDB는 drug class를 전혀 매핑하지 못한다. ATC가 인덱싱되어 있지 않으므로 당연한 결과.

### Q3: SNOMED hierarchy 적용 가능성 → ⚠️ 부분적

`cardiovascular disease`가 SNOMED에 정확한 이름으로 존재하지 않아 direct match 실패. `Disorder of cardiovascular system` (SNOMED ID: 49601007) 같은 다른 이름으로 존재할 수 있음. → **Drug 먼저 해결 후 별도 검토 필요.**

## 5. 수정된 설계 (Post-Verification)

### 핵심: ATC 전용 ChromaDB Collection

기존 `omop_concepts` collection은 `standard_concept='S'`만 포함하므로, **ATC 4th level 전용 collection을 추가**한다.

- Collection 이름: `atc_drug_classes`
- 크기: **936 documents** (ATC 4th level만)
- 빌드 시간: < 5초

### 벡터 검색 정확도 검증 (✅ 완료)

936건 collection에서의 검색 결과:

| 검색어 | Top-1 ATC Concept | Code | Dist | 판정 |
|--------|-------------------|:---:|:---:|:---:|
| `GLP1-RA` | Glucagon-like peptide-1 (GLP-1) analogues | A10BJ | 1.019 | ✅ |
| `DPP-4` | Dipeptidyl peptidase 4 (DPP-4) inhibitors | A10BH | 1.062 | ✅ |
| `ACE inhibitor` | ACE inhibitors, plain | C09AA | 0.195 | ✅ |
| `SGLT2 inhibitor` | SGLT2 inhibitors | A10BK | 0.490 | ✅ |
| `beta blocker` | Beta blocking agents | S01ED | 0.416 | ✅ |
| `sulfonylurea` | Sulfonylureas | A10BB | 0.092 | ✅ |
| `insulin` | Insulins and analogues (long-acting) | A10AE | 0.597 | ✅ |
| `HMG-CoA reductase inhibitor` | HMG CoA reductase inhibitors | C10AA | 0.038 | ✅ |

**8/8 정확 매칭** — dictionary/alias 없이 벡터 유사도만으로 drug class 인식 성공.

### 구현 흐름

```
Agent 1 output: "GLP1-RA" [Drug]
  → Step 1: atc_drug_classes collection 검색 (vector search)
       → "Glucagon-like peptide-1 (GLP-1) analogues" (A10BJ, ID=1123618)
  → Step 2: concept_ancestor 쿼리 (SQL)
       → 6 RxNorm Ingredients: exenatide, liraglutide, dulaglutide, ...
  → Step 3: 각 ingredient → descendants (기존 파이프라인)
```

### 구현 코드

```python
# drug_class_expander.py 에 추가

def expand_drug_class_via_vocab(query_text: str, db_conn) -> Tuple[Optional[str], List[int]]:
    """
    ATC ChromaDB + concept_ancestor 기반 drug class expansion.
    Dictionary fallback 없이 generalizable.
    """
    # Step 1: ATC collection에서 vector search
    atc_collection = get_chroma_client().get_collection("atc_drug_classes")
    results = atc_collection.query(
        query_texts=[query_text], n_results=1
    )
    
    if not results['documents'][0]:
        return None, []
    
    atc_name = results['documents'][0][0]
    atc_id = results['metadatas'][0][0]['concept_id']
    distance = results['distances'][0][0]
    
    # Distance threshold: > 1.2면 매칭 불확실 → skip
    if distance > 1.2:
        return None, []
    
    # Step 2: concept_ancestor → RxNorm Ingredient
    cur = db_conn.cursor()
    cur.execute("""
        SELECT c2.concept_id
        FROM concept_ancestor ca
        JOIN concept c2 ON ca.descendant_concept_id = c2.concept_id
        WHERE ca.ancestor_concept_id = %s
          AND c2.concept_class_id = 'Ingredient'
          AND c2.vocabulary_id IN ('RxNorm', 'RxNorm Extension')
    """, (atc_id,))
    
    ingredient_ids = [row[0] for row in cur.fetchall()]
    return atc_name, ingredient_ids
```

### 핵심 변경점

| 항목 | 기존 (dictionary) | 제안 (ATC ChromaDB) |
|------|-------------------|---------------------|
| Drug class 인식 | 하드코딩 alias dict | Vector similarity search |
| Ingredient 목록 | 하드코딩 list | concept_ancestor SQL |
| 새 drug class 지원 | 수동 추가 필요 | **자동** (OMOP vocab 업데이트 시) |
| 논문 validity | ❌ overfitting | ✅ generalizable |

### 남은 과제

1. `distance > 1.2` threshold 검증 — false positive 방지
2. `statin` → "Heparin group" (오답, dist=1.069) 케이스 대응 — reranking 또는 LLM judge 필요
3. `NSAID` → "Other opioids" (오답, dist=1.079) — 동일 이슈

## 6. 타임라인

1. **Phase 1** (0.5일): `populate_chromadb.py`에 ATC collection 빌드 추가
2. **Phase 2** (0.5일): `drug_class_expander.py`에 vocab 기반 함수 구현 + workflow 연결
3. **Phase 3** (0.5일): V5 벤치마크 재실행 + 결과 비교
