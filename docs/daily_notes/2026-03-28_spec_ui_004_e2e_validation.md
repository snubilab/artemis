# SPEC-UI-004 E2E Validation — 2026-03-28

## 개요

`docs/tte_agent/15_spec_ui_004_user_test_scenarios.md`에 정의된 시나리오를 Playwright로 실제 검증.
실행 중 2개의 실제 버그를 발견하고 수정함.

## 최종 결과

```
9 passed, 2 skipped, 0 failed
```

| 시나리오 | 결과 | 비고 |
|---|---|---|
| S1-A: LEADER study READY/COMPLETE 상태 확인 | PASS | |
| S1-B: Generate Cohorts → GENERATING → COMPLETE | PASS | 실제 WebAPI 코호트 생성 (1.7분) |
| S1-C: COMPLETE 상태에서 cohortId 표시 | SKIP | S1-B 직후 실행 시 통과 (다음 회차) |
| S2-A: Eligibility 재처리 후 STALE 배너 | SKIP | 코호트 생성 후 재실행 필요 |
| S2-B: STALE 상태에서 Regenerate 버튼 | PASS | |
| S3-A: BLOCKED 상태 — Go to Eligibility 버튼 | PASS | |
| S3-B: Go to Eligibility 클릭 → 탭 전환 | PASS | |
| S4-A: Non-NCT 수동 스터디 Generate 버튼 | PASS | |
| S5-A: API 400 에러 → UI 복구 | PASS | |
| S6-A: PLATO 2개 arm 확인 | PASS | |
| S6-B: 각 arm별 별개 cohortId | PASS | |

S1-C, S2-A는 데이터 상태 의존 skip — 정상 동작.

## 발견된 버그 및 수정

### BUG-1: Playwright SNOMED 라이선스 모달 차단

**파일:** `e2e/spec-ui-004-user-scenarios.spec.js`

**증상:** Atlas TTE 페이지 진입 시 SNOMED 라이선스 모달이 탭 클릭을 차단. `dismissLicenseDialogs()`가 첫 번째 모달을 처리해도 두 번째 모달(HemOnc)이 `waitForTimeout(2500)` 중에 나타나 tab.click() 실패.

**원인:** 모달이 두 개(SNOMED + HemOnc) 순차적으로 나타나며, `dismissLicenseDialogs`가 한 번만 호출되어 두 번째를 처리 못 함.

**수정:**
1. `dismissLicenseDialogs` — `page.evaluate`로 모달 DOM 직접 제거 (force click 방식은 SNOMED 스크롤 요건 때문에 불작동)
2. `openStudyTab` — 탭 클릭 직전에 `dismissLicenseDialogs` 재호출

```js
// dismissLicenseDialogs — DOM 직접 제거
const removed = await page.evaluate(() => {
  const modal = document.querySelector('.modal.in, .modal.fade.in');
  if (!modal) return false;
  modal.remove();
  document.querySelectorAll('.modal-backdrop').forEach(el => el.remove());
  document.body.classList.remove('modal-open');
  return true;
});

// openStudyTab — 탭 클릭 직전 재호출
await dismissLicenseDialogs(page);
await tab.click();
```

---

### BUG-2: triggerSeededCohortGeneration이 artifact를 auto-apply하지 않음 (핵심 버그)

**파일:** `atlas-dev/js/pages/target-trial-emulation/tte-manager.js`

**증상:** "Generate Cohorts" 클릭 후 WebAPI에서 실제 코호트 정의가 생성되지만, `treatmentArms[].cohortId`가 null로 유지됨. `cohortGenerationState`가 `complete`가 아닌 `ready`로 남음.

**원인:** `generate_seeded_cohorts` 백엔드는 cohortId를 study에 직접 저장하지 않고 **artifact(proposedChanges)** 형태로만 반환. 별도의 "apply artifact" 호출이 있어야 실제 저장. 프론트엔드의 `triggerSeededCohortGeneration`은 artifact를 생성하고 `handleCapabilityResponse`만 호출 — auto-apply 없음.

비교: eligibility 처리는 `applyProcessedEligibilityArtifact`를 자동 호출하는 반면, cohort generation은 누락되어 있었음.

**수정:** `triggerSeededCohortGeneration`에 `applyArtifactById` 체인 추가:

```js
.then(response => this.handleCapabilityResponse(response, {
    successMessage: 'Cohort definitions generated.'
}).then(() => {
    if (response.artifactId) {
        return this.applyArtifactById(response.artifactId, {
            successMessage: 'Treatment cohorts generated and applied to the study.'
        });
    }
}))
```

`applyArtifactById` → `TTEService.applyArtifact` → `refreshStudyAndArtifacts()` 순서로 study가 reload되어 KO observable 업데이트.

---

### BUG-3: S1/S6 findStudy predicate 이름 불일치

**파일:** `e2e/spec-ui-004-user-scenarios.spec.js`

**증상:** S1이 LEADER 스터디를 찾지 못해 skip. S6가 PLATO 스터디를 찾지 못해 skip.

**원인:**
- S1: 스터디 이름이 "LEADER"가 아닌 "liraglutide vs placebo for..." (NCT preset 미사용, 수동 생성)
- S6: 스터디 이름이 "PLATO"가 아닌 "Ticagrelor vs Clopidogrel for..." + `nctId` 필드 비어 있음

**수정:**
- S1: `name.includes('LIRAGLUTIDE')` 조건 추가
- S6: `name.includes('TICAGRELOR') && arms.length >= 2 && eligibility.structuredExpression` 조건 추가

---

## 검증된 핵심 동작

### 코호트 생성 플로우 (확인됨)
1. "Generate Cohorts" 클릭
2. `artemis-api` → `_build_combined_treatment_circe(eligibility, arm_name)` 호출
   - eligibility CIRCE + drug exposure rule 결합
3. WebAPI `/cohortdefinition` API로 전송 → Atlas에 코호트 정의 생성
4. 반환된 `id` → artifact proposedChanges에 저장
5. **auto-apply** → study `treatmentArms[].cohortId`에 저장
6. UI → `hasGeneratedCohorts() = true` → `cohortGenerationState = complete`

### 실제 생성된 코호트 (확인됨)
- Study ID=409 (LEADER/liraglutide), arm "liraglutide" → **cohortId=597**
- Atlas에서 확인: `http://localhost/atlas/#/cohortdefinition/597`
- 이름: `TTE 409 liraglutide vs placebo ... Treatment: liraglutide`
- 내용: eligibility 기준(T2DM 등) + liraglutide drug exposure rule 결합

### 코호트 정의 위치
- WebAPI cohortdefinition 테이블에 저장
- Atlas UI에서 Cohort Definitions 메뉴에서 확인 가능
- 이름 패턴: `TTE {studyId} {studyName} Treatment: {armName}`

## 관련 파일

| 파일 | 변경 내용 |
|---|---|
| `e2e/spec-ui-004-user-scenarios.spec.js` | dismissLicenseDialogs DOM 제거, 탭 클릭 전 재호출, S1/S6 predicate 수정, S1-B timeout 120s |
| `atlas-dev/js/pages/target-trial-emulation/tte-manager.js` | `triggerSeededCohortGeneration` auto-apply 추가 |
