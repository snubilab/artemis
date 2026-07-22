# Gold JSON Remediation TODO (Codex review, 2026-03-11)

> 상태: ✅ 완료 | 🔄 진행중 | ⬜ 미착수 | ⚠️ 재검토 필요 | N/A 해당없음

## LEADER

### 🔴 Red

- [x] [Fix] [🔴] ~~Implement E-7 (Planned revascularization)~~ — ✅ **Codex 판정: CDM/Circe 구조적 한계로 구현 불가.**
  - OMOP `ProcedureOccurrence`는 수행된 시술만 기록, "계획된" 시술은 first-class attribute 아님
  - `History of` / `Scheduled` concept class 없음. TROY v1.1/v3.4 양쪽 모두 같은 이유로 미구현
  - **결정**: `non-implementable by CDM design`으로 문서화. 보고서에 protocol gap으로 명시
- [ ] [Fix] [🔴] Lookback 180일 가정 검토 — ⏸️ **교수님 논의 필요**
  - 프로토콜에 명시 없는 operational 결정 (TROY 큐레이터 판단)
  - 만성 질환(CV disease, ESLD 등)에 180일은 과소 적용 가능성
  - **다음 단계**: 프로토콜 원문 확인 후 교수님과 적절한 lookback 결정
- [x] [Fix] [🔴] ~~Correct `No insulin` coverage so permitted classes (NPH/long-acting/premixed) are not excluded~~ — ✅ **현행 유지 결정 (선택지 C). TROY v3.4 보수적 배제 정책으로 문서화 완료**
- [ ] [Fix] [🔴] CHF severity 해석 불일치 — ⏸️ **교수님 논의 필요**
  - v1.1: NYHA **IV** (가장 심각한) 배제 → 프로토콜 원문에 부합
  - v3.4: NYHA **II–III** 배제 → 더 넓은 배제
  - GOLD는 v3.4 기준 사용 중 → 프로토콜보다 넓게 배제하는 상태
  - **다음 단계**: 프로토콜 원문 "NYHA class IV" 확인 후 결정
- [ ] [Fix] [🔴] CensoringCriteria `cs117 (DPP-4)` 조사 — ⏸️ **Codex 조사 필요**
  - 추적종료(censoring) 시 DPP-4 사용이 트리거 → 근거 문서화 없음
  - LEADER trial에서 DPP-4 금지이므로 사용 시 탈락 = censoring으로 추정
  - **다음 단계**: 프로토콜의 treatment discontinuation 규정 확인

### 🟡 Yellow

- [ ] [Remove/Flag] [🟡] `No substance abuse`와 `No pregnant`에 `source="troy_addition"` 플래그 추가 — ⬜ **현재 원문 기준과 동일하게 취급 중**
- [ ] [Replace] [🟡] 중복 CS 통합: `CS45↔124 (LVH)`, `CS46↔125 (LVD)`, `CS77↔97 (Revasc)`, `CS86↔118↔122 (microalb)` — ⬜ **미착수, MD에 문서화만 됨**
- [x] [Remove] [🟡] orphan CS 중복 2개 삭제 (CS 45 LVH, CS 86 microalb) — ✅ **활성 CS 124, 122가 동일 내용이므로 안전 삭제 완료. 나머지 13개는 고유 content 포함 → 현행 유지**
- [x] [Verify] [🟡] HbA1c rule이 `lt`, value `7`인지 확인 — ✅ **GOLD 구축 시 v3.4 버그 수정 완료 (Value=10→7, gte→lt)**
- [ ] [Verify] [🟡] `INVALID_REASON` 위반 4건 — ⏸️ **DB 접속 후 교수님 논의 필요**
  - CS 77 (orphan) + CS 97 (활성, Revascularization)에 동일 2개 concept 중복
  - `4214516` Insertion of drug coated stent → `INVALID_REASON='U'`, `STANDARD_CONCEPT='N'` → Maps-to: **없음** (유사 `44789455` drug-eluting stent이 CS 97에 이미 존재)
  - `4019536` Percutaneous transluminal angioplasty of artery NEC → `INVALID_REASON='U'`, `STANDARD_CONCEPT='N'` → Maps-to: `4050128` (Fluoroscopy guided angioplasty), CS 97에 **미포함**
  - ⚠️ 삭제/교체 위험: TROY 큐레이터가 의도적 포함 가능, Circe resolution 동작 불확실, 벤치마크 수치 변동 우려
  - **다음 단계**: DB 접속하여 `concept_relationship` 테이블에서 실제 Maps-to 확인 → 교수님 논의 후 결정
- [ ] [Fix] [🟡] `STANDARD_CONCEPT != 'S'` concept 23건 — ⏸️ **DB 접속 후 교수님 논의 필요**
  - CS 77+97 (Revascularization, 중복): 18건 — ICD9Proc 2, OPCS4 5, SNOMED 2 (INVALID_REASON 건과 동일)
  - CS 95 (Insulin): 1건 — `21600713` ATC class (`C`) → **현행 유지 결정 완료**
  - CS 110 (malignant neoplasm): 1건 — `42542326` HemOnc non-melanoma skin cancer (`N`, isExcluded용)
  - CS 80 (arterial stenosis): 1건 — `1414819` ICD10CN (`N`)
  - CS 83 (ischemic heart disease, orphan): 1건 — `44825431` ICD9CM (`N`)
  - CS 82 (unstable angina, orphan): 1건 — `35207680` ICD10CM (`N`)
  - **실질적 확인 필요**: CS 110(malignant)과 CS 80(arterial stenosis)만 활성 rule 관련. 나머지는 orphan 또는 이미 결정 완료

### 🟢 Green

- [ ] [Document] [🟢] `No transplant` branch 다운그레이드 사유 문서화 — ⬜ **R=20%로 악화된 원인 분석은 완료, 문서화 미착수**

## EMPA-REG

### 🔴 Red

- [ ] [Fix] [🔴] `No liver disease` exclusion concept 커버리지 확인 — ⚠️ **Gold에 rule 존재. 0% recall은 파이프라인(Agent 2) 매핑 실패이지 Gold 데이터 문제 아닐 수 있음 → 재검토**
- [ ] [Fix] [🔴] `No bariatric surgery` Procedure 하위 concept 보강 — ⚠️ **Gold에 rule 존재. 0% recall은 파이프라인 문제 → 재검토**
- [ ] [Fix] [🔴] `No anti-obesity drugs` concept 확장 — ⚠️ **Gold에 rule 존재. Agent 2 drug class 확장 실패가 원인 → 재검토**
- [ ] [Fix] [🔴] `No systemic steroids` exclusion 확장 — ⚠️ **Gold에 rule 존재. Agent 2 drug class 확장 실패가 원인 → 재검토**
- [ ] [Fix] [🔴] `No substance abuse` EMPA-REG 처리 — ⚠️ **Gold에 rule 존재 (R=0%는 파이프라인 문제) → 재검토**
- [ ] [Fix] [🔴] orphan `CS93` (cardiac surgery) 소속 결정 — ⬜ **의도적 유지 중이나 rule 미연결 상태**

### 🟡 Yellow

- [ ] [Fix] [🟡] `EMPA_REG_GOLD_DPP4.json`과 treatment arm 간 CS 일관성 비교 — ⬜ **미착수**
- [ ] [Verify] [🟡] `STANDARD_CONCEPT` 미준수 35건 교체/정당화 — ⬜ **Codex 리뷰에서 발견, 미조치**
- [ ] [Verify] [🟡] `INVALID_REASON` 위반 4건 수정 — ⬜ **Codex 리뷰에서 발견, 미조치**
- [ ] [Replace] [🟡] 중복 eGFR CS 제거 — ✅ **GOLD 구축 시 orphan CS 4개(136, 144, 169, 157) 제거 완료**

### 🟢 Green

- [ ] [Document] [🟢] 비프로토콜 concept 유지 사유 로그 — ⬜ **미착수**

## PLATO

### 🔴 Red

- [ ] [Fix] [🔴] `I-1 ACS hospitalization` 로직의 ACS concept 커버리지 확장 — ⚠️ **Gold에 STEMI/NSTEMI/ACS 개념 포함됨. 0% recall은 Agent 2 매핑 문제 → 재검토**
- [ ] [Fix] [🔴] `E-2 No fibrinolytics` drug class 확장 — ⚠️ **Gold에 7개 fibrinolytic agents 포함. 0% recall은 Agent 2 문제 → 재검토**
- [ ] [Fix] [🔴] `E-4 No oral anticoagulants` drug class 확장 — ⚠️ **Gold에 6개 anticoagulants 포함. 0% recall은 Agent 2 문제 → 재검토**
- [ ] [Fix] [🔴] `E-5 No CYP 3A4 inhibitors` 과확장 제한 — ⚠️ **Gold에 12개 약물 포함. 246 concepts 과확장은 Agent 2 문제 → 재검토**
- [ ] [Fix] [🔴] `CS28` STEMI의 `isExcluded=true` (NSTEMI 배제) 로직 검증 — ⬜ **resolved concept 계산 시 정확성 미검증**

### 🟡 Yellow

- [ ] [Add] [🟡] CYP3A4 12개 약물 목록 evidence/justification 문서화 — ⬜ **근거 문서화 없음**
- [ ] [Fix] [🟡] orphan CS 4개 (LBBB/MI/Prasugrel/ticagrelor중복) 정리 — ⬜ **미착수, MD에 문서화만 됨**
- [ ] [Verify] [🟡] `STANDARD_CONCEPT != 'S'` 9건 교체/정당화 — ⬜ **Codex 리뷰에서 발견, 미조치**
- [ ] [Verify] [🟡] `INVALID_REASON` 위반 2건 수정 — ⬜ **Codex 리뷰에서 발견, 미조치**
- [ ] [Remove/Flag] [🟡] ICH, Peptic ulcer, Prasugrel을 protocol-addition으로 표시 — ⬜ **미착수**

### 🟢 Green

- [ ] [Document] [🟢] PLATO E-1, E-5, E-6 protocol-vs-TROY gap 로그 — ⬜ **PLATO_GOLD.md에 일부 기록, 별도 문서 미작성**

## Cross-trial

### 🔴 Red

- [ ] [Fix] [🔴] 전체 `STANDARD_CONCEPT != 'S'` 교체 (LEADER 23 + EMPA 35 + PLATO 9 = 67건) — ⬜ **미착수**
- [ ] [Fix] [🔴] protocol 미구현 기준 중앙 목록 작성 — ⬜ **각 MD에 분산 기록, 통합 목록 없음**
- [ ] [Fix] [🔴] protocol-addition 항목에 명시적 태그 추가 (benchmark protocol-only 모드용) — ⬜ **미착수**

### 🟡 Yellow

- [ ] [Verify] [🟡] 전체 orphan CS 정리 (LEADER 14 + EMPA 1 + PLATO 4) — ⬜ **ID 파악 완료, 정리 미착수**
- [ ] [Verify] [🟡] cross-trial benchmark 한계 메모 작성 — ⬜ **`gold_data_issues_report.md`에 일부 분석, 별도 메모 미작성**
- [ ] [Add] [🟡] Gold 데이터가 TROY 기반 semi-automated reference임을 명시하는 공유 노트 — ⬜ **미착수**

### 🟢 Green

- [ ] [Document] [🟢] 향후 Gold 리뷰용 경량 체크리스트 작성 — ⬜ **미착수**
