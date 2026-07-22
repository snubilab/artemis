# 2026-03-10: includeDescendants Hybrid Policy 도입

## 요약

Precision 30%p+ 개선 목표 lab meeting 결과에 따라 `includeDescendants` 정책 변경.
3가지 ablation 실험 실행 후, **hybrid policy** (#11a)를 최종 채택.

## 실행한 실험

### Fix 1a: seeds-only (ALL non-seed → false)

- **P=72.8% (+20.4pp)** / R=72.4% (-15pp) → 너무 공격적
- "No malignant" R: 92→41%, "No ESLD" R: 91→1%
- 원인: sibling 개념도 포함 차단 → descendant 누락

### Fix 1b: hybrid policy (ancestors/climb만 false) ✅ 최종 채택

- **P=74.0% (+21.6pp)** / **R=81.5% (-6pp)** / F1=73.1% (+15.9pp)
- Seeds + siblings + maps_to → includeDesc=true
- Ancestors + ancestor_climb → includeDesc=false
- No malignant R 복원 (92%), No CHF P 6→96%

### Fix 2: ancestor 1-hop (max_sep=2→1)

- P=70.9% (-3.1pp) / R=81.5% (same) → 효과 없음
- MEN2 P 60→7% (LLM nondeterminism으로 다른 결과)
- **Reverted** — Fix 1b만으로 충분

## 주요 규칙별 변화 (baseline v4.3 → hybrid)

| Rule     | P (before) | P (after) | R (before) | R (after) |
| -------- | ---------- | --------- | ---------- | --------- |
| No CHF   | 6%         | **96%**   | 100%       | 100%      |
| No eGFR  | 7%         | **86%**   | 97%        | 95%       |
| No MEN2  | 0%         | **60%**   | 100%       | 100%      |
| No renal | 24%        | **78%**   | 99%        | 99%       |
| No ESLD  | 32%        | **37%**   | 91%        | 79%       |

## 변경된 파일

- `concept_set_refiner.py`: Pass 2 → relationship-aware policy
- `benchmark_a_direct.py`: `overbroad_concept_ids` pass-through
- `kg_expander.py`: Fix 2 적용 후 revert (변경 없음)

## 다음 단계 (TODO — 후순위)

> Lab meeting `2026-03-10_low_recall_cv_coronary.md` 참조

- [ ] **Fix A**: Procedure ancestor 예외 — `concept_set_refiner.py` Pass 2에서 Procedure 도메인 ancestor/climb은 `includeDescendants=true` 유지 (descendant_count < 200 조건)
- [ ] **Fix B**: Reranker Top-N 확대 — `workflow.py`에서 Condition/Procedure Top-3 → Top-5
- [ ] Fix C (후순위): Procedure seed template — "revascularization" compound query 대상 fallback seed 확보
- [ ] A_direct 재측정 후 ablation 반영
