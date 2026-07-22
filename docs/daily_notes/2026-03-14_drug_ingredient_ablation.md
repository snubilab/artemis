# 2026-03-14 Drug Ingredient includeDescendants Ablation

## 실험 목적

MRREL/ATC로 찾은 drug class ingredients(e.g., Fibrinolytic agents → 30개 ingredient)에
`includeDescendants=false`를 적용하여 Precision 개선 시도.

## 변경 사항

### 시도 1: ConceptSetRefiner Pass 2a — 범용 Ingredient gating

`concept_class_id='Ingredient'`인 **모든** seed에 `includeDescendants=false` 적용.

**결과**: LEADER **R=81.5% → 51.5%** (-30pp) 심각한 regression.

- insulin, GLP1-RA, HbA1C 등 **개별 Drug Ingredient** seed도 gating 적용되어
  해당 약의 clinical drugs/branded drugs가 전부 제외됨.
- Drug class 확장 목적의 gating이 개별 약물까지 영향.

### 시도 2: Drug class seed 경로에만 overbroad 적용

`expand_drug_class_via_vocab()`이 반환한 `drug_class_seed_ids`에만 `includeDescendants=false`.
일반 retriever 경로의 seed는 기존대로 유지.

**결과**: LEADER regression은 MRSTY 통합 부작용으로 판명.

| Study  | Metric | Baseline (3/10) | After |
| ------ | ------ | :-------------: | :---: |
| LEADER | R      |      81.5%      | 53.3% |
| LEADER | P      |      74.0%      | 57.7% |
| PLATO  | R      |      47.1%      | 20.1% |
| PLATO  | P      |      32.0%      | 17.7% |

## Per-Rule Regression (LEADER, MRSTY 원인)

| Rule                           | Baseline R | After R |
| ------------------------------ | :--------: | :-----: |
| HbA1C ≥ 7 %                    |    100%    |   0%    |
| No GLP1-RA, pramlintide, DPP-4 |    100%    |   0%    |
| No insulin                     |    97%     |   0%    |
| No T1DM                        |    100%    |   19%   |
| No FH/PH of MEN2 or FMTC       |    100%    |   0%    |

## 결론

1. **Drug class seed overbroad 자체는 동작함**: Fibrinolytic 28K→30, Anticoagulant 25K→48
2. **MRSTY 통합이 LEADER에도 regression** 유발 — HbA1C, insulin 등 seed가 MRSTY 필터링에 의해 소실
3. **코드 롤백함** — MRSTY regression 해결 후 drug class seed gating 재적용 필요

## 다음 조사

- [ ] MRSTY가 HbA1C, insulin, GLP1-RA seed를 왜 필터링하는지 분석
- [ ] MRSTY domain_hint 매핑에 Drug/Measurement 관련 STY 누락 가능성
- [ ] MRSTY를 disable한 baseline 벤치마크로 regression 범위 확인
