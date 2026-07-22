# 4-Trial Cohort Feasibility — Synthea 23M (2.7M patients)

**Database**: Synthea 23M (2,709,803 patients, OMOP CDM v5.3)  
**Date**: 2026-02-27  
**Trials**: LEADER, PLATO, EMPA-REG OUTCOME, DECLARE-TIMI 58

---

## 1. 약물 가용성

| Drug | Concept ID | Synthea 100K | Synthea 23M | 배율 |
|------|:---:|:---:|:---:|:---:|
| **Liraglutide** (LEADER) | 40170911 | 1,238 | **28,738** | 23x |
| Ticagrelor (PLATO) | 40228152 | 0 | **0** | — |
| **Clopidogrel** (PLATO) | 1322184 | 8,611 | **197,883** | 23x |
| Empagliflozin (EMPA-REG) | 43009032 | 0 | **0** | — |
| Dapagliflozin (DECLARE) | 43009089 | 0 | **0** | — |
| **DPP-4 / Insulin** | 21600712 | 7,568 | **176,013** | 23x |
| **Metformin** | 1503297 | — | **155,786** | — |

> [!IMPORTANT]
> **Ticagrelor, Empagliflozin, Dapagliflozin은 23M에서도 존재하지 않습니다.**
> Synthea 모듈 자체에 해당 약물의 처방 경로가 없으므로, 데이터 규모와 무관하게 부재.

---

## 2. 질환 가용성

| Condition | Concept ID | Synthea 23M |
|-----------|:---:|:---:|
| **T2DM** | 201826 | **189,512** |
| **ACS (general)** | 321042 | **99,937** |
| **Coronary arteriosclerosis** | 317576 | **169,869** |
| **Heart failure** | 316139 | **131,580** |
| **Acute MI** | 4329847 | **59,818** |

Synthea 100K에서 LEADER의 병목이었던 **CV 질환이 23M에서는 대규모로 존재**:
- CAD 170K, HF 132K, AMI 60K → "prior CV disease" 규칙 통과 가능성 대폭 증가

---

## 3. Trial별 Feasibility 판정

### LEADER (NCT01179048) — Liraglutide vs Placebo

| 항목 | Synthea 100K | Synthea 23M |
|------|:---:|:---:|
| Liraglutide 환자 | 1,238 | **28,738** |
| T2DM 환자 | 8,150 | 189,512 |
| CAD 환자 | — | 169,869 |
| Heart failure | — | 131,580 |

**판정**: ✅ **23M에서 Full TROY 재현 가능성 높음**
- 100K에서 CV disease에서 전멸했으나, 23M에서는 28,738명 중 CV 보유자가 충분할 것으로 예상
- **WebAPI cohort generation 실행 권장**

### PLATO (NCT01232322) — Ticagrelor vs Clopidogrel

| 항목 | Synthea 23M |
|------|:---:|
| Ticagrelor | **0** |
| Clopidogrel | 197,883 |
| ACS | 99,937 |

**판정**: ❌ **Treatment drug (Ticagrelor) 부재. 재현 불가.**
- 대안: Clopidogrel + ACS (양쪽 모두 197K/100K) 활용한 관찰적 연구는 가능

### EMPA-REG OUTCOME (NCT01131676) — Empagliflozin vs DPP-4

| 항목 | Synthea 23M |
|------|:---:|
| Empagliflozin | **0** |
| DPP-4 | 176,013 |

**판정**: ❌ **Treatment drug (Empagliflozin) 부재. 재현 불가.**

### DECLARE-TIMI 58 (NCT01730534) — Dapagliflozin vs DPP-4

| 항목 | Synthea 23M |
|------|:---:|
| Dapagliflozin | **0** |
| DPP-4 | 176,013 |

**판정**: ❌ **Treatment drug (Dapagliflozin) 부재. 재현 불가.**

---

## 4. 결론

| Trial | Treatment 존재? | Comparator 존재? | Full Cohort 가능? |
|-------|:---:|:---:|:---:|
| **LEADER** | ✅ 28,738 | ✅ (placebo=non-user) | **WebAPI 확인 필요** |
| PLATO | ❌ | ✅ 197,883 | ❌ |
| EMPA-REG | ❌ | ✅ 176,013 | ❌ |
| DECLARE-TIMI | ❌ | ✅ 176,013 | ❌ |

> [!TIP]
> **LEADER가 유일한 후보.** 23M에서는 Liraglutide 28,738명 + CV conditions 대규모 존재로,
> 100K에서 0명이었던 Full TROY 코호트가 유의미한 수를 반환할 가능성이 높습니다.
> **다음 단계: LEADER Full TROY를 SYNTHEA23M에서 WebAPI generation 실행.**
