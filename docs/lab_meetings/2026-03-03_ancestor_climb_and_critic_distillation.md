# Lab Meeting: Ancestor Climb 최적화 및 Critic 모델 증류 전략

**날짜**: 2026-03-03  
**참여 모델**: Claude, Codex (gpt-5.3-codex-spark)  
**참조**: [ADR-018](../adr/ADR-018_Neo4j_Full_Transitive_Closure.md), [RFC-009](../rfc/RFC-009_Lightweight_Critic_Distillation.md)

## 안건
1. Neo4j full transitive closure 이후 ancestor_climb 전략 최적화
2. KG expansion variant(A/B/C) 비교 및 기본 설정 결정
3. LLM Critic을 경량 모델로 대체하기 위한 학습 전략

---

## 1. Ancestor Climb 개선 결과

### 문제
- 이전: `sep BETWEEN 1 AND 3` → 불완전한 hierarchy, 잘못된 descendant count
- `max(desc_count)` 단일 ancestor 선택 → SNOMED multi-inheritance 문제로 무관 ancestor 선택
  - 예: Cerebral infarction → "Necrosis of anatomical site" (❌)

### 해결 (Codex 2회 상담)
| 시도 | 전략 | 결과 |
|---|---|---|
| v1 | max sep + min desc_count | ❌ 더 높이 올라감 ("Intracranial injury") |
| **v2** | min sep + Disorder class + max desc_count | ✅ MI→Ischemic heart disease |

### 최종 구현: Top-K Union
- **Disorder class whitelist**: concept_class_id = 'Disorder'만 허용
- **SNOMED vocab filter**: vocabulary_id = 'SNOMED'
- **All valid ancestors union**: single-best → 모든 IC 통과 ancestor의 descendants 합집합

### 성과

| 지표 | A_direct v2 (이전) | A_direct v3 (개선) | Δ |
|---|:---:|:---:|:---:|
| Avg Recall | 79.3% | **83.1%** | **+3.8pp** |
| Full(≥80%) | 12 | **13** | +1 |
| No malignant | 40% | **100%** | **+60pp** 🎉 |

---

## 2. A/B/C Variant 비교 (✅ 합의)

### 실험 설계

| Variant | 설명 | kg_limit | Critic |
|---|---|---|---|
| **C** (기본) | expand + climb → 합쳐서 1× Critic | 15-40 | 1회 |
| **B** | expand limit 대폭 상향 | **100** | 1회 |
| **A** | expand/climb 분리 → 각각 Critic | 15-40 | **2회** |

### 결과

| 지표 | **C (기본)** | **B (kg↑)** | **A (2×Critic)** |
|---|:---:|:---:|:---:|
| Avg Recall | 83.1% | **84.5%** | 84.0% |
| Avg Precision | **53.3%** | 48.1% | 49.6% |
| **Avg F1** | **55.8%** | 50.2% | 54.5% |

### 주요 차이 분석

| Rule | C | B | A | 분석 |
|---|:---:|:---:|:---:|---|
| No ESLD | 33% | **62%** | 46% | B의 kg↑이 liver hierarchy 확대 효과 |
| No renal | 87% | **99%** | 87% | B만 renal hierarchy 추가 커버 |
| No pregnant | P=100% | **P=2%** | P=100% | B의 폭발적 over-expansion (133K concepts) |
| No MEN2 | R=100% | R=83% | R=100% | B에서 오히려 회귀 |

### Decision: C variant 유지
- **근거**: F1 최고(55.8%), Critic 1회, Precision 안정적
- **Codex 의견**: A가 recall 최선이지만 C가 실무 안전값
- **B 위험**: pregnant P=2%(133K concepts), MEN2 R 하락 — aggressive expand의 부작용

---

## 3. 실패 패턴 분석: transplant vs MEN2

| | No transplant (R=18%, P=88%) | No MEN2 (R=100%, P=0%) |
|---|---|---|
| **패턴** | Under-expansion | Over-expansion |
| **원인** | KG hierarchy 탐색 부족 | ancestor_climb 무차별 확장 |
| **TROY 규모** | 319 concepts (중간) | 6 concepts (매우 작음) |
| **Cohort 영향** | 포함해야 할 환자 누락 | 제외하면 안 될 환자 제외 |
| **해결 방향** | transplant-specific depth 확대 | rare disease는 climb 제한 |

---

## 4. LLM Critic 대체 전략 (RFC-009)

### 동기
- 현재: GPT-4o API 호출 → 비용, latency(2-10s), non-determinism
- 목표: 로컬 경량 모델로 완전 대체

### 합의된 아키텍처: Cross-Encoder + Metadata

```
[CLS] query [SEP] concept_name | domain | class [SEP]
    → BioLinkBERT (110M) → MLP + metadata → sigmoid
```

### 학습 파이프라인 (Codex 합의)

| Phase | 내용 | 기간 |
|---|---|---|
| 1. OMOP DAPT | concept names/synonyms MLM 적응 | 2-3일 |
| 2. Supervised FT | TROY positive + Critic 증류 + hard negative | 1주 |
| 3. Calibration | Recall≥80% 하 threshold 최적화 | 3일 |

### 핵심 기법
- **Hard Negative Mining**: graph neighbor + same-domain + Critic-rejected
- **Soft Labels**: LLM Critic confidence → label smoothing
- **Rule-wise k-fold CV**: 1 rule hold-out으로 일반화 검증

### 목표 vs 현재

| 지표 | LLM Critic | Gatekeeper 모델 |
|---|:---:|:---:|
| Latency | 2-10s | **<100ms** |
| Cost/query | $0.01-0.05 | **$0** |
| Determinism | ❌ | **✅** |
| Recall (목표) | 83.1% | ≥80% |

---

## 실행 계획

- [x] Neo4j full transitive closure 재로딩 (CSV import 20초)
- [x] ancestor_climb: Disorder + SNOMED + top-K union 구현
- [x] A/B/C variant benchmark 실행 및 비교
- [x] C variant를 기본 설정으로 확정
- [ ] RFC-009 리뷰 후 Critic 모델 학습 착수 결정

## 반대 의견 기록
없음 — C variant 선택, Critic 증류 전략 모두 합의.
