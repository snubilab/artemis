# Benchmark V7: Hierarchical Rule × ConceptSet Comparison — Exp A vs C 상세

> 🏷 명명 규칙: [EXPERIMENT_NAMING_CONVENTION.md](./EXPERIMENT_NAMING_CONVENTION.md) | 실험 계열: **Exp A / C**

**Date**: 2026-02-28  
**Gold Standard**: TROY Liraglutide (LEADER) v3.4 — 18 rules, 49 ConceptSets  
**TROY Resolution**: Circe-compliant (`includeDescendants`/`isExcluded` 플래그 준수)

---

## 1. 실험 설계

### Experiment A: Rule Name Input

```
Input: TROY rule name 1개 (예: "prior CV disease")
Pipeline: Rule name → Agent 1 (분해) → Agent 2 (매칭, +ATC)
```

- **Agent 1에 들어가는 입력**: TROY rule name 텍스트 **그 자체** (예: `"prior CV disease"`)
- Agent 1이 이 텍스트를 sub-criteria로 분해 시도
- `"prior CV disease"` → Agent 1 출력: **`"Cardiovascular disease"` 1개만** (분해 실패)
- 이 1개가 Agent 2에 전달 → Agent 2가 concept 검색

### Experiment C: Design Paper Input

```
Input: Design paper에서 수동 추출한 38개 criteria (사람이 TROY rule에 매핑)
Pipeline: 각 criterion → Agent 2 (매칭, +ATC domain gating)
```

- **Agent 1을 거치지 않음** — criteria가 이미 분해된 상태로 직접 Agent 2에 입력
- 예: `"prior CV disease"` → 16개 sub-criteria로 분해 (MI, Stroke, PAD, ...)
- 각 sub-criterion을 개별적으로 Agent 2에 전달
- 결과를 TROY rule 단위로 aggregation

> [!IMPORTANT]
> Experiment C의 38개 criteria는 **Agent 1이 자동으로 뽑은 것이 아님**.
> Design paper를 사람이 읽고 수동 추출 후 TROY rule에 매핑한 것.

---

## 2. 평가 방법

### 지표

| 지표              | 정의                  |
| ----------------- | --------------------- | ------------- | --- | ------ | --------------------------------------- |
| **Recall (R)**    | `                     | TROY ∩ Agent2 | /   | TROY   | ` — TROY concept 중 Agent 2가 찾은 비율 |
| **Precision (P)** | `                     | TROY ∩ Agent2 | /   | Agent2 | ` — Agent 2 찾은 것 중 TROY에 있는 비율 |
| **F1**            | `2 × R × P / (R + P)` |

### Concept 해상도

**TROY 측**: ConceptSet의 각 item에 대해

- `includeDescendants=true` → `concept_ancestor`로 descendants 확장
- `includeDescendants=false` → concept ID만 사용
- `isExcluded=true` → 결과에서 제외
- Non-standard concept → `Maps to` 관계로 standard 치환

**Agent 2 측**: Agent 2가 반환하는 raw concept IDs를 standard 치환 후 `concept_ancestor`로 descendants 확장

### 비교 단위

- **Rule 레벨**: TROY rule에 속하는 모든 ConceptSet의 resolved concept 합집합 vs Agent 2 합집합
- **ConceptSet 레벨**: 개별 ConceptSet의 resolved concept vs Agent 2 합집합 (compound rule 내부 진단용)

---

## 3. Two-Way Comparison

| Rule / ConceptSet               |   TROY    |  A (rule)   |  C (paper)  | Delta |
| ------------------------------- | :-------: | :---------: | :---------: | :---: |
| **HbA1C ≥ 7 %**                 |   **1**   | **✅ 100%** | **✅ 100%** |   =   |
| **prior CV disease**            | **4,783** | **🔶 65%**  | **❌ 28%**  | A>>C  |
| ├─ ischemic heart disease       |   3,301   |   ✅ 94%    |   ❌ 18%    | A>>C  |
| ├─ MI                           |    131    |   ✅ 100%   |   ✅ 100%   |   =   |
| ├─ Heart Failure (NYHA II-III)  |    131    |   ✅ 100%   |   ✅ 99%    |   =   |
| ├─ unstable angina              |    10     |   ✅ 100%   |   ✅ 100%   |   =   |
| ├─ CAD                          |    45     |   ✅ 100%   |   ✅ 84%    |   ≈   |
| ├─ LVH                          |     6     |   ✅ 100%   |   ✅ 100%   |   =   |
| ├─ LV dysfunction               |     7     |   ✅ 100%   |   ✅ 100%   |   =   |
| ├─ microalbuminuria/proteinuria |    128    |    ❌ 1%    |   ✅ 100%   | C>>A  |
| ├─ arterial stenosis            |    352    |   ❌ 10%    |   ✅ 85%    | C>>A  |
| ├─ PAD                          |    247    |    ❌ 0%    |   ✅ 98%    | C>>A  |
| ├─ hypertension                 |    142    |    ❌ 5%    |   🔶 77%    | C>>A  |
| ├─ Stroke/TIAs                  |    96     |    ❌ 0%    |   ❌ 23%    |  C>A  |
| ├─ Revascularization            |    812    |    ❌ 2%    |   ❌ 29%    |  C>A  |
| ├─ intermittent claudication    |    12     |    ❌ 0%    |    ❌ 0%    |   =   |
| └─ eGFR                         |     1     |    ❌ 0%    |    ❌ 0%    |   =   |
| **No T1DM**                     |  **25**   | **🔶 76%**  | **🔶 76%**  |   =   |
| **No calcitonin**               |   **2**   |  **❌ 0%**  |  **❌ 0%**  |   =   |
| **No GLP1-RA/DPP-4**            | **3,399** | **✅ 100%** | **✅ 100%** |   =   |
| ├─ GLP-1 receptor agonists      |   1,409   |   ✅ 100%   |   ✅ 100%   |   =   |
| ├─ DPP4 inhibitors              |   1,989   |   ✅ 100%   |   ✅ 100%   |   =   |
| └─ pramlintide                  |     1     |    ❌ 0%    |    ❌ 0%    |   =   |
| **No insulin**                  | **8,526** | **✅ 97%**  | **✅ 97%**  |   =   |
| **No acute decompensation**     |   **8**   |  **❌ 0%**  |  **❌ 0%**  |   =   |
| **No acute coronary/cerebro**   | **1,015** | **❌ 10%**  | **❌ 10%**  |   =   |
| ├─ (acute) MI                   |    119    |   🔶 76%    |   🔶 76%    |   =   |
| ├─ Stroke                       |    84     |   ❌ 10%    |   ❌ 18%    |   ≈   |
| └─ Revascularization            |    812    |    ❌ 0%    |    ❌ 0%    |   =   |
| **No CHF**                      |  **166**  | **❌ 19%**  | **🔶 79%**  | C>>A  |
| ├─ Heart Failure (NYHA II-III)  |    131    |   ❌ 24%    |   ✅ 100%   | C>>A  |
| └─ Oxygen therapy (NYHA IV)     |    35     |    ❌ 0%    |    ❌ 0%    |   =   |
| **No renal replacement**        |  **143**  | **🔶 49%**  | **🔶 49%**  |   =   |
| **No eGFR <30**                 |  **38**   |  **❌ 5%**  | **✅ 100%** | C>>A  |
| ├─ eGFR                         |     3     |   🔶 67%    |   ✅ 100%   |  C>A  |
| └─ CKD 4-5                      |    35     |    ❌ 0%    |   ✅ 100%   | C>>A  |
| **No ESLD**                     |  **771**  | **🔶 33%**  | **🔶 33%**  |   =   |
| **No transplant**               |  **379**  |  **❌ 5%**  |  **❌ 0%**  |   ≈   |
| **No malignant**                | **5,314** | **🔶 40%**  | **🔶 40%**  |   =   |
| **No MEN2/FMTC**                |   **6**   | **✅ 100%** | **✅ 100%** |   =   |
| **No drug dependence**          |  **241**  |  **❌ 0%**  | **✅ 100%** | C>>A  |
| **No pregnant**                 | **2,253** |  **❌ 4%**  |  **❌ 4%**  |   =   |

---

## 4. Summary

|                       | A (rule name) | C (design paper) |
| --------------------- | :-----------: | :--------------: |
| ✅ Full (R≥80%)       |       4       |        6         |
| 🔶 Partial (R 30-80%) |       5       |        5         |
| ❌ Wrong (R<30%)      |       8       |        6         |

---

## 5. Analysis

### Design paper (C)가 크게 이기는 규칙 — **입력 상세도 차이**

| Rule             |  A→C   | 원인                                                             |
| ---------------- | :----: | ---------------------------------------------------------------- |
| eGFR <30         | 5→100% | Design paper에 "CKD stage 4", "CKD stage 5" 별도 기술            |
| Drug dependence  | 0→100% | "Substance use disorder" (Condition domain) ← 올바른 domain 부여 |
| CHF              | 19→79% | "Severe heart failure" ← "No CHF"보다 구체적                     |
| PAD              | 0→98%  | Design paper에 "Peripheral arterial disease" 명시                |
| Microalbuminuria | 1→100% | Design paper에 "Microalbuminuria", "Proteinuria" 명시            |

### Rule name (A)가 이기는 규칙 — **넓은 검색의 이점**

| Rule                  |  A→C   | 원인                                                                                                            |
| --------------------- | :----: | --------------------------------------------------------------------------------------------------------------- |
| CV disease (ischemic) | 94→18% | A는 "cardiovascular disease" 1 query → 넓은 ancestor concept 매칭. C는 16개로 분산시켜 각각 좁은 concept만 찾음 |

### 변화 없음 — **Agent 2 concept 탐색 한계**

Calcitonin 0%, Pregnancy 4%, ESLD 33%, Malignant 40%, Transplant 0-5%
→ 입력이 달라져도 Agent 2가 올바른 concept을 못 찾는 공통 문제.

---

## 6. Related Documents

| 문서                                                                             | 내용                      |
| -------------------------------------------------------------------------------- | ------------------------- |
| [V7 Rule Name Hierarchical](./BENCHMARK_V7_HIERARCHICAL.md)                      | Experiment A 상세         |
| [V7 Design Paper Hierarchical](./BENCHMARK_V7_DESIGN_PAPER_HIERARCHICAL.md)      | Experiment C 상세         |
| [Consolidated Report](./BENCHMARK_CONSOLIDATED_REPORT.md)                        | 이전 3-way 비교 (V5 기준) |
| [Domain Expansion Strategy](../issues/ISSUE_domain_expansion_strategy.md)        | 도메인별 확장 전략        |
| [RFC-006 ATC Expansion](../rfc/RFC-006_Vocabulary_Based_Drug_Class_Expansion.md) | Drug domain ATC 확장      |
