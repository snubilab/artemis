# LEADER GOLD Standard 구축: 원문 프로토콜 → TROY 버전 비교 → GOLD ConceptSet 확정

> 🏷 명명 규칙: [EXPERIMENT_NAMING_CONVENTION.md](./EXPERIMENT_NAMING_CONVENTION.md) | `A_direct` = **M 계열**

> LEADER Trial (NCT01179048) 기준  
> 원문 출처: NEJMoa1603827 Supplementary Appendix p.39  
> 관련: [종합 보고서](./BENCHMARK_CONSOLIDATED_REPORT.md)  
> GOLD JSON: [`data/gold/LEADER/LEADER_GOLD.json`](../../data/gold/LEADER/LEADER_GOLD.json)

---

## 1. 개요

|                        | **Design Paper**       | **TROY v1.1**    | **TROY v3.4**              |
| ---------------------- | ---------------------- | ---------------- | -------------------------- |
| **출처**               | ClinicalTrials.gov     | TROY 1.1 (OHDSI) | TROY 3.4 (OHDSI)           |
| **약물**               | Liraglutide vs placebo | Liraglutide      | DPP-4 / Liraglutide (동일) |
| **Inclusion rules**    | 4                      | 4 (17 total)     | 3 (18 total)               |
| **Exclusion rules**    | ~15                    | 13               | 15                         |
| **ConceptSets**        | —                      | 46               | 49                         |
| **Unique concepts**    | —                      | 242              | 217                        |
| **Jaccard similarity** | —                      | —                | 38.3% (v3.4 ↔ v1.1)        |

### 1.1 Design Paper 원문 기준 (NEJMoa1603827, Supplementary Appendix p.39)

**Inclusion criteria** (전문):

> 1. Type 2 diabetes
> 2. Anti-diabetic drug naïve **or** treated with ≥1 OADs **or** human NPH insulin / long-acting insulin analogue / premixed insulin (alone or + OADs)
> 3. Glycated hemoglobin ≥ 7.0%
> 4. **Prior CV disease cohort**: Age ≥ 50 and ≥ 1 of:
>    - Prior MI
>    - Prior stroke or TIA
>    - Prior coronary, carotid or peripheral arterial revascularization
>    - \>50% stenosis of coronary, carotid, or lower extremity arteries
>    - History of symptomatic CHD (positive stress test / cardiac imaging) or unstable angina with ECG changes
>    - Asymptomatic cardiac ischemia (positive nuclear imaging / exercise test / dobutamine stress echo)
>    - Chronic heart failure NYHA class II-III
>    - Chronic renal failure: eGFR <60 mL/min/1.73m² (MDRD) or eGFR <60 mL/min (Cockcroft-Gault)
> 5. **No prior CV disease group**: Age ≥ 60 and ≥ 1 of:
>    - Microalbuminuria or proteinuria
>    - Hypertension and left ventricular hypertrophy (ECG/imaging)
>    - Left ventricular systolic or diastolic dysfunction (imaging)
>    - Ankle-brachial index < 0.9

**Exclusion criteria** (전문):

> 1. Type 1 diabetes
> 2. Calcitonin ≥ 50 ng/L
> 3. Use of GLP-1 RA / pramlintide / DPP-4 inhibitor within 3 months
> 4. Use of insulin other than NPH / long-acting / premixed within 3 months
> 5. Acute decompensation of glycemic control
> 6. Acute coronary or cerebrovascular event in the previous 14 days
> 7. Currently planned coronary, carotid, or peripheral artery revascularization
> 8. Chronic heart failure (NYHA class IV)
> 9. Current continuous renal replacement therapy
> 10. End-stage liver disease
> 11. History of solid organ transplant or awaiting solid organ transplant
> 12. Malignant neoplasm
> 13. Family or personal history of MEN type 2 or familial medullary thyroid carcinoma
> 14. Personal history of non-familial medullary thyroid carcinoma
>     _(drug use/dependence, pregnancy는 Supplementary에 명시되지 않음 → TROY에서 추가한 항목)_

---

## 2. Eligibility Criteria 통합 비교

### 2.1 Protocol 원문 + 구현 비교 + GOLD 성능

|  #   | Rule                   | Criteria 원문                                                                                                                                 | v1.1                               | v3.4                            |   GOLD    |  R   |  P   |  F1  | 비고                                  |
| :--: | ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- | ------------------------------- | :-------: | :--: | :--: | :--: | ------------------------------------- |
|      | **— Inclusion —**      |                                                                                                                                               |                                    |                                 |           |      |      |      |                                       |
| I-1  | T2DM                   | "Diagnosed with type 2 diabetes"                                                                                                              | OAD/GLP-1/insulin DrugEra ≥7일     | DrugEra (cs117/32) ≥7일         |   v1.1    |  —   |  —   |  —   | v1.1: 약물 기반 T2DM 정의             |
| I-2  | Drug naive/OAD/insulin | "Anti-diabetic drug naïve or treated with ≥1 OADs and/or human NPH insulin, long-acting insulin analogue, or premixed insulin"                | ✅ OAD+insulin whitelist (73개)    | ❌ 없음                         |   v1.1    |  —   |  —   |  —   | ⚠️ v3.4: 기준 자체 누락               |
| I-3  | HbA1c ≥ 7%             | "HbA1c of 7.0% or more"                                                                                                                       | 2 concepts, **Value=7, lt** ✅     | 1 concept, ❌ **Value=10, gte** |   v1.1    | 100% | 100% | 100% | 🚨 v3.4 원본 버그 → GOLD에서 수정     |
| I-4  | Age ≥ 50               | "Age ≥ 50 years"                                                                                                                              | ✅ DemographicCriteria             | ✅ DemographicCriteria          |   동일    |  —   |  —   |  —   | —                                     |
| I-5  | ≥50 + prior CV         | "≥50 with ≥1 CV coexisting condition: prior MI, stroke/TIA, revascularization, >50% stenosis, CHD, cardiac ischemia, CHF NYHA II-III, CKD ≥3" | ✅ age-stratified OR (10 criteria) | ❌ flat list (15 CS)            |   v1.1    | 60%  |  8%  | 14%  | GOLD: v1.1 구조 이식                  |
| I-6  | ≥60 + risk factors     | "≥60 with ≥1 CV risk factor: microalbuminuria/proteinuria, hypertension+LVH, LV dysfunction, ABI <0.9"                                        | ✅ 4개 risk factor 모두 포함       | ❌ 없음 (age 무관 나열)         |   v1.1    |  —   |  —   |  —   | GOLD: v1.1 구조 이식, 7개 CS 추가     |
|      | **— Exclusion —**      |                                                                                                                                               |                                    |                                 |           |      |      |      |                                       |
| E-1  | No T1DM                | "Type 1 diabetes"                                                                                                                             | 3 concepts                         | 1 concept                       |   v1.1    | 100% |  3%  |  6%  | v1.1: +uncontrolled, +disorder due to |
| E-2  | No calcitonin ≥ 50     | "Calcitonin ≥50 ng/L"                                                                                                                         | 1 concept                          | 2 concepts                      |   v3.4    | 50%  |  6%  | 11%  | v3.4: Procalcitonin 추가              |
| E-3  | No GLP-1/DPP-4 (3mo)   | "Use of GLP-1RA, DPP-4 inhibitors, or pramlintide within 3 months"                                                                            | 18 concepts                        | 12 concepts                     |   v1.1    | 100% | 74%  | 85%  | v1.1: omarigliptin 등 6종 추가        |
| E-4  | No insulin (types)     | "Use of insulin other than human NPH, long-acting analogue, or premixed"                                                                      | ❌ 없음 (whitelist 방식)           | ✅ 19 concepts (blacklist)      |   v3.4    | 97%  | 77%  | 86%  | ⚠️ broad 배제: 허용 제형도 배제       |
| E-5  | No acute decomp.       | "Acute decompensation of glycemic control (e.g., DKA) in previous 90 days"                                                                    | 1 concept (DKA), v1.1=v3.4 동일    | 1 concept (DKA)                 |   동일    | 100% | 62%  | 76%  | —                                     |
| E-6  | No acute CV (14d)      | "Acute coronary or cerebrovascular event in the previous 14 days"                                                                             | MI+Stroke+PCI                      | MI+Stroke+Revasc                |   v3.4    | 87%  |  9%  | 17%  | 유사                                  |
| E-7  | No planned revasc      | "Planned coronary/carotid/peripheral artery revascularization"                                                                                | ❌ 없음                            | ❌ 없음                         | 🚫 미구현 |  —   |  —   |  —   | **양쪽 모두 누락**                    |
| E-8  | No CHF (NYHA IV)       | "Chronic heart failure, NYHA class IV"                                                                                                        | ✅ Oxygen+CHF                      | ✅ CHF+Oxygen                   |   유사    | 100% |  7%  | 13%  | —                                     |
| E-9  | No renal replace.      | "Currently on continuous renal replacement therapy"                                                                                           | 6 concepts (ESRD+dialysis+Tx)      | 6 concepts, v1.1과 동일         |   동일    | 87%  | 33%  | 47%  | —                                     |
| E-10 | No eGFR <30            | (implied by renal criteria)                                                                                                                   | ❌ 없음                            | ✅ 5 concepts (eGFR+CKD 4-5)    |   v3.4    | 100% | 24%  | 38%  | v3.4에만 별도 rule                    |
| E-11 | No ESLD                | "End-stage liver disease"                                                                                                                     | 9 concepts                         | **17 concepts**                 |   v3.4    | 31%  | 31%  | 31%  | v3.4: varices, jaundice 추가          |
| E-12 | No transplant          | "Prior solid organ transplant or awaiting transplant"                                                                                         | 6 concepts (desc=false)            | **19 concepts (desc=true)**     |   v3.4    | 20%  | 88%  | 33%  | v3.4: descendants 포함                |
| E-13 | No malignant (5y)      | "Malignant neoplasm within 5 years (except basal/squamous cell skin cancer)"                                                                  | 1 concept                          | 2 concepts                      |   v3.4    | 100% | 100% | 100% | v3.4: skin cancer 분리                |
| E-14 | No MEN2/FMTC           | "Personal or family history of MEN2 or medullary thyroid carcinoma"                                                                           | 2 concepts (MEN2+MTC)              | 2 concepts, v1.1과 동일         |   동일    | 100% |  0%  |  0%  | —                                     |
|  —   | No substance abuse     | ❌ 원문 미명시                                                                                                                                | 3 concepts (abuse/depend/use)      | 3 concepts, v1.1과 동일         |   동일    | 100% | 81%  | 89%  | TROY 추가 항목                        |
|  —   | No pregnant            | ❌ 원문 미명시                                                                                                                                | 1 concept (pregnancy)              | 1 concept, v1.1과 동일          |   동일    | 100% | 100% | 100% | TROY 추가 항목                        |

> [!NOTE]
> **성능 `—` 표시 규칙**: Benchmark는 **ConceptSet 기반 InclusionRule/ExclusionRule**만 평가합니다.
>
> - **I-1, I-2**: PrimaryCriteria (Entry Event) — DrugEra 기반이라 concept 매핑 대상 아님
> - **I-4**: DemographicCriteria — 단순 나이 조건 (`Age ≥ 50`)으로 ConceptSet 없음
> - **I-6**: I-5 (prior CV disease)와 동일 InclusionRule의 nested group → I-5에 합산 평가
> - **E-7**: v1.1/v3.4 양쪽 모두 미구현 → GOLD에도 없음 → 비교 불가

### 2.2 v1.1 vs v3.4 vs GOLD 구현 비교

|  #   | Rule                   | v1.1                                          | v3.4                            | GOLD 선택 | 비고                                  |
| :--: | ---------------------- | --------------------------------------------- | ------------------------------- | :-------: | ------------------------------------- |
|      | **— Inclusion —**      |                                               |                                 |           |                                       |
| I-1  | T2DM (Entry)           | OAD/GLP-1/insulin DrugEra ≥7일                | DrugEra (cs117/32) ≥7일         |   v1.1    | v1.1: 약물 기반 T2DM 정의             |
| I-2  | Drug naive/OAD/insulin | ✅ OAD+insulin whitelist (73개)               | ❌ 없음                         |   v1.1    | ⚠️ v3.4: 기준 자체 누락               |
| I-3  | HbA1c ≥ 7%             | 2 concepts, **Value=7, lt** ✅                | 1 concept, ❌ **Value=10, gte** |   v1.1    | 🚨 v3.4 원본 버그 → GOLD에서 수정     |
| I-4  | Age ≥ 50               | ✅ DemographicCriteria                        | ✅ DemographicCriteria          |   동일    | —                                     |
| I-5  | ≥50 + prior CV         | ✅ age-stratified OR (10 criteria)            | ❌ flat list (15 CS)            |   v1.1    | GOLD: v1.1 구조 이식                  |
| I-6  | ≥60 + risk factors     | ✅ microalb, LVD, HTN+LVH, ABI                | ❌ 없음                         |   v1.1    | GOLD: v1.1 구조 이식, 7개 CS 추가     |
|      | **— Exclusion —**      |                                               |                                 |           |                                       |
| E-1  | No T1DM                | 3 concepts                                    | 1 concept                       |   v1.1    | v1.1: +uncontrolled, +disorder due to |
| E-2  | No calcitonin ≥ 50     | 1 concept                                     | 2 concepts                      |   v3.4    | v3.4: Procalcitonin 추가              |
| E-3  | No GLP-1/DPP-4 (3mo)   | 18 concepts                                   | 12 concepts                     |   v1.1    | v1.1: omarigliptin 등 6종 추가        |
| E-4  | No insulin (types)     | ❌ 없음 (whitelist)                           | ✅ 19 concepts (blacklist)      |   v3.4    | ⚠️ broad 배제: 허용 제형도 배제       |
| E-5  | No acute decomp.       | 1 concept (DKA), v1.1=v3.4 동일               | 1 concept (DKA), v1.1=v3.4 동일 |   동일    | —                                     |
| E-6  | No acute CV (14d)      | MI+Stroke+PCI                                 | MI+Stroke+Revasc                |   v3.4    | 유사                                  |
| E-7  | No planned revasc      | ❌ 없음                                       | ❌ 없음                         | 🚫 미구현 | **양쪽 모두 누락**                    |
| E-8  | No CHF (NYHA IV)       | ✅ Oxygen+CHF                                 | ✅ CHF+Oxygen                   |   유사    | —                                     |
| E-9  | No renal replace.      | 6 concepts (ESRD+dialysis+Tx)                 | 6 concepts, v1.1과 동일         |   동일    | —                                     |
| E-10 | No eGFR <30            | ❌ 없음                                       | ✅ 5 concepts                   |   v3.4    | v3.4에만 별도 rule                    |
| E-11 | No ESLD                | 9 concepts                                    | **17 concepts**                 |   v3.4    | v3.4: varices, jaundice 추가          |
| E-12 | No transplant          | 6 (desc=false)                                | **19 (desc=true)**              |   v3.4    | v3.4: descendants 포함                |
| E-13 | No malignant (5y)      | 1 concept                                     | 2 concepts                      |   v3.4    | v3.4: skin cancer 분리                |
| E-14 | No MEN2/FMTC           | 2 concepts (MEN2+MTC), v1.1=v3.4 동일         | 2 concepts, v1.1과 동일         |   동일    | —                                     |
|  —   | No substance abuse     | 3 concepts (abuse/depend/use), v1.1=v3.4 동일 | 3 concepts, v1.1과 동일         |   동일    | **TROY 추가 (원문 미명시)**           |
|  —   | No pregnant            | 1 concept (pregnancy), v1.1=v3.4 동일         | 1 concept, v1.1과 동일          |   동일    | **TROY 추가 (원문 미명시)**           |

---

## 4. ConceptSet 품질 비교

### 4.1 Concept 커버리지 (category별)

| Category   |        v3.4        |      v1.1      |  Winner  | 근거                                       |
| ---------- | :----------------: | :------------: | :------: | ------------------------------------------ |
| T1DM       |         1          |       3        | **v1.1** | uncontrolled, disorder due to 포함         |
| T2DM       |         1          |       9        | **v1.1** | secondary, gestational, complications 포함 |
| DPP-4      |         5          |       11       | **v1.1** | omarigliptin, anagliptin 등 신약 포함      |
| Insulin    |         19         |       73       | **v1.1** | 개별 formulation까지 상세                  |
| HbA1c      |         1          |       2        | **v1.1** | CPT4 코드 추가                             |
| eGFR/CKD   |         5          |       11       | **v1.1** | CKD stage 1-3 포함                         |
| ESLD       |       **17**       |       9        | **v3.4** | varices, jaundice, toxic hepatitis 등      |
| Transplant | **19** (desc=true) | 6 (desc=false) | **v3.4** | descendants 포함으로 더 넓음               |
| Malignant  |         2          |       1        | **v3.4** | non-melanoma skin cancer 별도 처리         |
| **합계**   |         —          |       —        | **v1.1** | Drug/Lab 쪽 커버리지 우위                  |

### 4.2 includeDescendants 차이

v3.4의 Transplant 4개 concept에서 `includeDescendants=true` 설정:

- `Transplanted heart/kidney/liver/lung present`

v1.1은 동일 concept에서 `includeDescendants=false` → **v3.4가 더 넓은 커버리지**.

---

## 5. 원문 충실도 (Protocol Fidelity) — Supplementary Appendix 기준

| 기준 (Supp. Appendix)                             |    v1.1 충실도    |         v3.4 충실도          | 비고                              |
| ------------------------------------------------- | :---------------: | :--------------------------: | --------------------------------- |
| **Incl #2**: Anti-diabetic drug naive/OAD/insulin |   ✅ rule 존재    |         ❌ rule 누락         | v1.1 우위                         |
| **Incl #4**: Age ≥ 50 + CV (8개 하위 조건)        |  ✅ 정확히 재현   | ❌ flat 나열 (age 분기 없음) | v1.1 우위: age-stratified OR 구조 |
| **Incl #5**: Age ≥ 60 + risk factors (ABI 포함)   | ✅ ABI < 0.9 포함 |           ❌ 없음            | v1.1 우위                         |
| **Excl #2**: Calcitonin ≥ 50 ng/L                 |     1 concept     |          2 concepts          | v3.4: Procalcitonin 추가          |
| **Excl #3**: GLP-1/DPP-4/pramlintide (3mo)        |    18 concepts    |         12 concepts          | v1.1: 약물 커버리지 우위          |
| **Excl #4**: Insulin restriction (specific types) |   ❌ rule 없음    |        ✅ 19 concepts        | v3.4 우위                         |
| **Excl #7**: Planned revascularization            |      ❌ 없음      |           ❌ 없음            | **양쪽 모두 누락**                |
| **Excl #8**: CHF NYHA IV                          |  ✅ Oxygen + CHF  |       ✅ CHF + Oxygen        | 유사                              |
| **Excl #10**: ESLD                                |    9 concepts     |       **17 concepts**        | v3.4 우위                         |
| **Excl #11**: Solid organ transplant              |  6 (desc=false)   |      **19 (desc=true)**      | v3.4 우위                         |
| **Excl #13-14**: MEN2 + non-familial MTC          |    2 concepts     |          2 concepts          | 원문은 non-familial MTC 별도 명시 |
| substance abuse / pregnancy                       |      ✅ / ✅      |           ✅ / ✅            | **원문에 없음** — TROY 추가       |

### 종합 평점

| 관점                           |    v1.1    |   v3.4   |
| ------------------------------ | :--------: | :------: |
| **Inclusion criteria 충실도**  |  ⭐⭐⭐⭐  |   ⭐⭐   |
| **Exclusion criteria 충실도**  |   ⭐⭐⭐   | ⭐⭐⭐⭐ |
| **Drug concept 커버리지**      | ⭐⭐⭐⭐⭐ |  ⭐⭐⭐  |
| **Condition concept 커버리지** |   ⭐⭐⭐   | ⭐⭐⭐⭐ |
| **Protocol 구조 재현**         | ⭐⭐⭐⭐⭐ |  ⭐⭐⭐  |

> **결론**: v1.1이 NCT **프로토콜 구조**(age-stratified inclusion, 약물 상태 기준)에 더 충실.  
> v3.4는 **exclusion concept 커버리지**(ESLD, transplant)가 더 넓음.  
> 이상적으로는 **v1.1의 구조 + v3.4의 concept 커버리지**를 결합한 버전이 최적.

---

## 6. 벤치마크 + Circe-be 실행 결과

### 6.1 Mapping Accuracy (M 계열 benchmark)

| 지표             |   v3.4    | v1.1  | **GOLD** | **GOLD+Hybrid** |
| ---------------- | :-------: | :---: | :------: | :-------------: |
| Rules            |    18     |  17   |    18    |       18        |
| Evaluated        |    17     |  16   |    17    |       17        |
| Avg Recall       | **83.1%** | 61.6% |  75.0%   |    **79.6%**    |
| Avg Precision    |   53.3%   | 47.8% |  56.6%   |  **67.3%** 🎉   |
| Avg F1           |   55.8%   | 49.5% |  53.5%   |  **66.8%** 🎉   |
| Full (≥80%)      |    13     |   9   |    11    |       11        |
| Partial (30-80%) |     2     |   3   |    3     |        4        |
| Wrong (<30%)     |     2     |   4   |    3     |      **2**      |

> GOLD+Hybrid = GOLD input + includeDescendants hybrid policy (ancestors/climb→false). [ABLATION_STUDY.md #11a](./ABLATION_STUDY.md)  
> Report: [`benchmark_a_direct_20260310_1744.json`](../../output/benchmark_a_direct_20260310_1744.json)

### 6.2 GOLD Per-rule 전체 성능 (M-TROY v3 C, 2026-03-03)

> **실험 설정** (M-TROY v3 C — [CONSOLIDATED_REPORT](./BENCHMARK_CONSOLIDATED_REPORT.md) 최종 세팅)
>
> - Complexity Router: 활성 (fast/slow 자동 분기)
> - KG Expansion: Neo4j full transitive closure, kg_limit=15-40
> - ancestor_climb: IC threshold 8.0
> - Critic: 1회
> - `FORCE_SLOW_PATH`: 미사용 (기본 router 경로)

|  #  | Rule                    | GOLD raw | GOLD resolved | Agent2 resolved | Overlap | Recall | Precision |  F1  |   Status   |
| :-: | ----------------------- | :------: | :-----------: | :-------------: | :-----: | :----: | :-------: | :--: | :--------: |
|  1  | Age ≥ 50                |    -     |       -       |        -        |    -    |   -    |     -     |  -   |   ⬜ N/A   |
|  2  | HbA1C ≥ 7%              |    2     |       1       |        1        |    1    |  100%  |   100%    | 100% |  ✅ FULL   |
|  3  | prior CV disease        |   106    |     4,642     |      7,614      |  2,792  |  60%   |    37%    | 46%  | 🔶 PARTIAL |
|  4  | No T1DM                 |    3     |      129      |       788       |   129   |  100%  |    16%    | 28%  |  ✅ FULL   |
|  5  | No calcitonin ≥ 50      |    2     |       2       |       27        |    1    |  50%   |    4%     |  7%  | 🔶 PARTIAL |
|  6  | No GLP-1/DPP-4 (3mo)    |    12    |     3,310     |      4,498      |  3,310  |  100%  |    74%    | 85%  |  ✅ FULL   |
|  7  | No use of insulin       |    19    |     8,449     |     10,637      |  8,213  |  97%   |    77%    | 86%  |  ✅ FULL   |
|  8  | No acute decompensation |    1     |       8       |       93        |    8    |  100%  |    9%     | 16%  |  ✅ FULL   |
|  9  | No acute coronary (14d) |    58    |      876      |      1,447      |   810   |  92%   |    56%    | 70%  |  ✅ FULL   |
| 10  | No CHF                  |    3     |      164      |      2,415      |   164   |  100%  |    7%     | 13%  |  ✅ FULL   |
| 11  | No renal replacement    |    6     |      126      |       334       |   109   |  87%   |    33%    | 47%  |  ✅ FULL   |
| 12  | No eGFR <30             |    5     |      38       |       160       |   38    |  100%  |    24%    | 38%  |  ✅ FULL   |
| 13  | No ESLD                 |    20    |      770      |       789       |   241   |  31%   |    31%    | 31%  | 🔶 PARTIAL |
| 14  | No transplant           |    20    |      285      |       65        |   57    |  20%   |    88%    | 33%  |  ❌ WRONG  |
| 15  | No malignant (5y)       |    2     |     5,310     |      5,309      |  5,309  |  100%  |   100%    | 100% |  ✅ FULL   |
| 16  | No MEN2/FMTC            |    2     |       6       |      5,597      |    6    |  100%  |    0%     |  0%  |  ✅ FULL   |
| 17  | No substance abuse      |    3     |      241      |       299       |   241   |  100%  |    81%    | 89%  |  ✅ FULL   |
| 18  | No pregnant             |    1     |     2,253     |      2,253      |  2,253  |  100%  |   100%    | 100% |  ✅ FULL   |

**Summary**: 18 rules | Evaluated: 17 | Full(≥80%): 11 | Partial(30-80%): 3 | Wrong(<30%): 3 | **Avg R=75.0%** | Avg P=56.6% | Avg F1=53.5%

> ℹ️ GOLD v2는 v1.1의 age-stratified prior CV 구조(Group[0]: ≥50+CV, Group[1]: ≥60+risk)를 이식.  
> 7개 concept set 추가: carotid stenting, limb angioplasty, ABI<0.9, microalbuminuria, LVH, LVD, ACS.  
> 총 56 ConceptSets, 241 unique concepts. Circe-be 정상 변환 (Cohort ID=167, SQL 2863 lines).

### 6.3 Circe-be SQL 실행 결과

| 항목                    | v3.4                                    | GOLD                                               |
| ----------------------- | --------------------------------------- | -------------------------------------------------- |
| Cohort ID (WebAPI)      | 5                                       | **166**                                            |
| SQL 크기                | 2,786 lines / 113,444 bytes             | 2,786 lines / 113,444 bytes                        |
| Circe-be 엔진           | ✅ 정상 변환                            | ✅ 정상 변환                                       |
| Patient count (Synthea) | 0                                       | 0                                                  |
| SQL 파일                | `TROY_LEADER_Liraglutide_generated.sql` | `[GOLD]_LEADER_Liraglutide_v3.4+1.1_generated.sql` |

> ⚠️ personCount=0은 Synthea 데이터에 LEADER trial 조건(T2DM + 50세 이상 + CV disease/risk)을 만족하는 환자가 없기 때문이며, SQL 자체는 Circe-be에서 정상 생성됨.

→ [v3.4 상세 리포트](./BENCHMARK_A_DIRECT_V3_RESULTS.md)  
→ [GOLD benchmark JSON](../../output/benchmark_a_direct_20260303_2309.json)  
→ [GOLD SQL](../../data/sample/LEADER/[GOLD]_LEADER_Liraglutide_v3.4+1.1_generated.sql)

### 6.4 M-GOLD Fast-only vs Slow-only 비교 (2026-03-05)

> **실험 목적**: Complexity Router를 무시하고 전체 query를 Fast path 또는 Slow path로 강제하여, 각 경로의 GOLD 기준 순수 성능 비교.
>
> - `FORCE_FAST_PATH=1`: LLM Reranker 없이 Vector Search Top-1 → KG-RAG
> - `FORCE_SLOW_PATH=1`: UMLS Synonym + Multi-query + LLM Reranker Top-3 → KG-RAG

#### 총괄 비교

| 지표              | **M-GOLD (auto)** | **M-GOLD-fast** | **M-GOLD-slow** |
| ----------------- | :---------------: | :-------------: | :-------------: |
| **Avg Recall**    |     **75.0%**     |      72.8%      |      71.5%      |
| **Avg Precision** |     **56.6%**     |      52.9%      |      48.3%      |
| **Avg F1**        |     **53.5%**     |      50.1%      |      47.8%      |
| Full (≥80%)       |      **11**       |       11        |       10        |
| Partial (30-80%)  |         3         |        3        |        4        |
| Wrong (<30%)      |         3         |        3        |        3        |
| ⏱ 실행 시간       |       ~10분       |      ~16분      |      ~20분      |

#### Per-rule 통합 비교 (R = Recall, P = Precision)

|  #  | Rule               | GOLD  | **Auto** R⏐P |  **Fast** R⏐P  |  **Slow** R⏐P  | Fast↔Slow Δ | Best |
| :-: | ------------------ | :---: | :----------: | :------------: | :------------: | :---------: | :--: |
|  1  | HbA1C ≥ 7%         |   1   | ✅ 100%⏐100% |  ✅ 100%⏐50%   |  ✅ 100%⏐20%   |      —      | Auto |
|  2  | prior CV disease   | 1,749 |  🔶 60%⏐37%  |   🔶 35%⏐30%   | ✅ **80%⏐27%** |  **+45pp**  | Slow |
|  3  | No T1DM            |  129  | ✅ 100%⏐16%  |  ❌ 19%⏐100%   |  ❌ 19%⏐100%   |      —      | Auto |
|  4  | No calcitonin ≥ 50 |   2   |  🔶 50%⏐4%   |   🔶 50%⏐6%    |  ❌ **0%⏐0%**  |  **-50pp**  | Fast |
|  5  | No GLP-1/DPP-4     | 3,310 | ✅ 100%⏐74%  |  ✅ 100%⏐74%   |  ✅ 100%⏐74%   |      —      |  =   |
|  6  | No insulin         | 8,449 |  ✅ 97%⏐77%  |   ✅ 97%⏐77%   |   ✅ 97%⏐77%   |      —      |  =   |
|  7  | No acute decomp.   |   8   |  ✅ 100%⏐9%  |  ✅ 100%⏐62%   |  ✅ 100%⏐47%   |      —      |  =   |
|  8  | No acute coronary  |  876  |  ✅ 92%⏐56%  |   ❌ 12%⏐39%   | 🔶 **35%⏐62%** |  **+23pp**  | Auto |
|  9  | No CHF             |  164  |  ✅ 100%⏐7%  | ✅ **100%⏐7%** |   🔶 76%⏐5%    |  **-24pp**  | Fast |
| 10  | No renal replace.  |  126  |  ✅ 87%⏐33%  |   ✅ 87%⏐33%   | ✅ **99%⏐18%** |  **+12pp**  | Slow |
| 11  | No eGFR <30        |  38   | ✅ 100%⏐24%  |  ✅ 100%⏐24%   |   ✅ 95%⏐21%   |    -5pp     | Fast |
| 12  | No ESLD            |  770  |  🔶 31%⏐31%  |   🔶 31%⏐31%   |   ❌ 24%⏐34%   |    -7pp     | Fast |
| 13  | No transplant      |  285  |  ❌ 20%⏐88%  |   ❌ 20%⏐88%   | 🔶 **39%⏐66%** |  **+19pp**  | Slow |
| 14  | No malignant       | 5,310 | ✅ 100%⏐100% |  ✅ 86%⏐100%   |  ✅ 84%⏐100%   |    -2pp     | Auto |
| 15  | No MEN2/FMTC       |   6   |  ✅ 100%⏐0%  |   ✅ 100%⏐0%   | 🔶 **67%⏐1%**  |  **-33pp**  | Fast |
| 16  | No substance abuse |  241  | ✅ 100%⏐81%  |  ✅ 100%⏐80%   |  ✅ 100%⏐69%   |      —      |  =   |
| 17  | No pregnant        | 2,253 | ✅ 100%⏐100% |  ✅ 100%⏐100%  |  ✅ 100%⏐100%  |      —      |  =   |
|     | **Avg R⏐P**        |   —   | **75%⏐57%**  |  **73%⏐53%**   |  **72%⏐48%**   |   -1.3pp    | Auto |

> [!NOTE]
> **GOLD 열의 prior CV disease = 1,749 vs §6.2의 4,642 차이**:
>
> - §6.2의 4,642는 **TROY v3.4** 기준 — 15개 ConceptSet을 age 무관 flat list로 나열 (더 넓은 concept 집합)
> - 이 테이블의 1,749는 **GOLD** 기준 — v1.1의 age-stratified 구조 이식 (≥50+CV 8항목, ≥60+risk 4항목)
> - GOLD는 v1.1 구조를 채택하여 **더 적은 concept으로 프로토콜에 더 충실한 정의**를 사용
> - 따라서 동일 rule이라도 비교 기준(TROY vs GOLD)에 따라 resolved 수가 다름

#### Per-rule: M-GOLD-fast (FORCE_FAST_PATH=1)

|  #  | Rule               | GOLD resolved | Agent2 resolved | Recall  | Precision |  F1  |   Status   |
| :-: | ------------------ | :-----------: | :-------------: | :-----: | :-------: | :--: | :--------: |
|  1  | HbA1C ≥ 7%         |       1       |        2        |  100%   |    50%    | 67%  |  ✅ FULL   |
|  2  | prior CV disease   |     1,749     |      2,048      |   35%   |    30%    | 32%  | 🔶 PARTIAL |
|  3  | No T1DM            |      129      |       25        |   19%   |   100%    | 32%  |  ❌ WRONG  |
|  4  | No calcitonin ≥ 50 |       2       |       16        |   50%   |    6%     | 11%  | 🔶 PARTIAL |
|  5  | No GLP-1/DPP-4     |     3,310     |      4,498      |  100%   |    74%    | 85%  |  ✅ FULL   |
|  6  | No insulin         |     8,449     |     10,637      |   97%   |    77%    | 86%  |  ✅ FULL   |
|  7  | No acute decomp.   |       8       |       13        |  100%   |    62%    | 76%  |  ✅ FULL   |
|  8  | No acute coronary  |      876      |       277       | **12%** |    39%    | 19%  |  ❌ WRONG  |
|  9  | No CHF             |      164      |      2,415      |  100%   |    7%     | 13%  |  ✅ FULL   |
| 10  | No renal replace.  |      126      |       334       |   87%   |    33%    | 47%  |  ✅ FULL   |
| 11  | No eGFR <30        |      38       |       160       |  100%   |    24%    | 38%  |  ✅ FULL   |
| 12  | No ESLD            |      770      |       768       |   31%   |    31%    | 31%  | 🔶 PARTIAL |
| 13  | No transplant      |      285      |       65        |   20%   |    88%    | 33%  |  ❌ WRONG  |
| 14  | No malignant       |     5,310     |      4,588      |   86%   |   100%    | 93%  |  ✅ FULL   |
| 15  | No MEN2/FMTC       |       6       |      5,597      |  100%   |    0%     |  0%  |  ✅ FULL   |
| 16  | No substance abuse |      241      |       301       |  100%   |    80%    | 89%  |  ✅ FULL   |
| 17  | No pregnant        |     2,253     |      2,253      |  100%   |   100%    | 100% |  ✅ FULL   |

→ [Fast Report JSON](../../output/benchmark_a_direct_20260305_0012.json)

#### Per-rule: M-GOLD-slow (FORCE_SLOW_PATH=1)

|  #  | Rule               | GOLD resolved | Agent2 resolved | Recall  | Precision |  F1  |   Status   |
| :-: | ------------------ | :-----------: | :-------------: | :-----: | :-------: | :--: | :--------: |
|  1  | HbA1C ≥ 7%         |       1       |        5        |  100%   |    20%    | 33%  |  ✅ FULL   |
|  2  | prior CV disease   |     1,749     |      5,143      | **80%** |    27%    | 41%  |  ✅ FULL   |
|  3  | No T1DM            |      129      |       25        |   19%   |   100%    | 32%  |  ❌ WRONG  |
|  4  | No calcitonin ≥ 50 |       2       |       24        | **0%**  |    0%     |  0%  |  ❌ WRONG  |
|  5  | No GLP-1/DPP-4     |     3,310     |      4,498      |  100%   |    74%    | 85%  |  ✅ FULL   |
|  6  | No insulin         |     8,449     |     10,637      |   97%   |    77%    | 86%  |  ✅ FULL   |
|  7  | No acute decomp.   |       8       |       17        |  100%   |    47%    | 64%  |  ✅ FULL   |
|  8  | No acute coronary  |      876      |       494       | **35%** |    62%    | 44%  | 🔶 PARTIAL |
|  9  | No CHF             |      164      |      2,376      | **76%** |    5%     | 10%  | 🔶 PARTIAL |
| 10  | No renal replace.  |      126      |       698       | **99%** |    18%    | 30%  |  ✅ FULL   |
| 11  | No eGFR <30        |      38       |       170       |   95%   |    21%    | 35%  |  ✅ FULL   |
| 12  | No ESLD            |      770      |       537       |   24%   |    34%    | 28%  |  ❌ WRONG  |
| 13  | No transplant      |      285      |       169       | **39%** |    66%    | 49%  | 🔶 PARTIAL |
| 14  | No malignant       |     5,310     |      4,449      |   84%   |   100%    | 91%  |  ✅ FULL   |
| 15  | No MEN2/FMTC       |       6       |       270       | **67%** |    1%     |  3%  | 🔶 PARTIAL |
| 16  | No substance abuse |      241      |       350       |  100%   |    69%    | 82%  |  ✅ FULL   |
| 17  | No pregnant        |     2,253     |      2,253      |  100%   |   100%    | 100% |  ✅ FULL   |

→ [Slow Report JSON](../../output/benchmark_a_direct_20260305_0016.json)

#### 핵심 차이 분석 (Fast vs Slow)

| Rule              |  Fast R  | Slow R  | Delta | 승자 | 원인                                     |
| ----------------- | :------: | :-----: | :---: | :--: | ---------------------------------------- |
| prior CV disease  |   35%    | **80%** | +45pp | Slow | UMLS synonym이 sub-condition 다수 커버   |
| No acute coronary |   12%    | **35%** | +23pp | Slow | Multi-query로 MI/Stroke/Revasc 분리 탐색 |
| No transplant     |   20%    | **39%** | +19pp | Slow | LLM reranker가 procedure 구분            |
| No renal replace. |   87%    | **99%** | +12pp | Slow | synonym query로 dialysis variant 커버    |
| No CHF            | **100%** |   76%   | -24pp | Fast | Slow의 LLM reranker가 noise 추가         |
| No calcitonin     | **50%**  |   0%    | -50pp | Fast | Slow의 reranker가 calcitonin 놓침        |
| No malignant      | **86%**  |   84%   | -2pp  | Fast | 동등                                     |

> **결론**: Slow path는 **복합 조건** (CV disease +45pp, coronary +23pp)에서 우위이나, **단순 명확 query**에서는 Fast가 더 안전하다. Auto routing이 최고 성능(75.0%)인 이유는 단순↔복합을 적절히 분배하기 때문.

---

## 7. Codex Critic Review 결과

> Codex (gpt-5.3-codex-spark, reasoning=high) 2회 리뷰 + 수동 검증

### 7.1 구조적 무결성

- JSON 문법: ✅ 유효, 참조 무결성: ✅ 42개 참조 모두 정의됨
- **고아 ConceptSets**: 14개 (정의만 있고 rule 미참조) → 유지보수 리스크
- **중복 ConceptSets**: 45↔124(LVH), 46↔125(LVD), 77↔97(Revasc), 86↔118↔122(microalbuminuria)

### 7.2 🚨 HbA1c 임계값 오류 (v3.4 원본 버그, GOLD에서 수정됨)

|       | v3.4 ❌                       | v1.1 ✅                      | GOLD (수정 후) ✅ |
| ----- | ----------------------------- | ---------------------------- | ----------------- |
| Value | 10                            | 7                            | **7**             |
| Op    | `gte`                         | `lt`                         | **`lt`**          |
| 의미  | ≥10 없어야 함 (≤10 모두 포함) | <7 없어야 함 (**≥7만 포함**) | <7 없어야 함      |

> v3.4의 HbA1c rule은 이름("≥7%")과 구현(`≥10 배제`)이 불일치하는 **원본 오류**.

### 7.3 연구논문용 핵심 이슈

1. **Planned revascularization** (Excl #7) 미반영 → protocol gap
2. **시간창 가정**: 180일 lookback은 protocol 미명시 operational 결정 (만성 질환에 과소반영)
3. **No insulin**: broad 집합으로 허용 제형(NPH/long-acting/premixed)까지 배제 위험
4. **CHF severity**: v1.1(NYHA IV) vs v3.4(II-III) 해석 불일치
5. **No transplant**: GOLD merge에서 R=20% 악화 → 후속 개선 필요
6. **substance abuse / pregnancy**: 원문에 없는 TROY 추가 항목
7. **CensoringCriteria**: cs117(DPP-4) 추적종료 근거 불명확
