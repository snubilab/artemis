# PLATO Trial (NCT01232322) — Synthea 100K Cohort Feasibility Report

**Study**: PLATO (PLATelet Inhibition and Patient Outcomes) — Ticagrelor vs Clopidogrel in ACS  
**Database**: Synthea 100K (235,222 patients, OMOP CDM v5.3)  
**Date**: 2026-02-27  
**TROY Cohort**: Ticagrelor (PLATO indication), Clopidogrel (PLATO indication)

---

## 1. TROY PLATO 코호트 구조

| 항목 | Ticagrelor (Treatment) | Clopidogrel (Comparator) |
|------|:---:|:---:|
| PrimaryCriteria | DrugEra Ticagrelor | DrugEra Clopidogrel |
| EraStartDate | ≥ 2011-07-22 | ≥ 2011-07-22 |
| EraLength | ≥ 7 days | ≥ 7 days |
| Prior Observation | 180 days | 180 days |
| ConceptSets | 6 | 6 |
| InclusionRules | **1** (ACS) | **1** (ACS) |

LEADER(18 rules)와 달리 PLATO는 **단 1개 InclusionRule** (Acute Coronary Syndrome).

---

## 2. 약물 가용성 (Synthea 100K)

| Drug | Concept ID | Patients |
|------|:---:|:---:|
| **Ticagrelor** | 40228152 | **0** |
| Clopidogrel | 1322184 | 8,611 |
| Aspirin | 1112807 | 1,397 |

> [!CAUTION]
> **Ticagrelor가 Synthea 100K에 존재하지 않습니다.**
> Synthea의 기본 모듈에 ticagrelor 처방 경로가 포함되지 않아, treatment arm 코호트 구성이 불가능합니다.

---

## 3. ACS 조건 유병률 (Synthea 100K)

| Condition | Concept ID | Patients |
|-----------|:---:|:---:|
| Acute MI | 4329847 | 2,626 |
| ACS (general) | 321042 | 4,268 |
| Unstable angina | 315296 | 0 |

ACS 진단 환자는 충분하나, treatment drug(Ticagrelor)이 부재.

---

## 4. WebAPI Cohort Generation 결과

| Cohort | Patients | 비고 |
|--------|:---:|------|
| Ticagrelor Entry-Only | **0** | 약물 부재 |
| Ticagrelor Full (+ACS) | **0** | 약물 부재 |
| Clopidogrel Entry-Only | **262** | DrugEra temporal 필터 통과분 |
| Clopidogrel Full (+ACS) | **0** | ACS 규칙에서 전멸 |

### 분석

**Clopidogrel**: 8,611명이 처방받았으나 DrugEra 조건(EraStart ≥ 2011-07-22, EraLength ≥ 7d)을 충족하는 환자가 262명. 이 중 ACS 이력이 있는 환자는 0명.

**약물-진단 교차 확인**:

| 조합 | Patients |
|------|:---:|
| Clopidogrel + Acute MI | 1,577 |
| Ticagrelor + Acute MI | 0 |

Clopidogrel + AMI 환자(1,577명)가 존재하지만, 이들이 DrugEra temporal window를 통과하지 못하여 최종 0명.

---

## 5. LEADER 대비 비교

| 항목 | LEADER | PLATO |
|------|:---:|:---:|
| Treatment drug 존재 | ✅ (1,238명) | ❌ (0명) |
| Comparator drug 존재 | N/A (placebo) | ✅ (8,611명) |
| InclusionRules | 18개 | 1개 |
| Entry-Only 코호트 | 1,238명 | 0명 (Tica) / 262명 (Clop) |
| Full 코호트 | 0명 | 0명 |
| **주 원인** | CV disease 규칙 | **약물 자체 부재** |

---

## 6. 결론

### Synthea 100K에서 PLATO 재현이 불가능한 이유

| # | 한계 | 영향 |
|---|------|------|
| 1 | **Ticagrelor 미존재** (0건) | Treatment arm 구성 불가 |
| 2 | DrugEra temporal window | Clopidogrel 8,611 → 262명 |
| 3 | ACS + DrugEra 교차 | Clopidogrel 262명 중 ACS 0명 |

### 대안

1. **Clopidogrel-only 연구**: Clopidogrel + AMI(1,577명) vs Clopidogrel 미처방 AMI 환자로 관찰적 연구 가능
2. **Synthea 모듈 커스터마이징**: Ticagrelor 처방 경로 추가
3. **다른 약물 비교 trial**: Synthea에 존재하는 약물 기반 trial 선택
