# Benchmark V7 Exp B: Design Paper PDF → Agent 1 → Agent 2 (+ATC)

> 🏷 명명 규칙: [EXPERIMENT_NAMING_CONVENTION.md](./EXPERIMENT_NAMING_CONVENTION.md) | 실험 계열: **Exp B**

**Date**: 2026-03-01  
**Input**: NEJMoa1603827.pdf eligibility criteria section  
**Pipeline**: PDF text → Agent 1 (`parse`) → Agent 2 (+ATC)  
**Resolution**: Circe-compliant

### Agent 1 Input (53782 chars)

```
new england
journal of medicine
The

established in 1812

July 28, 2016

vol. 375

no. 4

Liraglutide and Cardiovascular Outcomes in Type 2 Diabetes
Steven P. Marso, M.D., Gilbert H. Daniels, M.D., Kirstine Brown‑Frandsen, M.D., Peter Kristensen, M.D., E.M.B.A.,
Johannes F.E. Mann, M.D., Michael A. ...
```

### Agent 1 Decomposition: 8 sub-criteria

|  #  |    Domain    | Entity Text                                                                  | → TROY Rule                                    |
| :-: | :----------: | ---------------------------------------------------------------------------- | ---------------------------------------------- |
|  1  |  Condition   | Type 2 Diabetes Mellitus                                                     | ???                                            |
|  2  | Measurement  | Hemoglobin A1c/Hemoglobin.total in Blood                                     | HbA1C >= 7 %                                   |
|  3  | Demographics | Age                                                                          | ???                                            |
|  4  | Demographics | Age                                                                          | ???                                            |
|  5  |  Condition   | Type 1 Diabetes Mellitus                                                     | No T1DM                                        |
|  6  |     Drug     | GLP-1 receptor agonists, DPP-4 inhibitors, pramlintide, rapid-acting insulin | No GLP1-RA, pramlintide, DPP-4 within 3 months |
|  7  |  Condition   | Multiple endocrine neoplasia type 2 or medullary thyroid cancer              | No malignant (1825 days prior)                 |
|  8  |  Condition   | Acute coronary or cerebrovascular event                                      | prior CV disease                               |

---

### Hierarchical Comparison

|  Level   | Rule / ConceptSet                                  |   TROY    |   Agent2   | Overlap |    R     |     |
| :------: | -------------------------------------------------- | :-------: | :--------: | :-----: | :------: | :-: |
| **Rule** | **Age >= 50**                                      |     -     |     -      |    -    |    ⏭    |     |
| **Rule** | **HbA1C >= 7 %**                                   |   **1**   |   **1**    |  **1**  | **100%** | ✅  |
| **Rule** | **prior CV disease**                               | **4,783** |  **139**   | **100** |  **2%**  | ❌  |
|          | ├─ left ventricular hypertrophy                    |     6     |            |    0    |    0%    | ❌  |
|          | ├─ left ventricular dysfunction                    |     7     |            |    0    |    0%    | ❌  |
|          | ├─ PAD                                             |    247    |            |    0    |    0%    | ❌  |
|          | ├─ intermittent claudication                       |    12     |            |    0    |    0%    | ❌  |
|          | ├─ Stroke, TIAs                                    |    96     |            |    5    |    5%    | ❌  |
|          | ├─ Revasculariazation_final                        |    812    |            |    0    |    0%    | ❌  |
|          | ├─ arterial stenosis                               |    352    |            |    1    |    0%    | ❌  |
|          | ├─ Heart Failure (NYHA class II-III)               |    131    |            |    0    |    0%    | ❌  |
|          | ├─ unstable angina                                 |    10     |            |    0    |    0%    | ❌  |
|          | ├─ ischemic heart disease                          |   3,301   |            |   95    |    3%    | ❌  |
|          | ├─ eGFR                                            |     1     |            |    0    |    0%    | ❌  |
|          | ├─ Coronary artery disease                         |    45     |            |    0    |    0%    | ❌  |
|          | ├─ hypertension                                    |    142    |            |    0    |    0%    | ❌  |
|          | ├─ Myocardial Infarction (MI)                      |    131    |            |   90    |   69%    | 🔶  |
|          | └─ microalbuminuria or proteimuria                 |    128    |            |    0    |    0%    | ❌  |
| **Rule** | **No T1DM**                                        |  **25**   |   **19**   | **19**  | **76%**  | 🔶  |
| **Rule** | **No calcitonin >= 50 ng/L**                       |   **2**   |   **0**    |  **0**  |  **0%**  | ❌  |
| **Rule** | **No GLP1-RA, pramlintide, DPP-4 within 3 months** | **3,399** | **10,741** | **558** | **16%**  | ❌  |
|          | ├─ pramlintide                                     |     1     |            |    0    |    0%    | ❌  |
|          | ├─ GLP-1 receptor agonists                         |   1,409   |            |   558   |   40%    | 🔶  |
|          | └─ DPP4 inhibitors                                 |   1,989   |            |    0    |    0%    | ❌  |
| **Rule** | **No use of insulin**                              | **8,526** |   **0**    |  **0**  |  **0%**  | ❌  |
| **Rule** | **No acute decompensation of glycemic control**    |   **8**   |   **0**    |  **0**  |  **0%**  | ❌  |
| **Rule** | **No acute coronary or cerebrovascular event **    | **1,015** |   **0**    |  **0**  |  **0%**  | ❌  |
|          | ├─ Stroke                                          |    84     |            |    0    |    0%    | ❌  |
|          | ├─ Revasculariazation_final                        |    812    |            |    0    |    0%    | ❌  |
|          | └─ (acute) MI                                      |    119    |            |    0    |    0%    | ❌  |
| **Rule** | **No CHF**                                         |  **166**  |   **0**    |  **0**  |  **0%**  | ❌  |
|          | ├─ Heart Failure (NYHA class II-III)               |    131    |            |    0    |    0%    | ❌  |
|          | └─ Oxygen therapy (NYHA class IV)                  |    35     |            |    0    |    0%    | ❌  |
| **Rule** | **No current continuous renal replacement**        |  **143**  |   **0**    |  **0**  |  **0%**  | ❌  |
|          | ├─ ESRD                                            |    16     |            |    0    |    0%    | ❌  |
|          | ├─ renal dialysis                                  |    70     |            |    0    |    0%    | ❌  |
|          | ├─ kidney transplant (condition)                   |    37     |            |    0    |    0%    | ❌  |
|          | └─ kidney transplant (procedure)                   |    20     |            |    0    |    0%    | ❌  |
| **Rule** | **No eGFR <30 mL/min/1.73m2**                      |  **38**   |   **0**    |  **0**  |  **0%**  | ❌  |
|          | ├─ eGFR                                            |     3     |            |    0    |    0%    | ❌  |
|          | └─ CKD 4-5                                         |    35     |            |    0    |    0%    | ❌  |
| **Rule** | **No ESLD**                                        |  **771**  |   **0**    |  **0**  |  **0%**  | ❌  |
|          | ├─ ESLD                                            |    108    |            |    0    |    0%    | ❌  |
|          | ├─ Total bilirubin                                 |     1     |            |    0    |    0%    | ❌  |
|          | ├─ liver disease_procedure                         |     2     |            |    0    |    0%    | ❌  |
|          | └─ significant liver disease                       |    708    |            |    0    |    0%    | ❌  |
| **Rule** | **No history of transplant**                       |  **379**  |   **0**    |  **0**  |  **0%**  | ❌  |
|          | ├─ organ transplant_cond                           |    115    |            |    0    |    0%    | ❌  |
|          | └─ transplant_proc                                 |    264    |            |    0    |    0%    | ❌  |
| **Rule** | **No malignant (1825 days prior)**                 | **5,314** |  **535**   | **248** |  **5%**  | ❌  |
| **Rule** | **No FH/PH of MEN2 or FMTC**                       |   **6**   |   **0**    |  **0**  |  **0%**  | ❌  |
|          | ├─ MEN2                                            |     4     |            |    0    |    0%    | ❌  |
|          | └─ MTC                                             |     2     |            |    0    |    0%    | ❌  |
| **Rule** | **No drug use or dependence**                      |  **241**  |   **0**    |  **0**  |  **0%**  | ❌  |
| **Rule** | **No pregnant**                                    | **2,253** |   **0**    |  **0**  |  **0%**  | ❌  |
