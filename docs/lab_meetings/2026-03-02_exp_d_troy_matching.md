# Lab Meeting: Exp D TROY Matching 해소 전략

**날짜**: 2026-03-02  
**참여 모델**: Claude, Codex (gpt-5.3-codex-spark)  
**참고**: Gemini (gemini-3.1-pro) 2회 실패로 제외, 2-모델 검증으로 진행

## 안건
Exp D benchmark에서 TROY 매칭 실패 (3 unmatched, 4 wrong) 해소 전략

## 제안 요약

| 모델 | 핵심 제안 | 주요 근거 |
|------|----------|----------|
| Claude | 4가지 해법: A) Compound split, B) N:1 aggregation, C) Ancestor climbing, D) Keyword fallback | GLP1-RA/Insulin의 compound text가 root cause. split + union이 가장 효과적 |
| Codex | 5가지 해법: 1) Drug compound split, 2) Agent 1 normalization, 3) N:1 matching (v4 패턴), 4) ABSENCE/PRESENCE guard, 5) Ancestor+LOINC | 1:1 매칭 정책이 근본 문제. v4의 N:1 grouping 패턴 이식 권장 |

## 교차 검증에서 발견된 문제점

### Claude 제안에 대한 Codex 검증
- **A (Compound split)**: 원칙적으로 맞지만 negation/temporal scope가 포함된 콤마는 split 불가. Drug domain에서만 적용해야 안전
- **B (Multi-rule aggregation)**: 개념적으로 맞지만, `used_troy` 1:1 정책 전체를 교체해야 함. v4-style grouping이 더 robust
- **D (Keyword fallback)**: "acute decompensation" 같은 obscure 매핑에는 fallback 필요하나, 주 매칭을 대체해서는 안 됨

### Codex 제안에 대한 Claude 검증
- **ABSENCE/PRESENCE guard**: hard blocking은 위험 (TROY occurrence가 underdefined일 수 있음). **soft penalty** 방식 권장
- **Agent 1 normalization**: 현재 post-normalization hook이 없어 별도 구현 필요. 효과 대비 공수 높음
- **v4 N:1 패턴**: `benchmark_v4.py:210-269`의 phase-based matching이 가장 robust한 기반

## 최종 합의 ✅

### 즉시 적용 (Priority 1-2, Exp D recall 48.6% → 55%+ 목표)

| # | Action | Layer | Expected Impact | Effort |
|:---:|--------|:---:|:---:|:---:|
| 1 | **Drug compound split** — Agent 1 output에서 `, or` 분리 → 개별 sub-query → union | benchmark script | GLP1-RA 58→90%+, Insulin 50→90%+ | Low |
| 2 | **N:1 TROY matching** — `used_troy` 1:1 제거, v4-style group matching 이식 | benchmark script | prior CV 3→~60%, unmatched 3→1 | Medium |
| 3 | **ABSENCE/PRESENCE soft penalty** — TROY occurrence type과 Agent 1 logic_type 비교, 불일치 시 recall에 0.5 penalty | benchmark script | 오매칭 방지 (T2DM→No T1DM 같은) | Low |

### 중기 적용 (Priority 3-4)

| # | Action | Layer | Expected Impact | Effort |
|:---:|--------|:---:|:---:|:---:|
| 4 | **Text-similarity fallback** — concept overlap < 1%인 경우에만 keyword matching | benchmark script | unmatched 1→0 | Low |
| 5 | **SNOMED ancestor climbing** — Condition domain seed concept 1-2 level up | Agent 2 | pregnant, ESLD 개선 | High |
| 6 | **LOINC eGFR panel expansion** — eGFR measurement variants 포함 | Agent 2 | eGFR 5%→20%+ | Medium |

### Compound Split 주의사항 (양 모델 합의)
- **Drug domain에서만** 적용 (Condition은 콤마가 modifier일 수 있음)
- `", or"` / `", and"` / `" or "` 패턴만 split
- 길이 < 4자인 fragment는 버림
- 예: "GLP-1 receptor agonist, pramlintide, or DPP-4 inhibitor" → 3개 sub-query

## 반대 의견 기록
- Codex는 Agent 1 post-normalization을 priority 2로 제안했으나, hook 부재로 공수 높아 후순위로 합의
- Codex의 ABSENCE/PRESENCE hard guard는 Claude의 soft penalty로 조정되어 합의

## 실행 계획
- [ ] `benchmark_exp_d.py`에 Drug compound split 적용
- [ ] `benchmark_exp_d.py`의 matching logic을 v4-style N:1로 교체
- [ ] TROY occurrence type 참조 + soft penalty 추가
- [ ] 재실행 후 Avg Recall ≥ 55% 달성 여부 확인

## 부록: 원본 제안 및 리뷰
> 상세 내용은 `tmp/lab_meeting/20260302_exp_d_troy_matching/` 참조
