# 2026-03-13: UMLS MRREL Drug Class Expansion

## 목표

PLATO 벤치마크에서 0% recall이었던 3개 drug class 규칙 해결:

- Fibrinolytic agents
- Anticoagulants (oral anticoagulation therapy)
- CYP3A inhibitors and inducers

## 근본 원인 분석

### ATC ChromaDB 한계

ATC ChromaDB(1315 concepts, level 1-4)는 pharmacological class 검색에 부적합:

| 쿼리                | ATC 매칭                 | 문제                         |
| ------------------- | ------------------------ | ---------------------------- |
| fibrinolytic agents | "Fibrinogen" (개별 약물) | 의미 혼동                    |
| anticoagulants      | "ANTITHROMBOTIC AGENTS"  | 너무 광범위 (67 ingredients) |
| CYP3A inhibitor     | "CDK inhibitors"         | 완전히 다른 클래스           |

### OMOP DB Vocabulary 현황

- **NDF-RT**: DB에 미적재 (0 concepts)
- **SNOMED Substance**: 15,003 concepts 있지만 `concept_relationship` → RxNorm 0건
- **ATC**: 유일한 Drug class vocabulary이지만 pharmacological class와 불일치

## 해결: UMLS MRREL 기반 확장

### 아키텍처

```
text → UMLSSynonymExpander.get_cuis() → UMLS CUI
     → MRREL SQLite `isa` children → child CUIs
     → MRCONSO RxNorm names → RxNorm ingredient names
     → OMOP concept table exact match → concept_ids
```

### 구현

- **MRREL.RRF** 추출 (2.5GB) → SQLite 적재 (7.4M rows, 895MB)
  - SAB 필터: MED-RT, MSH, NCI, SNOMEDCT_US, RXNORM
  - SY 관계 제외
- `drug_class_expander.py`에 `expand_drug_class_via_umls()` 추가
- Waterfall 순서: **MRREL first → ATC second**
  - MRREL이 정확한 pharmacological class 찾으면 사용
  - 못 찾으면 ATC fallback (DPP-4, GLP-1 등 ATC 정렬 클래스)
- 양쪽 모두 ≥3 ingredient count 검증

### 검증 결과

**Drug class expansion 단위 테스트:**

| Query                   | Strategy | IDs | 주요 성분                               |
| ----------------------- | -------- | :-: | --------------------------------------- |
| Fibrinolytic agents     | MRREL    | 30  | alteplase, streptokinase, urokinase     |
| anticoagulants          | MRREL    | 48  | warfarin, apixaban, heparin             |
| CYP3A inhibitors        | MRREL    | 10  | ketoconazole, ritonavir, clarithromycin |
| DPP-4 inhibitors        | ATC      |  8  | sitagliptin, linagliptin                |
| GLP-1 receptor agonists | ATC      |  6  | exenatide, liraglutide, semaglutide     |

## PLATO Benchmark 결과

| Rule                         |  R (전)  |  R (후)   |   P   |  F1   | 비고                    |
| ---------------------------- | :------: | :-------: | :---: | :---: | ----------------------- |
| ACS eligibility              |   82%    |    82%    |  87%  |  84%  | 변화 없음               |
| Clopidogrel contraindication |   100%   |   100%    |  9%   |  17%  | 변화 없음               |
| **Fibrinolytic therapy**     |  **0%**  | **100%**  |  5%   |  10%  | MRREL 30 concepts 적용  |
| Oral anticoagulation         |    0%    |    0%     |  0%   |  0%   | Agent1이 Condition 분류 |
| CYP inhibitors               |    0%    |    0%     |  0%   |  0%   | UMLS combined CUI 없음  |
| **Avg Recall**               | **~40%** | **56.4%** | 20.2% | 22.2% | **+16pp**               |

## 남은 이슈

### Anticoagulant (R=0%)

- MRREL은 48 concepts 정상 반환
- **Agent 1이 "oral anticoagulation therapy"를 `[Condition]`으로 분류** → Drug expander 미호출
- 해결: Agent 1 domain 분류 개선 필요

### CYP Inhibitors (R=0%)

- "CYP inhibitors and inducers" → UMLS CUI 없음 (combined 개념)
- Agent 1이 "Cytochrome P-450 3A inhibitors/inducers"로 분리했지만 각각 1 concept만 매핑
- MRREL은 "CYP3A inhibitors" (C3850056) → 10 ingredients 정상 작동 확인
- 해결: Agent 1 분리 후 각각에 대해 drug class expansion 호출 필요

## 파일 변경

- `src/agents/agent2/drug_class_expander.py`: MRREL-first waterfall 구현
- `data/umls/mrrel.sqlite`: MRREL SQLite DB (새로 생성)
- `GEMINI.md`: 하드코딩 금지 룰 추가
