# RFC-008: UMLS CUI Bridging for Clinical Synonym Resolution

**상태**: 검토 중  
**날짜**: 2026-03-02  
**제안자**: @kyh

## 1. 가설 및 목표

Agent 2의 ChromaDB vector search는 **표면 텍스트 유사도**에 의존하므로, 임상적 동의어 관계 (e.g., "acute decompensation of glycemic control" → "diabetic ketoacidosis")를 해소하지 못한다.

**가설**: UMLS의 CUI 관계 그래프를 bridging layer로 활용하면, 텍스트가 다르지만 의미적으로 동일한 concept을 포착하여 Agent 2의 recall을 높일 수 있다.

**성공 기준**: Exp D의 Empty TROY rules (acute decompensation, drug dependence) → overlap > 0 달성

## 2. 제안 설계 (Proposed Design)

### 2.1 3-Step Bridging Pipeline

```
Agent 1 entity_text
    │
    ▼
┌──────────────────────────────┐
│ Step 1: UMLS Text → CUI      │ UMLS REST API /search
│ "acute decompensation of..."  │ → CUI: C0235471 등
└──────────────────────────────┘
    │
    ▼
┌──────────────────────────────┐
│ Step 2: CUI → Related CUIs   │ UMLS /CUI/{CUI}/relations
│ has_manifestation, is_a 탐색  │ → C0011881 (DKA)
└──────────────────────────────┘
    │
    ▼
┌──────────────────────────────┐
│ Step 3: CUI → OMOP Concept   │ Local Athena DB
│ SNOMED concept_code 매칭      │ → concept_id: 443727
└──────────────────────────────┘
    │
    ▼
기존 ChromaDB 결과와 UNION
```

### 2.2 Step 별 구현

#### Step 1: UMLS Search
```python
import requests

UMLS_API_KEY = os.environ["UMLS_API_KEY"]
BASE = "https://uts-ws.nlm.nih.gov/rest"

def search_umls(text: str, sabs: str = None) -> list[str]:
    """텍스트 → UMLS CUI 리스트"""
    params = {
        "string": text,
        "apiKey": UMLS_API_KEY,
        "pageSize": 10,
    }
    if sabs:
        params["sabs"] = sabs  # e.g., "SNOMEDCT_US"
    resp = requests.get(f"{BASE}/search/current", params=params)
    results = resp.json().get("result", {}).get("results", [])
    return [r["ui"] for r in results if r["ui"] != "NONE"]
```

#### Step 2: CUI Relation Traversal
```python
def get_related_cuis(cui: str, max_depth: int = 2) -> set[str]:
    """CUI의 has_manifestation, is_a 관계 탐색"""
    related = set()
    queue = [(cui, 0)]
    visited = {cui}
    
    while queue:
        current, depth = queue.pop(0)
        if depth >= max_depth:
            continue
        resp = requests.get(
            f"{BASE}/content/current/CUI/{current}/relations",
            params={"apiKey": UMLS_API_KEY}
        )
        for rel in resp.json().get("result", []):
            rel_type = rel.get("additionalRelationLabel", "")
            target_cui = rel.get("relatedId", "").split("/")[-1]
            if rel_type in ("has_manifestation", "is_a", "mapped_to", 
                           "has_finding_site", "causative_agent_of"):
                if target_cui not in visited:
                    visited.add(target_cui)
                    related.add(target_cui)
                    queue.append((target_cui, depth + 1))
    return related
```

#### Step 3: CUI → OMOP via Athena DB
```sql
-- 방법 A: SNOMED concept_code 매칭
SELECT c.concept_id, c.concept_name
FROM {schema}.concept c
WHERE c.vocabulary_id = 'SNOMED'
  AND c.concept_code IN (
    -- UMLS atoms에서 SNOMEDCT_US source의 code 추출
    SELECT snomed_code FROM umls_cui_to_snomed_mapping
  )
  AND c.standard_concept = 'S';

-- 방법 B: concept_synonym 테이블 활용
SELECT c.concept_id, c.concept_name
FROM {schema}.concept_synonym cs
JOIN {schema}.concept c ON c.concept_id = cs.concept_id
WHERE cs.concept_synonym_name ILIKE '%diabetic ketoacidosis%'
  AND c.standard_concept = 'S';
```

### 2.3 Agent 2 통합 위치

```python
# src/agents/agent2/workflow.py — retrieve 단계 후
def resolve_concepts(entity_text, domain):
    # 1. 기존 ChromaDB vector search
    chroma_ids = chromadb_search(entity_text)
    
    # 2. NEW: UMLS CUI bridging (fallback)
    if len(chroma_ids) < MIN_THRESHOLD:
        umls_cuis = search_umls(entity_text)
        related_cuis = union(get_related_cuis(c) for c in umls_cuis)
        bridged_ids = cuis_to_omop(related_cuis)
        chroma_ids = chroma_ids | bridged_ids
    
    return chroma_ids
```

## 3. 예상되는 리스크 (Potential Risks)

| 리스크 | 심각도 | 대응 |
|---|:---:|---|
| UMLS API rate limit (20 req/sec) | 중 | 캐싱 + 배치 처리 |
| Relation traversal 폭발 (과도한 관련 CUI) | 고 | max_depth=2, 관계 유형 필터링 |
| UMLS API key 필요 (유료화 가능성) | 저 | 학술 라이센스 무료 |
| 추가 latency (~500ms/CUI) | 중 | 병렬 처리 + 로컬 캐시 |

## 4. 해결되지 않은 질문 (Unresolved Questions)

1. UMLS의 어떤 relation types가 가장 효과적인가? (`has_manifestation` vs `is_a` vs `mapped_to`)
2. 로컬 UMLS Metathesaurus 설치가 API보다 나은가? (속도 vs 유지보수)
3. LLM-based synonym expansion (방법 1)과 성능 비교가 필요
4. OMOP vocabulary 테이블에 UMLS vocabulary가 포함되어 있는지 확인 필요

## 5. 타임라인 (Timeline)

| 단계 | 기간 | 산출물 |
|---|:---:|---|
| UMLS API 프로토타입 | 1주 | `src/agents/agent2/umls_bridge.py` |
| DKA 케이스 검증 | 2-3일 | Exp D overlap 테스트 |
| Agent 2 통합 | 1주 | workflow.py 수정 |
| Exp D v3 벤치마크 | 2-3일 | Consolidated Report 업데이트 |
