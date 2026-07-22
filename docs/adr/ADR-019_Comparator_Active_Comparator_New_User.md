# ADR-019: Comparator = Active-Comparator New-User (gold 방식으로 복귀)

**상태**: 승인됨 (단계적 구현)
**날짜**: 2026-07-22
**의사결정자**: @kyh
**Supersedes**: `docs/tte_agent/25_comparator_design_decision.md`, `docs/tte_agent/23_comparator_target_minus_treatment_plan.md`

## 컨텍스트

기존 결정(2026-04-03, doc 25)은 comparator를 **"Target − Treatment"**(질환 기반 PrimaryCriteria + 치료약 ABSENCE)로 잡았다. 당시 근거:

1. PrimaryCriteria가 약물이면 Target 진입자 전원이 그 약 복용자 → comparator 파생 불가
2. **Synthea 벤치마크 CDM에 comparator 약물(clopidogrel, warfarin, placebo 등)이 없음**
3. "Target − Treatment = Comparator" 구조와 호환

즉 이 설계는 **대조약이 존재하지 않는 소형 벤치마크 CDM을 위한 편법**이었다.

2026-07 실제 병원 CDM(아주대 / 계명대) 실행에서 생성 코호트가 대량 0명/왜곡으로 보고되었고(김청수·조재형 선생님 피드백), 진단 결과 네 가지 결함이 확인됨:

- **A** entry가 약물이 아니라 질환(당뇨)으로 swap (`_swap_primary_to_disease`)
- **B** 약제 concept 오매핑 (linagliptin→sitagliptin 등, Agent2 단일성분 RAG)
- **C** comparator가 "치료약 없는 질환자"로, 실제 대조약(glimepiride 등)을 안 씀 (이 ADR의 대상)
- **D** 코딩 불가능한 기준을 필수 inclusion으로 강제

핵심: 실제 CDM에는 대조약이 **존재**하므로, doc 25 근거 #2가 더 이상 성립하지 않는다. 또한 "Target − Treatment"(new-user vs non-user)는 적응증 교란(confounding by indication)과 A 수정 시 자기모순(진입=치료약 + 배제=치료약)을 유발한다.

## 결정

Comparator를 **gold(TROY v1.1)의 active-comparator new-user 설계**로 되돌린다: comparator = **실제 대조약(클래스)의 신규 사용자 코호트**(DrugEra 진입 + 동일 eligibility 규칙). "치료약 ABSENCE" 로직은 폐기.

단계적으로 구현한다:

### Phase 0 — A (완료)
- `TTE_DRUG_ANCHORED_ENTRY` 플래그로 disease-swap 우회 → base의 DrugEra 진입 유지 (commit `7cf3fd5`)

### Phase 1 — 활성대조 트라이얼 (이번 범위)
- 대상: **CAROLINA / PLATO / ARISTOTLE** (arm[1]이 실제 약물)
- comparator = `treatmentArms[1]` 약제(glimepiride / clopidogrel / warfarin)로 **drug-anchored new-user 코호트** 생성
- 치료군과 동일 eligibility 규칙 공유, entry만 대조약으로

### Phase 2 — placebo 트라이얼 (다음 단계, 별도 작업)
- 대상: **LEADER / CARMELINA / EMPA-REG** (arm[1] = placebo, 실세계 CDM에 없음)
- placebo 코호트는 불가능 → **CV-neutral 활성 대조약 클래스로 대체**
- **comparator 추천기**를 도입: (적응증 + 아웃컴) → CV-neutral 활성 클래스 후보 추천
  - 매핑은 **ATC 클래스 경로** 사용 (단일성분 RAG의 B 오류를 피함; 클래스 = concept set 내부 OR)
  - **제안형 + HITL 승인** (조용한 자동 주입 금지) — comparator 선택은 estimand를 좌우하는 과학적 결정
  - gold 기준값: LEADER/EMPA → DPP-4 inhibitors, CARMELINA → Sulfonylureas

## 근거

- **원래 blocker 소멸**: 실제 CDM에 대조약이 존재 → 벤치마크용 편법의 전제가 사라짐
- **교란 회피**: active-comparator new-user(ACNU)는 pharmacoepi 표준. "non-user" 대조군은 적응증 교란·immortal time에 취약
- **CV-neutral 필요성**: 이들은 심혈관 아웃컴 시험(CVOT). 대조약 자체의 CV 효과가 HR을 오염시키므로, placebo 대체는 **CV-neutral**(예: DPP-4)이어야 치료약의 순수 효과가 분리됨
- **클래스 = OR**: 여러 후보약을 하나의 concept set에 넣으면 그 자체가 OR. 단, 무제한 "전 약물 OR"은 이질성/CV 오염을 유발하므로 **동질적 클래스**로 제한
- **매핑 안정성**: 클래스는 Agent2 ATC 라우트가 정확히 뽑음(예: Sulfonylureas → 12개 SU). 단일성분 RAG(B)를 우회

## 영향

- **수정 파일 (Phase 1)**: `src/services/tte_service.py`
  - `_materialize_seeded_treatment_cohorts` — 활성대조 arm은 comparator 약제(arm[1])로 라우팅
  - comparator 빌더 — drug-anchored 대조약 진입 코호트 생성, "No {treatment}" 규칙 제거
- **의존성**: Phase 1은 A(`TTE_DRUG_ANCHORED_ENTRY`) 활성 전제
- **미해결(별도 작업)**: B(약제 concept), D(불가능 규칙), Phase 2(placebo 추천기)
- **하위 호환**: 벤치마크 CDM 경로는 플래그 off로 기존 "Target − Treatment" 유지 가능
- **estimand 변화**: comparator가 "치료약 미사용"에서 "특정 활성 대조약"으로 바뀌므로 인과 해석·HR이 달라짐 (의도된 변화)

## 롤백 기준

- Phase 1도 플래그 게이팅. 문제 시 플래그 off → 기존 동작 복귀, IR 구조 변경 없음

## 관련 문서

- `docs/tte_agent/25_comparator_design_decision.md` — (superseded) 원래 Target−Treatment 결정
- `docs/tte_agent/22_three_study_gold_vs_ai_comparison.md` — gold 비교
- `artemis/output/gold_vs_generated/` — A/B/C/D 진단 대시보드 및 시뮬레이션
- `ADR-013_TROY_Is_Not_Ground_Truth.md` — TROY 위상 관련
