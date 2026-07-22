# RFC-009: LLM Critic 대체를 위한 경량 Gatekeeper 모델 학습 전략

**상태**: 검토 중  
**날짜**: 2026-03-03  
**제안자**: @kyh

## 1. 가설 및 목표

### 현재 문제
Agent 2 파이프라인의 Critic 단계가 **LLM API (GPT-4o)**를 사용하여 KG expansion 후보를 필터링.
- 비용: 매 query당 1-2회 API 호출 (A variant 기준 2×)
- Latency: 2-10초/query
- Non-determinism: 동일 입력에서 다른 출력 가능
- 외부 의존성: API 장애 시 전체 파이프라인 실패

### 목표
- **LLM API 호출 0**: 로컬 모델로 Critic 기능 완전 대체
- **성능 유지**: Avg Recall ≥80%, F1 ≥50% (현재 C variant: R=83.1%, F1=55.8%)
- **Determinism**: 동일 입력 → 동일 출력 보장
- **Latency**: <100ms/query (현재 2-10초)

### 성공 기준
| 지표 | LLM Critic (현재) | Gatekeeper 모델 (목표) |
|---|---|---|
| Avg Recall | 83.1% | ≥80% |
| Avg F1 | 55.8% | ≥50% |
| Latency/query | 2-10s | <100ms |
| API cost | $0.01-0.05/query | $0 |
| Determinism | ❌ | ✅ |

## 2. 제안 설계 (Proposed Design)

### 2.1 Task 정의

**Binary classification**: `(query_text, candidate_concept) → relevant (1) / irrelevant (0)`

```
Input:  query="substance abuse"
        concept_name="Drug dependence"
        domain="Condition"
        concept_class="Disorder"
        graph_distance=2
        
Output: relevant=1 (score=0.92)
```

### 2.2 모델 아키텍처: Cross-Encoder

```
[CLS] query_text [SEP] concept_name | domain | class [SEP]
                    ↓
            BioLinkBERT (110M params)
                    ↓
            MLP head + metadata features
                    ↓
            sigmoid → relevance score
```

**선택 근거** (Codex 합의):
- Cross-encoder가 query-concept 상호작용을 직접 학습 → bi-encoder보다 정확
- 후보 수 수백~수천 수준 → cross-encoder 속도 충분 (batch inference)
- BioLinkBERT: biomedical NLP에 최적화된 BERT variant

**Metadata features** (MLP head에 concat):
- `domain_match`: query 도메인과 candidate 도메인 일치 여부
- `graph_distance`: seed concept과의 Neo4j 최단 거리
- `ic_score`: Information Content (ancestor climbing에서 사용)
- `token_overlap`: query와 concept name의 토큰 교집합 비율

### 2.3 학습 파이프라인

```
Phase 1: OMOP Domain-Adaptive Pre-Training (DAPT)
    OMOP concept names + synonyms + ancestor relations
    → MLM objective, 1-2 epochs
    → biomedical terminology 강건성 확보

Phase 2: Supervised Fine-Tuning (Distillation)
    Training data:
    ├── TROY positive pairs (query, gold_concept) → label=1
    ├── LLM Critic logs (query, concept, accept/reject) → soft labels
    └── Hard negatives (same domain, near graph neighbors, rejected)
    → Binary CE loss, 5-10 epochs

Phase 3: Threshold Calibration
    Validation set에서 optimal threshold 탐색
    → Recall ≥ 80% 조건 하 Precision 최대화
```

### 2.4 학습 데이터 생성 전략

#### Positive 데이터
| Source | 규모 | 품질 |
|---|---|---|
| TROY gold standard | ~50K pairs (18 rules × ~3K avg) | ✅ 높음 (전문가 큐레이션) |
| LLM Critic accept 로그 | ~10K+ (기존 벤치마크 축적) | 🟠 중간 (LLM 판단) |

#### Negative 데이터 (핵심: Hard Negative Mining)
1. **Random negative**: 무관한 도메인의 concept 랜덤 샘플링
2. **Same-domain negative**: 같은 도메인이지만 TROY에 없는 concept
3. **Graph-neighbor negative**: seed 근처 graph 이웃이지만 TROY에 없는 concept (가장 어려움)
4. **Critic-rejected**: LLM Critic이 명시적으로 거부한 concept

**비율**: positive : random_neg : hard_neg = 1 : 1 : 2

### 2.5 일반화 전략 (18 rules → N rules)

18 rules만으로는 일반화 부족. 보강 방법:

1. **Rule-wise k-fold CV**: 1 rule hold-out → 나머지 17로 학습 → hold-out으로 평가
2. **Critic 증류 지속 증강**: 새로운 trial (PLATO 등) 벤치마크할 때마다 Critic 로그 축적
3. **Active Learning loop**: 모델 예측 확신도 낮은 샘플 → LLM Critic 재판정 → 학습셋 추가
4. **Cross-trial transfer**: LEADER 외 다른 trial의 TROY 데이터로 증강

## 3. 예상되는 리스크

| 리스크 | 심각도 | 완화 |
|---|---|---|
| 18 rules 일반화 부족 | 🔴 높음 | Active learning + cross-trial 증강 |
| TROY bias (LEADER trial 편향) | 🟠 중간 | Multi-trial 학습 데이터 |
| Cross-encoder 속도 (5K+ 후보) | 🟡 낮음 | Bi-encoder pre-filter + batch inference |
| Hard negative quality | 🟠 중간 | Curriculum learning (easy→hard) |

## 4. 해결되지 않은 질문

1. **BioLinkBERT vs PubMedBERT**: 어떤 base가 OMOP concept matching에 더 적합?
2. **Soft label 품질**: LLM Critic의 confidence를 어떻게 추출? (logprobs 사용 가능한지)
3. **Vocabulary-specific 처리**: Drug (ATC/RxNorm) vs Condition (SNOMED) 도메인별 모델 분리 필요?
4. **Online learning**: 프로덕션에서 Critic fallback + 모델 업데이트 주기?

## 5. 타임라인

| Phase | 기간 | 산출물 |
|---|---|---|
| 데이터 파이프라인 구축 | 1주 | TROY pair 추출 + Critic 로그 수집 스크립트 |
| OMOP DAPT | 2-3일 | Fine-tuned BioLinkBERT checkpoint |
| Supervised FT (v1) | 1주 | 초기 모델 + rule-wise CV 결과 |
| Hard negative mining + v2 | 1주 | 개선 모델 + 벤치마크 비교 |
| Threshold calibration + 통합 | 3일 | `critic.py` 대체 + A/B 테스트 |
| **합계** | **~4주** | LLM-free Critic |
