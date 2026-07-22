# Eligibility Tab UX Review — 2026-03-28

## Session Summary

Treatment 탭 디자인 점검 중 Eligibility 탭 UX도 함께 리뷰.
이 문서는 현재 상태 분석 + 개선 방향을 정리한 것으로, 다음 세션에서 구현 논의용.

---

## 1. Treatment Tab — 오늘 수정한 것

### 1-1. Console 이슈 2건 수정
- `[TTE] progress` console.log 스팸 제거 (`tte-manager.js:2996`)
- `preview-seeded-cohorts` 404 → artemis-api 재시작으로 해결 (엔드포인트 추가 후 컨테이너 미재시작이 원인)

### 1-2. Cohort Preview 간소화
**Before**: concept set 30행 테이블 + inclusion rule 29행 테이블 = 60행
**After**: Drug Entry Event 강조 + inclusion rules `<details>` 접기/펼치기

구조:
```
Treatment: Arm 0
[Drug Entry Event]  liraglutide (1 concepts, +descendants)
> 29 inclusion rules  (클릭하면 펼쳐서 전체 테이블 확인 가능)

Comparator: Rest of population excluding Arm 0 (auto-generated)
Washout: 180d  Grace: 30d  Follow-up: 365d

[Cancel]  [Approve & Register]
```

변경 파일:
- `artemis/src/services/tte_service.py` — `_parse_circe_for_preview()` 리팩터링
  - PrimaryCriteria에서 drug entry 추출 (liraglutide)
  - inclusion rules에 concept set 정보 합침 (rule + concept set = 1행)
- `artemis/src/api/models/tte.py` — `DrugEntryPreview`, `RulePreview`, `ArmPreview` 모델 변경
- `atlas-dev/js/.../tte-manager.html` — `tte-arm-preview-template` 재구성
- `atlas-dev/js/.../tte-manager.less` — preview drug/details 스타일

---

## 2. Eligibility Tab — 결과 뷰어 UX 분석

### 2-1. 현재 구조

Process Eligibility 실행 후 배너에서 "Open Builder" 클릭 시:

```
[Target Population 패널]
  ├── Target Cohort: (read-only input)
  └── [tte-structured-editor-shell]        ← 여기가 결과 뷰어
       ├── sticky header: "ATLAS Cohort Editor" + [Cancel] [Apply Structured Edit]
       ├── focus toggle: [Definition] [Concept Sets]
       ├── atlas.cohort-editor (Definition 모드)
       │   또는 conceptset-list + AI Mapping Candidates (Concept Sets 모드)
       └── sticky footer: [Cancel] [Apply Structured Edit]
```

핵심 파일:
- `atlas-dev/js/.../components/tte-eligibility-cohort-editor.html` (133줄)
- `atlas-dev/js/.../tte-manager.html` 283-307줄 (shell wrapper)
- `atlas-dev/js/.../tte-manager.less` 1121-1228줄 (shell/editor 스타일)

### 2-2. 문제점

#### P1: 에디터가 Target Population 패널 안에 파묻혀 있음
- criteria rows 아래에 인라인으로 열림 → 스크롤해야 발견
- `max-height: 60vh; overflow-y: auto` → 에디터 안에서 또 스크롤 (스크롤 in 스크롤)
- 사용자가 "처리 결과가 어디 있지?" 하고 찾아야 함

#### P2: "Apply Structured Edit" 버튼 의미 불명확
- 위/아래에 동일 버튼 2개 (sticky head + sticky foot)
- "Apply"가 저장인지, 확정인지, 다음 단계인지 불명확

#### P3: Definition vs Concept Sets 토글이 탭처럼 안 보임
- btn-group으로 구현 → Atlas 기존 탭 패턴과 다름
- 현재 모드 구분이 `active` class만으로 약함

#### P4: 결과물 vs 입력의 경계 모호
- 위: criteria rows (입력), 바로 아래: cohort editor (결과)
- 시각적 구분이 `border-top: 1px solid #dbe6ef` 하나뿐
- "Current Study Inputs" 섹션과 에디터가 같은 공간에서 혼재

#### P5: Criteria row 정보 과밀
- 한 row에 ~13개 UI 요소: 7개 badge + 4개 버튼 + 2개 input
- 처음 보는 사용자에게 압도적

### 2-3. 개선 방향

| # | 문제 | 제안 | 난이도 | 우선순위 |
|---|------|------|--------|----------|
| 1 | P1: 에디터 위치 | `editorPanelMode` 기본값을 side panel로 변경 → criteria와 나란히 | S | HIGH |
| 2 | P2: Apply 버튼 | "Save & Close"로 라벨 변경, 역할 명확화 | S | HIGH |
| 3 | P4: 결과/입력 경계 | 에디터 영역 배경색 차별화 + 명확한 섹션 헤더 | S | HIGH |
| 4 | P5: row 과밀 | badge를 2줄 분리 (상단=메타, 하단=입력) | S | MED |
| 5 | P3: 모드 토글 | Atlas 탭 패턴과 일치시키기 (nav-tabs) | S | LOW |
| 6 | P1 추가 | 배너에 결과 요약 인라인 표시 (concept sets 수, rules 수) + "View Details" | M | MED |
| 7 | P4 추가 | Inclusion/Exclusion 10개 이상이면 탭 전환 방식 검토 | M | LOW |

### 2-4. 기존 잘 된 부분 (유지)

- 배너 상태 머신 (pending/ready/stale) — 상태별 행동이 명확
- skeleton loading — 로딩 중 UX 좋음
- criteria row에 domain badge, sourceText, mapping status 메타정보 밀도 높음 (정보는 필요, 배치가 문제)
- search/filter (5개 이상일 때 자동 표시) — 실용적
- AI Mapping Candidates 패널 — concept set 뷰에서 접기/펼치기 잘 동작
- `editorPanelMode` side panel 모드 이미 구현되어 있음 (활용 가치 높음)

---

## 3. 다음 세션 TODO

- [ ] 위 개선 방향 중 우선순위 HIGH 3개 먼저 논의
- [ ] 실제 Eligibility 처리 결과 화면 스크린샷 확보 후 구체적 수정 범위 결정
- [ ] SPEC 문서 작성 여부 결정 (SPEC-UI-009?)
