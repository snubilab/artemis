# LEADER Trial (NCT01179048) — Synthea 100K Cohort Feasibility Report

**Study**: LEADER (Liraglutide Effect and Action in Diabetes: Evaluation of Cardiovascular Outcome Results)  
**Database**: Synthea 100K (235,222 patients, OMOP CDM v5.3)  
**Date**: 2026-02-27  
**TROY Cohort ID**: 5 (WebAPI)

---

## 1. Cumulative Exclusion (WebAPI Cohort Generation)

TROY LEADER 정의의 18개 InclusionRule을 순서대로 누적 적용:

| Step | Rule | Patients | Delta | Survival |
|:----:|------|:--------:|:-----:|:--------:|
| 0 | **Entry Only** (Liraglutide DrugEra) | **1,238** | — | 100% |
| 1 | + Age ≥ 50 | **272** | −966 | 22.0% |
| 2 | + HbA1c ≥ 7% | **272** | ±0 | 22.0% |
| 3 | + **Prior CV disease** | **0** | −272 | 0% |
| 4–18 | (나머지 15개 규칙) | — | — | skipped |

> [!IMPORTANT]
> Step 1에서 78% 탈락 이유: TROY는 `DrugEra`를 사용 (`EraStartDate ≥ 2010-10-06` + `EraLength ≥ 7일`).
> 단순 DrugExposure 기준으로는 Age ≥ 50이 **93.5%를 보존** (1,158 / 1,238).

---

## 2. Liraglutide 환자 연령 분포 (Synthea 100K)

| Age Group | N | % |
|:---------:|:---:|:---:|
| < 30 | 52 | 4.2% |
| 30–39 | 261 | 21.1% |
| 40–49 | 906 | 73.2% |
| **50–59** | **881** | **71.2%** |
| 60–69 | 245 | 19.8% |
| 70–79 | 30 | 2.4% |
| 80+ | 2 | 0.2% |

> 합계 > 100%: 환자가 여러 번 처방받아 다른 연령대에 중복 집계됨.

---

## 3. 심혈관 질환 유병률 (Lira + Age≥50, N=1,158, Synthea 100K)

| CV Condition | N | % |
|---|:---:|:---:|
| Coronary arteriosclerosis | 84 | 7.3% |
| Cerebrovascular disease | 56 | 4.8% |
| Heart failure | 39 | 3.4% |
| Atrial fibrillation | 24 | 2.1% |
| Myocardial infarction | 23 | 2.0% |
| Ischemic heart disease / Stroke / PVD / Angina | 0 | 0% |

> [!WARNING]
> CV 조건 보유 환자는 존재하나, TROY의 "prior CV disease"는 **CriteriaGroup 복합 조건**을 요구.
> DrugEra temporal window와 결합 시 0명이 됨.

---

## 4. 개별 규칙 독립 적용 (Synthea 100K, base=1,238)

| Exclusion Rule | 제외 환자 | 잔존 환자 | 영향도 |
|---|:---:|:---:|:---:|
| **No insulin use** | **1,238** | **0** | **100%** |
| No pregnancy | 453 | 785 | 36.6% |
| No CHF | 61 | 1,177 | 4.9% |
| No malignant neoplasm | 50 | 1,188 | 4.0% |
| No T1DM | 0 | 1,238 | 0% |
| No transplant | 0 | 1,238 | 0% |

> [!CAUTION]
> **"No insulin use" 규칙이 단독으로 전원 제외.**
> Synthea 100K에서 liraglutide 처방 환자 100%가 인슐린도 함께 처방됨.
> LEADER 원래 기준은 인슐린 미사용자 대상 — Synthea 처방 패턴이 현실과 상이.

---

## 5. HbA1c 측정 (Synthea 100K)

| 항목 | 결과 |
|------|------|
| HbA1c measurement 레코드 | **0건** |
| HbA1c ≥ 7% 규칙 영향 | ±0 (데이터 부재로 무력화) |

Synthea diabetes 모듈은 HbA1c measurement를 생성하지 않음.
WebAPI는 measurement 부재 시 규칙을 vacuously pass 처리.

---

## 6. Control Cohort 가용성 (Synthea 100K)

| Cohort | N |
|--------|:---:|
| 전체 T2DM 환자 | 8,150 |
| **Treatment** (T2DM + Liraglutide) | **1,238** |
| **Control** (T2DM, No Liraglutide) | **6,912** |
| Control + Age ≥ 50 | 5,991 |

Treatment 1,238 vs Control 6,912 — **비율 1:5.6**으로 PSM/IPTW 분석에 충분.

---

## 7. 결론

### Synthea 100K 데이터의 LEADER Trial 적용 한계

| # | 한계 | 영향 |
|---|------|------|
| 1 | Liraglutide 환자 100% 인슐린 동시 처방 | "No insulin" 규칙 적용 시 전멸 |
| 2 | HbA1c measurement 미생성 | HbA1c 기반 규칙 검증 불가 |
| 3 | CV comorbidity + DrugEra temporal 결합 시 0명 | Prior CV disease 규칙 통과 불가 |

### 실행 가능한 벤치마크 조건

Insulin + CV 규칙을 제외하면 유의미한 cohort study 가능:

```
Treatment: T2DM + Lira + Age≥50 + 기타 exclusion  → ~200–272명
Control:   T2DM + No Lira + Age≥50 + 동일 exclusion → ~5,000+명

→ PSM/IPTW → Cox PH → Hazard Ratio 산출 가능
```
