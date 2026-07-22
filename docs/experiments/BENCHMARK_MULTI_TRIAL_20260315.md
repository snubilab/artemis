# Multi-Trial Benchmark Results (2026-03-15)

**Version**: benchmark_v5.py + `map_single_entity()` (unified Agent 2 invocation)
**Date**: 2026-03-15T18:34 KST
**Commit**: `5e49495` (refactor: unify Agent 2 invocation)

## Summary

| Trial | Rules | Recall | Precision | F1 | Full(≥80%) | Partial(30-80%) | Wrong(<30%) |
|-------|-------|--------|-----------|------|-----------|-----------------|-------------|
| LEADER | 18 (17 eval) | **71.4%** | **52.3%** | **52.1%** | 10 | 4 | 3 |
| ARISTOTLE | 15 | 68.4% | 63.8% | 64.0% | 8 | 4 | 3 |
| PLATO | 5 | 79.1% | 21.4% | 24.5% | 4 | 0 | 1 |

## Per-Rule Details

### LEADER (Liraglutide v3.4)

| # | Rule | R | P | F1 | TROY | Agent 2 | Overlap |
|---|------|---|---|-----|------|---------|---------|
| 1 | T2DM primary criteria | 99% | 87% | 93% | 5,459 | 6,254 | 5,416 |
| 2 | Adults (≥18) | 100% | 100% | 100% | 1 | 1 | 1 |
| 3 | HbA1c ≥ 7% | 100% | 50% | 67% | 2 | 4 | 2 |
| 4 | No prior GLP-1 RA | 100% | 96% | 98% | 116 | 121 | 116 |
| 5 | No prior insulin use | 91% | 67% | 77% | 167 | 227 | 152 |
| 6 | No T1DM | 100% | 94% | 97% | 29 | 31 | 29 |
| 7 | eGFR ≥ 30 | 100% | 100% | 100% | 1 | 1 | 1 |
| 8 | No ACS within 14 days | 82% | 87% | 84% | 102 | 97 | 84 |
| 9 | No HF (NYHA IV) | 100% | 100% | 100% | 20 | 20 | 20 |
| 10 | No dialysis/ESRD | 32% | 100% | 49% | 246 | 79 | 79 |
| 11 | No pheochromocytoma | 100% | 83% | 91% | 5 | 6 | 5 |
| 12 | No pancreatitis (180d) | 100% | 47% | 64% | 8 | 17 | 8 |
| 13 | No ESLD | 91% | 5% | 9% | 770 | 13,972 | 699 |
| 14 | No history of transplant | 34% | 87% | 49% | 319 | 126 | 109 |
| 15 | No malignant (1825d) | 92% | 100% | 96% | 5,310 | 4,891 | 4,883 |
| 16 | No MEN2 or FMTC | 100% | 0% | 0% | 6 | 9,502 | 6 |
| 17 | No drug use/dependence | 100% | 80% | 89% | 241 | 300 | 241 |
| 18 | No pregnant | 100% | 100% | 100% | 2,253 | 2,253 | 2,253 |

### PLATO (Ticagrelor v3.4)

| # | Rule | R | P | F1 | TROY | Agent 2 | Overlap |
|---|------|---|---|-----|------|---------|---------|
| 1 | ACS hospitalization | 82% | 87% | 84% | 102 | 97 | 84 |
| 2 | Clopidogrel contraindication | 100% | 9% | 17% | 311 | 3,383 | 310 |
| 3 | Fibrinolytic therapy (24h) | 100% | 5% | 10% | 1,497 | 29,449 | 1,497 |
| 4 | Oral anticoagulation | **0%** | 0% | 0% | 1,797 | 8 | 0 |
| 5 | CYP3A inhibitor/inducer | **0%** | 0% | 0% | 12 | 840 | 0 |

### ARISTOTLE (Apixaban v3.4)

| # | Rule | R | P | F1 | TROY | Agent 2 | Overlap |
|---|------|---|---|-----|------|---------|---------|
| 1 | AF/AFL | 100% | 99% | 100% | 34 | 34 | 34 |
| 2 | Need for anticoagulation | **0%** | 0% | 0% | 1,797 | 4 | 0 |
| 3 | Stroke/TIA ≤7 days | **0%** | 0% | 0% | 2 | 48 | 0 |
| 4 | Prosthetic heart valve | **0%** | 0% | 0% | 3 | 10 | 0 |
| 5 | Active endocarditis | 100% | 10% | 18% | 4 | 42 | 4 |
| 6 | Reversible AF cause | 86% | 93% | 89% | 7 | 6 | 6 |
| 7 | VTE risk (PE/DVT) | 42% | 53% | 47% | 279 | 222 | 118 |
| 8 | Active bleeding | 96% | 4% | 8% | 155 | 3,530 | 149 |
| 9 | Hemorrhagic diathesis | 100% | 49% | 66% | 103 | 210 | 103 |
| 10 | Prior ICH | 100% | 100% | 100% | 58 | 58 | 58 |
| 11 | Severe renal insufficiency | 77% | 78% | 77% | 163 | 160 | 125 |
| 12 | ALT/AST/Bilirubin | 75% | 38% | 50% | 4 | 8 | 3 |
| 13 | Platelet count ≤100K | **0%** | 0% | 0% | 54 | 7 | 0 |
| 14 | Anemia | 100% | 98% | 99% | 566 | 579 | 565 |
| 15 | Pregnant | 100% | 99% | 100% | 2,406 | 2,421 | 2,406 |

## Failure Patterns

### 1. Drug Class Expansion 실패 (PLATO #4, #5 / ARISTOTLE #2)
- **Anticoagulants** (TROY=1,797): Agent 1이 Condition으로 분류 → Drug class expansion 미동작
- **CYP3A inhibitors** (TROY=12): UMLS/ATC based expansion이 TROY gold와 매칭 안 됨
- **Root cause**: Agent 1 domain 오분류 + pharmacological class expansion 한계

### 2. Mixed Domain Criteria (ARISTOTLE #13)
- **Platelet count**: TROY는 Thrombocytopenia(Condition) + Platelet measurement 혼합
- Agent 2는 Measurement만 반환 → Condition 부분 누락

### 3. Observation vs Condition Domain (ARISTOTLE #4)
- **Prosthetic heart valve**: TROY=Observation domain, Agent 2=Condition domain

### 4. Overbroad Expansion (LEADER #16, ARISTOTLE #8)
- MEN2/FMTC: 6 TROY → 9,502 Agent 2 (precision 0%)
- Active bleeding: 155 TROY → 3,530 Agent 2 (precision 4%)

## Raw Report Paths
- `output/benchmark_v5_20260315_1834.json` (LEADER)
- `output/benchmark_v5_20260315_1835.json` (PLATO)
- `output/benchmark_v5_20260315_1839.json` (ARISTOTLE)
