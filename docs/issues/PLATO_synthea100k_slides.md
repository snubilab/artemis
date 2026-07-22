---
theme: default
title: "PLATO Cohort Feasibility on Synthea 100K"
transition: slide-left
mdc: true
---

# PLATO Trial Cohort Feasibility
## Synthea 100K 데이터 적용 결과

<div class="mt-16 text-lg opacity-80">
ARTEMIS 3.1 — Ticagrelor vs Clopidogrel in ACS
</div>

<div class="abs-bl m-8 text-sm opacity-40">
2026-02-27 · Database: Synthea 100K (235,222 patients) · Trial: PLATO (NCT01232322)
</div>

---

# 약물 가용성 및 Cohort Generation

PLATO는 LEADER(18 rules)와 달리 **1개 InclusionRule** (ACS)만 보유 — 구조는 단순

| 항목 | Ticagrelor (Treatment) | Clopidogrel (Comparator) |
|------|:---:|:---:|
| Drug Exposure | **0명** | 8,611명 |
| Entry-Only (DrugEra) | **0명** | 262명 |
| Full (+ACS) | **0명** | **0명** |
| Drug + Acute MI | 0명 | 1,577명 |

<div class="mt-4"></div>

| ACS Condition | Patients |
|---------------|:---:|
| Acute MI | 2,626 |
| ACS (general) | 4,268 |
| Unstable angina | 0 |

**Ticagrelor는 Synthea에 존재하지 않음** → Treatment arm 구성 불가

---

# 결론 및 LEADER 대비 비교

| 항목 | LEADER | PLATO |
|------|:---:|:---:|
| Treatment drug 존재 | ✅ 1,238명 | ❌ **0명** |
| Comparator drug 존재 | N/A (placebo) | ✅ 8,611명 |
| InclusionRules | 18개 | 1개 |
| Full 코호트 | 0명 (CV disease) | 0명 (약물 부재) |
| **주 원인** | Exclusion 과다 | **약물 자체 부재** |

<div class="mt-4"></div>

### Synthea 100K 한계

| 한계 | 영향 |
|------|------|
| Ticagrelor 미존재 (0건) | Treatment arm 구성 불가 |
| DrugEra temporal window | Clopidogrel 8,611 → 262명 |
| ACS + DrugEra 교차 | 262명 중 ACS 보유 0명 |

---
layout: end
---

# Thank You

ARTEMIS 3.1 — 2026-02-27 | Synthea 100K | PLATO (NCT01232322)
