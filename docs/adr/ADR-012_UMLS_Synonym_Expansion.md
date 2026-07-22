# ADR-012: UMLS MRCONSO.RRF 기반 Synonym Expansion

**상태**: 승인됨  
**날짜**: 2026-02-10  
**의사결정자**: @kyh

## 컨텍스트
Agent 2의 Wrong 12건 중 LOINC Name Mismatch 유형이 존재한다 (예: "HbA1c" ≠ "Hemoglobin A1c/Hemoglobin.total in Blood"). 기존 `abbreviation_expander.py`는 수동 딕셔너리(~150개)로만 약어를 확장하므로 커버리지가 부족하다.

- 기존 방식: 하드코딩된 약어 사전 (수동 관리, LOINC만 일부 커버)
- 요구사항: 모든 vocabulary에 대한 포괄적 동의어 확장

## 결정
UMLS Metathesaurus의 MRCONSO.RRF를 로컬 SQLite DB로 변환하여, Agent 2 Slow Path에서 **Multi-query synonym expansion**을 수행한다.

- 정적 테이블 추출이 아닌 UMLS DB를 런타임에 직접 쿼리
- 쿼리 → CUI 매칭 → 같은 CUI의 동의어 수집 → ChromaDB 멀티 검색
- OHDSI 관련 vocabulary만 필터 (SNOMED, LOINC, RxNorm, ATC, MeSH 등 15종)

## 근거
- **포괄적 커버리지**: 200+ source vocabularies, LOINC/SNOMED/RxNorm 동의어를 하나의 DB로
- **유지보수성**: UMLS 업데이트 시 스크립트 재실행만으로 갱신 가능
- **성능**: SQLite 인덱스 기반 조회 (~ms), 최대 3개 동의어로 제한
- **대안**: 정적 JSON 추출 → 불완전하고 수동 관리 부담

고려한 대안:
1. UMLS API 호출: 네트워크 지연, API rate limit
2. 정적 synonym JSON: 커버리지 부족, 수동 관리
3. **로컬 SQLite (채택)**: 오프라인 동작, 빠른 조회, 전체 커버리지

## 영향
- 추가 파일: `scripts/build_umls_sqlite.py`, `src/agents/agent2/umls_synonym_expander.py`
- 수정 파일: `src/agents/agent2/workflow.py` (Slow Path에 UMLS 확장 추가)
- 데이터 파일: `data/umls/mrconso.sqlite` (~500MB, git 미포함)
- UMLS 라이센스 필요 (NLM UTS 계정)
