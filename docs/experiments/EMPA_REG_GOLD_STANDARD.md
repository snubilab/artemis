# EMPA-REG OUTCOME GOLD Standard 구축

> EMPA-REG OUTCOME (NCT01131676) 기준  
> 원문 출처: NEJMoa1504720 Supplementary Appendix  
> GOLD JSON: [`data/gold/EMPA-REG/EMPA_REG_GOLD.json`](../../data/gold/EMPA-REG/EMPA_REG_GOLD.json)

---

## 1. 개요

|                     | **Design Paper**         | **TROY v1.1**    | **TROY v3.4**    |
| ------------------- | ------------------------ | ---------------- | ---------------- |
| **출처**            | NEJMoa1504720 Appendix   | TROY 1.1 (OHDSI) | TROY 3.4 (OHDSI) |
| **약물**            | Empagliflozin vs placebo | Empagliflozin    | Empagliflozin    |
| **Inclusion rules** | CV risk 6개 + HbA1c      | 3                | 3                |
| **Exclusion rules** | 14                       | 10               | 11               |
| **ConceptSets**     | —                        | 46               | 57               |
| **Unique concepts** | —                        | 226              | 256              |

### 1.1 Design Paper 원문 기준 (Supplementary Appendix)

**Main Inclusion Criteria** (NEJMoa1504720 main paper + ClinicalTrials.gov):

> 1. Type 2 diabetes mellitus (T2DM)
> 2. BMI ≤ 45 kg/m²
> 3. HbA1c 7.0–10.0% (drug-naïve) or 7.0–10.0% (on background therapy)
> 4. Age ≥ 18 years
> 5. High risk of cardiovascular events (≥1 of criteria in Section C below)
> 6. Estimated GFR ≥ 30 mL/min/1.73 m²

**Section C: Definition of high risk of cardiovascular events** (Appendix p.16):

> ≥1 of the following:
>
> 1. History of MI >2 months prior
> 2. Multi-vessel CAD (≥2 major coronary arteries or left main), documented by:
>    - ≥50% stenosis on angiography (coronary or CT)
>    - Previous revascularization (PTCA ± stent or CABG) >2 months prior
>    - Combination of revascularization in one + ≥50% stenosis in another
> 3. Single-vessel CAD (≥50% stenosis, not subsequently revascularized) + ≥1 of:
>    - Positive non-invasive stress test for ischemia
>    - Hospital discharge for unstable angina ≤12 months prior
> 4. Unstable angina >2 months prior with evidence of CAD
> 5. History of stroke (ischemic or hemorrhagic) >2 months prior
> 6. Occlusive peripheral artery disease:
>    - Limb angioplasty, stenting, or bypass surgery
>    - Limb or foot amputation due to circulatory insufficiency
>    - Significant PAD stenosis (>50%)
>    - ABI <0.9 in ≥1 ankle

**Section D: Exclusion criteria** (Appendix p.17-18):

> 1. Uncontrolled hyperglycemia (glucose >240 mg/dL after overnight fast, confirmed by second measurement)
> 2. Liver disease (ALT, AST, or ALP above 3× ULN)
> 3. Planned cardiac surgery or angioplasty within 3 months
> 4. eGFR <30 mL/min/1.73 m²
> 5. Bariatric surgery within past 2 years / chronic malabsorption
> 6. Blood dyscrasias or disorders causing hemolysis or unstable RBCs
> 7. Cancer (except basal cell carcinoma) and/or treatment within last 5 years
> 8. Contraindications to background therapy
> 9. Anti-obesity drugs within 3 months prior / unstable body weight
> 10. Systemic steroids at informed consent or thyroid hormone dosage change within 6 weeks
> 11. Any uncontrolled endocrine disorder except T2DM
> 12. Pre-menopausal women: nursing, pregnant, or child-bearing potential without acceptable birth control
> 13. Alcohol or drug abuse within 3 months
> 14. Acute coronary syndrome, stroke, or TIA within 2 months prior

---

## 2. Eligibility Criteria 통합 비교

### 2.1 Protocol 원문 + 구현 비교

|  #   | Rule                       | Criteria 원문                                                                | v1.1                                    | v3.4                                    |   GOLD    | 비고                                    |
| :--: | -------------------------- | ---------------------------------------------------------------------------- | --------------------------------------- | --------------------------------------- | :-------: | --------------------------------------- |
|      | **— Inclusion —**          |                                                                              |                                         |                                         |           |                                         |
| I-1  | T2DM (Entry)               | "Type 2 diabetes mellitus"                                                   | DrugEra (OADs+GLP-1) + T2DM condition   | DrugEra (antidiabetic) + T2DM condition |    TBD    | PrimaryCriteria: Entry event            |
| I-2  | Age ≥ 18                   | "Age ≥ 18 years"                                                             | ❌ 없음                                 | ✅ DemographicCriteria                  |   v3.4    | v1.1 누락                               |
| I-3  | HbA1c 7-10%                | "HbA1c 7.0–10.0%"                                                            | ✅ 2 concepts (HbA1c)                   | ✅ 1 concept (HbA1c)                    |   v1.1    | v1.1: 2 concepts for measurement        |
| I-4  | High CV risk               | "≥1 CV condition (MI, multi-vessel CAD, stroke, PAD, etc.)"                  | ✅ age-conditioned OR                   | ✅ age-conditioned OR                   |    TBD    | 복합 조건                               |
| I-5  | BMI ≤ 45                   | "BMI ≤ 45 kg/m²"                                                             | ✅ BMI measurement                      | ✅ BMI measurement                      |   동일    | —                                       |
|      | **— Exclusion —**          |                                                                              |                                         |                                         |           |                                         |
| E-1  | No eGFR < 30               | "eGFR <30 mL/min/1.73 m²"                                                    | ✅ eGFR 5 concepts                      | ✅ eGFR 3 concepts + CKD 4-5            |    TBD    | v3.4: CKD stage 추가                    |
| E-2  | No liver disease           | "ALT/AST/ALP above 3× ULN"                                                   | ✅ liver disease 9 concepts             | ✅ liver disease 12 + procedure 1       |    TBD    | CS + lab measurements 별도              |
| E-3  | No bariatric surgery       | "Bariatric surgery within 2 years / chronic malabsorption"                   | ✅ 3 concepts                           | ✅ 3 concepts                           |   동일    | —                                       |
| E-4  | No blood dyscrasias        | "Blood dyscrasias causing hemolysis or unstable RBCs"                        | ✅ diseases of blood 8 concepts         | ✅ diseases of blood 9 concepts         |    TBD    | v3.4: 1개 추가                          |
| E-5  | No cancer (5y)             | "Cancer (except basal cell) within 5 years"                                  | ✅ malignant neoplasm + lymphoid        | ✅ malignant neoplasm + lymphoid        |    TBD    | both include isExcluded for skin cancer |
| E-6  | No anti-obesity drugs      | "Anti-obesity drugs 3 months prior"                                          | ✅ 9 concepts                           | ✅ 11 concepts                          |    TBD    | v3.4: 2 약물 추가                       |
| E-7  | No systemic steroids       | "Systemic steroids at informed consent"                                      | ✅ systemic glucocorticoid 231 concepts | ✅ oral corticosteroids 8 concepts      |    TBD    | v1.1이 훨씬 넓음                        |
| E-8  | No substance abuse         | "Alcohol or drug abuse within 3 months"                                      | ✅ substance abuse 3 concepts           | ✅ substance abuse 3 + alcohol 3        |    TBD    | v3.4: alcohol 별도 분리                 |
| E-9  | No ACS/stroke (2mo)        | "ACS, stroke, or TIA within 2 months"                                        | ✅ ACS+Stroke+TIA                       | ✅ ACS+Stroke+TIA+unstable angina       |    TBD    | 유사                                    |
| E-10 | No pregnant                | "Pre-menopausal women: nursing/pregnant/child-bearing without birth control" | ✅ Pregnancy 1 concept                  | ✅ Pregnancy + Contraception            |    TBD    | v3.4: contraception CS 추가             |
| E-11 | No planned cardiac surgery | "Planned cardiac surgery or angioplasty within 3 months"                     | ❌ 없음                                 | ✅ cardiac surgery 2 concepts           |   v3.4    | v1.1 누락                               |
| E-12 | No hyperglycemia           | "Glucose >240 mg/dL (fasting, confirmed)"                                    | ❌ 없음                                 | ❌ 없음                                 | 🚫 미구현 | 양쪽 모두 누락 (lab value 기반)         |
| E-13 | No contraindications       | "Contraindications to background therapy"                                    | ❌ 없음                                 | ❌ 없음                                 | 🚫 미구현 | 너무 일반적, 코딩 불가                  |
| E-14 | No endocrine disorder      | "Any uncontrolled endocrine disorder except T2DM"                            | ❌ 없음                                 | ❌ 없음                                 | 🚫 미구현 | 너무 일반적, 코딩 불가                  |

---

## 3. TROY-specific 추가 항목

v1.1/v3.4에 있지만 원문에 명시되지 않은 항목:

| 항목                 | v1.1 | v3.4 | 비고                     |
| -------------------- | :--: | :--: | ------------------------ |
| DPP4 inhibitors CS   |  ❌  |  ✅  | v3.4에서 추가 (E-? 없음) |
| Insulin CS           |  ❌  |  ✅  | v3.4에서 추가            |
| Entry: Empagliflozin |  ✅  |  ✅  | 양쪽 Entry Event         |

---

## 4. 벤치마크 결과

_Phase 4 진행 후 업데이트 예정_

---

## 5. Codex Critic Review

_Phase 7 진행 후 업데이트 예정_
