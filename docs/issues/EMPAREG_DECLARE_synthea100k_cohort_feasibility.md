# EMPA-REG OUTCOME (NCT01131676) — Synthea 100K Cohort Feasibility Report

**Study**: EMPA-REG OUTCOME (Empagliflozin Cardiovascular Outcome Event Trial in T2DM)  
**Database**: Synthea 100K (235,222 patients, OMOP CDM v5.3)  
**Date**: 2026-02-27  
**Comparison**: Empagliflozin (Treatment) vs DPP-4 inhibitor (Comparator)

---

## 1. TROY 코호트 구조

| 항목 | 값 |
|------|---|
| ConceptSets | 57 |
| InclusionRules | **14개** |
| PrimaryCriteria | DrugEra (EraStart ≥ 날짜, EraLength ≥ 7d, 180d prior obs) |

### InclusionRules

1. Age ≥ 18
2. Insufficient glycemic control
3. High risk of CV
4. BMI ≤ 45 kg/m² at baseline
5. No eGFR < 30 mL/min/1.73m²
6. No liver disease
7. No bariatric surgery
8. No blood dyscrasias
9. No history of cancer (1825 days prior)
10. No anti-obesity drugs (3 months prior)
11. No systemic steroids
12. No alcohol or drug abuse
13. No ACS, stroke, etc within 2 months
14. No pregnant

---

## 2. 약물 가용성 (Synthea 100K)

| Drug | Concept ID | Patients |
|------|:---:|:---:|
| **Empagliflozin** | 43009032 | **0** |
| DPP-4 inhibitor | 21600712 | 7,568 |
| DPP-4 + T2DM | — | 7,568 |

> [!CAUTION]
> **Empagliflozin이 Synthea 100K에 존재하지 않습니다.**
> Treatment arm 구성이 불가능합니다.

---

## 3. WebAPI Cohort Generation 결과

| Cohort | Patients |
|--------|:---:|
| Empagliflozin Entry-Only | **0** |
| Empagliflozin Full (14 rules) | **0** |
| DPP-4 Entry-Only | **0** |
| DPP-4 Full (14 rules) | **0** |

DPP-4 환자(7,568명)가 존재하지만 DrugEra temporal window를 통과하지 못하여 Entry-Only에서도 0명.

---

## 4. 결론

| 한계 | 영향 |
|------|------|
| Empagliflozin 미존재 (0건) | Treatment arm 구성 불가 |
| DPP-4 DrugEra temporal 미충족 | Comparator arm도 0명 |

**EMPA-REG OUTCOME은 Synthea 100K에서 재현 불가.**

---

# DECLARE-TIMI 58 (NCT01730534) — Synthea 100K Cohort Feasibility Report

**Study**: DECLARE-TIMI 58 (Dapagliflozin Effect on CardiovascuLAR Events)  
**Database**: Synthea 100K (235,222 patients, OMOP CDM v5.3)  
**Date**: 2026-02-27  
**Comparison**: Dapagliflozin (Treatment) vs DPP-4 inhibitor (Comparator)

---

## 1. TROY 코호트 구조

| 항목 | 값 |
|------|---|
| ConceptSets | 91 |
| InclusionRules | **14개** |
| PrimaryCriteria | DrugEra (EraStart ≥ 날짜, EraLength ≥ 7d, 180d prior obs) |

### InclusionRules

1. Age ≥ 40
2. High risk of CV
3. Excluded medications: pioglitazone
4. No current CV event
5. No T1DM, MODY, Secondary DM
6. No bladder cancer or radiation therapy
7. No history of cancer
8. No chronic cystitis / recurrent UTI
9. No pregnant
10. No HbA1c ≥ 12 or < 6.5
11. No AST/ALT > 3x ULN or Total bilirubin > 2.5x ULN
12. No CrCl < 60 ml/min
13. No hematuria
14. Systolic BP > 180 or diastolic BP > 100 mmHg

---

## 2. 약물 가용성 (Synthea 100K)

| Drug | Concept ID | Patients |
|------|:---:|:---:|
| **Dapagliflozin** | 43009089 | **0** |
| DPP-4 inhibitor | 21600712 | 7,568 |
| DPP-4 + T2DM | — | 7,568 |

> [!CAUTION]
> **Dapagliflozin이 Synthea 100K에 존재하지 않습니다.**
> Treatment arm 구성이 불가능합니다.

---

## 3. WebAPI Cohort Generation 결과

| Cohort | Patients |
|--------|:---:|
| Dapagliflozin Entry-Only | **0** |
| DPP-4 Entry-Only | 생성 중 중단 (추정 0) |

---

## 4. 결론

| 한계 | 영향 |
|------|------|
| Dapagliflozin 미존재 (0건) | Treatment arm 구성 불가 |
| DPP-4 DrugEra temporal 미충족 | Comparator arm도 0명 추정 |

**DECLARE-TIMI 58은 Synthea 100K에서 재현 불가.**
