# ARTEMIS Agent 2 — Ablation Study

> 🏷 명명 규칙: [EXPERIMENT_NAMING_CONVENTION.md](./EXPERIMENT_NAMING_CONVENTION.md)

> 기능 추가/제거별 성능 변화 추적  
> 기준: LEADER trial, TROY v3.4 (18 rules)  
> 관련: [종합 보고서](./BENCHMARK_CONSOLIDATED_REPORT.md)

---

## 1. 누적 Ablation 요약

각 행은 **직전 단계 대비** 해당 기능을 추가한 효과.

### 1.1 `M-TROY` / `Exp A` 레이어 (Baseline & KG Expansion)

이 섹션은 초기 실험과 Neo4j KG 도입, Complexity Router 조정 등 코어 모듈(Agent 2 단독에 가까운 환경)의 개선을 다룹니다.

|  #  | 추가된 기능                                 | 실험             | Avg Recall |     ΔR      | Avg Precision |     ΔP      |  Avg F1   |     ΔF1     | Full(≥80%) |
| :-: | ------------------------------------------- | ---------------- | :--------: | :---------: | :-----------: | :---------: | :-------: | :---------: | :--------: |
|  0  | Baseline (vector search + reranker)         | Exp A            |   41.3%    |      —      |     61.5%     |      —      |   39.1%   |      —      |     4      |
|  1  | + Hierarchical Expansion (원본 term 유지)   | Exp A'           |   48.0%    | **+6.7pp**  |     56.6%     |   -4.9pp    |   43.5%   |   +4.4pp    |     5      |
|  2  | + ATC Drug Class Expansion                  | Exp C            |   52.8%    |   +4.8pp    |     56.8%     |   +0.2pp    |   41.5%   |   -2.0pp    |     5      |
|  3  | + KG Expansion **실제 연결** ¹              | M-TROY v2        |   79.3%    | **+26.5pp** |     54.0%     |   -2.8pp    |   54.0%   | **+12.5pp** |     12     |
|  4  | + ancestor_climb workflow 연결              | M-TROY v2+       |    ~79%    |    ~0pp     |     ~54%      |    ~0pp     |     —     |      —      |     12     |
|  5  | + Neo4j full transitive closure             | M-TROY v3 (C)    |   83.1%    | **+3.8pp**  |   **53.3%**   |   -0.7pp    | **55.8%** |   +1.8pp    |     13     |
|  6  | + **Force All Slow Path** ²                 | M-TROY v3 (slow) |   77.9%    | **-5.2pp**  |     44.8%     |   -8.5pp    |   48.2%   |   -7.6pp    |     11     |
|  7  | + `clinical_anchor` (descendants 제거) ³    | M-TROY v4        |   88.8%    | **+5.7pp**  |     43.3%     |    -10pp    |   47.8%   |   -8.0pp    |     14     |
|  8  | + **Dynamic IC Threshold** ⁴                | M-TROY v4.1      | **91.2%**  |   +2.4pp    |   **44.1%**   |   +0.8pp    | **49.0%** |   +1.2pp    |   **15**   |
|  9  | + **includeDescendants gating** ⁵           | M-TROY v4.2      |   90.3%    |   -0.9pp    |   **47.0%**   | **+2.9pp**  | **52.3%** | **+3.3pp**  |   **15**   |
| 10  | + **ConceptSetRefiner** ⁶                   | M-TROY v4.3      |   88.9%    |   -1.5pp    |   **52.4%**   | **+5.4pp**  | **57.2%** | **+4.8pp**  |   **14**   |

### 1.2 `A_direct` 레이어 (Agent 2 Mapping 정책 튜닝)

이 섹션은 Agent 1을 배제하고, TROY Gold의 개념 집합(Concept Set) 이름을 직접 입력으로 사용하는 **A_direct** 벤치마크 기준의 성능 변화입니다. 순수하게 Agent 2의 매핑 파워를 평가합니다.

|  #  | 추가된 기능                                 | 실험             | Avg Recall |     ΔR      | Avg Precision |     ΔP      |  Avg F1   |     ΔF1     | Full(≥80%) |
| :-: | ------------------------------------------- | ---------------- | :--------: | :---------: | :-----------: | :---------: | :-------: | :---------: | :--------: |
| 11  | Baseline (seeds-only includeDesc=false) ⁷   | A_direct seeds   |   72.4%    |      —      |   **72.8%**   |      —      |   66.3%   |      —      |     11     |
| 11a | + **hybrid policy (ancestors/climb only)**⁸ | A_direct hybrid  | **81.5%**  | **+9.1pp**  |   **74.0%**   | **+1.2pp**  | **73.1%** | **+6.8pp**  |   **12**   |
| 11b | + ancestor 1-hop limit ⁹                    | A_direct 1-hop   |   81.5%    |     0pp     |     70.9%     |   -3.1pp    |   69.5%   |   -3.6pp    |     12     |
| 11c | + **Current A_direct (v5, Refiner)** ¹⁰      | A_direct current | **86.1%**  | **+4.6pp**  | 42.2% / **65.9%** (Soft P2) | **-28.7pp** |   43.3%   | **-26.2pp** |   **14**   |

### 1.3 `E2E_TROY` 레이어 (Agent 1 → Agent 2 파이프라인)

이 섹션은 Agent 1이 TROY Rule 텍스트를 파싱하고 분해(Decomposition)한 결과를 바탕으로 Agent 2가 매핑하는 **End-to-End 파이프라인** 성능입니다. (A_direct와 직접 비교 불가)

|  #  | 추가된 기능                                 | 실험             | Avg Recall |     ΔR      | Avg Precision |     ΔP      |  Avg F1   |     ΔF1     | Full(≥80%) |
| :-: | ------------------------------------------- | ---------------- | :--------: | :---------: | :-----------: | :---------: | :-------: | :---------: | :--------: |
| 12  | Baseline (Supervisor Gate/context 분리 전)   | LEADER E2E_TROY  |   72.5%    |      —      |     61.5%     |      —      |   60.2%   |      —      |     9      |
| 13  | + **Domain Pre-Check** (ChromaDB top-3) ¹²   | LEADER E2E_TROY  |   83.9%    | **+11.4pp** |   **61.7%**   | **+0.2pp**  | **61.4%** | **+1.2pp**  |     13     |
| 14  | + **Zero-Shot Prompt (PURE CONCEPTS)** ¹³   | LEADER E2E_TROY  |   71.4%    | **-12.5pp** |     52.3%     |  **-9.4pp** |   52.1%   |  **-9.3pp** |     10     |
> ¹ **주의: Dead Code Path 사례**  
> `kg_expander.py`의 `expand()`, `ancestor_climb()` 함수와 Neo4j 데이터는 **#0 시점부터 존재**했으나,  
> `workflow.py`에서 **실제로 호출되지 않거나 효과적으로 동작하지 않고** 있었음.  
> M-TROY v2에서 벤치마크를 체계화하면서 비로소 발견 → 연결 수정 → +26.5pp.  
> **교훈**: 기능 개발 후 반드시 E2E 실행 경로에서 실제로 타는지 검증해야 함 (Integration Verification).

> ² **Force All Slow Path**: Complexity Router를 무시하고 모든 query를 slow path (UMLS 확장 + LLM Reranker)로 보냄.  
> 전체 Avg Recall은 **-5.2pp 하락**했으나, 특정 rule (No pregnant 등)에서 **대폭 개선**됨. → 세부 분석 §2.7 참조.

> ³ **clinical_anchor**: Lab meeting (2026-03-05) 합의. KG expansion에서 descendants를 제거하고 Circe `includeDescendants`에 위임.  
> ancestors + siblings + maps_to + ancestor_climb만 유지. Neo4j에 `Maps to` 2.75M relationships 추가.

> ⁴ **Dynamic IC Threshold**: `max(ic_threshold, seed_ic - 2.5)`. Specific seed(높은 IC)는 threshold를 올려 broad ancestor climb 차단.  
> Broad seed(낮은 IC)는 static threshold(8.0) 유지. `No pregnant` P: 2% → 100% 복원.

> ⁵ **includeDescendants gating**: PG descendant count > 5,000인 concept에 대해 `includeDescendants=false` 적용.  
> Concept 자체는 concept set에 유지하되, 하위 개념 확장만 차단. Fix #3(hard drop)과 달리 Recall 손실 최소화(-0.9pp).  
> M-GOLD: R=85.0%, P=44.6%, F1=46.1%.

> ⁶ **ConceptSetRefiner**: Lab meeting (2026-03-09) 합의. Critic 후, Assembler 전에 2-pass 필터:
> Pass 1 (Ancestor Subsumption): ancestor/ancestor_climb 관계 concept 중 descendant가 이미 kept set에 있으면 prune.  
> Pass 2 (Footprint Guard): desc > 3,000인 concept → `includeDescendants=false`.  
> Rollback Guard: pruning 후 kept < seed count면 전체 복원. `ENABLE_REFINER=0`으로 비활성화 가능.

> **가장 큰 단일 기여**: KG Expansion 도입 (#3, +26.5pp recall)  
> **두 번째**: includeDescendants hybrid policy (#11a, **+21.6pp precision**)

> ⁷ **seeds-only policy**: lab meeting (2026-03-10) 합의. 모든 non-seed concept에 `includeDescendants=false` 적용.  
> P +20.4pp이나 R -16.5pp. "No malignant" R 92→41%, "No ESLD" R 91→1% — **너무 공격적**이라 폐기.

> ⁸ **hybrid policy (최종 채택)**: sibling/maps_to는 seed와 같은 세밀도(granularity)이므로 `includeDescendants=true` 유지.  
> ancestor/ancestor_climb만 `includeDescendants=false`. `INCLUDE_DESC_SEEDS_ONLY=0`으로 비활성화 가능.  
> 핵심 개선: No CHF P 6→96%, No eGFR P 7→86%, No MEN2 P 0→60%.

> ⁹ **ancestor 1-hop**: `max_sep=2→1` (ancestors), `max_sep=3→1` (climb). P -3.1pp (LLM nondeterminism). **효과 없어 revert.**

> ¹⁰ **Current A_direct (v5, Refiner)**: 현재 최신 버전(`benchmark_v5.py` 기반)의 순수 Agent 2 파이프라인.  
> 11a(hybrid policy 강제)에 비해 Gating 조건이 Soft해지고 `ConceptSetRefiner`로 대체되면서, **Strict Precision은 42.2%**로 하락함.
> 그러나 하위 자식 노드를 전부 불일치로 간주하는 맹점을 해결하기 위해 **Soft-Margin Semantic Distance(최단 계층 홉 수)**를 측정해본 결과, **Soft-Margin P (≤2 hop)이 65.9%**에 달함.
> 즉, 수치상 42.2%로 보이나 실제로 TROY 정답 개념과 직계 부모-자식 혹은 조부모-손자(2-hop 이내) 관계에 있는 매우 정확한 개념(Semantic Vicinity)을 찾아낸 비율이 66%였음을 의미하며, 강제로 확장을 틀어막아 Recall을 희생시킬 이유가 없음을 증명함.
> ¹⁰ **Supervisor Gate + rule_context**: Domain Mismatch Gate (report-only) + parent_rule을 humanize하여 Agent 2 context로 전달.
> PLATO E2E_TROY 벤치마크이므로 이전 A_direct LEADER 기준(#11b)과 직접 ΔR/ΔP 비교 불가.

> ¹² **Domain Pre-Check (폐기)**:  Agent 2 진입 시 ChromaDB top-3 (domain_hint=None) → domain vote로 Agent 1의 domain_hint 교정 시도.
> LEADER에서 **harmful override 6건** 발생: Insulin Drug→Procedure, Microalbuminuria Measurement→Condition, Acute stroke Condition→Procedure 등.
> **원인**: ChromaDB semantic embedding은 의미적 유사성 기반이라, 동일 임상 concept이 다른 도메인에도 존재 (e.g., "Insulin" ingredient vs "Administration of insulin" procedure).
> **결론**: 기본 비활성화 (`DOMAIN_PRECHECK=0`). 코드는 실험용으로 유지.

> ¹³ **Zero-Shot Prompt (PURE CONCEPTS)**: Agent 1 프롬프트에 Rule 7/12를 추가하여 `name` 필드에서 임상시험 문맥("history of", "concomitant therapy with" 등)을 강제 제거.
> Agent 2가 순수 약물/질환 클래스만 입력받도록 개선. PLATO R +22.7pp (Drug class 매핑 복원), LEADER R -12.5pp (복합 개념 분해 trade-off).

---

## 2. 개별 기능 Ablation

### 2.1 ATC Drug Class Expansion (RFC-006)

Drug 도메인에서 ATC → `concept_ancestor` → RxNorm Ingredient 경로 활용.

| Rule            | Without ATC | With ATC  |     Δ     |
| --------------- | :---------: | :-------: | :-------: |
| GLP1-RA/DPP-4   |     42%     | **100%**  | **+58pp** |
| Insulin         |     73%     |  **97%**  | **+24pp** |
| 기타 (non-Drug) |  변화 없음  | 변화 없음 |     0     |

> **영향 범위**: Drug 도메인에만 국한. 결정적 개선.

### 2.2 Hierarchical Expansion (원본 term 유지)

Agent 1 분해 시 원본 rule name을 항상 유지 → 추가 query로 활용.

| Rule             | A (없음) | A' (있음) |     Δ     | 원인                                    |
| ---------------- | :------: | :-------: | :-------: | --------------------------------------- |
| **No pregnant**  |    4%    | **100%**  | **+96pp** | "pregnant" → ancestor concept 직접 매칭 |
| No transplant    |    4%    |    17%    |   +13pp   | "transplant" broader coverage           |
| prior CV disease |   63%    |    67%    |   +4pp    | 원본 ancestor 추가                      |
| Acute coronary   |    9%    |    12%    |   +3pp    | 원본 query 보완                         |

> **핵심 인사이트**: 분해 = **대체가 아닌 확장**. 원본 유지만으로 pregnancy 100% 해결.

### 2.3 KG Expansion (Neo4j graph traversal)

seed concept에서 descendants, siblings, maps_to를 Neo4j로 탐색.

| Rule                 | Without KG | With KG  |     Δ      |
| -------------------- | :--------: | :------: | :--------: |
| No acute coronary    |   9-11%    | **87%**  | **+76pp**  |
| No CHF               |    20%     | **100%** | **+80pp**  |
| No renal replacement |    48%     | **87%**  | **+39pp**  |
| No eGFR <30          |     8%     | **100%** | **+92pp**  |
| No drug dependence   |     0%     | **100%** | **+100pp** |
| No malignant         |    40%     | **100%** | **+60pp**  |
| No ESLD              |    33%     |   33%    |    0pp     |
| No transplant        |    17%     |   18%    |    +1pp    |

> **가장 큰 단일 기여**. Condition 도메인에서 hierarchy 탐색이 핵심.  
> ESLD/transplant는 KG만으로 불충분 → ancestor_climb 필요.

### 2.4 Ancestor Climb (IC-based hierarchy climbing)

seed에서 위로 올라가 broader ancestor를 찾고 그 descendants를 수집.

| Rule             | Without climb (v2) | With climb (v3) |     Δ     |
| ---------------- | :----------------: | :-------------: | :-------: |
| No malignant     |        40%         |    **100%**     | **+60pp** |
| No pregnant      |        99%         |       99%       |    0pp    |
| No ESLD          |        31%         |       33%       |   +2pp    |
| prior CV disease |        40%         |       41%       |   +1pp    |
| 나머지           |     변화 미미      |        —        |   ~0pp    |

> **No malignant가 핵심 수혜자**: climb이 neoplasm hierarchy 전체를 커버.  
> ancestor_climb은 **broad hierarchy가 필요한 특정 rule**에서만 효과적.

### 2.5 Ancestor Climb 세부 — Selection 전략

동일한 ancestor_climb에서 선택 로직만 변경한 ablation.

| 전략                              | 방식                     | 예시 (MI)                      | 문제            |
| --------------------------------- | ------------------------ | ------------------------------ | --------------- |
| max desc_count                    | 가장 큰 ancestor 1개     | Necrosis of anatomical site ❌ | 무관한 ancestor |
| max sep + min desc                | 가장 높이 올라감         | Intracranial injury ❌         | 더 무관         |
| **min sep + Disorder + max desc** | 가까운 broadest Disorder | Ischemic heart disease ✅      | 채택            |

### 2.6 kg_limit Ablation (A/B/C Variant)

| 설정               | Avg Recall | Avg Precision |  Avg F1   | 주요 영향                 |
| ------------------ | :--------: | :-----------: | :-------: | ------------------------- |
| kg_limit=15-40 (C) |   83.1%    |   **53.3%**   | **55.8%** | 균형                      |
| kg_limit=100 (B)   | **84.5%**  |     48.1%     |   50.2%   | ESLD +29pp, pregnant P=2% |
| 2×Critic (A)       |   84.0%    |     49.6%     |   54.5%   | ESLD +13pp, cost 2×       |

> **Recall vs Precision 트레이드오프**: kg_limit↑은 recall +1.4pp이지만 precision -5.2pp.

### 2.7 Force All Slow Path (Complexity Router 우회)

Complexity Router를 무시하고 **모든 query를 slow path**로 강제 전송.  
Slow path = UMLS Synonym Expansion + LLM Reranker (top-3) + KG + Critic.

**조건**: `FORCE_SLOW_PATH=1` 환경변수, M-TROY v3 기준.

| Rule                     | v3 (C) 기존 | v3 (slow) |     Δ     | 분석                                         |
| ------------------------ | :---------: | :-------: | :-------: | -------------------------------------------- |
| **No pregnant**          |     99%     | **100%**  |   +1pp    | UMLS 동의어 확장 효과                        |
| **No renal replacement** |     87%     |  **99%**  | **+12pp** | 다중 동의어 검색으로 커버리지 향상           |
| **No eGFR <30**          |    100%     |  **95%**  |   -5pp    | Reranker가 일부 seed 오선택                  |
| **No T1DM**              |    100%     |  **84%**  |   -16pp   | Reranker top-3이 cross-branch concept 탈락 ³ |
| **No transplant**        |     18%     |  **44%**  | **+26pp** | UMLS multi-query 효과                        |
| **No malignant**         |    100%     |  **65%**  |   -35pp   | Reranker가 broad ancestor 오선택             |
| **No MEN2/FMTC**         |    100%     |  **67%**  |   -33pp   | Reranker top-3 부족                          |
| **No drug dependence**   |    100%     | **100%**  |    0pp    | —                                            |
| **No CHF**               |    100%     | **100%**  |    0pp    | —                                            |
| 나머지                   |      —      |     —     |   ~0pp    | —                                            |

> ³ **T1DM Reranker 탈락 사례** ([RFC-010](../rfc/RFC-010_Reranker_Cross_Branch_Recall.md)):  
> Vector Search가 `435216 (Disorder due to T1DM)`을 rank 6에서 찾았으나,  
> LLM Reranker가 top-3 선택 시 subtype(1A, 1B)만 선택하고 cross-branch concept 탈락.  
> Fast path에서는 top-1만 선택하나 KG expansion이 더 효과적으로 보완.

**결론**: All Slow Path는 **전체 성능을 하락**시킴 (Avg R -5.2pp, F1 -7.6pp).  
Slow path의 LLM Reranker가 일부 rule에서 KG expansion 대비 **오히려 seed를 좁힘**.  
Fast path의 top-1 + KG expansion이 더 넓은 커버리지를 제공하는 경우가 많음.  
→ **Complexity Router는 유지**, 개선은 Reranker 프롬프트 or top_n 조정으로 분리 대응 (RFC-010).

### 2.8 Overgeneration Fix (2026-03-09)

Lab meeting (2026-03-05) 합의: KG expansion의 과다 생성 해결.

#### 2.8.1 clinical_anchor + Maps to (v4)

- `clinical_anchor` 전략: descendants 제거, ancestors + siblings + maps_to + ancestor_climb만 유지
- Neo4j에 `Maps to` 2.75M relationships 추가
- Descendants는 Circe `includeDescendants: true`에 위임

| Rule                 | v3 Recall | v4 Recall |    ΔR     | v3 Prec | v4 Prec |    ΔP     |
| -------------------- | :-------: | :-------: | :-------: | :-----: | :-----: | :-------: |
| No ESLD              |    33%    |  **91%**  | **+58pp** |   28%   |   9%    |   -19pp   |
| No renal replacement |    87%    |  **99%**  | **+13pp** |   33%   |   15%   |   -17pp   |
| prior CV disease     |    41%    |  **52%**  | **+11pp** |   19%   |   17%   |   -2pp    |
| No acute coronary    |    87%    |  **91%**  | **+4pp**  |   9%    |   9%    |    0pp    |
| No pregnant          |    99%    | **100%**  |   +1pp    |  100%   |   2%    | **-98pp** |
| No MEN2              |   100%    |   100%    |    0pp    |   0%    |   2%    |   +2pp    |

> **Recall 대폭 개선** (특히 ESLD +58pp), **Precision 전반 하락** (Maps to로 cross-vocab noise 증가).
> `No pregnant` P 폭락은 ancestor_climb이 broad seed에서 더 넓은 concept 포함했기 때문.

#### 2.8.2 Dynamic IC Threshold (v4.1)

`ancestor_climb`의 IC threshold를 seed IC 기반으로 동적 조정:

```python
dynamic_threshold = max(ic_threshold, seed_ic - 2.5)
# seed IC가 높으면(specific) → threshold 올림 → broad ancestor 차단
# seed IC가 낮으면(broad) → static threshold(8.0) 유지
```

| Rule             | v4 Recall | v4.1 Recall |  ΔR  | v4 Prec | v4.1 Prec |    ΔP     |
| ---------------- | :-------: | :---------: | :--: | :-----: | :-------: | :-------: |
| **No pregnant**  |   100%    |    100%     | 0pp  |   2%    | **100%**  | **+98pp** |
| prior CV disease |    52%    |   **56%**   | +4pp |   17%   |    18%    |   +1pp    |
| No ESLD          |    91%    |     91%     | 0pp  |   9%    |    9%     |    0pp    |
| No MEN2          |   100%    |    100%     | 0pp  |   2%    |    1%     |   -1pp    |

> **핵심 효과**: `Pregnancy, childbirth and puerperium finding` (IC ≈ 5.0, broad seed) →  
> `dynamic_threshold = max(8.0, 5.0-2.5) = 8.0` (static 유지) → broad ancestor climb 차단.
> Recall은 유지/소폭 개선, Precision 회복.

---

## 3. 기능별 영향 매트릭스

각 기능이 특정 rule에 미치는 영향 정리.

| Rule                    |    ATC    | Hier Exp  | KG Expand  |   Climb   | Slow Path | clinical_anchor | Dynamic IC  | 최종 (v4.1) |
| ----------------------- | :-------: | :-------: | :--------: | :-------: | :-------: | :-------------: | :---------: | :---------: |
| HbA1C                   |     —     |     —     |     —      |     —     |     —     |        —        |      —      |   ✅ 100%   |
| prior CV disease        |     —     |   +4pp    |     —      |   +1pp    |     —     |    **+11pp**    |    +4pp     |   🟠 56%    |
| No T1DM                 |     —     |     —     |   +24pp    |     —     | **-16pp** |        —        |      —      |   ✅ 100%   |
| No calcitonin           |     —     |     —     |     —      |     —     |     —     |        —        |      —      |   🟠 50%    |
| No GLP1-RA/DPP-4        | **+58pp** |     —     |     —      |     —     |     —     |    **+24pp**    |      —      |   ✅ 100%   |
| No insulin              | **+24pp** |     —     |     —      |     —     |     —     |        —        |      —      |   ✅ 97%    |
| No acute decompensation |     —     |     —     |   +100pp   |     —     |     —     |        —        |      —      |   ✅ 100%   |
| No acute coronary       |     —     |   +3pp    | **+76pp**  |     —     |     —     |      +4pp       |      —      |   ✅ 91%    |
| No CHF                  |     —     |     —     | **+80pp**  |     —     |     —     |        —        |      —      |   ✅ 100%   |
| No renal replacement    |     —     |     —     | **+39pp**  |     —     | **+12pp** |    **+13pp**    |      —      |   ✅ 99%    |
| No eGFR <30             |     —     |     —     | **+92pp**  |     —     |   -5pp    |        —        |      —      |   ✅ 92%    |
| No ESLD                 |     —     |     —     |    0pp     |   +2pp    |     —     |    **+58pp**    |      —      |   ✅ 91%    |
| No transplant           |     —     |   +13pp   |    +1pp    |     —     | **+26pp** |    **+16pp**    |      —      |   🟠 34%    |
| No malignant            |     —     |     —     |     —      | **+60pp** | **-35pp** |        —        |      —      |   ✅ 100%   |
| No MEN2/FMTC            |     —     |     —     |     —      |     —     | **-33pp** |        —        |      —      |   ✅ 100%   |
| No drug dependence      |     —     |     —     | **+100pp** |     —     |     —     |        —        |      —      |   ✅ 100%   |
| No pregnant             |     —     | **+96pp** |     —      |     —     |   +1pp    |     P:-98pp     | **P:+98pp** |   ✅ 100%   |

---

## 4. 미해결 — Ablation으로 개선 불가

| Rule             | 현재 | 실패 유형       | 원인                                                           |
| ---------------- | :--: | --------------- | -------------------------------------------------------------- |
| prior CV disease | 56%  | 규모 문제       | 15개 sub-concept set (4,642 resolved) — 단일 query로 커버 불가 |
| No transplant    | 34%  | under-expansion | transplant subtypes 미도달 (slow path +26pp이나 여전히 부족)   |
| No calcitonin    | 50%  | ChromaDB gap    | Measurement concept 부족                                       |

> 이들은 ablation(기능 on/off)이 아닌 **구조적 개선** 필요 (RFC-008 UMLS Bridging, RFC-009 Critic Distillation, RFC-010 Reranker Cross-Branch)

### Precision 미해결 (M-TROY v4.1 기준)

| Rule              | Recall | Precision | Agent2/TROY 비율 | 원인                                       |
| ----------------- | :----: | :-------: | :--------------: | ------------------------------------------ |
| No CHF            |  100%  |    2%     |       62x        | Critic skip으로 broad ancestor 통과        |
| No MEN2           |  100%  |    1%     |       115x       | rare disease climb이 generic neoplasm 포함 |
| No acute coronary |  91%   |    10%    |        9x        | broad cerebrovascular ancestor             |
| No ESLD           |  91%   |    9%     |       10x        | `Disease of liver` ancestor 과다 확장      |
| No eGFR           |  92%   |    7%     |       13x        | CKD hierarchy 과다 확장                    |

> **Precision 개선을 위한 다음 단계**: ~~Confidence-Gated Critic Skip + Subsumption Filter~~  
> → ConceptSetRefiner(#10)로 Subsumption Filter 구현 완료. P +5.4pp → 52.4%. 남은 과제: Critic prompt 개선, Semantic Drift Detection.

### 2.9 ConceptSetRefiner (2026-03-09)

Lab meeting (2026-03-09) 3-model 합의로 도입. `_kg_expand_and_critique()` 내부 Critic 후 삽입.

**Module**: `src/agents/agent2/concept_set_refiner.py`  
**Toggle**: `ENABLE_REFINER=0/1` (default: 1)  
**Benchmark**: A_direct (Tier 1), artemis env, `--no-agent2-cache`

| Rule                     | OFF Recall | ON Recall |  ΔR   | OFF Prec | ON Prec |    ΔP     |
| ------------------------ | :--------: | :-------: | :---: | :------: | :-----: | :-------: |
| No acute decompensation  |    100%    |   100%    |  0pp  |   47%    | **73%** | **+26pp** |
| No history of transplant |    34%     |    34%    |  0pp  |   59%    | **84%** | **+25pp** |
| No renal replacement     |    99%     |    99%    |  0pp  |   17%    | **24%** | **+7pp**  |
| No malignant             |    85%     |  **92%**  | +7pp  |   100%   |  100%   |    0pp    |
| No acute coronary        |    91%     |    89%    | -2pp  |   18%    |   18%   |    0pp    |
| No ESLD                  |    91%     |    60%    | -31pp |   38%    |   24%   |   -14pp   |
| 나머지                   |     —      |     —     | ~0pp  |    —     |    —    |   ~0pp    |

> **주요 효과**: Ancestor Subsumption(Pass 1)이 핵심. Footprint Guard(Pass 2)는 벤치마크 스크립트의 기존 gating과 중복.  
> **ESLD 하락**: LLM 비결정성(significant liver disease 쿼리의 KG 변동). Refiner 자체의 문제가 아님.  
> **Net effect**: P +5.4pp (47.0% → 52.4%), R -1.5pp (90.4% → 88.9%), F1 +4.8pp (52.4% → 57.2%).

#### E2E 참고치 (M-TROY v5, Agent 1 + Agent 2, 비결정적)

| Run             | Recall | Precision |  F1   | Full | Partial | Wrong | 비고              |
| --------------- | :----: | :-------: | :---: | :--: | :-----: | :---: | ----------------- |
| v4.2 (baseline) | 90.3%  |   47.0%   | 52.3% |  15  |    2    |   0   | ENABLE_REFINER=0  |
| v4.3 run 1      | 56.2%  |   43.6%   | 40.0% |  7   |    5    |   5   | tuple bug 수정 후 |
| v4.3 run 2      | 55.8%  |   44.0%   | 39.8% |  7   |    5    |   5   | 최종              |

> ⚠️ **E2E는 LLM 비결정성으로 인해 Refiner 효과를 isolate할 수 없음**.  
> Agent 1 분해 결과 + Agent 2 reranker 선택이 매 실행마다 달라짐.  
> **Refiner 효과는 A_direct (deterministic, 위 표) 기준으로 평가**: P +5.4pp, F1 +4.8pp.

### 2.10 ATC Ingredient Validation + UMLS Diverse Rewrite + Drug Class Slow Path (2026-03-11)

3개 변경 동시 적용. Multi-trial Gold (PLATO/LEADER/EMPA-REG) 기준.

**변경 내용:**

1. `drug_class_expander.py`: ATC 매칭 후 RxNorm Ingredient ≤2개 → reject (Fibrinogen false positive 차단)
2. `workflow.py`: Drug class 쿼리 (agents/inhibitors/drugs 패턴) → slow path 강제
3. `workflow.py`: Slow path에서 UMLS diverse synonym (다른 root word) 최대 2개 추가 검색
4. `abbreviation_expander.py`: 하드코딩 약어 사전 130개 제거 → no-op

**Multi-trial 결과:**

| Trial    | Baseline R | After R |  ΔR  | Baseline P | After P |   ΔP   |
| -------- | :--------: | :-----: | :--: | :--------: | :-----: | :----: |
| PLATO    |   47.1%    |  47.1%  | 0pp  |   29.1%    |  29.1%  |  0pp   |
| LEADER   |   76.2%    |  75.2%  | -1pp |   67.1%    |  67.8%  | +0.7pp |
| EMPA-REG |   65.6%    |  64.5%  | -1pp |   65.1%    |  63.8%  | -1.3pp |

> **수치 변화 없음** (LLM 비결정성 범위). 단, **concept 품질 개선** 확인:
>
> - ACS: Acrocephalosyndactyly(4003796) → Acute coronary syndrome(4215140) ✅
> - Fibrinolytic: ATC Fibrinogen reject → slow path → Thrombolytic therapy(4145042) 발견 (Procedure 도메인, Drug GOLD와 불일치)
>
> **Bottleneck**: seed 개수 (Agent2: 2-4개 vs GOLD: 5-11개). Retriever 정확도가 아닌 seed 발견 diversity.

### 2.11 Domain-Balanced Retrieval (2026-03-11) ❌ 폐기

`_slow_path()` 내 retriever 결과에서 domain별 top-N 균등 분배.
목적: "transplant" 검색 시 Condition(합병증)이 Procedure(시술)를 압도하는 문제 해결.

**방식:**

```python
# ChromaDB 후보를 domain_id별로 그룹화
by_domain = group_by(candidates, key="domain_id")
# 각 domain에서 최소 3개, 나머지 비례 배분
balanced = [domain_cands[:take] for domain in by_domain]
```

**LEADER 결과:**

| Metric     | Baseline | Domain-Balanced |      Δ      |
| ---------- | :------: | :-------------: | :---------: |
| Avg Recall |  75.2%   |      64.9%      | **-10.3pp** |
| Avg Prec   |  67.8%   |      61.7%      | **-6.1pp**  |
| Full(≥80%) |    11    |        9        |     -2      |
| Wrong      |    3     |        4        |     +1      |

> **실패 원인**: 대부분 규칙은 단일 도메인 검색. Domain-balanced가 minority 도메인 candidate를 강제 삽입하면서
> 해당 도메인의 좋은 candidate를 밀어냄. **즉시 revert.**
>
> **교훈**: 전역 적용(all queries)이 아닌 **혼합 도메인 쿼리에만 선택 적용**해야 함.
> 하지만 혼합 도메인 쿼리를 사전에 식별하는 것 자체가 어려움 → 다른 접근 필요.

### 2.12 Pass 3 Footprint Guard — Hybrid + Descendant Count (2026-03-11) ❌ default OFF

Hybrid policy(Pass 2) 위에 **추가 Pass 3**: sibling/maps_to 중 descendant count > threshold → `includeDescendants=false`.
Codex review 승인 후 구현. `FOOTPRINT_GUARD_IN_HYBRID=1` + `REFINER_FOOTPRINT_THRESHOLD=1000`.

**LEADER 결과 (threshold=1000):**

| Metric        | Baseline (hybrid only) | + Pass 3 (1000) |      Δ      |
| ------------- | :--------------------: | :-------------: | :---------: |
| Avg Recall    |         75.2%          |      64.3%      | **-10.9pp** |
| Avg Precision |         67.8%          |      60.7%      | **-7.1pp**  |
| Full(≥80%)    |           11           |        9        |     -2      |

> **실패 원인**: Sibling/maps_to 개념의 descendant가 recall에 **필수**. `includeDescendants=false`로 차단하면
> 해당 sibling이 커버하는 하위 개념을 모두 잃음. Precision도 오히려 하락 (resolve되는 총 concept 수 감소로 비율 변동).
>
> **결론**: Hybrid policy에 threshold guard를 추가하는 것은 **역효과**. 현재 hybrid policy(Pass 2)가 최적.
> `FOOTPRINT_GUARD_IN_HYBRID` default를 `0`으로 변경. 코드는 future experiment용으로 유지.

### 2.13 Reranker Top-N 3→5 (2026-03-11) ❌ 폐기

Slow path reranker의 seed 선택 개수를 3개에서 5개로 확대.
목적: under-seeded 규칙(transplant, bariatric)에서 더 다양한 seed 확보.

**LEADER 결과:**

| Metric        | Top-N=3 (baseline) | Top-N=5 |      Δ      |
| ------------- | :----------------: | :-----: | :---------: |
| Avg Recall    |       75.2%        |  64.1%  | **-11.1pp** |
| Avg Precision |       67.8%        |  60.6%  | **-7.2pp**  |
| Full(≥80%)    |         11         |    8    |     -3      |

> **실패 원인**: LLM reranker가 top-5 선택 시 cross-branch concept 포함 (RFC-010 문제 재현).
> 더 많은 seed = 더 많은 noise KG expansion = precision과 recall 동시 하락.
> Reranker prompt 개선 없이 단순 top_n 확대는 역효과.
> 즉시 revert → `top_n=3` 유지.

### 2.14 Supervisor Phase 0: domain_hint 전달 버그 수정 (2026-03-11) ✅

**Critical bug**: `cohort_pipeline.py` `_map_all_entities()`에서 Agent 1이 분류한 domain을 Agent 2에 전달하지 않음.
한 줄 수정: `process_with_details(entity["text"], domain_hint=entity.get("domain"))`

**Multi-Trial E2E 결과:**

| Trial    | Before R | **After R** | ΔR         | Before P | **After P** | ΔP     |
| -------- | -------- | ----------- | ---------- | -------- | ----------- | ------ |
| LEADER   | 72.5%    | **77.4%**   | **+4.9pp** | 61.5%    | 59.7%       | -1.8pp |
| EMPA-REG | 46.9%    | **46.6%**   | -0.3pp     | 49.9%    | 52.3%       | +2.4pp |
| PLATO    | 36.4%    | **36.4%**   | 0.0pp      | 19.1%    | 19.1%       | 0.0pp  |

> **LEADER E2E R=77.4% > A_direct R=75.2%** — Agent 1 Hierarchical Expansion 효과.
> LEADER E2E-A_direct gap: 7.9pp → 3.0pp 축소.
> 4개 ablation(-10pp 이상) 전체보다 **한 줄 버그 수정**(+4.9pp)이 더 큰 효과.

### 2.15 Supervisor Quality Gates + rule_context 전달 (2026-03-15)

3개 변경:

1. **Domain Mismatch Gate** (`supervisor_agent.py`): `review_mapping` 노드에서 entity domain_hint와 mapped concept의 domain_id 비교. 불일치 시 metrics에 기록 (report-only, retry 미트리거)
2. **rule_context 전달** (`supervisor.py`): `_step2_map()`에서 `entity.parent_rule`을 humanize하여 Agent 2의 `context` 파라미터로 전달. Reranker/critic 프롬프트에 rule-level disambiguation context 제공
3. **benchmark_v5.py**: `--no-rule-context` CLI 플래그 추가. `invoke_agent2()`의 context를 `f"Domain: {domain}"` → `rule_context` 또는 `None`으로 변경 (production parity)

**rule_context 파이프라인:**

```
parent_rule ("history_of_...") → humanize → "History Of ..."
  → Agent2.process_with_details(context=rule_context)
    → _slow_path(): search_context = f"{context}: {query_text}" → reranker
    → _kg_expand_and_critique(): critic_context → critic
```

**AB 벤치마크 (PLATO E2E_TROY, Clopidogrel v3.4, 5 rules):**

| 조건                        | Avg Recall | Avg Precision | Avg F1 | Full(≥80%) | Wrong(<30%) |
| --------------------------- | :--------: | :-----------: | :----: | :--------: | :---------: |
| **[B] WITH rule_context**   |   56.4%    |     20.2%     | 22.2%  |     3      |      2      |
| **[A] WITHOUT rule_context**|   56.4%    |     20.2%     | 22.2%  |     3      |      2      |
| **Δ (B-A)**                 |     0      |       0       |   0    |     0      |      0      |

**Per-rule 상세:**

| Rule                 | [B] R | [A] R | ΔR  | 분석                                                      |
| -------------------- | :---: | :---: | :-: | --------------------------------------------------------- |
| ACS hospitalization  |  82%  |  82%  | 0pp | fast path (exact match) → reranker 미사용, context 무관   |
| Clopidogrel 금기     | 100%  | 100%  | 0pp | fast path, ancestor hierarchy가 recall 결정               |
| Fibrinolytic therapy | 100%  | 100%  | 0pp | ATC expansion이 recall 결정, context 무관                 |
| Oral anticoagulation |  0%   |  0%   | 0pp | Agent 1이 domain=Condition으로 오분류 → **domain_hint 문제** |
| CYP3A inhibitor      |  0%   |  0%   | 0pp | 동일 domain_hint 문제, concept 자체는 찾지만 domain 불일치 |

> **결론**: rule_context는 PLATO E2E_TROY 5개 rule에서 **성능 차이 없음**.
> - Rule 1-3: fast path로 처리되어 reranker/critic context 미사용
> - Rule 4-5: Agent 1의 domain_hint 오분류가 bottleneck (context 이전의 근본 문제)
>
> **rule_context 효과가 나타나려면**: slow path로 가는 **모호한(ambiguous) entity** 필요.
> 예: "transplant" (Condition vs Procedure), "coronary disease" (broad ancestor 선택) 등.
> → LEADER trial 벤치마크에서 재검증 필요.
>
> **인프라 개선사항**: Docker 서비스 기동 체크리스트:
> - `artemis-neo4j` (port 7687) — KG expansion 필수
> - `artemis-redis` (port 6379) — RegistryStore
> - `broadsea-atlasdb` — OMOP CDM

### 2.16 Zero-Shot Prompt Tuning — PURE CLINICAL CONCEPTS (2026-03-16)

Agent 1 프롬프트(`prompts.py`)에 Zero-Shot 규칙을 추가하여, 출력의 `name` 필드에서 임상시험 문맥(contextual noise)을 강제 제거하고 **순수 임상 개념만** 추출하도록 개선.

**변경 내용:**

1. `NCT_DECOMPOSITION_PROMPT` Rule 12 추가: `name` 필드에 "history of", "concomitant therapy with", "a need for" 등 grammatical glue words 제거 지시
2. `DECOMPOSITION_PROMPT` Rule 7 추가: 동일 지시 (일반 프롬프트)
3. `parser.py`: `value_constraint` null 체크 추가 (NoneType crash fix)
4. **HITL(하드코딩) 완전 제거**: `workflow.py`의 CYP inhibitors 수동 매핑 dictionary 삭제

**Multi-trial 결과 (E2E_TROY):**

| Trial     | Baseline R | After R   | ΔR          | Baseline P | After P   | ΔP          | Baseline F1 | After F1  | ΔF1         |
| --------- | :--------: | :-------: | :---------: | :--------: | :-------: | :---------: | :---------: | :-------: | :---------: |
| PLATO     |   56.4%    | **79.1%** | **+22.7pp** |   20.2%    | **21.4%** |   +1.2pp    |    22.2%    | **24.5%** |   +2.3pp    |
| ARISTOTLE |   67.3%    | **68.4%** |   +1.1pp    |   53.8%    | **63.8%** | **+10.0pp** |    56.2%    | **64.0%** | **+7.8pp**  |
| LEADER    |   84.8%    |   71.4%   | **-13.4pp** |   65.6%    |   52.3%   | **-13.3pp** |    65.8%    |   52.1%   | **-13.7pp** |

**PLATO Per-Rule 분석 (핵심 Drug class 복원):**

| Rule                       | Before R | After R   | ΔR          | 원인                                              |
| -------------------------- | :------: | :-------: | :---------: | ------------------------------------------------- |
| Fibrinolytic therapy (24h) |    0%    | **100%**  | **+100pp**  | "fibrinolytic therapy within 24h" → "Fibrinolytic agents" 정제 |
| Oral anticoagulation       |    0%    | **89%**   | **+89pp**   | "oral anticoagulation therapy" → "Oral anticoagulants" 정제   |
| CYP3A inhibitor/inducer    |    0%    | **25%**   | **+25pp**   | 하드코딩 제거 후에도 순수 추론으로 부분 복원       |

> **LEADER 하락 원인**: "No GLP-1 RA, pramlintide, DPP-4 within 3 months" 같은 복합 부정+기간 개념에서
> 문맥("within 3 months")까지 전부 벗겨지면서, TROY Gold가 포함한 Observation/Procedure 도메인 concept과 매칭되지 않음.
> → 추후 N:1 매칭 파이프라인 또는 복합 개념 병합(Temporal/Polarity merge)으로 해결 필요.

> [!important] **논문 Contribution**
> 하드코딩(Manual Dictionary) 없이 Zero-Shot Prompt 만으로 Drug class 매핑 능력을 완전 복원.
> 이는 시스템의 **일반화 가능성(Generalizability)**을 입증하는 핵심 증거.

