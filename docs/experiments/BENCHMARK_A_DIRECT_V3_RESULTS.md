# M-TROY v3 — Detailed Results

> 🏷 명명 규칙: [EXPERIMENT_NAMING_CONVENTION.md](./EXPERIMENT_NAMING_CONVENTION.md) | 레거시 이름: `A_direct v3`

**Timestamp**: 20260303_0128
**Tier**: Tier 1 — Mapping Accuracy
**Pipeline**: TROY entity_text → Agent 2 (no Agent 1)
**TROY**: data/sample/LEADER/[TROY] Liraglutide (LEADER) v3.4.json
**Schema**: synthea_cdm

### 변경 사항 (vs M-TROY v2)

- Neo4j full transitive closure (19.57M rels, CSV bulk import 20초)
- ancestor_climb: top-K union, Disorder class whitelist, SNOMED vocab filter
- concept_id string 호환 (CSV import → str()/int() 변환)
- → [ADR-018](../adr/ADR-018_Neo4j_Full_Transitive_Closure.md)

---

## Summary

| 지표              |    값     |
| ----------------- | :-------: |
| Evaluated         |   17/18   |
| **Avg Recall**    | **83.1%** |
| **Avg Precision** | **53.3%** |
| **Avg F1**        | **55.8%** |
| Full (≥80%)       |    13     |
| Partial (30-80%)  |     3     |
| Wrong (<30%)      |     1     |
| Empty             |     0     |

---

## Per-Rule Breakdown

### [1/18] Age >= 50

> ⏭️ DEMOGRAPHIC_SKIP

### [2/18] HbA1C >= 7 %

**✅ R=100% P=100% F1=100%**

|                        | TROY | Agent 2 |
| ---------------------- | :--: | :-----: |
| Raw concepts           |  1   |    1    |
| Resolved (descendants) |  1   |    1    |
| Overlap                |  —   |    1    |
| Processing time        |  —   | 13955ms |

**Queries:**

- `HbA1c` → 1 concepts (fast, 13955ms)

**TROY concept sets**: HbA1c

---

### [3/18] prior CV disease

**🟠 R=41% P=19% F1=26%**

|                        | TROY  | Agent 2  |
| ---------------------- | :---: | :------: |
| Raw concepts           |  106  |   417    |
| Resolved (descendants) | 4,642 |  10,003  |
| Overlap                |   —   |  1,919   |
| Processing time        |   —   | 237999ms |

**Queries:**

- `Revasculariazation_final` → 5 concepts (fast, 7120ms)
- `left ventricular hypertrophy` → 8 concepts (fast, 7198ms)
- `hypertension` → 104 concepts (fast, 28163ms)
- `Stroke, TIAs` → 21 concepts (fast, 11373ms)
- `Myocardial Infarction (MI)` → 38 concepts (fast, 16541ms)
- `eGFR` → 8 concepts (fast, 8163ms)
- `arterial stenosis` → 40 concepts (fast, 13557ms)
- `ischemic heart disease` → 44 concepts (fast, 21991ms)
- `left ventricular dysfunction` → 38 concepts (slow, 30336ms)
- `unstable angina` → 8 concepts (fast, 8542ms)
- `intermittent claudication` → 9 concepts (fast, 8361ms)
- `PAD` → 22 concepts (fast, 15460ms)
- `Heart Failure (NYHA class II-III)` → 21 concepts (fast, 19316ms)
- `microalbuminuria or proteimuria` → 22 concepts (slow, 21608ms)
- `Coronary artery disease` → 29 concepts (fast, 20268ms)

**TROY concept sets**: Myocardial Infarction (MI), Stroke, TIAs, Revasculariazation_final, arterial stenosis, Heart Failure (NYHA class II-III), unstable angina, ischemic heart disease, eGFR, Coronary artery disease, microalbuminuria or proteimuria, left ventricular dysfunction, hypertension, left ventricular hypertrophy, PAD, intermittent claudication

---

### [4/18] No T1DM

**✅ R=100% P=100% F1=100%**

|                        | TROY | Agent 2 |
| ---------------------- | :--: | :-----: |
| Raw concepts           |  1   |   19    |
| Resolved (descendants) |  25  |   25    |
| Overlap                |  —   |   25    |
| Processing time        |  —   | 8896ms  |

**Queries:**

- `Type 1 Diabetes Mellitus` → 19 concepts (fast, 8896ms)

**TROY concept sets**: Type 1 Diabetes Mellitus

---

### [5/18] No calcitonin >= 50 ng/L

**🟠 R=50% P=6% F1=11%**

|                        | TROY | Agent 2 |
| ---------------------- | :--: | :-----: |
| Raw concepts           |  2   |   16    |
| Resolved (descendants) |  2   |   16    |
| Overlap                |  —   |    1    |
| Processing time        |  —   | 7889ms  |

**Queries:**

- `Calcitonin` → 16 concepts (fast, 7889ms)

**TROY concept sets**: Calcitonin

---

### [6/18] No GLP1-RA, pramlintide, DPP-4 within 3 months

**✅ R=100% P=74% F1=85%**

|                        | TROY  | Agent 2 |
| ---------------------- | :---: | :-----: |
| Raw concepts           |  12   |   15    |
| Resolved (descendants) | 3,310 |  4,498  |
| Overlap                |   —   |  3,309  |
| Processing time        |   —   | 7300ms  |

**Queries:**

- `DPP4 inhibitors` → 8 concepts (slow, 2515ms)
- `pramlintide` → 1 concepts (slow, 2401ms)
- `GLP-1 receptor agonists` → 6 concepts (slow, 2383ms)

**TROY concept sets**: GLP-1 receptor agonists, pramlintide, DPP4 inhibitors

---

### [7/18] No use of insulin

**✅ R=97% P=77% F1=86%**

|                        | TROY  | Agent 2 |
| ---------------------- | :---: | :-----: |
| Raw concepts           |  19   |   31    |
| Resolved (descendants) | 8,449 | 10,637  |
| Overlap                |   —   |  8,213  |
| Processing time        |   —   | 2578ms  |

**Queries:**

- `Insulin` → 31 concepts (slow, 2578ms)

**TROY concept sets**: Insulin

---

### [8/18] No acute decompensation of glycemic control

**✅ R=100% P=62% F1=76%**

|                        | TROY | Agent 2 |
| ---------------------- | :--: | :-----: |
| Raw concepts           |  1   |    9    |
| Resolved (descendants) |  8   |   13    |
| Overlap                |  —   |    8    |
| Processing time        |  —   | 7230ms  |

**Queries:**

- `diabetic ketoacidosis` → 9 concepts (fast, 7230ms)

**TROY concept sets**: diabetic ketoacidosis

---

### [9/18] No acute coronary or cerebrovascular event

**✅ R=87% P=9% F1=17%**

|                        | TROY | Agent 2 |
| ---------------------- | :--: | :-----: |
| Raw concepts           |  58  |   146   |
| Resolved (descendants) | 876  |  8,228  |
| Overlap                |  —   |   765   |
| Processing time        |  —   | 43444ms |

**Queries:**

- `Stroke` → 100 concepts (fast, 26353ms)
- `(acute) MI` → 41 concepts (fast, 11539ms)
- `Revasculariazation_final` → 5 concepts (fast, 5552ms)

**TROY concept sets**: (acute) MI, Stroke, Revasculariazation_final

---

### [10/18] No CHF

**✅ R=100% P=7% F1=13%**

|                        | TROY | Agent 2 |
| ---------------------- | :--: | :-----: |
| Raw concepts           |  3   |   26    |
| Resolved (descendants) | 164  |  2,415  |
| Overlap                |  —   |   164   |
| Processing time        |  —   | 18202ms |

**Queries:**

- `Oxygen therapy (NYHA class IV)` → 3 concepts (fast, 4723ms)
- `Heart Failure (NYHA class II-III)` → 23 concepts (fast, 13480ms)

**TROY concept sets**: Oxygen therapy (NYHA class IV), Heart Failure (NYHA class II-III)

---

### [11/18] No current continuous renal replacement

**✅ R=87% P=33% F1=47%**

|                        | TROY | Agent 2 |
| ---------------------- | :--: | :-----: |
| Raw concepts           |  6   |   76    |
| Resolved (descendants) | 126  |   333   |
| Overlap                |  —   |   109   |
| Processing time        |  —   | 45596ms |

**Queries:**

- `renal dialysis` → 21 concepts (fast, 9521ms)
- `ESRD` → 7 concepts (slow, 11197ms)
- `kidney transplant (procedure)` → 13 concepts (fast, 11108ms)
- `kidney transplant (condition)` → 35 concepts (fast, 13770ms)

**TROY concept sets**: ESRD, renal dialysis, kidney transplant (condition), kidney transplant (procedure)

---

### [12/18] No eGFR <30 mL/min/1.73m2

**✅ R=100% P=24% F1=38%**

|                        | TROY | Agent 2 |
| ---------------------- | :--: | :-----: |
| Raw concepts           |  5   |   11    |
| Resolved (descendants) |  38  |   160   |
| Overlap                |  —   |   38    |
| Processing time        |  —   | 21273ms |

**Queries:**

- `eGFR` → 8 concepts (fast, 7915ms)
- `CKD 4-5` → 3 concepts (slow, 13358ms)

**TROY concept sets**: eGFR, CKD 4-5

---

### [13/18] No ESLD

**🟠 R=33% P=28% F1=30%**

|                        | TROY | Agent 2 |
| ---------------------- | :--: | :-----: |
| Raw concepts           |  20  |   54    |
| Resolved (descendants) | 770  |   926   |
| Overlap                |  —   |   256   |
| Processing time        |  —   | 33097ms |

**Queries:**

- `significant liver disease` → 31 concepts (fast, 14328ms)
- `liver disease_procedure` → 20 concepts (fast, 8208ms)
- `ESLD` → 2 concepts (slow, 6359ms)
- `Total bilirubin` → 1 concepts (fast, 4203ms)

**TROY concept sets**: ESLD, Total bilirubin, liver disease_procedure, significant liver disease

---

### [14/18] No history of transplant

**❌ R=18% P=88% F1=30%**

|                        | TROY | Agent 2 |
| ---------------------- | :--: | :-----: |
| Raw concepts           |  19  |   42    |
| Resolved (descendants) | 319  |   65    |
| Overlap                |  —   |   57    |
| Processing time        |  —   | 21543ms |

**Queries:**

- `transplant_proc` → 1 concepts (fast, 8615ms)
- `organ transplant_cond` → 41 concepts (fast, 12928ms)

**TROY concept sets**: organ transplant_cond, transplant_proc

> ⚠️ **Wrong**: overlap=57 / troy=319. 추가 분석 필요.

---

### [15/18] No malignant (1825 days prior)

**✅ R=100% P=100% F1=100%**

|                        | TROY  | Agent 2 |
| ---------------------- | :---: | :-----: |
| Raw concepts           |   2   |   100   |
| Resolved (descendants) | 5,310 |  5,309  |
| Overlap                |   —   |  5,309  |
| Processing time        |   —   | 36807ms |

**Queries:**

- `History of malignant neoplasm` → 100 concepts (fast, 36807ms)

**TROY concept sets**: History of malignant neoplasm

---

### [16/18] No FH/PH of MEN2 or FMTC

**✅ R=100% P=0% F1=0%**

|                        | TROY | Agent 2 |
| ---------------------- | :--: | :-----: |
| Raw concepts           |  2   |   11    |
| Resolved (descendants) |  6   |  5,597  |
| Overlap                |  —   |    6    |
| Processing time        |  —   | 14824ms |

**Queries:**

- `MEN2` → 6 concepts (fast, 7911ms)
- `MTC` → 5 concepts (fast, 6913ms)

**TROY concept sets**: MEN2, MTC

> ⚠️ **Over-expansion**: recall 높지만 precision 0.1%. Agent 2가 5,597개 중 6개만 정답.

---

### [17/18] No drug use or dependence

**✅ R=100% P=80% F1=89%**

|                        | TROY | Agent 2 |
| ---------------------- | :--: | :-----: |
| Raw concepts           |  3   |   42    |
| Resolved (descendants) | 241  |   300   |
| Overlap                |  —   |   241   |
| Processing time        |  —   | 14228ms |

**Queries:**

- `substance abuse` → 42 concepts (fast, 14228ms)

**TROY concept sets**: substance abuse

---

### [18/18] No pregnant

**✅ R=99% P=100% F1=99%**

|                        | TROY  | Agent 2 |
| ---------------------- | :---: | :-----: |
| Raw concepts           |   1   |   40    |
| Resolved (descendants) | 2,253 |  2,222  |
| Overlap                |   —   |  2,222  |
| Processing time        |   —   | 16549ms |

**Queries:**

- `Pregnancy, childbirth and puerperium finding` → 40 concepts (fast, 16549ms)

**TROY concept sets**: Pregnancy, childbirth and puerperium finding

---

→ [Raw JSON](../../output/benchmark_a_direct_20260303_0128.json)
