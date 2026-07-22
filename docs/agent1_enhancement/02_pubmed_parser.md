# Task: PubMed Full Text 파싱 (Eligibility Section)

## 1. Specification (Strict)
- **Input**: `pmid: str` 
- **Output**: `PubMedPaper` (abstract + extracted eligibility criteria section)
- **Logic**:
  1. PubMed E-utilities `efetch.fcgi`로 abstract 조회
  2. PMC ID 확인 후 full text 접근 시도
  3. Full text에서 "Eligibility Criteria" / "Inclusion" / "Exclusion" 섹션 LLM 파싱
  4. 파싱된 criteria를 structured list로 변환

## 2. TDD Strategy
- [ ] Test Case A: PMID → abstract 조회 (mock)
- [ ] Test Case B: Abstract에서 eligibility section 추출
- [ ] Test Case C: Full text 없는 경우 graceful fallback

## 3. Implementation Log
(pending)

## 4. Final Status
- [PENDING]
