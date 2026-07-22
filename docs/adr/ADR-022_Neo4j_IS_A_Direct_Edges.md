# ADR-022: Neo4j IS_A Direct Edges (CONCEPT_RELATIONSHIP 기반)

**상태**: 승인됨  
**날짜**: 2026-03-10  
**의사결정자**: @kyh

## 컨텍스트

기존 Neo4j KG는 CONCEPT_ANCESTOR의 full transitive closure (39.1M edges)를 `HAS_DESCENDANT` edge로 로드.
이 구조에서 `ancestor_climb()`이 조상의 모든 자손을 한번에 가져오면 토폴로지가 납작해져 overgeneration 발생.

- "모든 조상이 direct neighbor가 되어 topology가 납작해짐" (Lab meeting 2026-03-10)
- CHF (P=2%), MEN2 (P=1%), acute coronary (P=10%) 등 worst precision rules의 공통 원인

## 결정

1. **CONCEPT_RELATIONSHIP의 `Is a` edge만 Neo4j에 로드** (39M → 800K edges, 95% 감소)
2. **Variable-length path `[:IS_A*1..N]`으로 traversal depth 제어**
3. **CONCEPT_ANCESTOR는 PostgreSQL 직접 조회로 IC 계산에만 사용** (기존 hybrid approach 유지)
4. **새 컨테이너 `artemis-neo4j-v2` (7475/7688)에서 병렬 테스트**

## 근거

- CONCEPT_ANCESTOR는 transitive closure → edge로 쓰면 모든 조상이 1-hop neighbor
- CONCEPT_RELATIONSHIP `Is a`는 직접 부모-자식 관계만 → 실제 온톨로지 계층 구조 보존
- `ancestor_climb` descendant expansion이 `[:IS_A*1..3]`으로 제한되어 3-hop 이내만 반환
- IC 계산은 여전히 PostgreSQL CONCEPT_ANCESTOR에서 정확한 desc_count 사용

## 영향

- **수정 파일**:
  - `scripts/load_omop_to_neo4j_v2.py` — 새 ETL (IS_A + MAPS_TO)
  - `docker-compose.neo4j-v2.yml` — 새 컨테이너 정의
  - `src/agents/agent2/kg_expander.py` — 7개 Cypher 쿼리 IS_A 전환
- **검증 결과** (Cerebral infarction, concept_id=443454):
  - Ancestors: 5, Siblings: 30, Descendants: 50, Ancestor climb: 100
  - 모든 메서드 정상 동작 확인
- **추가 작업**: M-TROY 벤치마크로 Precision/Recall 비교 필요
