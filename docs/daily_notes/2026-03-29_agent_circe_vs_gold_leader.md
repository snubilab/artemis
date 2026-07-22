# Agent CIRCE vs Gold LEADER 비교 — 2026-03-29

## 목적
artemis agent가 생성한 CIRCE JSON으로 Gold와 동일한 LEADER 코호트가 뽑히는지 검증.

## 환경
- Source: `LEADER_BENCHMARK` (synthea_cdm_leader, 10k persons)
- Gold CIRCE: `artemis/output/e2e_leader_gold/circe_cohort.json` (12 rules, 75 concept sets)

---

## 문제 발굴 과정

### 1단계: 구버전 CIRCE (cohort 596, 2월 10일 생성)
- L00: 1132명
- L01: **0명** ← EndWindow `[0d~0d]` 버그

**원인**: assembler.py가 EndWindow를 `Days:0`으로 생성 → 만성질환 환자 전원 탈락.  
**수정**: 2026-03-26에 EndWindow 완전 제거 (`assembler.py:374` 주석 참고).

### 2단계: 현버전 CIRCE (cohort 596, 3월 이후 생성)
- L00: 1132명
- L01: 1132명 (EndWindow 버그 수정됨 ✅)
- L02: **0명** ← Rule "ultralente insulin, human" PRESENCE → 데이터 없음

**원인**: Agent2 fast path가 "ultralente insulin, human"을 INCLUSION 룰로 잘못 생성.

---

## 근본 원인: Agent2 Fast Path

complexity_router가 짧은 임상 쿼리를 "Simple"로 분류 → fast path → RAG top-1만 반환 (LLM 없음).

| 쿼리 | fast path 결과 | 올바른 결과 |
|------|---------------|-----------|
| GLP-1 receptor agonists | Adverse reaction to GLP-1 | liraglutide, exenatide 등 |
| Human NPH insulin | ultralente insulin, human | insulin isophane |
| Cardiovascular conditions | Sequelae of CV disorders | Disorder of CV system |

**수정**: `workflow.py`에서 fast path 분기 주석처리 → 전부 slow path 강제.

---

## Slow Path 적용 후 재생성 결과 (cohort 757, study 420)

```
L00 EntryOnly:              1132명
L01 Type 2 diabetes:        1132명  ✅
L02 Cardiovascular cond:      85명  (Sequelae of CV disorders → 너무 좁음)
L03 Cardiovascular risk:       0명  ❌ (Evaluation procedure 매핑 오류)
```

### INCL/EXCL 방향은 수정됨 ✅
이전엔 exclusion 룰도 모두 INCL(presence)로 생성됐으나, 현재는 정확히 분류.

---

## 남은 문제

1. **Concept mapping 품질** (Agent2 slow path도 일부 틀림)
   - "Cardiovascular conditions" → `Sequelae of CV disorders` (너무 좁은 개념)
   - "GLP-1 receptor agonists" → `prucalopride` (완전 무관)
   - "Human NPH insulin" → `ultralente insulin` (NPH ≠ ultralente)

2. **Rule 수 과다**: agent 28룰 vs Gold 12룰

3. **Rule naming**: concept name을 rule name으로 사용 (임상 의미 없음)

---

## Gold vs Agent 비교 요약

| 항목 | Gold CIRCE | Agent CIRCE (757) |
|------|-----------|------------------|
| Inclusion rules | 12 | 29 |
| Concept sets | 75 | 30 |
| INCL/EXCL 방향 | 정확 | ✅ 정확 (수정 후) |
| L00 (Entry) | 1378명 | 1132명 |
| L02 통과 | 대부분 통과 | 85명으로 급감 |
| Final 환자 수 | 1222명 | 0명 (L03 탈락) |

---

## 다음 단계
- Agent2 drug class 매핑 개선 (GLP-1, DPP-4 등 drug class → 실제 약물 개념)
- "Cardiovascular conditions" 매핑 → 구체적 CV disease 개념 (4심질환, 뇌졸중 등)
- Rule 수 축소 전략 검토
