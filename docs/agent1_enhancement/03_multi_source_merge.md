# Task: Agent 1 `parse_nct` 확장 (Multi-Source Merge)

## 1. Specification (Strict)
- **Input**: `nct_id: str`, `enrich_from_pubmed: bool = True`
- **Output**: `ARTEMISRequest` (enriched IR)
- **Logic**:
  1. 기존 NCT API → TrialData 생성 (현재 flow)
  2. `enrich_from_pubmed=True`면:
     a. NCT → PMID 연결 (Subtask 01)
     b. PMID → PubMedPaper 파싱 (Subtask 02)
     c. PubMedPaper.eligibility_section의 criteria를 TrialData에 **병합**
  3. 병합 로직: NCT 요약보다 design paper가 더 상세하면 **교체**
  4. 최종 TrialData로 LLM prompt 구성 → IR 생성

## 2. TDD Strategy
- [ ] Test Case A: enrich=True, PMID found → enriched criteria
- [ ] Test Case B: enrich=True, no PMID → NCT only (fallback)
- [ ] Test Case C: enrich=False → 기존 동작 유지

## 3. Implementation Log
(pending)

## 4. Final Status
- [PENDING]
