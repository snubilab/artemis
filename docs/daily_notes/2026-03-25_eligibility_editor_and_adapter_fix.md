# 2026-03-25: Eligibility Editor UI 정렬 + Expression Adapter Exclusion 수정

## 오늘 완료

### UI 정렬 수정 (tte-manager.html + tte-manager.less)

- [x] valueConstraint badge (e.g. "gte 50 years") 너무 큰 문제
  - `.input-group-addon`: `white-space: nowrap`, `width: auto`, `font-size: 12px`, `padding: 4px 8px`
- [x] X 삭제 버튼 세로 정렬 불일치
  - `.input-group`: `display: flex`, `align-items: stretch`
  - `.input-group-btn`: `width: auto`
- [x] domain dropdown 높이 불일치 (select가 input보다 짧음)
  - `input-sm` 클래스 제거 (inclusion + exclusion 모두)
  - 모든 요소 통일: `height: 34px`

### Expression Adapter Exclusion 수정 (eligibility-expression-adapter.js)

**문제**: exclusion criteria가 ATLAS cohort editor에 inclusion으로 합쳐져 표시됨.
- `buildStructuredExpressionFromEligibility`: exclusion criteria의 ConceptSet + InclusionRule 미생성
- `buildEligibilitySummaryFromStructuredExpression`: 모든 InclusionRules를 inclusion으로 분류

**수정**:
- [x] `createRuleExpression(codesetId, exclusion)`: exclusion flag 추가
  - inclusion: `Occurrence: {Type: 2, Count: 1}` (1회 이상 발생)
  - exclusion: `Occurrence: {Type: 0, Count: 0}` (0회 발생 = 제외)
- [x] `buildStructuredExpressionFromEligibility`: exclusion도 ConceptSets + InclusionRules에 포함
  - exclusion rule 이름에 `[EXCLUDE]` prefix 부착
  - ConceptSet id 순차 할당 (inclusion 뒤에 exclusion)
- [x] `isExclusionRule(rule)`: `[EXCLUDE]` prefix 또는 `Occurrence.Count === 0` 감지
- [x] `splitRulesByType(rules)`: InclusionRules를 inclusion/exclusion으로 분리
- [x] `buildEligibilitySummaryFromStructuredExpression`: split 기반 파싱
  - inclFallback / exclFallback 각각 독립적 fallback 체인
- [x] `buildCriteriaFromRules`: 새 rule 구조 지원
  - Old: `{ ConditionOccurrence: { CodesetId } }`
  - New: `{ Criteria: { ConditionOccurrence: { CodesetId } }, Occurrence: ... }`
  - `[EXCLUDE]` prefix 제거 후 criteria shell에 표시
- [x] `ObservationWindow.PriorDays`: 0 → 365 (백엔드와 일치)

**버그 발견 및 수정** (테스트 중 발견):
- [x] `toSummaryCriterion`: `Number(null)` = 0이 `Number.isFinite(0)` = true로 통과
  - `conceptSetId: null`이 `0`으로 변환되어 TteCriteriaShell의 exclusion conceptSetId가 잘못됨
  - 수정: `item.conceptSetId == null ? NaN : Number(item.conceptSetId)`

### 테스트 (신규)

- [x] `tests/pages/target-trial-emulation/eligibility-expression-adapter.test.js` 생성
  - 18개 테스트 케이스, 3개 describe 블록
  - `buildStructuredExpressionFromEligibility` (9 tests): ConceptSets 생성, Occurrence 분리, [EXCLUDE] prefix, CodesetId 매칭, TteCriteriaShell, ObservationWindow, 빈 criteria
  - `buildEligibilitySummaryFromStructuredExpression` (6 tests): round-trip, conceptSetId, [EXCLUDE] strip, 백엔드 스타일 Occurrence 감지, DrugExposure domain, TteSummary fallback
  - `normalizeStructuredExpression` (3 tests): null 처리, Occurrence 보존, 이중 normalization 멱등성
- [x] 전체 테스트 스위트 56/56 pass

## 변경 파일

| 파일 | 변경 내용 |
|------|----------|
| `atlas-dev/js/pages/target-trial-emulation/tte-manager.less` | input-group 정렬, addon 축소 |
| `atlas-dev/js/pages/target-trial-emulation/tte-manager.html` | `input-sm` 제거 |
| `atlas-dev/js/pages/target-trial-emulation/eligibility-expression-adapter.js` | exclusion CIRCE 지원, null 버그 수정 |
| `atlas-dev/tests/pages/target-trial-emulation/eligibility-expression-adapter.test.js` | 신규: 18 tests |

## ATLAS CIRCE 포맷 참고

ATLAS의 cohort definition JSON (CIRCE)에는 별도의 `ExclusionRules` 필드가 없음.
Exclusion은 `InclusionRules` 안에서 `Occurrence: {Type: 0, Count: 0}` (해당 이벤트 0회 발생)으로 표현.
이는 ATLAS/OHDSI 표준 방식이며, ATLAS cohort editor UI에서는 "having 0 occurrences of..."로 표시됨.

### Demographics → DemographicCriteriaList

- [x] `_build_demographic_rule` 추가: Age criteria (gte/gt/lt/lte/eq)를 CIRCE `DemographicCriteriaList`로 변환
- [x] Demographics inclusion criteria가 이전에는 완전 스킵 → 이제 age constraint 포함
- [x] Demographics exclusion criteria는 여전히 스킵 (의미 없음)

### valueConstraint → ValueAsNumber

- [x] `_build_seeded_eligibility_rule`에서 criterion의 `valueConstraint` → CIRCE `ValueAsNumber` 변환
- [x] op 매핑: gt/gte/lt/lte/eq → CIRCE Op
- [x] valueConstraint 없으면 ValueAsNumber 안 넣음

### Docker 의존성 관리

- [x] `pyproject.toml` 누락 패키지 추가 (langchain-core, requests, structlog), 미사용 제거 (seaborn, google-generativeai)
- [x] `requirements.txt` 생성 (pyproject.toml 기반, 25 패키지)
- [x] `src/boot_check.py` — requirements.txt에서 자동 파싱, 빌드 타임 검증
- [x] `Dockerfile.tte-api` — requirements.txt 사용 + `RUN python -m src.boot_check`
- [x] 결과: placeholder 0 / real OMOP concept 20 (이전: 20 placeholder)

### 기타 수정

- [x] `structlog.stdlib.add_logger_name` 제거 (PrintLoggerFactory 비호환)
- [x] `libgdk-pixbuf2.0-0` → `libgdk-pixbuf-2.0-0` (Debian trixie)
- [x] Outcomes 탭 duplicate `data-bind` 제거

## 남은 것 (다음 세션)

- [ ] IR `window` (TemporalWindow)를 eligibility shell에 보존 → CIRCE StartWindow에 반영
  - `_criterion_dict_from_ir_item`에 `window` 필드 추가
  - `_build_seeded_eligibility_rule`에서 criterion.window 사용 (현재 하드코딩 365일)
- [ ] IR `observation_window`를 PrimaryCriteria에 반영 (현재 하드코딩 365/0)
- [ ] Drug Era 속성 (EraStartDate, EraLength) trial metadata에서 추출
- [ ] PHOEBE 테이블 생성/로딩
- [ ] Redis 캐싱 연결
