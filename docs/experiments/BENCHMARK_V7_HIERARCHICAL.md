# Benchmark V7: Rule → ConceptSet Hierarchical Comparison — Exp A 상세

> 🏷 명명 규칙: [EXPERIMENT_NAMING_CONVENTION.md](./EXPERIMENT_NAMING_CONVENTION.md) | 실험 계열: **Exp A**

**Date**: 2026-02-28  
**Input**: TROY rule names → Agent 1 → Agent 2 (+ATC)  
**Resolution**: Circe-compliant (`includeDescendants`/`isExcluded` respected)  
**Overall**: Avg R=41.5% | Avg F1=39.2%

|  Level   | Rule / ConceptSet                                  |   TROY    |   Agent2   |  Overlap  |    R     |     |
| :------: | -------------------------------------------------- | :-------: | :--------: | :-------: | :------: | :-: |
| **Rule** | **Age >= 50**                                      |     -     |     -      |     -     |    ⏭    |     |
| **Rule** | **HbA1C >= 7 %**                                   |   **1**   |   **1**    |   **1**   | **100%** | ✅  |
| **Rule** | **prior CV disease**                               | **4,783** | **3,107**  | **3,107** | **65%**  | 🔶  |
|          | ├─ left ventricular hypertrophy                    |     6     |            |     6     |   100%   | ✅  |
|          | ├─ left ventricular dysfunction                    |     7     |            |     7     |   100%   | ✅  |
|          | ├─ PAD                                             |    247    |            |     0     |    0%    | ❌  |
|          | ├─ intermittent claudication                       |    12     |            |     0     |    0%    | ❌  |
|          | ├─ Stroke, TIAs                                    |    96     |            |     0     |    0%    | ❌  |
|          | ├─ Revasculariazation_final                        |    812    |            |    15     |    2%    | ❌  |
|          | ├─ arterial stenosis                               |    352    |            |    36     |   10%    | ❌  |
|          | ├─ Heart Failure (NYHA class II-III)               |    131    |            |    131    |   100%   | ✅  |
|          | ├─ unstable angina                                 |    10     |            |    10     |   100%   | ✅  |
|          | ├─ ischemic heart disease                          |   3,301   |            |   3,107   |   94%    | ✅  |
|          | ├─ eGFR                                            |     1     |            |     0     |    0%    | ❌  |
|          | ├─ Coronary artery disease                         |    45     |            |    45     |   100%   | ✅  |
|          | ├─ hypertension                                    |    142    |            |     7     |    5%    | ❌  |
|          | ├─ Myocardial Infarction (MI)                      |    131    |            |    131    |   100%   | ✅  |
|          | └─ microalbuminuria or proteimuria                 |    128    |            |     1     |    1%    | ❌  |
| **Rule** | **No T1DM**                                        |  **25**   |   **19**   |  **19**   | **76%**  | 🔶  |
| **Rule** | **No calcitonin >= 50 ng/L**                       |   **2**   |   **15**   |   **0**   |  **0%**  | ❌  |
| **Rule** | **No GLP1-RA, pramlintide, DPP-4 within 3 months** | **3,399** | **4,593**  | **3,398** | **100%** | ✅  |
|          | ├─ pramlintide                                     |     1     |            |     0     |    0%    | ❌  |
|          | ├─ GLP-1 receptor agonists                         |   1,409   |            |   1,409   |   100%   | ✅  |
|          | └─ DPP4 inhibitors                                 |   1,989   |            |   1,989   |   100%   | ✅  |
| **Rule** | **No use of insulin**                              | **8,526** | **10,741** | **8,285** | **97%**  | ✅  |
| **Rule** | **No acute decompensation of glycemic control**    |   **8**   |  **180**   |   **0**   |  **0%**  | ❌  |
| **Rule** | **No acute coronary or cerebrovascular event **    | **1,015** |  **230**   |  **99**   | **10%**  | ❌  |
|          | ├─ Stroke                                          |    84     |            |     8     |   10%    | ❌  |
|          | ├─ Revasculariazation_final                        |    812    |            |     0     |    0%    | ❌  |
|          | └─ (acute) MI                                      |    119    |            |    91     |   76%    | 🔶  |
| **Rule** | **No CHF**                                         |  **166**  |   **34**   |  **32**   | **19%**  | ❌  |
|          | ├─ Heart Failure (NYHA class II-III)               |    131    |            |    32     |   24%    | ❌  |
|          | └─ Oxygen therapy (NYHA class IV)                  |    35     |            |     0     |    0%    | ❌  |
| **Rule** | **No current continuous renal replacement**        |  **143**  |  **127**   |  **70**   | **49%**  | 🔶  |
|          | ├─ ESRD                                            |    16     |            |     0     |    0%    | ❌  |
|          | ├─ renal dialysis                                  |    70     |            |    70     |   100%   | ✅  |
|          | ├─ kidney transplant (condition)                   |    37     |            |     0     |    0%    | ❌  |
|          | └─ kidney transplant (procedure)                   |    20     |            |     0     |    0%    | ❌  |
| **Rule** | **No eGFR <30 mL/min/1.73m2**                      |  **38**   |   **7**    |   **2**   |  **5%**  | ❌  |
|          | ├─ eGFR                                            |     3     |            |     2     |   67%    | 🔶  |
|          | └─ CKD 4-5                                         |    35     |            |     0     |    0%    | ❌  |
| **Rule** | **No ESLD**                                        |  **771**  |  **675**   |  **255**  | **33%**  | 🔶  |
|          | ├─ ESLD                                            |    108    |            |    33     |   31%    | 🔶  |
|          | ├─ Total bilirubin                                 |     1     |            |     0     |    0%    | ❌  |
|          | ├─ liver disease_procedure                         |     2     |            |     0     |    0%    | ❌  |
|          | └─ significant liver disease                       |    708    |            |    234    |   33%    | 🔶  |
| **Rule** | **No history of transplant**                       |  **379**  |   **20**   |  **20**   |  **5%**  | ❌  |
|          | ├─ organ transplant_cond                           |    115    |            |     0     |    0%    | ❌  |
|          | └─ transplant_proc                                 |    264    |            |    20     |    8%    | ❌  |
| **Rule** | **No malignant (1825 days prior)**                 | **5,314** | **2,118**  | **2,118** | **40%**  | 🔶  |
| **Rule** | **No FH/PH of MEN2 or FMTC**                       |   **6**   |  **293**   |   **6**   | **100%** | ✅  |
|          | ├─ MEN2                                            |     4     |            |     4     |   100%   | ✅  |
|          | └─ MTC                                             |     2     |            |     2     |   100%   | ✅  |
| **Rule** | **No drug use or dependence**                      |  **241**  |  **837**   |   **0**   |  **0%**  | ❌  |
| **Rule** | **No pregnant**                                    | **2,253** |   **95**   |  **95**   |  **4%**  | ❌  |

## Legend

- **Rule** rows: aggregate across all ConceptSets in that rule
- **├─/└─** rows: individual ConceptSet within a compound rule
- ✅ R≥80% | 🔶 R 30-80% | ❌ R<30%
