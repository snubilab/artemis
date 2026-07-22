# Task: DrugEra PrimaryCriteria 지원

## 1. Specification (Strict)
- **Input**: IR의 `PrimaryCriteria(domain="Drug")` + `CohortAssembler`
- **Output**: Circe JSON에서 `PrimaryCriteria.CriteriaList[0]`의 key가 `DrugEra` (not `DrugExposure`)
- **Logic**:
  1. `DOMAIN_TO_CRITERIA_TYPE`은 InclusionRule용으로 유지 (Drug→DrugExposure)
  2. 신규 `DOMAIN_TO_PRIMARY_CRITERIA_TYPE` 매핑 추가 (Drug→DrugEra)
  3. `_build_primary_criteria`에서 `DOMAIN_TO_PRIMARY_CRITERIA_TYPE` 사용

## 2. TDD Strategy
- [ ] Test A: Drug domain → PrimaryCriteria uses "DrugEra"
- [ ] Test B: Condition domain → PrimaryCriteria still uses "ConditionOccurrence"
- [ ] Test C: InclusionRule Drug still uses "DrugExposure"

## 3. Implementation Log
- 2026-02-18 00:13 코드 확인 결과 이미 구현 완료:
  - `DOMAIN_TO_PRIMARY_CRITERIA_TYPE["Drug"] = "DrugEra"` (mappings.py:54)
  - `_build_primary_criteria`에서 `DOMAIN_TO_PRIMARY_CRITERIA_TYPE` 사용 중
- 2026-02-18 00:14 명시적 테스트 6개 작성 → 전체 PASSED
  - `tests/test_troy_gap_02_drug_era.py`

## 4. Final Status
- [DONE]
