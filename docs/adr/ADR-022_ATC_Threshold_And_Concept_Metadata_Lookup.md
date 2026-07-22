# ADR-022: ATC Drug Class Expansion Threshold & Concept Metadata DB Lookup

**상태**: 승인됨  
**날짜**: 2026-03-05  
**의사결정자**: @kyh

## 컨텍스트

E2E 파이프라인 디버깅 중 "Liraglutide"가 Lithium으로 잘못 매핑되는 버그를 발견했다.

### 문제 1: ATC Drug Class Expansion의 과도한 Distance Threshold

- `expand_drug_class_via_vocab()` 함수가 ATC ChromaDB에서 `distance_threshold=1.2`로 검색
- "Liraglutide"(개별 약물)가 ATC class "Lithium"에 dist=1.1137로 매칭 → threshold 통과
- early return으로 ChromaDB 개별 약물 검색을 완전히 건너뜀
- 결과: `[751246, 767410, 19124477]` (lithium 성분 3개 반환)

### 문제 2: Concept Metadata DB Lookup 부재 (`_register_concept_sets`)

- `_register_concept_sets()`에서 `concept_name=ms["name"]` (검색어 그대로 사용), `vocabulary_id="SNOMED"` (하드코딩)
- Agent 2가 잘못된 ID를 반환해도, 원래 검색어를 이름으로 붙이기 때문에 **이름-ID 불일치가 은폐**됨
- Circe JSON에 `CONCEPT_NAME:"Liraglutide"` + `CONCEPT_ID:751246(lithium)` 발생

## 결정

### 수정 1: ATC Distance Threshold 강화

- `distance_threshold` 기본값을 `1.2` → `0.9`로 변경
- 약물 클래스("GLP-1 RA" dist=0.64)는 정상 통과, 개별 약물("Liraglutide" dist=1.11)은 차단

### 수정 2: Concept Metadata DB Lookup 추가

- `_register_concept_sets()`에서 `_fetch_concept_metadata()` 도입
- SQLAlchemy `engine.connect()` + batch query(`concept_id = ANY(:ids)`)로 `concept_name`, `domain_id`, `vocabulary_id`, `concept_class_id`, `standard_concept` 조회
- `RegisteredConcept` 모델에 `concept_class_id`, `standard_concept` 필드 추가
- `assembler.py`에서 하드코딩 제거, 실제 DB 메타데이터 사용
- DB 실패 시 fallback 없이 예외 전파

### 수정 3: ID Lineage Logging 추가

- Agent 2의 `[LINEAGE]` 태그 로그를 retriever → reranker → decompose → slow_path → kg_expand → critic → FINAL 각 단계에 추가
- 향후 매핑 문제 발생 시 `grep LINEAGE`로 즉시 추적 가능

## 근거

- **Threshold 0.9 선택**: 실측 데이터 기반. 정상 drug class 쿼리는 dist < 0.7, 개별 약물은 dist > 1.0. 0.9는 이 경계를 안전하게 분리.
- **Fallback 제거**: placeholder 데이터가 오히려 더 위험 (이름-ID 불일치 은폐). DB가 없으면 명확히 실패하는 것이 나음.
- **Codex CLI (gpt-5.3-codex-spark, xhigh)** 리뷰 통과: import 이슈 없음, `ANY(:ids)` 패턴 기존 코드와 일관, 하위호환 확인.

## 영향

- 수정 파일:
  - `src/agents/agent2/drug_class_expander.py` — threshold 변경
  - `src/registry/models.py` — 필드 추가
  - `src/pipeline/cohort_pipeline.py` — `_register_concept_sets` + `_fetch_concept_metadata` 전면 교체
  - `src/agents/agent3/assembler.py` — 하드코딩 → 실제 값
  - `src/agents/agent2/workflow.py` — LINEAGE 로깅 추가
- 기존 벤치마크 스크립트: `RegisteredConcept` default 값으로 하위호환 유지
- DB 접근 필수: `_fetch_concept_metadata`가 DB 없으면 예외 발생
