# ADR-002: Agent 2 KG-RAG 구현 전략 — Neo4j Knowledge Graph

**상태**: 승인됨  
**날짜**: 2026-02-10  
**의사결정자**: @kyh

## 컨텍스트

Agent 2의 Vector Search만으로는 해결할 수 없는 mapping 실패 22건이 남아있다.

| 실패 패턴 | 건수 | 근본 원인 |
|----------|------|----------|
| Multi-concept (1→N) | 8 | "Stroke" → 1개만 반환, TROY는 10개 필요 |
| Near-miss | 6 | "Oxygen therapy management" vs "Oxygen therapy" |
| LOINC 세부 코드 | 4 | HbA1c 여러 LOINC 변형 중 오선택 |
| Semantic reversal | 1 | "Stable angina" vs "Unstable angina" |

## 결정

**Neo4j 기반 Knowledge Graph RAG**를 채택한다.

OMOP CDM의 concept/concept_ancestor/concept_relationship을 Neo4j 그래프 DB로 로드하고, Cypher 쿼리로 graph traversal을 수행한다.

```
Vector Search (ChromaDB) → Neo4j KG Traversal (Cypher) → LLM Critic (multi-select)
```

이는 biomedical KG-RAG의 de facto 표준인 **KRAGEN** (Bioinformatics, 2024)과 동일한 아키텍처이다:
- KRAGEN: Neo4j (KG) + Weaviate (Vector) + GoT prompting
- ARTEMIS:  Neo4j (KG) + ChromaDB (Vector) + LLM Critic

## 근거

### 고려한 대안들

| Option | 설명 | 장점 | 단점 |
|--------|------|------|------|
| A. PostgreSQL 인덱싱 | 인덱스 추가 후 SQL 쿼리 | 구현 단순 | 논문 기여도 낮음, 그래프 분석 불가 |
| B. NetworkX In-Memory | Python 메모리 로드 | 가볍고 빠름 | 논문 레퍼런스 약함, 그래프 DB 아님 |
| **C. Neo4j (채택)** | 전용 그래프 DB | 표준 KG-RAG 스택, Cypher, 시각화 | Docker 서비스 추가 |

### 선택한 이유

1. **연구 표준**: Neo4j는 biomedical KG-RAG 논문의 de facto 표준 (KRAGEN 등)
2. **논문 contribution**: "Neo4j-based OMOP Knowledge Graph + RAG"는 강력한 차별점
3. **Cypher 쿼리**: SQL보다 graph traversal에 자연스럽고 표현력이 강함
4. **시각화**: Neo4j Browser로 concept 관계를 직접 탐색/시각화 → 논문 Figure 활용
5. **기술 확장성**: GNN, Graph Embeddings, Community Detection으로 자연스럽게 발전

### 토론 이력
- **Perplexity**: Neo4j + Weaviate 조합을 연구 표준으로 확인
- **Gemini CLI**: PostgreSQL 추천했으나, 로컬 환경 최적화 관점
- **사용자 결정**: 연구 실적 + 기술 표준 → Neo4j 채택

## 영향

- **Docker**: `docker-compose.yml`에 Neo4j 서비스 추가
- **추가 파일**: `scripts/load_omop_to_neo4j.py` (PostgreSQL → Neo4j ETL)
- **추가 파일**: `src/agents/agent2/kg_expander.py` (Neo4j Cypher 쿼리)
- **추가 파일**: `src/agents/agent2/critic.py` (LLM multi-select)
- **수정 파일**: `src/agents/agent2/workflow.py` (KG expansion 통합)
