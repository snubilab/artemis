# SPEC-UI-004: Treatment Cohort Generation from Eligibility CIRCE

Date: 2026-03-28
Branch: `main` (직접 커밋)
Commits: `aed0aa6`, `04081d4`, `d89a7d5`
SPEC: SPEC-UI-004

---

## 요약

TTE 연구에서 치료군(treatment arm) 코호트를 생성할 때 적격기준(eligibility)을 반영하지 못하던 근본적인 버그를 수정하고, Treatment 탭에 코호트 생성 UI를 추가했다.

---

## 전체 시나리오에서의 위치

```
1. 연구 생성
2. Eligibility 처리   → Process Eligibility 실행 → structuredExpression 생성
3. Treatment 정의     → 비교 약물 arm 지정
4. 코호트 생성        ← 이번 SPEC이 수정한 단계
5. Outcome / 분석 설정 / 실행  (미구현)
```

---

## 문제

### 잘못된 코호트 합성

`generate_seeded_cohorts()` 실행 시 treatment arm 코호트가 **약물 노출만** 기준으로 생성되었다.

예: "당뇨 환자 중 아스피린을 처방받은 사람" 을 원하지만
실제로는 "아스피린을 처방받은 **모든** 사람" 이 생성됨

2번에서 정의한 Eligibility 기준이 treatment 코호트 생성에 전혀 반영되지 않았다.

### UI 단절

`triggerSeededCohortGeneration()` 함수는 코드에 존재했지만 Treatment 탭에 연결된 버튼이 없었다. 사용자가 직접 실행할 방법이 없었다.

### NCT 전용 잠금

`canGenerateSeededCohorts` 가 NCT 번호로 import한 연구에만 `true` 를 반환했다. 수동으로 만든 연구는 eligibility를 처리해도 생성 불가.

---

## 수정 내용

### 백엔드

**`_build_combined_treatment_circe(eligibility, arm_name)` 신규 메서드**

- `_build_seeded_target_circe(eligibility)` 를 호출해 완성된 eligibility CIRCE 를 베이스로 가져온다
- deep-copy 후 `_criterionMappingMetadata` private key 제거
- arm 이름으로 drug concept set 을 조회해 추가
- concept set ID 충돌 없이 동적 할당 (`max(existing IDs) + 1`)
- DrugExposure inclusion rule 추가 후 반환
- Observation window 는 eligibility 설정값이 자동 상속됨 (hardcoded 365일 제거)

**`_materialize_seeded_treatment_cohorts()` 수정**

기존의 drug-only 빌더 대신 새 combined 빌더를 사용하도록 교체.
`eligibility` 파라미터 추가해 호출 체인 연결.

**`generate_seeded_cohorts()` 검증 추가**

eligibility 가 처리되지 않은 상태에서 호출 시 HTTP 400 반환.
오류 메시지: "Eligibility must be processed before generating treatment cohorts."

### 프론트엔드

**새 observables**

| Observable | 역할 |
|-----------|------|
| `isGeneratingCohorts` | API 호출 중 여부 |
| `hasGeneratedCohorts` | 어느 arm이라도 cohortId 보유 여부 |
| `generateButtonLabel` | "Generate Cohorts" / "Regenerate Cohorts" |
| `cohortGenerationState` | 5-state 상태 머신 |

**`canGenerateSeededCohorts` 재작성**

- NCT 제한 제거
- eligibility 처리 완료 + arm 정의됨 → `true`
- 재생성 가능 (기존에는 cohortId 존재 시 false였음)

**`triggerSeededCohortGeneration()` 수정**

`isGeneratingCohorts(true/false)` 라이프사이클 추가.

**5-state Cohort Generation 배너 (tte-manager.html)**

| 상태 | 조건 | UI |
|------|------|----|
| `blocked` | eligibility 미처리 또는 arm 없음 | 경고 + "Go to Eligibility" 버튼 |
| `ready` | eligibility 처리 + arm 있음 | 파란 패널 + "Generate Cohorts" 버튼 |
| `generating` | API 호출 중 | skeleton loader + spinner |
| `complete` | cohortId 존재 + fresh | 초록 패널 + "Regenerate Cohorts" |
| `stale` | cohortId 존재 + eligibility 재처리됨 | 주황 패널 + stale 경고 |

기존 Eligibility 탭의 `tte-eligibility-banner` 패턴을 동일하게 적용.

---

## 테스트 결과

| 항목 | 결과 |
|------|------|
| pytest `test_tte_service_ui004.py` | 12 passed |
| pytest regression (IR pipeline) | 29 passed |
| Jest `tte-manager.cohortGeneration.test.js` | 22 passed |
| Jest 전체 TTE | 49 passed |
| Playwright E2E | 6 passed, 5 skipped (상태 의존적) |
| TRUST 5 | PASS (Critical 0, Warning 0) |

---

## 주요 기술적 결정

1. **Option A (deep-copy) 채택**: `_build_seeded_target_circe()` 재호출 방식.
   약 200줄의 로직(병렬 매핑, demographic rule, groupId 병합)을 중복 구현하지 않아도 됨.

2. **`_build_seeded_drug_circe()` 유지**: 다른 호출자가 있을 수 있으므로 삭제하지 않음.

3. **`shouldShowSeededCohortGeneration()` 부분 수정**: lines 171, 210 (artifact review 용)은 변경 없이 line 567만 수정.

---

## 다음 단계

- `fork/main` PR 생성 (`/moai sync SPEC-UI-004`)
- SPEC-UI-005 검토: Outcome 정의 및 분석 실행 UI
- `_build_seeded_drug_circe()` 호출자 확인 후 제거 여부 결정
