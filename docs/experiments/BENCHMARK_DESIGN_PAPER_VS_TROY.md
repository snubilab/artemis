# ARTEMIS Design Paper vs TROY Comparison — Exp A / B / C 비교

> 🏷 명명 규칙: [EXPERIMENT_NAMING_CONVENTION.md](./EXPERIMENT_NAMING_CONVENTION.md) | 실험 계열: **Exp A / B / C**

**Date**: 2026-02-28  
**Trial**: LEADER (Liraglutide vs Placebo)  
**Gold Standard**: `[TROY] Liraglutide (LEADER) v3.4.json` (49 ConceptSets, 18 InclusionRules)

## 1. 실험 구성

|  Exp  | Input                        | Pipeline                     | 특징                                |
| :---: | ---------------------------- | ---------------------------- | ----------------------------------- |
| **A** | TROY rule name (1줄)         | Agent 1 → Agent 2 +ATC       | V6 벤치마크. Agent 1이 분해해야 함  |
| **B** | Design paper e2e (prebuilt)  | 이미 생성된 Circe JSON       | ARTEMIS 전체 파이프라인 결과물 비교 |
| **C** | Design paper criteria (38개) | Agent 2 +ATC (domain gating) | B의 criteria를 Agent 2 재실행       |

## 2. 전체 비교

| 지표              | A (rule name) | B (prebuilt) | C (live +ATC) |
| ----------------- | :-----------: | :----------: | :-----------: |
| **Avg Recall**    |     41.3%     |    58.4%     |   **52.8%**   |
| **Avg Precision** |     61.5%     |    62.9%     |   **50.1%**   |
| **Avg F1**        |     39.1%     |    52.0%     |   **41.5%**   |
| Full (≥80%)       |       4       |      5       |     **5**     |
| Partial (30-80%)  |       5       |      9       |     **7**     |
| Wrong (<30%)      |       8       |      3       |     **5**     |

## 3. Per-Rule 비교

| TROY Rule                 | troy  | A (rulename) | B (prebuilt) | C (live+ATC) | 분석                                      |
| ------------------------- | :---: | :----------: | :----------: | :----------: | ----------------------------------------- |
| HbA1C ≥ 7%                |   1   |   ✅ 100%    |   ✅ 100%    |   ✅ 100%    | 모두 정확                                 |
| prior CV disease          | 4,932 |    🔶 63%    |    🔶 62%    |  🔶 **60%**  | 세 실험 모두 비슷 — Agent 2 한계          |
| No T1DM                   |  25   |    🔶 76%    |   ✅ 100%    |    🔶 76%    | B만 100% (prebuilt가 정확한 concept 포함) |
| No calcitonin             |   2   |    ❌ 0%     |    🔶 50%    |  🔶 **50%**  | A만 0% (LLM 비결정성)                     |
| **No GLP1-RA/DPP-4**      | 3,326 |  ✅ **99%**  |    🔶 42%    | ✅ **100%**  | **ATC expansion 효과** (B는 ATC 미적용)   |
| **No insulin**            | 8,449 |  ✅ **97%**  |    🔶 73%    |  ✅ **97%**  | **ATC expansion 효과**                    |
| No acute decompensation   |   8   |    ❌ 0%     |   ✅ 100%    |    ❌ 0%     | B만 정확 (prebuilt concept 포함)          |
| No acute coronary/cerebro | 1,193 |    ❌ 9%     |    ❌ 10%    |    ❌ 10%    | 모두 저성능 — 범위 차이                   |
| No CHF                    |  166  |    ❌ 20%    |    🔶 79%    |  🔶 **79%**  | "Severe heart failure" > "CHF" 검색       |
| No renal replacement      |  126  |    🔶 48%    |    🔶 49%    |    🔶 49%    | 동일                                      |
| No eGFR <30               |  38   |    ❌ 8%     |   ✅ 100%    | ✅ **100%**  | C: CKD stage 4/5 split이 효과적           |
| No ESLD                   |  770  |    🔶 33%    |    🔶 33%    |    🔶 33%    | 동일 — ancestor climbing 필요             |
| No transplant             |  319  |    ❌ 4%     |    🔶 46%    |  ❌ **0%**   | C: "Organ transplant" → 4 concept 미스    |
| No malignant              | 5,310 |    🔶 40%    |    🔶 36%    |    🔶 40%    | 동일                                      |
| No MEN2/FMTC              |   6   |   ✅ 100%    |   ✅ 100%    |   ✅ 100%    | 모두 정확                                 |
| No drug dependence        |  241  |    ❌ 0%     |    ❌ 0%     |    ❌ 0%     | TROY raw=0 (비교 불가)                    |
| No pregnant               | 2,253 |    ❌ 4%     |    ❌ 13%    |    ❌ 4%     | concept granularity 문제                  |

## 4. 핵심 분석

### 4.1 ATC Expansion 효과 (A/C vs B)

| Rule          | B (without ATC) | A/C (with ATC) |   변화   |
| ------------- | :-------------: | :------------: | :------: |
| GLP1-RA/DPP-4 |       42%       |  **99-100%**   | 🎉 +58pp |
| Insulin       |       73%       |    **97%**     | 🎉 +24pp |

ATC expansion이 Drug domain에서 결정적 차이를 만듦.

### 4.2 입력 상세도의 효과 (A vs B/C)

| Rule                 | A (축약) |    B/C (상세)     | 원인                                             |
| -------------------- | :------: | :---------------: | ------------------------------------------------ |
| CHF                  |   20%    |      **79%**      | "No CHF" vs "Severe heart failure" — 검색어 품질 |
| eGFR                 |    8%    |     **100%**      | 1개 rule vs CKD 4/5 분리                         |
| Acute decompensation |    0%    | 100% (B) / 0% (C) | B는 prebuilt concept 포함                        |

**Agent 1의 분해 능력이 아니라, 입력 텍스트의 상세도가 핵심 차이.**

### 4.3 변하지 않는 한계

| Rule                      | 모든 실험 | 원인                                                                    |
| ------------------------- | :-------: | ----------------------------------------------------------------------- |
| No pregnant               |   4-13%   | Concept granularity (Pregnancy vs Pregnancy, childbirth and puerperium) |
| No acute coronary/cerebro |   9-10%   | Agent 2 coverage 부족                                                   |
| CV disease                |  60-63%   | Agent 2 매핑 한계 (15개 sub-category 중 일부만 커버)                    |
