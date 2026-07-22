# ADR-018: Neo4j Full Transitive Closure Loading

**상태**: 승인됨  
**날짜**: 2026-03-02  
**의사결정자**: @kyh

## 컨텍스트
`ancestor_climb()` 구현 중 Neo4j의 `desc_count`가 PostgreSQL과 불일치하는 문제 발견.

- `load_omop_to_neo4j.py`가 `concept_ancestor`의 `min_levels_of_separation BETWEEN 1 AND 3`으로만 로딩
- Neo4j에 partial graph만 존재 → ancestor별 descendant count가 실제보다 매우 작음
- IC 계산이 부정확하여 **무관한 ancestor가 선택되는 심각한 버그** 발생
  - 예: Cerebral infarction → "Traumatic or non-traumatic injury" (Neo4j desc=수백 → IC>8 통과)
  - 실제: PostgreSQL desc=17,351 → IC=7.31 → REJECT

## 결정
1. **Neo4j에 full transitive closure를 로딩한다** (`sep >= 1`, 제한 없음)
2. `ancestor_climb()`의 desc_count는 **PostgreSQL에서 직접 조회**하는 hybrid approach를 유지한다 (fallback 안전장치)
3. ETL 최적화: `CREATE` + batch 50K (fresh DB 전제, MERGE 불필요)
4. 컨테이너명을 `artemis-neo4j`로 통일한다

## 근거
- **정확한 IC 계산 필수**: ancestor_climb의 핵심 로직은 IC threshold 기반 필터링. desc_count가 부정확하면 전체 전략이 실패
- **데이터 규모 관리 가능**: sep 제한 해제 시 15M → ~20M relationships. Neo4j 디스크 ~3-4GB로 충분
- **Hybrid approach (PostgreSQL desc_count)**: Neo4j가 향후 다시 partial loading으로 돌아가더라도 정확한 IC 유지 가능
- **CSV bulk import 시도 → Cypher ETL 복귀**: `neo4j-admin import`에서 `:ID` 필드가 string으로 고정되어 기존 코드(integer concept_id 매칭)와 비호환

## 영향
- **수정 파일**:
  - `scripts/load_omop_to_neo4j.py` — sep 제한 해제, batch 50K, CREATE
  - `src/agents/agent2/kg_expander.py` — `_get_pg_descendant_counts()` 추가, `ancestor_climb()` hybrid approach
  - `docker-compose.yml` — 변경 없음 (이미 `artemis-neo4j`)
- **추가 작업**: ETL 재실행 필요 (~15-20분)
- **하위 호환성**: 기존 `expand()`, `get_ancestors()`, `expand_from_ancestors()`는 영향 없음
