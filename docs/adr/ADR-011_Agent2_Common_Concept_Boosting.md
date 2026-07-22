# ADR-011: Agent 2 Common Concept Boosting 전략

**상태**: 승인됨  
**날짜**: 2026-02-10  
**의사결정자**: @kyh

## 컨텍스트
Agent 2의 OMOP Concept 매핑에서 임상적으로 표준인 코드(LOINC Measurement, Core SNOMED Procedure)가 
유사한 이름의 비표준 코드에 밀려 선택되지 않는 문제가 반복적으로 발생했다.

- "Oxygen therapy" (4239130)가 "Oxygen therapy management"에 밀림
- "Total bilirubin" (3024128)이 specific LOINC panel code에 밀림
- "Calcitonin" (3010989)가 유사 measurement code에 밀림

기존 방식(Vector Search + LLM Reranker)만으로는 "임상적 빈도/표준성"이라는 도메인 지식을 반영할 수 없었다.

## 결정
**데이터 기반 Common Concept Boosting** 전략을 도입한다.

1. **DB 통계 자동 생성**: `scripts/generate_concept_stats.py`가 OMOP CDM(Synthea/MIMIC)의 
   `measurement`, `procedure_occurrence`, `condition_occurrence`, `drug_exposure` 테이블에서 
   빈출 concept의 빈도를 추출하고, 로그 스케일 가중치를 계산하여 
   `src/agents/agent2/resources/concept_priority_db.json`에 저장한다.

2. **Default 설정 파일**: 임상적으로 반드시 우선되어야 할 핵심 코드(6개)는 
   `src/agents/agent2/resources/concept_priority_defaults.json`에 별도 관리한다.

3. **Retriever 로딩**: `ConceptRetriever.__init__`에서 두 파일을 모두 로드하여 
   `self.concept_weights` 딕셔너리로 통합한다. 중복 시 더 강한 boost(min)를 채택한다.

4. **검색 시 적용**: `search()` 메서드에서 `adjusted_score`에 가중치를 더하여 순위를 조정한다.

5. **Retriever Top-1 강제 포함**: `workflow.py`의 `_slow_path`에서 Reranker 결과와 별도로 
   Retriever 1위 후보를 Seed에 강제 포함한다.

## 근거
- **고려한 대안 1 (Hardcoded Dictionary)**: 소스 코드 내 딕셔너리로 관리 → 확장성/유지보수성 부족. 폐기.
- **고려한 대안 2 (LLM Prompt 강화)**: Reranker 프롬프트에 "표준 코드 우선" 지시 → 비결정적. 보류.
- **선택한 이유**: DB 통계 기반이므로 데이터가 바뀌면 자동 갱신 가능. 설정 파일 분리로 코드 변경 없이 조정 가능.

## 영향
- 수정된 파일: `retriever.py`, `workflow.py`
- 추가된 파일: `generate_concept_stats.py`, `concept_priority_db.json`, `concept_priority_defaults.json`
- TROY Score: Full Match 11 → 24 (+13), Wrong 32 → 12 (-20)
- 추가 작업: DB가 변경(MIMIC 등)되면 `generate_concept_stats.py` 재실행 필요
