# Lab Meeting: M-TROY Precision 개선 전략 (Recall 유지)

**날짜**: 2026-03-09
**참여 모델**: Claude, Gemini (gemini-3.1-pro-preview), Codex (gpt-5.3-codex-spark)
**Meeting ID**: 20260309_precision_improvement

## 안건

M-TROY Recall 88.8% (역대 최고) 달성했으나 Precision 43.3%로 하락.
Recall ≥ 85% 유지하면서 Precision 60%까지 개선하는 방안.

## 현재 성능

| Benchmark | Recall | Precision | F1    |
| --------- | ------ | --------- | ----- |
| M-TROY    | 88.8%  | 43.3%     | 47.8% |
| E2E (v5)  | 61.2%  | 42.2%     | 43.6% |

## 제안 요약

| 모델   | 핵심 제안                                                                         | 주요 근거                         |
| ------ | --------------------------------------------------------------------------------- | --------------------------------- |
| Claude | 3-Layer Filter (IC threshold + Critic 제거 + Hierarchy dedup)                     | 단계별 noise 제거                 |
| Gemini | Safe Critic Skip + Dynamic IC climbing (`seed_ic - 4.0`) + Anti-broadening prompt | Root cause 분석 기반 surgical fix |
| Codex  | KG scoring (`KG_score` formula) + Calibrated Critic + Post-processing fusion      | 정량적 scoring으로 체계적 필터링  |

## 교차 검증에서 발견된 문제점

### Claude 제안 문제

- **Layer 3 (hierarchy dedup)의 방향 오류**: ancestor를 남기고 descendant를 제거하는 건 반대. 임상적으로는 child(specific) 유지, parent(broad) 제거가 맞음
- **Critic skip 완전 제거**: latency/비용 폭증, exact match에도 불필요한 LLM 호출
- **Domain threshold 튜닝**: 경험적 tuning 필요, 1-2일 내 최적화 어려움

### Gemini 제안 문제

- **Anti-broadening prompt 절대적 표현**: "DO NOT select broader" → vocabulary에 broad concept만 있을 때 유일한 valid mapping을 거부
- **Safe Critic Skip (ancestor 완전 배제)**: broad intent일 때 ancestor가 정답인 경우 Recall 손실

### Codex 제안 문제

- **Full fusion (Strategy 3)**: 1-2일 구현 불가, embedding + KG path + synonym scorer 파이프라인 필요
- **Self-consistency (2-3x Critic)**: LLM 비용 3배, latency 폭증
- **`1/degree` penalization**: SNOMED 핵심 concept이 high-degree, 잘못된 penalty

## 최종 합의 (3개 모델 + 리뷰 종합)

### ✅ Action 1: Dynamic IC Threshold (Gemini 제안 B, 합의)

**3개 모델 모두 동의.** Codex도 검증 시 "best candidate"로 인정.

```python
# ancestor_climb() 내부
seed_desc = self._get_pg_descendant_counts([concept_id]).get(int(concept_id), 0)
seed_ic = self.compute_ic(seed_desc)
dynamic_threshold = max(6.5, min(9.0, seed_ic - 2.5))  # Codex 제안 bounds 적용
```

- IC 높은 seed (rare disease) → threshold 올림 → broad ancestor 차단
- IC 낮은 seed (broad condition) → threshold 내림 → broad climb 허용
- 예상 효과: P +8-14pp, R -1-2pp

### ✅ Action 2: Confidence-Gated Critic Skip (Gemini + 리뷰 합의)

Critic skip을 완전 제거(Claude)도, 완전 유지도 아닌 **조건부 skip**:

```python
# workflow.py _kg_expand_and_critique
if len(unique_kg) <= 10:
    # Only skip if ALL concepts are safe (maps_to or sibling, not ancestor/ancestor_climb)
    safe_ids = [c.concept_id for c in unique_kg if c.relationship in ("maps_to", "sibling")]
    unsafe_ids = [c.concept_id for c in unique_kg if c.relationship in ("ancestor", "ancestor_climb")]
    if unsafe_ids:
        # Has ancestors → must go through Critic
        final_ids = seed_ids + safe_ids + await critic.evaluate(query, unsafe_ids)
    else:
        # All safe → skip Critic
        final_ids = seed_ids + [c.concept_id for c in unique_kg]
```

- 예상 효과: P +5-8pp, R -0-1pp (safe relationships은 그대로 유지)

### ✅ Action 3: Subsumption Filter (Gemini 리뷰 대안, 합의)

Post-processing 단계에서 **parent-child 중복 제거** (child 유지, parent 제거):

```python
# 최종 concept_ids에서 ancestor 관계 확인
# parent AND child가 모두 있으면 parent를 drop (child가 더 specific)
```

- Circe `includeDescendants=true`로 child의 descendants가 이미 커버
- parent도 있으면 parent의 전체 subtree가 추가되어 FP 폭증
- 예상 효과: P +3-5pp, R -0pp

### 합의 결과 요약

| Action                | 출처         | 구현 난이도  | P 기대     | R 기대        |
| --------------------- | ------------ | ------------ | ---------- | ------------- |
| Dynamic IC            | Gemini+Codex | 낮음 (1시간) | +8-14pp    | -1-2pp        |
| Confidence-Gated Skip | Gemini 리뷰  | 중간 (2시간) | +5-8pp     | -0-1pp        |
| Subsumption Filter    | Gemini 리뷰  | 중간 (2시간) | +3-5pp     | 0pp           |
| **합산 예상**         |              | **~반나절**  | **P ~60%** | **R ~85-87%** |

## 반대 의견 기록

- **Claude의 Critic 완전 제거**는 Gemini, Codex 모두 반대 → 비용/latency 문제
- **Codex의 full score fusion**은 Claude, Gemini 모두 "1-2일 불가능" → 향후 과제로
- **Claude의 hierarchy dedup 방향**은 Gemini가 "치명적 논리 오류" 지적 → child 유지로 수정

## 실행 계획

1. [ ] Action 1: `kg_expander.py` ancestor_climb에 dynamic IC threshold 구현
2. [ ] Action 2: `workflow.py` confidence-gated Critic skip 구현
3. [ ] Action 3: Post-processing subsumption filter 구현
4. [ ] M-TROY 벤치마크 재실행 및 ablation
5. [ ] E2E 벤치마크 재실행

## 부록: 원본 제안 및 리뷰

> 상세 내용은 `tmp/lab_meeting/20260309_precision_improvement/` 참조
