---
theme: default
title: "EMPA-REG OUTCOME & DECLARE-TIMI 58 Cohort Feasibility"
transition: slide-left
mdc: true
---

# EMPA-REG OUTCOME & DECLARE-TIMI 58
## Synthea 100K Cohort Feasibility

<div class="mt-16 text-lg opacity-80">
ARTEMIS 3.1 — SGLT2 Inhibitor CVOT Feasibility Check
</div>

<div class="abs-bl m-8 text-sm opacity-40">
2026-02-27 · Synthea 100K (235,222 patients)
</div>

---

# 약물 가용성 및 Cohort 결과

두 Trial 모두 **Treatment drug이 Synthea에 부재**

| | EMPA-REG (NCT01131676) | DECLARE-TIMI (NCT01730534) |
|---|:---:|:---:|
| Treatment | Empagliflozin | Dapagliflozin |
| Treatment 환자 | **0명** | **0명** |
| Comparator | DPP-4 inhibitor | DPP-4 inhibitor |
| Comparator 환자 | 7,568명 | 7,568명 |
| ConceptSets | 57 | 91 |
| InclusionRules | 14 | 14 |
| Entry-Only (Treatment) | **0명** | **0명** |
| Full (Treatment) | **0명** | **0명** |

Synthea 기본 모듈에 SGLT2 inhibitor (Empagliflozin, Dapagliflozin) 처방 경로가 없음

---

# 4 Trial 종합 비교 (Synthea 100K)

| Trial | Treatment Drug | 존재? | Comparator | Full Cohort |
|-------|---------------|:---:|-----------|:---:|
| **LEADER** | Liraglutide | ✅ 1,238명 | Placebo | 0명 (CV rule) |
| **PLATO** | Ticagrelor | ❌ 0명 | Clopidogrel 8,611명 | 0명 |
| **EMPA-REG** | Empagliflozin | ❌ 0명 | DPP-4 7,568명 | 0명 |
| **DECLARE-TIMI** | Dapagliflozin | ❌ 0명 | DPP-4 7,568명 | 0명 |

<div class="mt-4"></div>

**결론**: 4개 Trial 중 Synthea 100K에서 Treatment Drug이 존재하는 것은 **LEADER(Liraglutide)뿐**

LEADER도 Full TROY 적용 시 0명이나, simplified eligibility (Insulin/CV 제외) 적용 시 ~272명으로 유일하게 분석 가능

---
layout: end
---

# Thank You

ARTEMIS 3.1 — 2026-02-27 | Synthea 100K (235,222 patients)
