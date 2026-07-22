# RFC-003: Knowledge Graph RAG for Agent 2 Concept Expansion

**상태**: 검토 중  
**날짜**: 2026-02-10  
**제안자**: @kyh

## 1. 가설 및 목표

### 배경: 현재 Agent 2의 한계

현재 Agent 2는 **Vector Search (ChromaDB) → LLM Reranker** 파이프라인으로 동작한다. 
Abbreviation Expander + Drug Class Expander 추가 후에도 46개 TROY ConceptSet 중 **22건이 Wrong**이다.

| 실패 패턴 | 건수 | 예시 |
|----------|------|------|
| Multi-concept (1→N) | ~8 | "Stroke" → TROY는 10개 concept 필요 |
| Near-miss concept | ~6 | "Oxygen therapy management" vs "Oxygen therapy" |
| LOINC 세부 코드 선택 | ~4 | HbA1c의 여러 LOINC 변형 |
| Semantic reversal | ~1 | "Stable angina" vs "Unstable angina" |
| 기타 | ~3 | prefix 이슈, domain confusion |

**근본 원인**: Vector search는 **한 개의 가장 유사한 concept을 반환**한다. 그러나 전문가가 정의하는 ConceptSet은 **hierarchy를 따라 관련 concept을 수집한 그래프 구조**이다.

### 가설

> OMOP CDM의 `concept_ancestor`와 `concept_relationship` 테이블을 Knowledge Graph로 활용하여 
> vector search 결과를 **graph traversal로 확장**하면, multi-concept set 매핑 정확도를 유의미하게 향상시킬 수 있다.

### 성공 지표

- TROY 대비 **Full+Partial Match: 23 → 35+** (50% 이상 향상)
- **Wrong: 22 → 10 이하**
- Agent 2 단일 쿼리 처리 시간: **< 2초**

---

## 2. 제안 설계 (Proposed Design)

### 2.1 아키텍처 개요

```
Query Text
    │
    ├─ Step 0: Abbreviation Expansion (기존)
    ├─ Step 0b: Drug Class Expansion (기존)
    │
    ▼
[Vector Search] ──→ Top-K candidates (k=20)
    │
    ▼
[KG Expansion] ──→ 각 candidate의 graph neighborhood 수집
    │                ├─ Ancestors (concept_ancestor, sep ≤ 2)
    │                ├─ Descendants (concept_ancestor, sep ≤ 3)
    │                ├─ Siblings (같은 parent의 children)
    │                └─ Maps-to (cross-vocabulary mapping)
    │
    ▼
[Merged Candidate Pool] ──→ 중복 제거, 최대 50개
    │
    ▼
[LLM Critic] ──→ "이 query에 맞는 concept을 모두 선택하시오"
    │               ├─ Multi-select (1→N 지원)
    │               ├─ Negation-aware ("unstable" ≠ "stable")
    │               └─ Context-aware (domain, severity)
    │
    ▼
Final Concept IDs (복수)
```

### 2.2 KG Expansion 모듈

```python
class KGExpander:
    """
    OMOP Knowledge Graph를 활용한 concept 확장.
    concept_ancestor (pre-computed transitive closure)를 주로 사용.
    """
    
    def expand(self, concept_id: int, strategy: str = "clinical") -> List[int]:
        """
        주어진 concept_id를 중심으로 관련 concepts를 확장.
        
        Strategies:
        - "descendants": 하위 개념만 (e.g., Stroke → Cerebral hemorrhage, ...)
        - "siblings": 같은 parent 아래 형제 개념
        - "clinical": descendants + siblings + maps_to (default)
        """
        
    def get_descendants(self, concept_id: int, max_sep: int = 3) -> List[int]:
        """concept_ancestor에서 descendant 조회"""
        # SELECT descendant_concept_id FROM concept_ancestor
        # WHERE ancestor_concept_id = :id AND min_levels_of_separation <= :max_sep
        
    def get_ancestors(self, concept_id: int, max_sep: int = 2) -> List[int]:
        """concept_ancestor에서 ancestor 조회"""
        
    def get_siblings(self, concept_id: int) -> List[int]:
        """같은 parent를 공유하는 sibling 조회"""
        # 1. Find parent: concept_ancestor WHERE descendant = :id AND sep = 1
        # 2. Find siblings: concept_ancestor WHERE ancestor = :parent AND sep = 1
        
    def get_maps_to(self, concept_id: int) -> List[int]:
        """concept_relationship에서 'Maps to' 관계 조회"""
```

### 2.3 LLM Critic (Multi-Select Reranker)

기존 reranker는 **단일 best concept**을 선택한다. KG-RAG에서는 **복수 선택**이 필요하다.

```python
CRITIC_PROMPT = """
당신은 OMOP CDM 전문가입니다.
아래 clinical query에 해당하는 OMOP concept을 **모두** 선택하시오.

Query: "{query_text}"
Context: "{context}"

후보 concepts:
{candidates_table}

규칙:
1. query와 직접 관련된 concept을 모두 선택하시오 (복수 선택 가능)
2. "unstable"과 "stable", "acute"와 "chronic" 등 부정어/수식어를 구분하시오
3. Drug class query의 경우 개별 ingredient를 모두 선택하시오
4. Measurement query의 경우 LOINC Standard concept을 우선하시오

선택한 concept_id를 JSON array로 반환: [id1, id2, ...]
"""
```

### 2.4 DB 성능 최적화

현재 DB 상태:

| 테이블 | 행 수 | 인덱스 |
|--------|-------|--------|
| concept | 6,328,777 | `xpk_concept` (PK), `idx_syn_concept_name` |
| concept_relationship | 39,273,730 | 없음 ⚠️ |
| concept_ancestor | 75,689,500 | `idx_ca_anc` (ancestor_concept_id만) |

**필수 인덱스 추가:**

```sql
-- concept_ancestor: descendant 기준 조회용 (sibling 탐색)
CREATE INDEX idx_ca_desc ON synthea_cdm.concept_ancestor(descendant_concept_id);

-- concept_ancestor: 복합 인덱스 (ancestor + sep 조건)
CREATE INDEX idx_ca_anc_sep ON synthea_cdm.concept_ancestor(
    ancestor_concept_id, min_levels_of_separation
);

-- concept_relationship: source concept 기준 조회
CREATE INDEX idx_cr_c1 ON synthea_cdm.concept_relationship(
    concept_id_1, relationship_id
);

-- concept: standard concept 필터링용
CREATE INDEX idx_concept_std ON synthea_cdm.concept(
    standard_concept, domain_id
);
```

**대안: SQLite Export**

75M rows의 `concept_ancestor`를 매번 PostgreSQL로 조회하는 것은 비효율적이다.
자주 사용하는 Standard SNOMED/LOINC/RxNorm concept만 추출하여 **SQLite 캐시**를 만들면 ms 단위 조회가 가능하다.

```python
# 약 2M Standard concepts의 ancestor/descendant 관계만 추출
# → ~10M rows SQLite ≈ 200MB, 인덱스 포함 ~400MB
```

### 2.5 전체 파이프라인 변경

```
현재: Query → Abbreviation → DrugClass → Vector → Reranker(1개) → Result
제안: Query → Abbreviation → DrugClass → Vector → KGExpand → Critic(N개) → Result
```

**변경 파일:**

| 파일 | 변경 |
|------|------|
| `src/agents/agent2/kg_expander.py` | **[NEW]** KG Expansion 모듈 |
| `src/agents/agent2/critic.py` | **[NEW]** LLM Multi-Select Critic |
| `src/agents/agent2/workflow.py` | KG expansion + Critic 통합 |
| `src/agents/agent2/retriever.py` | 변경 없음 (기존 vector search 유지) |

---

## 3. 예상되는 리스크 (Potential Risks)

### 3.1 성능 리스크
- `concept_ancestor` 75M rows에서 조회 시 인덱스 없으면 **수십 초** 소요
- 해결: 인덱스 추가 또는 SQLite 캐시

### 3.2 Over-expansion 리스크
- "Stroke"의 descendant가 수백 개에 달할 수 있음 → LLM context window 초과
- 해결: `max_sep` 제한 (≤3), Standard Concept만 필터링, 최대 50개 cap

### 3.3 LLM Critic 비용
- 매 쿼리마다 LLM 호출 → latency + API cost 증가
- 해결: Fast path는 KG+Rule만 사용, Slow path에서만 Critic 호출

### 3.4 Synthea CDM Vocabulary 제한
- `synthea_cdm`이 최소 vocab만 포함할 경우 graph traversal 결과가 빈약
- 해결: `omop_vocab` 스키마에 인덱스 추가하여 full vocab 활용, 또는 vocab 통합

---

## 4. 해결되지 않은 질문 (Unresolved Questions)

1. **SQLite 캐시 vs PostgreSQL 인덱싱**: 어느 쪽이 운영/유지보수에 유리한가?
2. **LLM Critic 모델 선택**: GPT-4o-mini vs Claude Haiku — 비용과 정확도 tradeoff
3. **max_sep 최적값**: descendants를 몇 단계까지 확장할 것인가? (2? 3? domain별 차이?)
4. **Batch vs Single**: 46개 ConceptSet을 batch로 처리할 때의 최적 strategy
5. **Vocabulary 범위**: `synthea_cdm` vs `omop_vocab` — 어느 스키마의 concept_ancestor를 사용할 것인가?

---

## 5. 타임라인 (Timeline)

| Phase | 작업 | 예상 기간 |
|-------|------|----------|
| **Phase 1** | DB 인덱스 추가 + KGExpander 기본 구현 | 1일 |
| **Phase 2** | LLM Critic (multi-select) 구현 | 1일 |
| **Phase 3** | Workflow 통합 + TROY 재검증 | 0.5일 |
| **Phase 4** | SQLite 캐시 최적화 (필요 시) | 0.5일 |

---

## 부록: TROY 실패 케이스별 KG-RAG 적용 예시

### Example 1: "Stroke" → 10 concepts

```
Vector Search: "Stroke" → Completed stroke (ID=4099974)
KG Expand(4099974):
  ancestor(sep=1): Cerebrovascular disease (ID=381591)
  descendants(381591, sep≤3): 
    - Cerebral artery occlusion (372924) ✅
    - Cerebral embolism (373503) ✅  
    - Cerebral hemorrhage (376713) ✅
    - Subarachnoid hemorrhage (432923) ✅
    - Cerebral infarction (439847) ✅
    ...
Critic: query="Stroke" → [372924, 373503, 376713, 432923, 439847, ...]
```

### Example 2: "unstable angina" → 2 concepts

```
Vector Search: "unstable angina" → Stable angina (4119942) ← WRONG
KG Expand(4119942):
  siblings: Unstable angina (35207680) ✅, Preinfarction syndrome (315296) ✅
Critic: query="unstable angina" → [35207680, 315296] (Stable angina 제외)
```

### Example 3: "Hemoglobin A1c" → 1 LOINC concept

```
Vector Search: "Hemoglobin A1c" → 3034639 (LOINC, wrong variant)
KG Expand(3034639):
  maps_to: 3004410 (Hemoglobin A1c/Hemoglobin.total in Blood) ✅
  siblings: 3004410, 3034639, 36304734, ...
Critic: query="HbA1c lab test" → [3004410] (가장 표준적인 LOINC 선택)
```

---

## 6. Peer Review 결과 (2026-02-10)

### Reviewer 1: Perplexity (보수적)
- RFC 원안의 75M rows ad-hoc 쿼리는 인덱스 없으면 위험
- LLM Critic에 Few-shot CoT, JSON schema, Self-consistency 필요
- Caching, Error handling, Orphan concept 엣지 케이스 미고려 지적

### Reviewer 2: Gemini CLI (현실적) ← **채택**
- **Option A (PostgreSQL + 인덱싱) 강력 추천**
- 근거:
  1. 로컬 Docker, QPS < 1 — 극단적 최적화 불필요
  2. B-tree 인덱스로 < 10ms 가능 — "20s+" 우려는 인덱스 부재 시 한정
  3. NetworkX 1-2GB 메모리는 LLM Agent + ChromaDB 환경에서 낭비
  4. PostgreSQL이 이미 Source of Truth — 복잡성 최소화
- `standard_concept = 'S'` + `LIMIT` 조건으로 결과 폭증 방지

### 최종 결정: Option B (NetworkX In-Memory KG) — ADR-002

```
Vector Search → NetworkX KG Traversal (in-memory) → LLM Critic (multi-select)
```

**채택 이유**: 연구 실적(KG-RAG 논문 contribution), 기술 확장성(GNN 발전 경로), 시각화 가능  
**전제 조건**: Standard Concept만 로드, max_sep ≤ 3, LIMIT 50
