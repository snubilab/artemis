# Benchmark V4 Experiment Report: 2026-02-20

**Trial**: LEADER (NCT01179048)
**Reference**: TROY Liraglutide (LEADER) v3.4
**Subject**: ARTEMIS E2E Design Paper Pipeline Output

## Summary

| Metric | Before | After | Δ |
|--------|--------|-------|---|
| Avg Recall | 49.2% | **61.9%** | **+12.7pp** |
| Full (≥80%) | 6 | **7** | +1 |
| Partial | 5 | **9** | +4 |
| Wrong (<30%) | 7 | **2** | -5 |
| Missed | 0 | 0 | — |

## Changes Applied

### V4 Benchmark Infra
- Default path corrected (`TELOS` → actual filename)
- JSON report output added (`output/benchmark_v4_{timestamp}.json`)
- Manual mapping added for eGFR + CKD 4-5 composite rule

### Entity Text Improvements (verify_leader_design_e2e.py)

| Rule | Old Entity Text | New Entity Text | Recall Change |
|------|----------------|-----------------|---------------|
| Insulin | `insulin other than human NPH...` | `insulin` | 2% → 74% |
| Transplant | `solid organ transplant` | Split: condition + procedure | 18% → 45% |
| ESLD | `end-stage liver disease` | 9 specific conditions | 8% → 33% |
| Malignant | `malignant neoplasm` | `malignant neoplastic disease` | 29% → 36% |
| eGFR | `estimated glomerular filtration rate` | Split: GFR measurement + CKD 4-5 condition | 8% → 100% |
| Substance | `drug use or dependence` | `drug abuse, drug dependence, substance abuse` | 0% → 0% |
| Pregnancy | `pregnancy or childbirth` | `pregnancy, childbirth and puerperium finding` | 13% → 13% |

## Remaining Issues

### Substance Abuse (0% recall)
TROY uses **non-standard** SNOMED concepts (436954, 440069, 4279309 — all `invalid_reason=D/U`). Standard equivalents via "Maps to": `1448779` (Harmful pattern of substance use), `37165431` (Substance dependence). Agent 2 correctly picks standard concepts from different hierarchies. This is a TROY-side data quality issue.

### Pregnancy (13% recall)
TROY uses parent concept `4088927` (Pregnancy, childbirth and puerperium finding, 2253 descendants). ARTEMIS maps to child concept `4299535` (Pregnancy, 112 descendants). Agent 2's semantic search does not climb to the highest parent. Future fix: improve Agent 2's hierarchy climbing logic.

## Report Files
- `output/benchmark_v4_20260220_1702.json` (baseline)
- `output/benchmark_v4_20260220_1717.json` (after entity_text = 56.8%)
- `output/benchmark_v4_20260220_1720.json` (after eGFR fix = 61.9%)
