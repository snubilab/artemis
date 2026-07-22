# Multi-Trial GOLD Benchmark (Post-Refactoring)

> **날짜**: 2026-03-11
> **변경 사항**: Drug class expansion 리팩토링 + E2E benchmark input fix

---

## 변경 요약

| 변경                   | 파일                     | 설명                                       |
| ---------------------- | ------------------------ | ------------------------------------------ |
| Dictionary 삭제        | `drug_class_expander.py` | LEADER 전용 하드코딩 제거, ATC vocab only  |
| `_guess_domain()` 삭제 | `workflow.py`            | 휴리스틱 → Agent 1 `domain_hint` 전환      |
| ATC gate 수정          | `workflow.py`            | `domain_hint == "Drug"` 조건으로 변경      |
| Per-CS domain          | `benchmark_v5.py`        | Multi-domain rule 지원 (`cs_domains` dict) |
| E2E input 보강         | `benchmark_v5.py`        | Agent 1에 rule name + CS names 전달        |
| `[GOLD]` prefix 제거   | 4 GOLD JSONs             | 146 CS name에서 [GOLD] prefix strip        |
| DB connection safety   | `workflow.py`            | `finally: db_conn.close()` 추가            |

---

## Exp A_direct (Agent 2 Only) — GOLD 기준

| Trial        | Rules | Recall    | Precision | F1        | ✅Full | 🔶Partial | ❌Wrong |
| ------------ | ----- | --------- | --------- | --------- | ------ | --------- | ------- |
| **LEADER**   | 17    | **80.4%** | 68.0%     | **67.3%** | 12     | 3         | 2       |
| **EMPA-REG** | 13    | **64.6%** | 63.8%     | **61.5%** | 5      | 6         | 2       |
| **PLATO**    | 5     | **47.1%** | 32.0%     | **32.0%** | 1      | 2         | 2       |

> ⚠️ PLATO row는 2026-03-11 기준. MRSTY+MRREL 적용 후 결과는 §4 참조.

### EMPA-REG 리팩토링 전후 비교

| Rule                  | Before R  | After R   | Δ           |
| --------------------- | --------- | --------- | ----------- |
| Systemic steroids     | 0%        | **100%**  | +100pp      |
| Alcohol or drug abuse | 0%        | **100%**  | +100pp      |
| Glycemic control      | 36%       | **99%**   | +63pp       |
| ACS/Stroke 2mo        | 10%       | **58%**   | +47pp       |
| CV risk               | 57%       | **76%**   | +19pp       |
| **AVERAGE**           | **31.6%** | **64.6%** | **+33.0pp** |

---

## Exp E2E v2 (Agent 1 → Agent 2 + domain_hint fix) — 2026-03-11 21:40

**Critical bug fix**: `_map_all_entities()`에서 Agent 1 domain을 Agent 2에 전달하지 않던 버그 수정.

| Trial        | Rules | Recall    | Precision | F1        | ✅Full | 🔶Partial | ❌Wrong |
| ------------ | ----- | --------- | --------- | --------- | ------ | --------- | ------- |
| **LEADER**   | 17    | **77.4%** | 59.7%     | **56.1%** | 11     | 4         | 2       |
| **EMPA-REG** | 14    | **46.6%** | 52.3%     | **39.0%** | 4      | 4         | 5       |
| **PLATO**    | 5     | **36.4%** | 19.2%     | **20.2%** | 2      | 0         | 3       |

### E2E v1 vs v2 (domain_hint fix)

| Trial    | E2E v1 R | E2E v2 R  | Δ          |
| -------- | -------- | --------- | ---------- |
| LEADER   | 72.5%    | **77.4%** | **+4.9pp** |
| EMPA-REG | 46.9%    | **46.6%** | -0.3pp     |
| PLATO    | 36.4%    | **36.4%** | 0.0pp      |

---

## A_direct vs E2E v2 Gap

| Trial    | A_direct R | E2E v2 R  | Gap     |
| -------- | ---------- | --------- | ------- |
| LEADER   | 80.4%      | **77.4%** | -3.0pp  |
| EMPA-REG | 64.6%      | 46.6%     | -18.0pp |
| PLATO    | 47.1%      | 36.4%     | -10.7pp |

> **LEADER gap 7.9pp → 3.0pp 축소** (domain_hint fix 효과).
> A_direct 75.2% (hybrid) 기준으로는 E2E가 **+2.2pp 초과** — Agent 1 Hierarchical Expansion 효과.

### Gap 원인 분석

- **LEADER -3.0pp**: Agent 1 domain 정확 + Hierarchical expansion → 거의 gap 해소
- **EMPA-REG -18.0pp**: Agent 1이 복합 기준(eGFR, BMI, liver disease)을 정밀 분해하지 못함
- **PLATO -10.7pp**: fibrinolytics, CYP-450 같은 전문 약리학 용어에서 Agent 1 한계

---

## 남은 이슈

| Issue                                  | 영향                                                 |
| -------------------------------------- | ---------------------------------------------------- |
| Bariatric surgery / Anti-obesity drugs | A_direct에서도 0% — GOLD에 대응 concept 없음         |
| CYP-450 3A inhibitors/inducers         | ATC에서 미지원 — 별도 vocabulary 필요                |
| Fibrinolytic agents                    | ATC distance threshold로 매칭 불안정                 |
| ~~Agent 1 domain 오분류~~              | ~~E2E gap의 주요 원인~~ → **domain_hint fix로 완화** |

---

## 4. PLATO A_direct — MRSTY + MRREL 통합 후 (2026-03-13)

> **변경 사항**: MRSTY domain-aware CUI filtering + MRREL drug class expansion (waterfall)

### Per-Rule 비교 (Before → After)

| Rule                | Before R  | After R   | Before P  | After P   | Δ Recall    |
| ------------------- | --------- | --------- | --------- | --------- | ----------- |
| ACS                 | 38%       | **0%**    | 98%       | 0%        | ❌ -38pp    |
| Clopidogrel contra. | 100%      | **100%**  | 58%       | 58%       | — (유지)    |
| Fibrinolytic agents | 0%        | **100%**  | 0%        | 5%        | 🎉 +100pp   |
| Anticoagulants      | 98%       | **89%**   | 5%        | 6%        | -9pp        |
| CYP inhibitors      | 0%        | **0%**    | 0%        | 0%        | — (미해결)  |
| **AVERAGE**         | **47.1%** | **57.7%** | **32.0%** | **13.9%** | **+10.6pp** |

### Summary

| Metric        | Before (03-11) | After (03-13) | Δ           |
| ------------- | -------------- | ------------- | ----------- |
| Avg Recall    | 47.1%          | **57.7%**     | **+10.6pp** |
| Avg Precision | 32.0%          | 13.9%         | -18.1pp     |
| Avg F1        | 27.5%          | 19.0%         | -8.5pp      |
| Full (≥80%)   | 1              | **3**         | +2          |
| Partial       | 2              | 0             | -2          |
| Wrong (<30%)  | 2              | 2             | 0           |

### 분석

- **Fibrinolytic**: MRREL `isa` 관계로 30 raw concepts 매핑 → R=100% 달성 🎉
- **Anticoagulant**: MRREL 48 concepts 정상 매핑. R=98%→89%는 일부 variant 누락
- **ACS regression**: MRSTY domain filtering이 ACS seed를 걸러냈을 가능성. 2 raw concepts만 반환 → 조사 필요
- **Precision 하락**: MRREL expansion이 매우 넓음 (fibrinolytic 28K, anticoagulant 25K resolved) → includeDescendants gating 필요

---

## Report Files

| Trial    | Experiment           | File                                                       |
| -------- | -------------------- | ---------------------------------------------------------- |
| LEADER   | A_direct             | `data/gold/LEADER/benchmark_a_direct_20260311_1437.json`   |
| LEADER   | E2E v1               | `data/gold/LEADER/benchmark_v5_20260311_1503.json`         |
| LEADER   | **E2E v2**           | `data/gold/LEADER/benchmark_v5_20260311_2151.json`         |
| EMPA-REG | A_direct             | `data/gold/EMPA-REG/benchmark_a_direct_20260311_1425.json` |
| EMPA-REG | E2E v1               | `data/gold/EMPA-REG/benchmark_v5_20260311_1502.json`       |
| EMPA-REG | **E2E v2**           | `data/gold/EMPA-REG/benchmark_v5_20260311_2210.json`       |
| PLATO    | A_direct (03-11)     | `data/gold/PLATO/benchmark_a_direct_20260311_1343.json`    |
| PLATO    | **A_direct (03-13)** | `data/gold/PLATO/benchmark_a_direct_20260313_1649.json`    |
| PLATO    | E2E v1               | `data/gold/PLATO/benchmark_v5_20260311_1502.json`          |
| PLATO    | **E2E v2**           | `data/gold/PLATO/benchmark_v5_20260311_2158.json`          |
