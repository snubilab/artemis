# Lab Meeting: prior CV disease Recall 개선 전략

**날짜**: 2026-03-02  
**참여 모델**: Claude, Codex (gpt-5.3-codex-spark)  
**Gemini**: 실패 (exit code 1) → 2-모델 검증

## 안건
prior CV disease Recall 40% → 70%+ 개선 방법 (TROY 4,642 concepts 대비 1,872 overlap)

## 제안 요약

| 모델 | 핵심 제안 | 주요 근거 |
|------|----------|----------|
| Claude | **3단계 Concept Hierarchy Climbing**: Agent 2 seed → ancestor 1~2단계 → descendants 확장. Domain/separation 필터 + LLM Critic | TROY 큐레이터가 수작업으로 SNOMED 계층을 탐색한 것을 자동화. Stroke→Cerebrovascular disease→+200 descendants |
| Codex | **Domain-Gated Ancestor Climbing** + **Procedure 키워드 보강**: (1) N:1 분해+raw 유지, (2) Condition/Procedure에서만 ancestor climbing, (3) Revascularization 키워드 템플릿 | 기존 D v2에서 63~76% 달성했으므로 70%+ 현실적. Procedure는 별도 특화 필요 |

## 합의 (✅ 2/2 동의)

### Decision 1: Domain-Gated Ancestor Climbing 구현
- **대상**: `Condition`과 `Procedure` domain만
- **위치**: `kg_expander.py`에 `"ancestor_climb"` 전략 추가
- **파라미터**:
  - `max_levels = 2` (ancestor 최대 2단계)
  - `descendant_cap = 3000` (ancestor의 descendant 수 상한)
  - `domain_filter`: seed와 같은 domain만
- **Critic 검증**: ancestor가 원래 query와 관련 있는지 LLM이 판단

### Decision 2: Procedure 키워드 Fallback
- Revascularization 같은 Procedure domain에서 1차 seed가 부족하면:
  - 키워드 템플릿 확장: `revascularization` → `PCI`, `PTCA`, `CABG`, `stent`, `bypass`
  - 템플릿 기반 추가 seed → ancestor climbing

### Decision 3: Precision 통제
- **Rule-independent**: prior CV disease의 climbing이 다른 rule에 영향 없음 (rule별 독립 평가)
- **Per-rule gating**: descendant_cap + domain_filter + LLM Critic
- **모니터링**: 전체 ruleset precision regression 추적

### 예상 효과

| Sub-CS | 현재 R | 예상 개선 | 방법 |
|---|:---:|:---:|---|
| Stroke, TIAs | ~1% | +20~30pp | ancestor → Cerebrovascular disease |
| Revascularization | ~0% | +10~20pp | 키워드 template + ancestor |
| arterial stenosis | ~2% | +5~10pp | Vascular disease ancestor |
| microalbuminuria | 0% | +5~10pp | Kidney measurement ancestor |
| 나머지 11개 | 이미 양호 | 변화 적음 | - |

## 실행 계획
- [ ] `kg_expander.py`에 `ancestor_climb` 전략 추가
- [ ] `workflow.py`에서 Condition/Procedure seed에 climbing 적용
- [ ] Procedure 키워드 fallback template 구현
- [ ] A_direct v3 벤치마크 실행 및 결과 비교
- [ ] Precision regression 체크

## 부록
> 상세 내용은 `tmp/lab_meeting/20260302_prior_cv_disease_analysis/` 참조
