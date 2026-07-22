---
theme: default
title: "TROY LEADER Cohort Feasibility on Synthea"
transition: slide-left
mdc: true
---

# TROY LEADER Cohort Feasibility
## Synthea 100K 데이터 적용 결과

<div class="mt-16 text-lg opacity-80">
ARTEMIS 3.1 — Cohort Definition Pipeline E2E 검증
</div>

<div class="abs-bl m-8 text-sm opacity-40">
2026-02-27 · Database: Synthea 100K (235,222 patients) · Trial: LEADER (NCT01179048)
</div>

---

# Eligibility Rule 누적 적용 결과

TROY LEADER의 18개 InclusionRule을 순서대로 적용 — **3번째 규칙에서 전멸**

<div class="mt-6"></div>

| Step | Eligibility Rule | 환자 수 | 감소 | 잔존율 |
|:----:|------------------|:-------:|:----:|:------:|
| 0 | Liraglutide DrugEra (Entry) | **1,238** | — | 100% |
| 1 | Age ≥ 50 | 272 | −966 | 22% |
| 2 | HbA1c ≥ 7% | 272 | 0 | 22% |
| 3 | **Prior CV disease** | **0** | **−272** | **0%** |

<div class="mt-6"></div>

**원인**: Synthea 환자는 단일 질환 경로 중심으로 생성되어, LEADER가 요구하는 **T2DM + CV 고위험 + 특정 temporal window** 조합을 동시에 충족하는 환자가 부재

---

# 개별 규칙 독립 분석 및 데이터 한계

각 exclusion을 **단독으로** base 1,238명에 적용하여 규칙별 영향도 측정

<div class="mt-4"></div>

| Exclusion Rule | 제외 환자 | 영향도 | 비고 |
|----------------|:--------:|:------:|------|
| No insulin use | **1,238** | **100%** | Synthea: Lira 환자 전원 insulin 동시 처방 |
| No pregnancy | 453 | 36.6% | |
| No CHF | 61 | 4.9% | |
| No malignancy | 50 | 4.0% | |
| No T1DM / No transplant | 0 | 0% | |

<div class="mt-4"></div>

| Synthea 데이터 한계 | 영향 |
|--------------------|----- |
| Liraglutide → Insulin 100% 동반 처방 | "No insulin" 규칙에서 전멸 |
| HbA1c measurement 미생성 (0건) | HbA1c 기반 규칙 검증 불가 |
| CV comorbidity low prevalence | Prior CV + temporal 결합 시 0명 |

---

# 결론 및 향후 계획

<div class="mt-2"></div>

| 검증 항목 | 결과 |
|-----------|------|
| WebAPI SQL Pipeline | ✅ 정상 — T2DM 8,155명 추출 (2.8초) |
| Entry-Only 코호트 비교 (TROY vs ARTEMIS) | ✅ Jaccard Index **100%** |
| Full TROY LEADER (18 rules) | ❌ 0명 — CV disease 규칙에서 전멸 |
| Control 코호트 가용성 | ✅ Treatment 1,238 : Control 6,912 (**1:5.6**) |

<div class="mt-6"></div>

### 향후 계획

1. **Insulin / CV 규칙 제외**한 simplified eligibility로 E2E 분석 실행 (Treatment ~272 vs Control ~5,000)
2. HDPS 대규모 공변량 추출 → PSM/IPTW → Cox PH → Hazard Ratio 산출
3. 벤치마크 V5 Dual-Track 구현 (Design Paper GT 기반)

---
layout: end
---

# Thank You

ARTEMIS 3.1 — Automated Clinical Evidence Generation
