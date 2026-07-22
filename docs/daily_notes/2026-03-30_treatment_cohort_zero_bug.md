# Treatment Cohort 0 Patients Bug Fix

Date: 2026-03-30

## Symptoms

Execute Study 실행 후 Generation & Analysis 탭에서:
- Target: 387, Treatment: **0**, Comparator: 387
- standalone 테스트에서는 Treatment ~300명 정상

## Root Cause 1: Wrong arm name key (`armName` vs `name`)

**File:** `artemis/src/services/tte_service.py:3207`

`preview_seeded_cohorts()`에서 arm 객체의 drug name을 잘못된 키로 참조:

```python
# Before (bug)
arm_name = arm.get("armName", f"Arm {i}")  # "armName" 키 없음 → "Arm 0" fallback

# After (fix)
arm_name = (arm.get("name") or "").strip() or f"Arm {i}"
```

`arm.get("armName")`이 None을 반환해 `"Arm 0"`으로 폴백. 이 잘못된 이름으로 drug concept 검색 → 빈 concept set 생성 → `_preview_cache`에 저장 → `register_seeded_cohorts` → WebAPI 제출 → 0명.

standalone 테스트는 `preview_seeded_cohorts()`를 거치지 않고 실제 arm name을 직접 사용하므로 정상 동작.

## Root Cause 2: Existing cohort ID skips CIRCE update

**File:** `artemis/src/services/tte_service.py:2463`

`_materialize_seeded_cohort_item()`에서 `existing_cohort_id`가 있으면 즉시 "already_attached"로 리턴:

```python
if existing_cohort_id is not None:
    return ...status="skipped"...  # expression_builder() 호출 안 함
```

Root Cause 1 버그로 잘못 생성된 cohort 840(0명)이 study에 저장된 상태에서, arm_name 버그를 고쳐도 재실행 시 `existing_cohort_id=840`이 있으므로 CIRCE를 업데이트하지 않고 그냥 재사용 → 여전히 0명.

**Fix:** `existing_cohort_id`가 있어도 `create_cohort_definition()`을 호출해 WebAPI 정의를 PUT 업데이트 (best-effort). `create_cohort_definition`은 이름 기반으로 기존 cohort를 찾아 expression을 PUT으로 업데이트하는 로직을 이미 내장함.

## Validation Warnings (cosmetic, non-blocking)

함께 확인된 validate_design 경고들:

| Warning | 원인 | 실행 영향 |
|---------|------|-----------|
| ConceptSet 1~21 not found in global registry | `_study_to_provisional_circe()`가 생성한 임시 concept set을 global registry에 등록 안 함 | 없음 (registry는 validation 표시용 shadow 구조) |
| Age rule uses CriteriaList instead of DemographicCriteriaList | `_study_to_provisional_circe()`가 모든 기준을 CriteriaList로 생성 | 없음 (provisional CIRCE는 validation 전용; 실제 실행은 `_build_seeded_target_circe()` 사용) |

두 경고 모두 Blocker Count: 0, 실행 결과에 영향 없음.
