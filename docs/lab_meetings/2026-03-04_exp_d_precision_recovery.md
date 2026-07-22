# Lab Meeting: Exp D Precision Recovery

**날짜**: 2026-03-04
**참여 모델**: Claude, Codex (gpt-5.3-codex-spark) / Gemini (2회 실패 → 제외)

## 안건

Main paper skip(ADR-020) 후 LLM 재호출로 entity_text가 broad해짐 → Precision 39.8% → 26.0% 급락.
핵심 범인: `[E4] Insulin (short-acting or other types)` → 138,964 resolved concepts.

## 제안 요약

| 모델   | 핵심 제안                                                                                                      | 주요 근거                  |
| ------ | -------------------------------------------------------------------------------------------------------------- | -------------------------- |
| Claude | 3-Layer Defence: (1) 프롬프트 specificity (2) resolved count cap (3) best-fit contributor matching             | 근본→보완→보험 순서        |
| Codex  | (1) `_normalize_drug_entity_text()` rule-based guardrail (2) 프롬프트 Rule #11 추가 (3) overlap density metric | LLM 비결정성을 코드로 보정 |

## 교차 검증

### Claude → Codex 검증

- ✅ `_normalize_drug_entity_text()` guardrail: Drug domain 제한으로 안전. fallback 패턴이 일반화 보조
- ⚠️ direct_map 하드코딩: LEADER 한정이지만 fallback이 보완하므로 수용
- ❌ dead code (`raw = text` 미사용) → 정리 필요

### 합의 사항

- ✅ **프롬프트 Rule #11**: few-shot 없이 generic 지침으로 채택 (user 결정)
- ✅ **`_normalize_drug_entity_text()` guardrail**: 즉시 채택 (Codex 구현 유지)
- ⏳ **overlap density metric**: 별도 실험으로 검증 후 채택 여부 결정

## 반대 의견 기록

- Claude: resolved count cap(50K) 제안 → Codex 미채택 (정규화로 충분)
- User: 프롬프트에 few-shot 사용 금지 → Rule #11에서 예시 제거

## 실행 계획

- [x] `prompts.py` Rule #11 추가 (generic, no few-shot)
- [x] `parser.py` `_normalize_drug_entity_text()` guardrail 추가
- [ ] dead code 정리 (`raw = text`)
- [ ] 벤치마크 재실행으로 Precision 회복 확인
- [ ] overlap density metric 실험 (후속 과제)

## 부록

> 상세 내용은 `tmp/lab_meeting/20260304_exp_d_precision_recovery/` 참조
