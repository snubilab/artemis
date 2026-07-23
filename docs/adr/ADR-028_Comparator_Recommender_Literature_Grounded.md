# ADR-028: Comparator Recommender (문헌 근거 기반, placebo → CV-neutral 활성 대조약)

**상태**: 제안됨 (Proposed) — ADR-027 Phase 2, 미구현
**날짜**: 2026-07-23
**의사결정자**: @kyh
**관련**: ADR-027 (comparator = active-comparator new-user)

## 컨텍스트

ADR-027 Phase 1로 **활성대조 트라이얼**(arm[1]이 실제 약물: CAROLINA/PLATO/ARISTOTLE)은 대조군을 arm[1] 약제로 생성한다. 그러나 **placebo 대조 트라이얼**(LEADER/CARMELINA/EMPA-REG)은 arm[1]="placebo"라 실세계 CDM에 코호트가 없다. gold(TROY)는 이를 **CV-neutral 활성 대조약 클래스**(DPP-4 / Sulfonylureas)로 대체했다.

이 대체 약을 **사람이 매번 정하지 않고 에이전트가 문헌 근거로 추천**하되, 최종 선택은 사람이 승인한다.

핵심 제약: 이들은 **심혈관 아웃컴 시험(CVOT)**. 대조약 자체의 CV 효과가 HR을 오염시키므로, 대체 약은 해당 **아웃컴에 대해 CV-neutral**이어야 한다. "중립성"은 **아웃컴 특이적**이다 (예: saxagliptin은 MACE엔 중립이나 SAVOR에서 HF 신호).

## 결정

placebo 대조군에 대해 **문헌 근거 기반 comparator 추천기**를 도입한다.

- 근거 소스: **PubMed 문헌 에이전트** (실시간 조사, 인용 PMID 포함)
- 자율성: **제안 + 사람 승인(HITL)** — 자동 주입 금지. comparator 선택은 estimand를 좌우하는 과학적 결정
- 산출물: 약 이름이 아니라 **감사가능한 근거 아티팩트**

## 파이프라인

```
placebo 감지 (_is_placebo_arm)
  ① 컨텍스트 해석  치료약 → 성분 + ATC 클래스, 적응증, primary outcome
  ② 후보 생성     같은 적응증 · 다른 기전 · 처방가능(CDM 존재) 클래스 (치료 클래스 제외)
  ③ 문헌 근거     후보별로 "이 outcome에 대한 CV 효과" PubMed 조사
                   → 방향(superior/neutral/inferior/harm) + PMID + 효과크기(HR/CI)
                   ★1순위: 이 트라이얼의 기존 RWD emulation이 쓴 대조약
  ④ adversarial   선택 후보에 대해 "중립이 아니라는 근거" 반증 조사 → 반증되면 강등/플래그
  ⑤ 랭킹          CV-neutral 우선, CDM 처방빈도↑, 가이드라인 적합, 치료와 다른 클래스
  ⑥ 추천 아티팩트  top + 대안 1~2, 각 {근거 PMID, 중립성 판정, 신뢰도, caveat}
  ⑦ HITL          기존 AI review panel에 제안 → 승인/교체/기각
  ⑧ 생성          승인 시 ATC로 클래스 매핑 → _build_drug_anchored_comparator_circe 재사용
```

## 추천 아티팩트 스키마 (감사가능 provenance)

```json
{
  "trigger": {"studyId", "treatmentDrug", "treatmentClassAtc", "indication", "primaryOutcome"},
  "candidates": [{
    "class": "DPP-4 inhibitors", "atc": "A10BH",
    "cvEffectOnOutcome": "neutral",            // superior|neutral|inferior|harm|unknown
    "evidence": [{"pmid": "...", "trial": "CARMELINA", "finding": "MACE HR 1.02 (0.89-1.17) vs placebo"}],
    "rwdPrecedent": [{"pmid": "...", "comparatorUsed": "DPP-4i"}],
    "cdmPrevalence": 0.34,                       // optional
    "confidence": 0.86,
    "adversarial": {"refuted": false, "notes": "no MACE harm; HF caveat for saxagliptin"}
  }],
  "recommendation": {"class": "DPP-4 inhibitors", "rationale": "...", "alternatives": ["Sulfonylureas"]},
  "caveats": ["saxagliptin HF signal (SAVOR) — exclude/flag if outcome includes HF"],
  "status": "proposed"                           // proposed -> approved | overridden
}
```

## PubMed 쿼리 전략

- **선행 emulation (1순위)**: `"{trial}" AND (emulation OR "real-world" OR observational) AND comparator`
- **후보 CV 효과**: `"{candidate class}" AND (MACE OR "cardiovascular outcomes") AND (placebo OR "cardiovascular safety") AND (trial OR meta-analysis)`
- **반증(adversarial)**: `"{candidate}" AND (cardiovascular OR "heart failure") AND (increase OR risk OR harm)`
- 추출: 초록에서 효과 방향 + HR/CI + 트라이얼명 + PMID

## 컴포넌트 설계

- 신규: `src/agents/comparator/recommender.py` (또는 문헌 sub-agent에 위임하는 TTEService 메서드)
- 인터페이스: `recommend_comparator(treatment_drug, indication, outcome, target_cdm=None) -> RecommendationArtifact`
- 재사용: 문헌 에이전트(PubMed), Agent2 ATC(후보 열거 + 클래스 매핑, B 회피), LLM 효과 추출기, adversarial 검증기, 기존 review panel, `_build_drug_anchored_comparator_circe`
- 트리거: `_materialize_seeded_treatment_cohorts`에서 placebo 감지 + 승인된 comparator 아티팩트 없음 → **추천 아티팩트 발행(코호트는 아직 생성 안 함)**. 승인 시 C 빌더로 생성

## 근거

- **환각 위험 최소화**: 반드시 ≥1 검색 인용 + adversarial 반증 + 신뢰도. 모호하면 자동선택 금지
- **선행 emulation 우선**: "약의 CV효과를 우리가 판정"하기보다 "이미 검증된 comparator 선택을 따옴" → 방어력↑
- **아웃컴 특이성**: primary outcome로 조건화, 부작용 caveat 표기 (MACE≠HF)
- **estimand 명시**: 추천 comparator가 인과 질문("drug X vs CV-neutral 활성대조")을 정의함을 provenance로 남김
- **매핑 안정성**: 클래스는 ATC 경로가 정확(단일성분 RAG=B 회피)

## 미해결 / 리스크

- 캐싱: (treatmentClass, indication, primaryOutcome)별 추천 캐시 + 무효화 정책 (TBD)
- 다중 아웃컴: primary 기준 조건화, secondary는 caveat (정책 TBD)
- CDM 처방빈도 조회는 선택(있으면 랭킹 보강)
- Phase 1의 B(약제 concept 오매핑)가 선행 해결되면 comparator 클래스 매핑 품질도 향상

## 관련 문서

- `ADR-027_Comparator_Active_Comparator_New_User.md` — Phase 1 (활성대조)
- `docs/tte_agent/25_comparator_design_decision.md` — (superseded) 원래 Target−Treatment
