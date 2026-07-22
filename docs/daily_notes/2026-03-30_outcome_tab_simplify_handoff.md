# Outcome Tab Simplification — Handoff

**Date**: 2026-03-30
**Branch**: `feat/agent2-mapping-accuracy`
**Study**: 428 (apixaban vs warfarin, LEADER benchmark)

---

## Completed (3 commits)

### 1. `b4f0da5` — orphan dict bug fix
- **File**: `artemis/src/services/tte_service.py:2349`
- **Bug**: `primary = outcomes.get("primary") or {}` created orphan dict when primary is None/empty
- **Fix**: `if not outcomes.get("primary"): outcomes["primary"] = {}; primary = outcomes["primary"]`
- **Same fix for secondary** (line ~2371)
- **Tests**: `artemis/tests/test_seeded_outcome_cohort.py` — 7 tests (5 unit + 2 integration)
- **Effect**: Generate Seeded Cohorts now correctly sets outcome cohortId

### 2. `5991a8c` — hide manual selection UI
- **File**: `tte-manager.html`
- Hidden with `ko if: false`:
  - "Suggest Outcomes" button
  - Search icon (manual cohort selection)
  - "Outcome Selection Required" banner
  - Mapping guidance alert
  - Secondary outcomes "+ Add" button

### 3. `616199f` + `1c5ade4` — remaining UI fixes
- **File**: `tte-manager.html` + `tte-manager.js`
- Hidden: "Select primary and secondary outcome cohorts" info banner (on outcomes tab)
- Hidden: entire `tte-status-banner` container (was showing empty yellow bar)
- Relaxed gating: `tabCompletionStates.outcomes` now accepts `primaryOutcomeHasDraftText()` (not just cohortId)
- Same relaxation in `workflowPrerequisites`

---

## Current State (after commits)

- Outcomes tab: clean UI, shows Primary Outcome name/description only
- Progress indicator: Outcomes step shows as complete when draft text exists
- Generate Seeded Cohorts: outcome cohortId now correctly assigned
- View/Change buttons appear when cohortId is set

---

## OPEN ISSUE: Outcome Cohort 생성 로직 근본 문제

### 문제

Generate Seeded Cohorts에서 outcome cohort를 만들 때:

```
_build_seeded_condition_circe("Stroke or Systemic Embolism")
  → _build_seeded_single_codeset_circe(label=...)
    → _recommend_seeded_concept_set(label, ...)  # RAG fallback, top_k=5
      → 8개 SNOMED concept으로 bare cohort definition 생성
```

**결과**: Entry event 하나("condition occurrences of 'Stroke or Systemic Embolism'")에 8개 빈약한 concept만 있는 의미 없는 cohort definition.

### 왜 문제인가

1. **Eligibility IR을 전혀 참조하지 않음** — Agent2가 이미 풍부한 concept set을 매핑해놨는데, outcome cohort 생성 시 완전 무시하고 label 텍스트만으로 fresh RAG 검색
2. **RAG fallback top_k=5 하드코딩** — `tte_service.py:3423` — 최대 5~8개 concept만 반환
3. **concept set 품질이 아니라 설계 자체가 문제** — IR에서 넘어온 구조화된 데이터를 활용해야 하는데, 처음부터 다시 만들고 있음

### 추가 발견: 이름 문제

- 코호트 이름: `TTE 428 apixaban vs warfarin for Stroke or Systemic Emb Primary Outcome: Stroke or Systemic Embolism`
- `:` (콜론)이 Atlas 금지 문자 → validation error
- study_name + label 중복으로 이름 과도하게 긴 문제
- **메서드**: `_seeded_cohort_definition_name()` at line 2501-2521
- **Fix needed**: 특수문자 sanitize + 이름 간소화

### 관련 코드 위치

| 파일 | 메서드 | 라인 | 설명 |
|------|--------|------|------|
| `tte_service.py` | `_build_seeded_condition_circe` | 2519 | outcome CIRCE 생성 진입점 |
| `tte_service.py` | `_build_seeded_single_codeset_circe` | 2528 | RAG로 concept set 만들어서 CIRCE 빌드 |
| `tte_service.py` | `_recommend_seeded_concept_set` | 3269 | concept set 추천 (Agent2 or RAG fallback) |
| `tte_service.py` | RAG fallback `top_k=5` | 3423 | 하드코딩된 top_k 제한 |
| `tte_service.py` | `_seeded_cohort_definition_name` | 2501 | 이름 생성 (sanitize 없음) |
| `tte_service.py` | `_materialize_seeded_outcome_cohorts` | 2340 | outcome cohort 생성 오케스트레이션 |

### 재설계 방향 (미정)

- IR에서 outcome 관련 concept set을 가져와서 cohort definition에 반영
- eligibility의 Agent2 매핑 결과를 outcome cohort에도 활용
- 또는: outcome cohort를 별도로 생성하지 않고 IR 기반으로 직접 구성

### Gold 비교 참고

- Gold CIRCE: 232 concepts (205 Standard, 1 Classification, 13 NULL)
- Agent outcome cohort: 8 concepts — 비교 자체가 무의미한 수준

---

## Plans Written

- `docs/superpowers/plans/2026-03-30-outcome-cohortid-orphan-fix.md` — completed
- `docs/superpowers/plans/2026-03-30-outcome-tab-simplify.md` — completed

## Memory References

- `~/.claude/projects/-Users-kyh-Workspace-Broadsea/memory/MEMORY.md`
- `artemis/docs/daily_notes/2026-03-29_agent_circe_vs_gold_session2_summary.md`
