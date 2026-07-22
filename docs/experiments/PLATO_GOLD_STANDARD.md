# PLATO GOLD Standard 구축

> PLATO Trial (NCT00391872) 기준  
> 원문 출처: NEJMoa0904327 (Wallentin et al., NEJM 2009)  
> GOLD JSON: [`data/gold/PLATO/PLATO_GOLD.json`](../../data/gold/PLATO/PLATO_GOLD.json)

---

## 1. 개요

|                     | **Design Paper**          | **TROY v1.1**    | **TROY v3.4**    |
| ------------------- | ------------------------- | ---------------- | ---------------- |
| **출처**            | NEJMoa0904327             | TROY 1.1 (OHDSI) | TROY 3.4 (OHDSI) |
| **약물**            | Ticagrelor vs Clopidogrel | Ticagrelor       | Ticagrelor       |
| **Inclusion rules** | 1 (ACS hospitalization)   | 1                | 1                |
| **Exclusion rules** | ~6                        | 4                | 4                |
| **ConceptSets**     | —                         | 23               | 28               |
| **Unique concepts** | —                         | 119              | 109              |

> [!NOTE]
> PLATO는 LEADER/EMPA-REG과 달리 **ACS (Acute Coronary Syndrome)** 치료 trial로, eligibility criteria가 훨씬 단순하다.
> Entry event는 "ACS로 입원"이고, 대부분의 criteria는 ACS 서브타입(STEMI vs NSTE-ACS) 분류와 약물 금기사항에 집중한다.

### 1.1 Design Paper 원문 기준 (NEJMoa0904327, Methods section p.1046)

**Inclusion criteria** (전문):

> Patients were eligible for enrollment if they were hospitalized for an **acute coronary syndrome**, with or without ST-segment elevation, with an **onset of symptoms during the previous 24 hours**.
>
> **For NSTE-ACS** (without ST-segment elevation), at least 2 of the following 3 criteria had to be met:
>
> 1. ST-segment changes on ECG indicating ischemia
> 2. Positive biomarker test indicating myocardial necrosis
> 3. One of several risk factors:
>    - Age ≥ 60 years
>    - Previous MI or CABG
>    - CAD with stenosis ≥50% in ≥2 vessels
>    - Previous ischemic stroke, TIA, carotid stenosis ≥50%, or cerebral revascularization
>    - Diabetes mellitus
>    - Peripheral arterial disease
>    - Chronic renal dysfunction (CrCl <60 mL/min/1.73 m²)
>
> **For STEMI** (with ST-segment elevation):
>
> 1. Persistent ST elevation ≥0.1 mV in ≥2 contiguous leads or new LBBB
> 2. Intention to perform primary PCI

**Exclusion criteria** (전문):

> 1. Any contraindication against the use of clopidogrel
> 2. Fibrinolytic therapy within 24 hours before randomization
> 3. Need for oral anticoagulation therapy
> 4. Increased risk of bradycardia
> 5. Concomitant therapy with a strong CYP 3A4 inhibitor or inducer

> [!IMPORTANT]
> **NCT JSON의 exclusion 추가 항목** (원문 미기재, ClinicalTrials.gov에만 명시):
>
> - Moderate or severe liver disease
> - Already treated with invasive (angioplasty) procedure for current ACS episode
> - Being treated with blood-clotting agents that cannot be stopped

> [!NOTE]
> **PLATO design paper의 protocol publication**:  
> James S, et al. "Ticagrelor versus clopidogrel in acute coronary syndromes in relation to renal function: results from the Platelet Inhibition and Patient Outcomes (PLATO) trial." _Circulation_ 2010.  
> 상세 protocol은 NEJM 본문의 Methods 섹션에 기술되어 있으며, Supplementary Appendix는 subgroup analysis 결과만 포함.

---

## 2. Eligibility Criteria 통합 비교

### 2.1 Protocol 원문 + 구현 비교

|  #  | Rule                            | Criteria 원문                                                            | v1.1                              | v3.4                                    |   GOLD    | 비고                           |
| :-: | ------------------------------- | ------------------------------------------------------------------------ | --------------------------------- | --------------------------------------- | :-------: | ------------------------------ |
|     | **— Inclusion (Entry) —**       |                                                                          |                                   |                                         |           |                                |
| I-1 | ACS hospitalization             | "Hospitalized for ACS (± ST-elevation), onset within 24 hours"           | ✅ STEMI + ACS(excl STEMI) entry  | ✅ STEMI + ACS(excl STEMI) + LBBB entry |    TBD    | v3.4: LBBB CS 추가             |
| I-2 | NSTE-ACS risk factors           | "≥2 of: ST changes, positive biomarker, risk factors (age≥60, MI, etc.)" | ✅ biomarkers (TnT, TnI, CK-MB)   | ✅ biomarkers (TnT, TnI, CK-MB)         |   동일    | ECG/biomarker criteria         |
| I-3 | NSTE-ACS risk factor: old MI    | "Previous MI or CABG"                                                    | ✅ Old MI 1 concept               | ✅ Old MI 1 concept + MI 1 concept      |    TBD    | v3.4: CAD, MI 별도 CS 추가     |
| I-4 | NSTE-ACS risk factor: CAD       | "CAD ≥50% stenosis in ≥2 vessels"                                        | ❌ 없음 (implicit)                | ✅ CAD 1 concept                        |   v3.4    | v3.4에서 명시적 추가           |
| I-5 | NSTE-ACS risk factor: DM        | "Diabetes mellitus"                                                      | ✅ DM 7 concepts                  | ✅ DM 2 concepts                        |    TBD    | v1.1이 더 넓음                 |
| I-6 | NSTE-ACS risk factor: PAD/CKD   | "PAD; CrCl <60 mL/min"                                                   | ✅ PAD 1 + CrCl 3 concepts        | ✅ PAD 1 + CrCl 1 concept               |    TBD    | v1.1: lab concept 더 넓음      |
| I-7 | STEMI criteria                  | "Persistent ST elevation + intention for primary PCI"                    | ✅ PCI+CABG 42 concepts           | ✅ PCI 41 + PCI+CABG 44 concepts        |    TBD    | v3.4: PCI 별도 CS 추가         |
|     | **— Exclusion —**               |                                                                          |                                   |                                         |           |                                |
| E-1 | No clopidogrel contraindication | "Any contraindication against the use of clopidogrel"                    | ❌ 없음 (너무 일반적)             | ❌ 없음                                 | 🚫 미구현 | 코딩 불가                      |
| E-2 | No fibrinolytics (24h)          | "Fibrinolytic therapy within 24 hours before randomization"              | ✅ Fibrinolytic agents 6 concepts | ✅ Fibrinolytic agents 6 concepts       |   동일    | —                              |
| E-3 | No oral anticoagulants          | "Need for oral anticoagulation therapy"                                  | ✅ Anticoagulants 6 concepts      | ✅ Anticoagulants 6 concepts            |   동일    | —                              |
| E-4 | No CYP 3A4 inhibitors           | "Concomitant therapy with strong CYP 3A4 inhibitor or inducer"           | ✅ CYP inhibitors 12 concepts     | ✅ CYP inhibitors 12 concepts           |   동일    | —                              |
| E-5 | No bradycardia risk             | "Increased risk of bradycardia"                                          | ❌ 없음                           | ❌ 없음                                 | 🚫 미구현 | 임상적 판단 필요, 코딩 어려움  |
| E-6 | No liver disease                | "Moderate or severe liver disease" (NCT only)                            | ❌ 없음                           | ❌ 없음                                 | 🚫 미구현 | NCT에만 명시, 본문에 없음      |
|     | **— TROY 추가 —**               |                                                                          |                                   |                                         |           |                                |
|  —  | Intracranial hemorrhage         | ❌ 원문 미명시                                                           | ✅ 15 concepts                    | ✅ 15 concepts                          |   동일    | TROY가 추가한 임상적 exclusion |
|  —  | Peptic ulcer                    | ❌ 원문 미명시                                                           | ✅ 1 concept                      | ✅ 1 concept                            |   동일    | TROY가 추가한 출혈 위험 관련   |
|  —  | Prasugrel                       | ❌ 원문 미명시                                                           | ❌ 없음                           | ✅ Prasugrel 1 concept                  |     —     | v3.4에서 추가                  |

---

## 3. v1.1 vs v3.4 주요 차이

| 관점                    |    v1.1     |   v3.4    |
| ----------------------- | :---------: | :-------: |
| **ConceptSets 수**      |     23      |    28     |
| **Unique Concepts 수**  |     119     |    109    |
| **LBBB entry criteria** |   ❌ 없음   |  ✅ 추가  |
| **CAD concept**         |   ❌ 없음   |  ✅ 추가  |
| **Prasugrel exclusion** |   ❌ 없음   |  ✅ 추가  |
| **PCI 별도 CS**         |   ❌ 없음   |  ✅ 추가  |
| **DM concept 수**       | 7 (더 넓음) |     2     |
| **Chronic renal CrCl**  | 3 concepts  | 1 concept |

> **결론**: v3.4가 STEMI entry (LBBB 추가)와 약물 exclusion (Prasugrel)에서 더 충실.  
> v1.1이 DM, CKD 등 risk factor concept 커버리지에서 더 넓음.  
> 전반적으로 **v3.4의 구조 + v1.1의 concept 커버리지**를 결합하는 것이 최적.

---

## 4. PLATO indication-only 버전 비교

PLATO에는 "indication" 버전이 별도 존재:

- `[TROY v1.1] Ticagrelor (PLATO indication).json` — 44KB (vs full 158KB)

Indication-only 버전은 cohort 정의 자체가 다르며 (indication cohort vs treatment cohort), **GOLD 기준은 full 버전을 사용**한다.

---

## 5. 벤치마크 결과

_Phase 4 진행 후 업데이트 예정_

---

## 6. Codex Critic Review

_Phase 7 진행 후 업데이트 예정_
