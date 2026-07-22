# Task: NCT → PubMed PMID 연결

## 1. Specification (Strict)
- **Input**: `nct_id: str` (e.g., "NCT01179048")
- **Output**: `List[str]` (PMIDs, e.g., ["23953384", "27295427"])
- **Logic**:
  1. ClinicalTrials.gov API v2에서 `referencesModule.references[]` 조회
  2. 이미 PMID가 포함되어 있는 경우 직접 추출
  3. 없는 경우 PubMed E-utilities `esearch.fcgi`로 NCT ID 검색
  4. "design" 또는 "protocol" 키워드가 포함된 논문 우선 순위 부여

## 2. TDD Strategy
- [x] Test Case A: NCT01179048 → PMID list (cached mock response)
- [x] Test Case B: Invalid NCT ID → empty list
- [x] Test Case C: referencesModule에 PMID 직접 포함된 케이스

## 3. Implementation Log
- 13:20: Test Created (Fail)
- 13:25: Implementation Code Written
- 13:27: Test Passed

## 4. Final Status
- [DONE]
