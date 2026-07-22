# 2026-04-02 Handoff — TTE Target Population / Execute Flow

## 한 줄 요약

TTE UI 정리와 time parameter 관련 수정은 커밋 `4f96b0d`로 반영했다. 현재 남은 핵심 문제는 study `437`에서 `eligibility.targetCohortName`이 `liraglutide`로 잘못 저장되어 target/treatment cohort가 모두 `0명`이 되는 구조적 오류다.

---

## 이번 세션에서 반영된 것

커밋: `4f96b0d` `fix(tte): streamline execute flow and align time params`

포함 변경:
- `Execute Study` 후 자동 `Analysis` 탭 이동 제거
- Execute 완료 배너에 `Go to Analysis` 버튼 추가
- `Run Full Pipeline` 버튼 숨김
- AI review panel의 excluded candidate `%` 표시 제거
- artifact review 4/8 split wrapper class 정리
- TTE 기본 follow-up default를 `30 days`로 변경
- Treatment preview/generation이 `timeParams`를 읽도록 수정
- treatment CIRCE drug rule의 pre-index window가 hardcoded `365` 대신 `washoutPeriod`를 따르도록 수정
- Outcomes가 draft text만으로 완료 처리되던 게이팅 수정

주요 수정 파일:
- `atlas-dev/js/pages/target-trial-emulation/tte-manager.js`
- `atlas-dev/js/pages/target-trial-emulation/tte-manager.html`
- `atlas-dev/js/pages/target-trial-emulation/components/tte-ai-review-panel.html`
- `artemis/src/api/models/tte.py`
- `artemis/src/services/tte_service.py`

---

## Confirmed Findings

### 1. `Execute Study` 경고 노출

- `Execute Study` 클릭 시 실제로는 먼저 validation이 돈다.
- validation artifact가 최신 visible artifact로 자동 선택되면서 긴 warning 목록이 Artifact Review에 노출된다.
- 이 부분은 UX 문제다.
- 하지만 이것만으로 설명되지 않는 별도 실제 데이터 문제도 확인됐다.

### 2. study `437`의 `0 / 0 / 0`은 진짜 결과 문제

live state 확인:
- study `437`
- `results.mode = "webapi_generation"`
- `targetN = 0`
- `treatmentN = 0`
- `comparatorN = 0`
- `primaryOutcomeN = 1105`

artifact 확인:
- applied execution artifact `art_828` 안에도 같은 `0 / 0 / 0`이 저장되어 있음
- 즉 프론트 표시 버그가 아니라 backend execution payload 자체가 0이다

### 3. 더 앞단의 원인: wrong target population

study `437` 현재 상태:
- `eligibility.targetCohortName = "liraglutide"`

이 값은 `Execute`에서 생긴 게 아니라, 더 앞선 draft generation artifact에서 이미 들어와 있었다:
- `art_823` `draft_generation`
- 그 안의 `proposedChanges.eligibility.targetCohortName = "liraglutide"`

이후:
- `process_eligibility`가 그 값을 계속 신뢰
- target cohort `1139`가 사실상 drug-based target처럼 생성
- treatment cohort `1140`도 거의 같은 방향으로 생성
- `LEADER_BENCHMARK`에서 둘 다 `0명`

### 4. WebAPI cohort definition 상태

study `437` 관련 cohort ids:
- target: `1139`
- treatment: `1140`
- primary outcome: `1141`

관찰:
- `1139` 이름: `Target - liraglutide`
- `1140` 이름: `Treatment - liraglutide`
- 둘 다 PrimaryCriteria가 `DrugEra`
- outcome `1141`만 condition-based로 정상적이고 nonzero

즉 현재 문제는:
- target population에 환자군이 아니라 treatment name이 들어가서
- target/treatment cohort 생성 전체가 뒤틀린 상태

---

## 개념 정리

- `target population`:
  - criteria가 설명하는 환자군의 대표 라벨
  - 예: `T2DM patients with high cardiovascular risk`
- `criteria`:
  - 실제 inclusion / exclusion filtering rule

원칙적으로는 criteria가 진짜 필터링을 해야 한다.
하지만 현재 구현은 `targetCohortName`도 target cohort generation의 anchor처럼 써서, 잘못된 값이 들어가면 전체가 망가진다.

---

## ClinicalTrials.gov 관련 결론

ClinicalTrials에서 직접 안정적으로 가져올 수 있는 건 원문 필드다:
- `briefTitle`
- `officialTitle`
- `briefSummary`
- `eligibilityCriteria`
- `conditions`

하지만 우리가 필요한 `targetCohortName` 같은 정규화된 patient-population label은 단일 확정 필드로 주어지지 않는다.

따라서:
- 원문 source는 ClinicalTrials에서 바로 가져올 수 있음
- 하지만 target population 라벨은 파싱/요약 단계가 필요함

---

## 지금 당장 필요한 수정 방향

### A. 구조 수정

목표:
- `target population`을 generation anchor에서 가능한 한 내려놓고
- criteria / structuredExpression 중심으로 cohort generation이 되게 하기

최소 방향:
1. `targetCohortName`이 treatment arm 이름과 같으면 blocker 또는 hard warning
2. `process_eligibility` / `generate_seeded_cohorts`에서 target이 drug-like면 차단
3. structured eligibility가 있으면 generation은 그것을 우선 진실로 사용
4. `targetCohortName`은 라벨 역할로만 축소

### B. study `437` 복구

복구 순서:
1. `eligibility.targetCohortName`을 올바른 population 텍스트로 교정
2. 잘못 생성된 target/treatment cohort ids 제거 또는 무효화
3. `process_eligibility` 재실행
4. target preview가 drug name이 아닌 population인지 확인
5. `Generate Treatment Cohorts` 재실행
6. `Execute Study` 재실행
7. `targetN / treatmentN / comparatorN` nonzero 확인

### C. UI 보완

별도 UX 과제:
- `results.mode === webapi_generation`만으로 `generation complete`를 띄우지 말 것
- `target/treatment/comparator`가 전부 `0`이면 warning state로 보여야 함
- validation artifact가 execute 직후 자동 전면 노출되는 것도 줄일 필요 있음

---

## 추천 다음 세션 순서

1. study `437` 복구용 수동/반자동 수정
2. `targetCohortName == treatmentArms[0].name` guard 추가
3. structured criteria 우선 generation으로 이동
4. zero-count execute 결과에 대한 UI warning 보완
5. source dropdown 3-source allowlist 적용 여부 결정

---

## 참고용 live facts

- study: `437`
- source: `LEADER_BENCHMARK`
- target cohort id: `1139`
- treatment cohort id: `1140`
- outcome cohort id: `1141`
- wrong target label: `liraglutide`

---

## 남은 주의사항

- 현재 worktree에는 unrelated benchmark/doc 변경도 남아 있음
- 이번 커밋 `4f96b0d`는 TTE 변경만 묶었고, benchmark daily note churn은 포함하지 않았음

