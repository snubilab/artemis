---
theme: default
title: "4-Trial Cohort Feasibility — Synthea 23M"
transition: slide-left
mdc: true
---

# 4-Trial Cohort Feasibility
## Synthea 23M (2,709,803 patients)

<div class="mt-16 text-lg opacity-80">
ARTEMIS 3.1 — LEADER · PLATO · EMPA-REG · DECLARE-TIMI
</div>

<div class="abs-bl m-8 text-sm opacity-40">
2026-02-27 · Database: Synthea 23M (2.7M patients, OMOP CDM v5.3)
</div>

---

# 약물 가용성 (Synthea 23M vs 100K)

| Drug | Trial | 100K | **23M** |
|------|-------|:---:|:---:|
| Liraglutide | LEADER | 1,238 | **28,738** |
| Ticagrelor | PLATO | 0 | **0** |
| Clopidogrel | PLATO | 8,611 | **197,883** |
| Empagliflozin | EMPA-REG | 0 | **0** |
| Dapagliflozin | DECLARE | 0 | **0** |
| DPP-4 / Insulin | EMPA/DECL | 7,568 | **176,013** |

<div class="mt-4"></div>

**질환 가용성** (23M):
T2DM **189K** · ACS **100K** · CAD **170K** · HF **132K** · AMI **60K**

Ticagrelor, Empagliflozin, Dapagliflozin은 **Synthea 모듈 자체에 부재** → 규모와 무관

---

# Trial별 판정 및 결론

| Trial | Treatment | 23M 존재? | Full Cohort 전망 |
|-------|-----------|:---:|------|
| **LEADER** | Liraglutide | ✅ **28,738명** | CV 질환 대규모 존재, **재현 가능성 높음** |
| PLATO | Ticagrelor | ❌ 0명 | 재현 불가 |
| EMPA-REG | Empagliflozin | ❌ 0명 | 재현 불가 |
| DECLARE-TIMI | Dapagliflozin | ❌ 0명 | 재현 불가 |

<div class="mt-4"></div>

### LEADER 100K → 23M 변화

| 항목 | 100K | 23M |
|------|:---:|:---:|
| Liraglutide 환자 | 1,238 | 28,738 (23x) |
| CAD 환자 | 84 | 169,869 |
| Heart failure | 39 | 131,580 |
| Full TROY 결과 | **0명** (CV rule) | **WebAPI 확인 필요** |

**Next Step**: LEADER Full TROY를 SYNTHEA23M에서 WebAPI generation 실행

---
layout: end
---

# Thank You

ARTEMIS 3.1 — 2026-02-27 | Synthea 23M (2,709,803 patients)
