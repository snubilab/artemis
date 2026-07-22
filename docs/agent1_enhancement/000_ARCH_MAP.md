# 000_ARCH_MAP: Agent 1 Enhancement — Multi-Source Input

## Project Goal
Agent 1이 NCT API 요약본만이 아니라 **Design Paper의 Full Eligibility Criteria**를 입력으로 받아 
보다 완전한 IR을 생성하도록 확장.

## Tech Stack
- Python 3.12
- LangChain + LLM (Azure OpenAI)
- PubMed E-utilities API (NCT → PMID 연결)
- Pydantic (IR models)

## Sub-tasks

| # | Task | Status | Dependency |
|---|------|--------|------------|
| 01 | NCT → PubMed PMID 연결 | DONE | — |
| 02 | PubMed Full Text 파싱 (Eligibility Section) | DONE | 01 |
| 03 | Agent 1 `parse_nct` 확장 (multi-source merge) | DONE | 01, 02 |
| 04 | Integration Test (LEADER E2E) | DONE | 03 |
