# Lab Meeting #2: Precision Fix — Root Cause 기반 구현 전략

**날짜**: 2026-03-09
**참여 모델**: Claude, Gemini (gemini-3.1-pro-preview), Codex (gpt-5.3-codex-spark)
**Meeting ID**: 20260309_precision_fix_v2

## 안건

M-TROY v4.1 (R=91.2%, P=44.1% after Dynamic IC) 에서 여전히 Precision 폭락하는 3개 rule의 root cause 분석 및 fix 전략.

## Root Cause 분석 결과

### No CHF (TROY=164, Agent2=10,105, **62x**, P=2%)

- **주범**: `Oxygen therapy (NYHA class IV)` query → Vector Search가 `Introduction procedure` (desc=9,534, IC=5.4) 반환
- Critic skip (unique_kg ≤ 10) → broad procedure가 **필터링 없이 통과**
- Heart Failure query 자체는 정상 (13 raw → 510 resolved)

### No acute coronary (TROY=876, Agent2=8,275, **9x**, P=10%)

- **주범**: `Revasculariazation_final` (typo+suffix) query → `Limb operation` (desc=5,463), `Vascular surgery procedure` (desc=3,635) 반환
- MI (33 raw → 361 resolved), Stroke (32 raw → 301 resolved)는 양호

### No MEN2 (TROY=6, Agent2=278, **46x**, P=2%)

- **주범**: `MTC` query → `Neuroendocrine neoplasm, malignant` (desc=243, IC=10.7) → 244 resolved
- MEN2 query 자체는 정상 (6 raw → 16 resolved)

## 제안 요약

| 모델   | 핵심 제안                                                                    | 주요 근거           |
| ------ | ---------------------------------------------------------------------------- | ------------------- |
| Claude | Raw concept hard-drop (desc > 500)                                           | 단순, 빠른 구현     |
| Gemini | 3-Layer: descendant-gated skip + domain enforcement + low-confidence pruning | 구조적 routing 개선 |
| Codex  | 조건부 skip (관계 유형 기반) + domain gate + query normalization             | 안전한 관계만 skip  |

## 교차 검증에서 발견된 문제점

### Claude 제안 문제

- **Hard-drop은 위험**: desc > 500 hard-drop은 legitimate broad query도 삭제. "Cardiovascular disease" 같은 valid broad query도 silent fail
- **Critic을 우회하는 것이 문제**: KG level에서 삭제하면 Critic이 판단할 기회 자체가 없음
- **MEN2 미해결**: desc=243이므로 threshold 500에서 통과

### Gemini 제안 문제 (Gemini 자체 리뷰)

- **Domain enforcement**: Clinical criteria는 cross-domain. Diabetes rule이 HbA1c(Measurement) + Insulin(Drug) 참조 가능. 하드 필터링 불가
- **Similarity score < 0.85 threshold**: embedding model 의존적, 불안정

### Codex 제안 문제

- **Query normalization (typo fix)**: `revasculariazation` 하드코딩은 band-aid. 다음 typo에서 또 깨짐
- **Scalable solution 아님**: 근본 해결은 Agent 1에서 정규화된 의학 용어 출력

## 최종 합의 (3개 모델 + 리뷰 종합)

### ✅ 핵심 합의: "Hard-drop 아닌, Critic으로 라우팅"

**3개 모델 모두 동의**: broad concept을 **삭제하지 말고**, Critic LLM에게 **판단을 위임**해야 함.

### ✅ Action 1: Descendant-Gated Critic Skip

```python
# workflow.py _kg_expand_and_critique
MAX_DESC_FOR_SKIP = 500

if len(unique_kg) <= 10:
    # Check if any concept has massive descendant footprint
    desc_counts = kg_expander._get_pg_descendant_counts([c.concept_id for c in unique_kg])
    max_desc = max(desc_counts.values(), default=0)

    if max_desc > MAX_DESC_FOR_SKIP:
        # Has broad concept → MUST go through Critic
        logger.info(f"Critic forced: max_desc={max_desc} > {MAX_DESC_FOR_SKIP}")
        final_ids = seed_ids + await critic.evaluate(query, unique_kg)
    else:
        # All concepts are specific → safe to skip
        final_ids = seed_ids + [c.concept_id for c in unique_kg]
```

- **왜 workflow level?**: KG는 찾은 것을 그대로 반환해야 함. 필터링 결정은 workflow가 해야 함 (Gemini 리뷰 합의)
- **왜 hard-drop 아닌 Critic?**: broad concept이 valid한 경우 Critic이 살릴 수 있음 (Claude 리뷰 수정)

### ✅ Action 2: Relationship-Type Safety Check (Codex 제안 보강)

```python
# workflow.py — Critic skip 추가 조건
SAFE_RELATIONSHIPS = {"maps_to", "sibling"}
UNSAFE_RELATIONSHIPS = {"ancestor", "ancestor_climb"}

unsafe_concepts = [c for c in unique_kg if c.relationship in UNSAFE_RELATIONSHIPS]
if unsafe_concepts:
    # ancestor/ancestor_climb은 항상 Critic 통과
    safe_ids = [c.concept_id for c in unique_kg if c.relationship in SAFE_RELATIONSHIPS]
    critic_ids = await critic.evaluate(query, unsafe_concepts)
    final_ids = seed_ids + safe_ids + critic_ids
```

### ⚠️ 보류: Domain Enforcement

- 3개 모델 모두 **hard domain filter 반대**
- Domain mismatch는 Critic 강제 실행의 추가 trigger로만 사용 (향후 과제)

### ⚠️ 보류: Query Normalization

- Band-aid 성격. Agent 1 개선이 근본 해결
- 단, `_final` suffix 제거는 trivial cost이므로 추가 가능

## 합의 결과 요약

| Action                 | 출처                 | 구현 난이도  | P 기대      | R 기대     |
| ---------------------- | -------------------- | ------------ | ----------- | ---------- |
| Desc-Gated Critic Skip | Gemini+Claude 수정안 | 중간 (2시간) | +5-10pp     | -0-1pp     |
| Relationship Safety    | Codex+Lab#1 합의     | 중간 (1시간) | +3-5pp      | -0-1pp     |
| **합산 예상**          |                      | **~반나절**  | **P ~55%+** | **R ~90%** |

## 반대 의견 기록

- **Claude의 hard-drop**: Gemini가 "massive risk to recall, prevents Critic from doing its job" 지적 → **수정 수용** (hard-drop → Critic routing으로 변경)
- **Gemini의 domain enforcement**: 모든 모델이 cross-domain 위험 지적 → **보류**
- **Codex의 query normalization**: Gemini가 "band-aid, not scalable" 지적 → **보류** (Agent 1 개선으로 분리)

## 실행 계획

1. [ ] Action 1: `workflow.py` descendant-gated Critic skip 구현
2. [ ] Action 2: `workflow.py` relationship-type safety check 구현
3. [ ] M-TROY 벤치마크 재실행
4. [ ] 결과 ABLATION_STUDY.md 기록

## 부록

> 상세 제안 및 리뷰: `tmp/lab_meeting/20260309_precision_fix_v2/` 참조
