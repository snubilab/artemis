# ADR-017: Agent 1 역할 축소 — Data Fetching 분리

**상태**: 제안됨  
**날짜**: 2026-03-02  
**의사결정자**: @kyh

## 컨텍스트

Agent 1이 현재 두 가지 역할을 수행한다:
1. **Data Fetching**: NCT 번호 → ClinicalTrials.gov, PubMed, PDF에서 eligibility criteria 수집 및 enrichment
2. **IR Construction**: 수집된 criteria → LLM으로 structured IR(Inclusion/Exclusion Rules) 변환 + sub-criteria 분해

ADR-016에서 발견한 `as_completed` 비결정성 이외에도 **Azure AI Foundry LLM 자체가 `temperature=0.0` + `seed=42`에서도 비결정적**임이 확인되었다. 연속 2회 실행에서 28 rules vs 29 rules, rule 이름 구조까지 달라지는 문제가 발생.

### AS-IS (현재)

```
NCT 번호 입력
  → Agent 1: ClinicalTrials.gov fetch
  → Agent 1: PubMed 논문 검색
  → Agent 1: PDF enrichment (pdftotext + regex)
  → Agent 1: LLM IR 생성 (비결정적 ❌)
  → Agent 2: Concept Mapping
```

모든 단계가 Agent 1 내부에 결합되어 있어, LLM 비결정성이 전체 파이프라인에 전파.

### TO-BE (제안)

```
[Data Layer] NCT fetch + PubMed + PDF enrichment → TrialData (결정적 ✅)
  → Agent 1: TrialData → LLM IR 생성 + sub-criteria 분해 (캐시로 결정적)
  → Agent 2: Concept Mapping
```

## 결정

Agent 1의 역할을 **IR 구성 + sub-criteria 분해**로 축소한다.

- **분리**: NCT fetch, PubMed 검색, PDF enrichment → 별도 Data Layer (또는 Fetcher 모듈)로 이동
- **Agent 1 입력**: 이미 정리된 `TrialData` (inclusion/exclusion criteria 리스트)
- **Agent 1 출력**: `ARTEMISRequest` IR (structured rules + sub-criteria)
- **공통 핵심 역할**: LLM 기반 **sub-criteria 분해** (e.g., "No pregnant" → 하위 concept 분리)

## 근거

1. **결정성**: Data fetching은 이미 결정적 (pdftotext + regex). LLM 호출만 비결정적이므로 캐시로 해결 가능
2. **관심사 분리**: Data acquisition과 NLU parsing은 독립된 관심사
3. **재사용성**: TrialData를 다른 경로(직접 입력, 다른 DB)에서도 받을 수 있음
4. **테스트 용이성**: Agent 1을 TrialData 입력으로 단위 테스트 가능 (PDF/네트워크 의존 없음)

## 영향

- `src/agents/agent1/parser.py`의 `parse_nct()` 리팩터링: fetch 로직 분리
- `src/agents/agent1/nct_fetcher.py`, `pubmed_linker.py`, `enricher.py` → data layer로 이동 가능
- 현재는 IR 캐시 (`data/cache/agent1_ir/`)로 즉시 문제 해결, 리팩터링은 후속 작업
