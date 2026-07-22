# Lab Meeting: Supervisor 선별적 매핑 재시도 설계

**날짜**: 2026-03-15
**참여 모델**: Claude, Codex (gpt-5.4) — Gemini 제외 (429 rate limit, 2회 실패)

## 안건

현재 Supervisor는 매핑 품질을 감지하지만 재매핑 액션으로 연결하지 않는다. 룰별 선별적 재시도 + Agent 1 피드백 경로를 설계한다.

## 제안 요약

| 모델 | 핵심 제안 | 주요 근거 |
|------|-----------|-----------|
| Claude | `triage_mapping` 노드로 entity별 분류 (PASS/SOFT_RETRY/HARD_RETRY/IR_FAULT) + `selective_remap` + `refine_ir` | 기존 audit 인프라 활용, LLM 비용 70-80% 절감 |
| Codex | `plan_mapping_remediation` + `execute_mapping_remediation` 분리, stable `entity_key`/`rule_path`, shared `mapping_retry.py`, localized `repair_criterion()` | review는 순수 분류기로 유지, ADR-024 준수를 위한 benchmark/production 공유 |

## 교차 검증에서 발견된 문제점

### 🛑 Critical Blocker (양측 공통)

**현재 파이프라인은 per-entity identity가 없다.**
- `_collect_cohort_entities()`에서 수집한 entity를 lowercase text로만 식별
- Consolidator가 mapping review 전에 sibling concepts를 병합 → raw per-entity 매핑 결과 소실
- Agent 3는 `source_entity_text`로 ConceptSet을 찾음 → 동일 텍스트가 여러 rule에 등장하면 첫 번째 매치만 반환
- **이 상태에서 "이 entity만 다시 매핑"은 안전하지 않음**

### Claude 제안(A) 문제점
1. `concept_count == 1 → SOFT_RETRY`는 현재 정책과 충돌 (`MIN_SEED_COUNT=1`이 의도적)
2. `force_slow_path`가 `map_single_entity()` API에 없음 — Agent 2 route는 환경변수로만 제어
3. `IR_FAULT` 판단 기준 미정의 ("IR이 잘못됐다" vs "매핑이 약하다"의 측정된 비율 없음)
4. Post-consolidation 데이터를 보고 triage하므로 원본 매핑 손실

### Codex 제안(B) 문제점
1. `entity_key`/`rule_path` 전파가 entity 수집 → 매핑 → 통합 → 레지스트리 → 어셈블러 전체를 관통해야 함 — 과소평가
2. `domain_mismatch → Agent 1 repair` 기본값이 현재 증거 대비 너무 공격적
3. 재시도 결과가 원본보다 나쁠 때의 rollback 메커니즘 미정의
4. `force_critic`, `force_route` 등이 현재 코드에 없음

## 최종 합의

### ✅ 합의된 사항 (2/2 모델 동의)

1. **Proposal B 기반으로 구현하되, v1 스코프를 축소한다**
   - `review_mapping()`은 순수 분류기 유지 (진단 + 사이드이펙트 혼합 금지)
   - 새 노드 2개: `plan_mapping_remediation`, `execute_mapping_remediation`
   - 공유 모듈: `src/pipeline/mapping_retry.py` (benchmark/production 공유, ADR-024)

2. **3가지 선결 조건 (Prerequisite)**
   - **P1: Stable entity identity** — `entity_key = {cohort}:{section}:{rule_idx}:{sub_idx}` 형식으로 `_collect_cohort_entities()`부터 전파
   - **P2: Pre-consolidation raw mapping 보존** — `mapping_node()`에서 통합 전 원본 `mapped_sets`를 state에 보관
   - **P3: Legacy Loop 1 통합** — `supervisor.py` `_step4_5_assemble_validate()`의 text-only 재매핑을 entity_key 기반으로 교체

3. **v1 재시도 대상 (보수적)**

   | Audit Signal | v1 Action | 근거 |
   |---|---|---|
   | empty mapping | Agent 2 selective retry (`slow` 강제) | 확실한 실패이므로 |
   | domain_mismatch | **1차** 원래 `domain_hint` 유지 + `slow` 강제, **2차** 강한 증거가 있을 때만 corrected `domain_hint` | Agent 1 intent를 기본 보존하고, 명백한 오분류만 제한적으로 교정 |
   | too_few_concepts (==1) | **Report-only** | `MIN_SEED_COUNT=1`이 의도적, 다른 약한 signal과 결합 시에만 |
   | high_risk (fast, critic_skipped) | **Report-only** | 추가 signal과 결합 시에만 retry |
   | overbroad | **Report-only** | Refiner가 이미 처리함 |

4. **concept_count == 1은 단독 retry 트리거가 아니다** (Codex의 "paired with another weak signal" 정책 채택)

5. **Agent 1 feedback은 v2로 연기** — 현재 "IR이 잘못됐다"의 실제 발생률 데이터가 없음. 벤치마크에서 측정 후 결정

6. **Rollback 게이트 필요** — 재시도 결과가 원본보다 나쁘면 원본 유지 (assembly completeness 비교)

7. **Domain correction gate (distribution branch)** — 자동 domain 변경은 아래 조건을 모두 만족할 때만 허용
   - 첫 `domain_mismatch` 재시도는 항상 원래 `domain_hint` 유지
   - `expected_domain_count == 0`
   - `dominant_non_expected_count >= 3`
   - `dominant_non_expected_ratio >= 0.8`
   - `unknown_domain_count == 0`

8. **Configurable env overrides (distribution branch)**
   - `SUPERVISOR_DOMAIN_CORRECTION_AFTER_RETRIES` (default: `1`)
   - `SUPERVISOR_DOMAIN_CORRECTION_MIN_COUNT` (default: `3`)
   - `SUPERVISOR_DOMAIN_CORRECTION_MIN_RATIO` (default: `0.8`)
   - `SUPERVISOR_DOMAIN_CORRECTION_REQUIRE_ZERO_EXPECTED` (default: `true`)
   - `SUPERVISOR_DOMAIN_CORRECTION_REQUIRE_KNOWN_ONLY` (default: `true`)

9. **Escalation semantics (distribution branch)** — `ESCALATE`는 현재 종료(action-to-END)가 아니라 상태 기록용 신호다.
   - `escalate_reason`는 state에 남긴다.
   - 라우팅은 다음 단계로 계속 진행한다.
   - 즉시 종료/HITL interrupt는 future phase에서 별도 설계한다.

### ⚠️ 즉시 수정이 필요한 기존 버그

- **Loop 1이 `domain_hint`/`rule_context`를 누락**함 ([supervisor.py#L402-406](file:///Users/kyh/Workspace/Broadsea/artemis/src/pipeline/supervisor.py#L402))
  - `get_agent2().process(text)` → `map_single_entity(text, domain_hint=..., rule_context=...)` 로 교체

## 반대 의견 기록

- **Claude**: Agent 1 feedback을 v1에 포함하자고 제안했으나, Codex가 "IR wrong vs mapping weak 비율이 측정되지 않은 가설"이라 반박. Claude 수용.
- **concept_count == 1 → RETRY**: Claude의 초기 제안을 Codex가 반박 (MIN_SEED_COUNT=1 의도적 설계). 합의: report-only.

## 실행 계획

- [ ] **Phase 0 (0.5일)**: 기존 버그 수정 — Loop 1의 `domain_hint`/`rule_context` 누락 해결
- [ ] **Phase 1 (1일)**: P1 구현 — `entity_key` 도입, `_collect_cohort_entities()` ~ `HealAction` 전파
- [ ] **Phase 2 (1일)**: P2 구현 — `ArtemisState`에 `raw_mapped_sets` 필드 추가, 통합 전 보존
- [ ] **Phase 3 (1.5일)**: 핵심 구현 — `mapping_retry.py` + `plan_mapping_remediation` + `execute_mapping_remediation` + `map_single_entity(force_slow_path=True)` API 확장
- [ ] **Phase 4 (0.5일)**: P3 구현 — Legacy Loop 1 → shared retry module로 교체
- [ ] **Phase 5 (future)**: Agent 1 feedback — 벤치마크에서 IR fault 비율 측정 후 결정

## 부록

> 상세 제안 및 리뷰는 `tmp/lab_meeting/20260315_supervisor_selective_retry/` 참조
