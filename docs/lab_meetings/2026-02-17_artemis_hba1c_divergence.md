# Lab Meeting: ARTEMIS HbA1c 규칙 분기 원인 분석

**날짜**: 2026-02-17
**참여 모델**: Claude, Codex (gpt-5.3-codex-spark) *(Gemini: 429 rate limit으로 제외)*

## 안건
LEADER 임상시험 Attrition Analysis에서 TROY L2=512 vs ARTEMIS L2=0 으로 분기되는 HbA1c 포함 규칙 차이의 근본 원인 분석 및 수정 전략 결정.

## 제안 요약

| 모델 | 핵심 제안 | 주요 근거 |
|------|----------|----------|
| Claude | 3대 버그 식별: (1) 시간 창 부호 오류, (2) Agent 1 value emission 실패, (3) Occurrence 반전 | 실제 ARTEMIS JSON 분석, `assembler.py` 코드 추적 |
| Codex | 시간 창 정규화 + decomposer 상속 + parser prompt 4단계 수정 | 코드 전수 검토, prompt/parser/planner/assembler 경로별 분석 |

## 교차 검증에서 발견된 문제점

### Claude 제안 반박 (Codex 검증)
- ❌ **Bug 2 원인 단정 과잉**: Claude는 "Agent 1이 value_constraint를 미생성"이라 단정 → Codex가 `parser.py:245-270`에 파싱 경로 존재함을 확인. LLM 준수율 또는 Planner 상속 누락이 더 유력.
- ❌ **Bug 3 과대평가**: Occurrence type 매핑은 `assembler.py`에서 정상 작동. `logic_type` 상속도 `decomposer.py`에서 이미 수행 중 → Agent 1의 ABSENCE 태깅 미수행이 원인.

### Codex 제안 반박 (Claude 검증)
- ⚠️ **"Agent 3 먼저" 우선순위**: 시간 창만 수정하면 ARTEMIS L2가 즉시 해결되진 않음 — value filter + occurrence 문제가 여전히 잔존.

### 추가 발견 (Codex)
- TROY 자체에 데이터 품질 이슈: HbA1c 규칙 이름 "≥7%"이지만 실제 value=10 (upper bound check)
- `ValueConstraint`가 `between`/`not between` 미지원 → 범위 체크 불가
- `unit_concept_id`는 파싱되나 Assembler에서 거의 미사용

## 최종 합의

### ✅ 합의 (2/2 모델 동의)

| # | 합의 사항 | 파일 | 우선순위 |
|---|----------|------|---------|
| 1 | **시간 창 기본값 수정**: `Days:365, Coeff:-1` | `assembler.py:231` | **P0** |
| 2 | **정규화 헬퍼 `offset_to_window()` 분리** | `assembler.py` (신규) | **P0** |
| 3 | **decomposer에 `value_constraint` 상속 추가** | `decomposer.py:100-107` | **P1** |
| 4 | **Window 검증 안전장치** (`start < end` 확인) | `assembler.py` (신규) | **P1** |

### ⚠️ 부분 합의
- Agent 1 프롬프트의 value threshold 추출 보강 — 방향 동의, 구체적 범위는 추가 분석 필요

## 반대 의견 기록
- Claude가 제안한 "Agent 1 단독 원인론"은 Codex에 의해 반박됨. 다중 경로(parser → planner → assembler) 전체를 점검해야 함.
- 기본 시간 창 `-365~0`이 모든 임상시험에 적절한지 의문 — 추후 context-aware 디폴트 또는 "window 미지정 시 명시적 에러" 정책 검토 필요.

## 실행 계획
- [x] Attrition analysis 완료 (TROY vs ARTEMIS L0~L4)
- [x] `assembler.py` 시간 창 기본값 수정 (P0)
- [x] `offset_to_window()` 헬퍼 구현 (P0)
- [x] `decomposer.py` value_constraint 상속 추가 (P1)
- [x] v5b 진단 실행: 버그 개별 영향도 측정
- [x] Agent 1 prompt 보강 (C2Q 3.0 기반, P2)
- [x] 개선된 프롬프트로 파이프라인 재실행 검증

## v5b 진단 결과 (2026-02-17 21:30)

| Variant | Count | 설명 |
|---------|-------|------|
| TROY L2 (reference) | **512** | Expert 정의 |
| ARTEMIS L2 (original) | **0** | 3대 버그 활성 |
| Fix A (window only) | **0** | 시간 창 수정만으로 불충분 |
| **Fix C (TROY-style)** | **512** | TROY 규칙 + ARTEMIS ConceptSet = 완전 일치 |

### 핵심 발견
- P0 코드 수정(시간 창)은 **필요조건이지만 충분조건이 아님**
- L2 분기의 1차 원인: Agent 1이 "HbA1c 7-10%" 조건을 잘못 해석
  - TROY: **HbA1c ≥ 10% 부재** (ABSENCE, 상한 안전 체크)
  - ARTEMIS: **HbA1c 측정값 존재** (PRESENCE, 값 필터 없음)
- Agent 1 프롬프트/추론 품질 개선이 근본 해결책

## v5 Attrition (시간 창 패치, 2026-02-17 21:50)

| Level | ARTEMIS_Patched | Drop |
|-------|--------------|------|
| L0_Entry | 1238 | |
| L1_Age | 512 | -726 (-59%) |
| L2_HbA1c | **0** | -512 (-100%) |
| L3_CVRisk | 0 | +0 |

→ 시간 창 수정만으로 L2=0 **불변** — Agent 1 의미론이 근본 원인임을 재확인

## C2Q 3.0 기반 Agent 1 프롬프트 개선 (2026-02-17 22:30)

[Criteria2Query 3.0](https://pmc.ncbi.nlm.nih.gov/articles/PMC11129920/) (Park et al, JAMIA 2024) 분석 후 4개 개선 적용:

| # | 개선 사항 | C2Q 근거 |
|---|----------|---------|
| 1 | OMOP 도메인 레퍼런스 (Measurement→value_as_number) | C2Q §2.2.1: 프롬프트에 OMOP 테이블 정의 포함 |
| 2 | Clinical Pattern 분류법 (A-D: 범위/임계/부정/이력) | C2Q §2.2.1: Value/Temporal 카테고리 분리 |
| 3 | One-shot 예시: HbA1c 7-10% → PRESENCE+ABSENCE | C2Q §2.1: 모든 프롬프트에 예시 포함 |
| 4 | 후처리 검증기 `_validate_measurement_rules()` | C2Q §2.2.3: Reasoning 프롬프트 변형 |

### 검증 결과
**Free-text ("HbA1c 7-10%"):**
```
[INC] HbA1c lower bound (>=7%): PRESENCE VC(gte 7.0 %) W(-180→0) ✅
[INC] HbA1c upper bound (no >=10%): ABSENCE VC(gte 10.0 %) W(-180→0) ✅
```

**NCT path (NCT01179048):**
```
[INC] HbA1c >= 7%: PRESENCE VC(gte 7.0 %) W(-180→0) ✅
```
→ ClinicalTrials.gov에 10% 상한 미기재로 인한 정상 누락

## 부록: 원본 제안 및 리뷰
> 상세 내용은 `/Users/kyh/Workspace/Broadsea/tmp/lab_meeting/20260217_artemis_hba1c_divergence/` 참조
