# TROY Cohort Feasibility — Synthea 분석 종합 보고서

**Date**: 2026-02-27  
**Analyst**: ARTEMIS 3.1  
**Databases**: Synthea 100K (235,222 patients), Synthea 23M (2,709,803 patients)  
**Trials**: LEADER, PLATO, EMPA-REG OUTCOME, DECLARE-TIMI 58

---

## 1. 4-Trial 약물 가용성

| Drug | Trial (Role) | 100K | 23M |
|------|-------------|:---:|:---:|
| **Liraglutide** | LEADER (Treatment) | 1,238 | **28,738** |
| Ticagrelor | PLATO (Treatment) | 0 | **0** |
| Clopidogrel | PLATO (Comparator) | 8,611 | 197,883 |
| Empagliflozin | EMPA-REG (Treatment) | 0 | **0** |
| Dapagliflozin | DECLARE (Treatment) | 0 | **0** |
| DPP-4 | EMPA-REG/DECLARE (Comparator) | 7,568 | 176,013 |

**결론**: Synthea 모듈에 Ticagrelor, Empagliflozin, Dapagliflozin 처방 경로가 없음. **LEADER만 분석 가능.**

---

## 2. LEADER Incremental Exclusion (TROY v1.1)

TROY LEADER 정의: PrimaryCriteria = DrugEra Liraglutide, 49 ConceptSets, **18 InclusionRules**

### 2.1 Synthea 100K 결과

| Step | Rule | Patients | Delta | Survival |
|:----:|------|:--------:|:-----:|:--------:|
| 0 | Entry Only | 1,238 | — | 100% |
| 1 | +Age ≥ 50 | 272 | −966 | 22.0% |
| 2 | +HbA1c ≥ 7% | 272 | 0 | 22.0% |
| 3 | +Prior CV disease | **0** | −272 | **0%** |

개별 규칙 독립 적용 (100K):

| Rule | Excluded | Impact |
|------|:---:|:---:|
| No insulin use | 1,238 | **100%** |
| No pregnancy | 453 | 36.6% |
| No CHF | 61 | 4.9% |

### 2.2 Synthea 23M 결과 (EraStartDate 제거)

`EraStartDate ≥ 2010-10-06` temporal 제약을 제거하고 실행:

| Step | Rule | Patients | Delta | Survival |
|:----:|------|:--------:|:-----:|:--------:|
| 0 | Entry Only | 14,397 | — | 100% |
| 1 | +Age ≥ 50 | 2,343 | −12,054 | 16.3% |
| 2 | +HbA1c ≥ 7% | 2,343 | 0 | 16.3% |
| 3 | +Prior CV disease | **9** | −2,334 | 0.06% |
| 4 | +다음 규칙 | 9 | 0 | 0.06% |
| 5 | +다음 규칙 | 9 | 0 | 0.06% |
| 6+ | (실행 중) | ... | ... | ... |

100K에서 0명이었던 CV disease가 23M에서 **9명** 통과. 하지만 통계적으로 유의미한 분석에는 부족.

---

## 3. 발견된 버그

### ConceptSet Stripping → Silent 0-Patient Failure

- **문서**: `docs/issues/BUG_conceptset_stripping_silent_failure.md`
- **증상**: 23M에서 Entry-Only=14,397인데 +Age≥50=0
- **원인**: incremental 스크립트가 InclusionRule이 참조하는 ConceptSet만 남기고 나머지 제거 → WebAPI가 에러 없이 0명 반환
- **수정**: 49개 ConceptSets 전부 유지 → +Age≥50=**2,343명** 정상 반환

---

## 4. Synthea 구조적 한계 (100K + 23M 공통)

| # | 한계 | 상세 |
|---|------|------|
| 1 | **약물 누락** | Ticagrelor, SGLT2i (Empagliflozin, Dapagliflozin) 없음 |
| 2 | **Lira=Insulin 동반** | Liraglutide 환자 100%가 Insulin 동시 처방 |
| 3 | **HbA1c 미생성** | diabetes 모듈이 HbA1c measurement를 생성하지 않음 |
| 4 | **CV comorbidity 희소** | T2DM+Lira+Age50+CV 교차 환자 극소 (23M에서 9명) |
| 5 | **Temporal window 제약** | DrugEra EraStartDate가 Synthea 데이터 분포와 미스매치 |

---

## 5. 실행 가능한 분석 경로

| 경로 | 조건 | Treatment | Control | 비고 |
|------|------|:---:|:---:|------|
| A. Simplified (23M) | Age≥50, CV/Insulin 제외 | ~2,343 | ~수만 명 | 즉시 실행 가능 |
| B. Full TROY (23M) | 전체 18 rules | ~9명 | — | 통계적 무의미 |
| C. Synthea 커스텀 | 모듈 수정 | 자유 | 자유 | 개발 비용 |
| D. 실 데이터 | MIMIC 등 | ? | ? | 접근성 문제 |

---

## 6. 생성된 파일 목록

```
docs/issues/
├── LEADER_synthea100k_cohort_feasibility.md    # LEADER 100K 리포트
├── LEADER_synthea100k_slides.md                # LEADER 100K 슬라이드
├── PLATO_synthea100k_cohort_feasibility.md     # PLATO 100K 리포트
├── PLATO_synthea100k_slides.md                 # PLATO 100K 슬라이드
├── EMPAREG_DECLARE_synthea100k_cohort_feasibility.md  # EMPA+DECLARE 100K
├── EMPAREG_DECLARE_synthea100k_slides.md
├── ALL_TRIALS_synthea23m_cohort_feasibility.md # 4-Trial 23M 약물 체크
├── ALL_TRIALS_synthea23m_slides.md
├── BUG_conceptset_stripping_silent_failure.md  # 버그 리포트
└── SUMMARY_all_analyses.md                     # ← 이 파일
```
