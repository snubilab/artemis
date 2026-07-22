# TTE Pipeline End-to-End UX Fix — 2026-03-30

**Date**: 2026-03-30
**Commit**: `46eed12`
**Branch**: `main`

## 배경

Execute Study → Analysis → Results 전체 흐름이 막혀 있었음.
세 가지 문제가 복합적으로 작용:
1. Execute 완료 후 `results` 탭으로 이동 → Analysis 탭 건너뜀
2. 실행 artifact가 자동 apply되지 않아 `canTriggerRunAnalysis`가 영구 blocked
3. `shouldShowNextRequiredAction`이 하드코딩 `false` → 안내 CTA 전부 dead code

## 변경 사항

### Frontend (`tte-manager.js`)

| 항목 | 이전 | 이후 |
|------|------|------|
| `executeAnalysis()` 완료 후 탭 이동 | `selectTab({ key: 'results' })` | `selectTab({ key: 'analysis' })` |
| Artifact auto-apply | 없음 | `handleCapabilityResponse` 후 자동 apply |
| `shouldShowNextRequiredAction` | 하드코딩 `() => false` | 실제 조건: `!!nextRequiredAction() && selectedTabKey() !== nextRequiredAction().tabKey` |
| `isAnalysisFallback` | 없음 | `results().generatedBy === 'artemis-agent5-fallback'` pureComputed 추가 |
| `primaryOutcome.source` | 없음 | `ko.observable('')` 추가, populateFromStudy/payload 연동 |

### Frontend (`tte-manager.html`)

- **Analysis 탭**: 코호트 생성 완료 후 상단에 targetN / treatmentN / comparatorN 배너 추가
  - null 값은 `'-'` 표시 (기존 패턴과 통일)
- **Results 탭**: Agent5 fallback 경고 배너 + HR/CI/p-value에 `.text-muted` 스타일
- **Treatment 탭**: Time Parameters 패널을 Generate 버튼 위로 이동 (UX 흐름: 설정 → 생성 → 확인)
- **Outcomes 탭**: source 배지 (NCT / AI Generated / Manual), Cohort #ID, "Registered in WebAPI" 표시

### Backend

**`artemis/src/api/models/tte.py`**
- `Outcome` 모델에 `source: str = ""` 필드 추가 (유효값: `"nct"` | `"ai"` | `"manual"` | `""`)

**`artemis/src/services/tte_service.py`**
- `_study_from_ir()` / `_outcome_dict_from_ir()` — `source` 파라미터 전달
- `_generate_with_trial_agent_from_nct()` — `source="nct"` 전달
- NCT heuristic fallback 경로 — `primary.source = "nct"` 설정

**`artemis/src/pipeline/webapi_client.py`**
- `generate_existing_cohort()` early-return guard에 `and info.get("isValid") is not False` 추가
  - stale cache가 isValid=False인 경우 재생성 강제

**`tte_service.py` `_execute_via_webapi()`**
- `generate_existing_cohort(..., force_regenerate=True)` — explicit execute 시 항상 fresh 실행

## 발견된 버그 및 수정

### `isFallback` dead code
초기 구현에서 `|| this.results().isFallback === true` 조건 추가했으나,
`AnalysisResultPayload`에 `isFallback` 필드가 존재하지 않음 → 항상 false.
dead arm 제거 후 `generatedBy === 'artemis-agent5-fallback'`만 사용.

### 배너 null 표시
초기: `(results().targetN || 0).toLocaleString()` → null일 때 `"0"` 표시
수정: `results().targetN != null ? results().targetN.toLocaleString() : '-'`
기존 line 1658/1667 패턴과 통일.

### NCT heuristic fallback source 누락
`_heuristic_draft()` 경로에서 `source` 필드 미설정.
`generated_study.setdefault("outcomes", {}).setdefault("primary", {})["source"] = "nct"` 추가.

## 파이프라인 흐름 (수정 후)

```
[Eligibility 탭] criteria 확인
  → [Treatment 탭] Time Parameters 설정 → Generate → Preview/Approve
  → [Execute Study 탭] Run Execute → (auto-apply artifact) → Analysis 탭으로 이동
  → [Analysis 탭] cohort count 배너 확인 → Run Analysis
  → [Results 탭] HR/CI/p-value 표시 (fallback이면 경고 배너)
```

## 잔여 이슈 (미수정, 낮은 우선순위)

코드 리뷰에서 발견된 항목 중 미적용:
- H1: `executeAnalysis` 중복 guard 없음 (더블클릭 방어 미흡)
- H2: `run_analysis` 타임아웃 없음
- H4: WebAPI polling 에러 핸들링 불충분
- H5: `force_regenerate=True` 시 긴 대기 시간 UX
- H6: Results 탭 빈 상태 처리 미흡
- C2: Agent5 통계 플레이스홀더 값이 현실적 (0.83, 0.005) → 실수 유발 가능
- M1~M7: UX 일관성, 에러 메시지 개선 등
