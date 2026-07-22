# ARTEMIS Concept Mapping 벤치마크 종합 보고서

**Date**: 2026-03-04  
**Trial**: LEADER (Liraglutide vs Placebo, NCT01179048)  
**Gold Standard**: [TROY Liraglutide v3.4](../../data/sample/LEADER/%5BTROY%5D%20Liraglutide%20%28LEADER%29%20v3.4.json) (49 ConceptSets, 18 Rules)  
**Schema**: `synthea_cdm`

---

## 0. 핵심 변경 이력

> 실험 명명 규칙은 [EXPERIMENT_NAMING_CONVENTION.md](./EXPERIMENT_NAMING_CONVENTION.md) 참조.

### A → A' (Hierarchical Expansion)

원본 rule name을 Agent 1 분해 결과에 항상 포함. Broad ancestor query가 Specific sub-query의 gap을 보완.

- **No pregnant**: 4% → **100%** (+96pp) — "pregnant" 원본이 Pregnancy ancestor concept에 매칭
- **No transplant**: 4% → **17%** (+13pp) — 원본 "transplant"의 넓은 커버리지
- **prior CV disease**: 63% → **67%** (+4pp) — 원본 ancestor 추가 효과
- **Avg Recall**: 41.3% → **48.0%** (+6.7pp)

### A → D v2 (End-to-End + Drug Compound Split + N:1 Matching)

NCT + appendix 자동 파싱 + Drug compound split + N:1 per-group union TROY 매칭.

- **GLP1-RA/DPP-4**: 99% → **100%** — Drug compound split (`, or` 분리 → 개별 검색 → union)
- **Insulin**: 97% → **97%** — Drug compound split 동일 효과
- **prior CV disease**: 63% → **76%** (+13pp) — N:1 matching (12 Agent 1 rules 합산)
- **acute coronary**: 9% → **41%** (+32pp) — N:1 matching 효과
- **Avg Recall**: 41.3% → **61.1%** (+19.8pp, 전 실험 최고)

### D v2 → D v3 (Batch Optimization)

Agent 2 파이프라인 전체 배치/병렬 처리로 실행 시간 68% 단축 (20분 → 6분 12초).

- `_slow_path` UMLS synonym retriever 병렬화, `_slow_path_batch` UMLS+KG+Critic 전체 파이프라인 재구현
- `_kg_expand_and_critique` seed별 Neo4j 병렬화, KG 캐시 지연 쓰기
- `rerank_topn_batch` LLM 병렬 호출 추가
- **Recall**: 61.1% → 56.6% (-4.5pp) — `_slow_path_batch`에 KG+Critic 추가된 영향 + LLM non-determinism
- **실행 시간**: 20분 → **6분 12초** (-68%) 🎉

### D v3 → D v5 (Determinism + Agent 1 Cache)

Agent 2 `as_completed` 비결정성 버그 수정 + KG cache thread-safety + Agent 1 IR 캐시.

- `as_completed(futures)` → 순서 보존 리스트 (4개소) — candidate 순서 고정 → LLM reranker 결정적 ([ADR-016](../adr/ADR-016_ThreadPoolExecutor_Deterministic_Ordering.md))
- KG cache `threading.Lock` 추가 (read/write 모두 보호)
- `save_cache()` 호출 위치 정리 + `domain_hint` 누락 수정
- Agent 1 `parse_nct()` prompt hash 기반 IR 캐시 — Azure API `temperature=0 + seed=42`에서도 비결정적 → 캐시로 해결 ([ADR-017](../adr/ADR-017_Agent1_Role_Reduction.md))
- **Recall**: 56.6% → **57.5%** (+0.9pp, Agent 1 결정성 확보)
- **실행 시간**: 6분 12초 → **~8분** (캐시 HIT으로 Agent 1 즉시, Agent 2 미세 변동)

### M-TROY v2 → M-TROY v3 (Ancestor Climb + Full Transitive Neo4j)

Neo4j full transitive closure 재로딩 + IC-based ancestor climbing + SNOMED Disorder 필터.

- **Neo4j**: `sep BETWEEN 1 AND 3` → `sep >= 1` (full transitive, 19.57M rels, CSV bulk import 20초)
- ⚠️ 레거시 이름: A_direct v2/v3 → **M-TROY v2/v3** ([명명 규칙](./EXPERIMENT_NAMING_CONVENTION.md#5-레거시-이름--현재-이름-매핑))
- **ancestor_climb**: top-K union (single-best → all valid ancestors), Disorder class whitelist, SNOMED vocab filter
- **concept_id 타입**: CSV import로 string 저장 → Python str()/int() 변환 적용 (Codex 점검)
- **prior CV disease**: 40% → **TBD** (CV-only에서 +20.6pp 확인)
- **acute coronary**: 87% → **87%** (유지)
- **Avg Recall**: 79.3% → **83.1%** (+3.8pp) 🎉
- **Full(≥80%)**: 12 → **13** (+1)
- **Wrong(<30%)**: 1 → **1** (유지)
- → [ADR-018: Neo4j Full Transitive Closure](../adr/ADR-018_Neo4j_Full_Transitive_Closure.md)

### 미해결 (전 실험 공통 실패) — 파이프라인 추적 분석 (2026-03-02)

두 가지 근본적으로 다른 실패 유형이 존재한다:

**유형 1: 입력 source 부재** — `No pregnant` (R=0~4%)

- NCT JSON (1,039자), Main PDF, Appendix PDF 모두에서 "pregnant" 검색 **0건**
- LEADER trial 공개 문서에 pregnancy exclusion이 명시적으로 기술되지 않음
- Agent 1 입력에 없으므로 rule 자체 미생성 → **구조적 한계**, 자동화로 해결 불가
- Exp A'에서 100%인 이유: TROY rule name "No pregnant"를 직접 입력했기 때문

**유형 2: 의미론적 브릿징 실패** — `No acute decompensation` (R=0%)

- Agent 1: ✅ "Acute decompensation of glycemic control" rule 생성
- Agent 2: ✅ 12 raw → 180 resolved concepts 매핑
- TROY: `443727` (Diabetic ketoacidosis/DKA) + 8 descendants
- **Overlap = 0** — Agent 2의 180개 concept 중 DKA가 하나도 없음
- 원인: TROY 큐레이터의 **임상적 판단** (decompensation→DKA)을 텍스트 검색으로 브릿징 불가
- → [RFC-008 UMLS CUI Bridging](../rfc/RFC-008_UMLS_CUI_Bridging.md)

**기타:**

- **drug dependence**: 0% — Agent 1이 rule 자체를 미추출
- **calcitonin**: 0~50% — ChromaDB에 해당 Measurement concept 부족

## 1. 실험 개요

### 1.1 실험 명명 규칙

> 📌 **정식 명명 규칙 문서**: [EXPERIMENT_NAMING_CONVENTION.md](./EXPERIMENT_NAMING_CONVENTION.md)

|  계열   | 의미                                           | Agent1  | 입력 단위               |
| :-----: | ---------------------------------------------- | :-----: | ----------------------- |
|  **M**  | **Mapping direct** — CS name → Agent2 직접     | ❌ 없음 | Concept Set name (개별) |
|  **A**  | Agent1 경유 — rule name → Agent1 분해 → Agent2 | ✅ 사용 | Rule name (1개)         |
|  **D**  | End-to-End — NCT+PDF → Agent1 → Agent2         | ✅ 사용 | 논문 전체               |
| **B/C** | Design paper 기반 비교                         |    —    | Design paper criteria   |

**M 계열 variants** (Tier 1 Primary Benchmark):

| 실험명          | 입력 데이터                       | 파이프라인                    | 비고                |
| --------------- | --------------------------------- | ----------------------------- | ------------------- |
| **M-TROY**      | TROY v3.4 CS name (49개 개별)     | Agent2 + climb                | 전문가 약칭, 상한선 |
| **M-GOLD**      | GOLD CS name (18 rule 단위 merge) | Agent2 + climb                | v1.1+v3.4 최적 조합 |
| **M-SUPP**      | Supplement appendix 원문          | Agent2 + climb (auto routing) | 실전 시뮬레이션     |
| **M-SUPP-fast** | Supplement appendix 원문          | Agent2 fast path only         | Athena-only 매핑    |

> [!IMPORTANT]
> **M vs A의 핵심 차이**: M은 concept set name을 Agent2에 **직접** 입력 (Agent1 미사용).  
> A는 rule name을 Agent1이 **분해**한 후 Agent2에 전달. A'는 A + 원본 term 유지.

### 1.2 실험 목록

|  Exp  | Input                              | Pipeline                     | 측정 대상                             |
| :---: | ---------------------------------- | ---------------------------- | ------------------------------------- |
| **M** | CS name (TROY/GOLD/SUPP)           | Agent 2 직접                 | Agent 2 순수 매핑 — **Primary**       |
| **A** | TROY rule name (1줄씩)             | Agent 1 → Agent 2 +ATC       | Agent 1 분해 + Agent 2 매핑 결합      |
| **B** | Design paper (prebuilt Circe JSON) | 기생성 결과 비교             | 전체 파이프라인 과거 출력물           |
| **C** | Design paper criteria (38개)       | Agent 2 +ATC (domain gating) | Agent 2 매핑 + ATC expansion          |
| **D** | NCT + papers_dir (appendix)        | Agent 1 → Agent 2 +ATC       | **End-to-end** (compound split + N:1) |

> **Tier 1 (Mapping Accuracy)** — Agent 2 순수 매핑 평가:  
> M-TROY / M-GOLD / M-SUPP / M-SUPP-fast — **Primary Benchmark**  
> Exp A / A' — Agent 1 경유 비교군  
> Exp B / C — Design paper 비교군
>
> **Tier 2 (Emulation Accuracy)** — E2E 파이프라인 평가:  
> Exp D v2~v6: NCT + PDF → Agent 1 → Agent 2 → N:1 TROY 매칭
>
> Lab Meeting Decision (2026-03-02): [회의록](../lab_meetings/2026-03-02_benchmark_evaluation_strategy.md)

---

## 2. 전체 성능 비교

### Tier 1: Mapping Accuracy (Agent 2 순수 매핑)

| 지표              | **M-TROY+Hybrid** |  M-TROY  | **M-GOLD+Hybrid** | M-GOLD | **M-SUPP** | **M-SUPP-fast** | **A+Climb** |   A   | A' (hier) | B (prebuilt) | C (live+ATC) |
| ----------------- | :---------------: | :------: | :---------------: | :----: | :--------: | :-------------: | :---------: | :---: | :-------: | :----------: | :----------: |
| **Avg Recall**    |       81.5%       | 83.1% 🎉 |       79.6%       | 75.0%  |   60.4%    |      55.3%      |    53.8%    | 41.3% |   48.0%   |    58.4%     |    52.8%     |
| **Avg Precision** |   **74.0%** 🎉    |  53.3%   |     **67.3%**     | 56.6%  |   55.3%    |      56.0%      |    51.1%    | 61.5% |   56.8%   |    62.9%     |    50.1%     |
| **Avg F1**        |   **73.1%** 🎉    |  55.8%   |     **66.8%**     | 53.5%  |   45.4%    |      41.4%      |    42.2%    | 39.1% |   43.5%   |    52.0%     |    41.5%     |
| Full (≥80%)       |      **12**       |    13    |        11         |   11   |     7      |        6        |      4      |   4   |     5     |      5       |      5       |
| Partial (30-80%)  |         4         |    3     |         4         |   3    |     5      |        5        |      5      |   5   |     5     |      9       |      7       |
| Wrong (<30%)      |       **1**       |    1     |       **2**       |   3    |     5      |        6        |      8      |   8   |     7     |      3       |      5       |
| **⏱ 실행 시간**   |     **~10분**     |  ~10분   |      ~5.5분       | ~10분  |   ~20분    |      ~10분      |    ~20분    | ~20분 |   ~21분   |     N/A      |     ~8분     |

### Tier 2: Emulation Accuracy (E2E 파이프라인)

| 지표              | D v2 (NCT+split+N:1) | D v3 (batch) | D v5 (deterministic) | **D v6 (guardrail)** |
| ----------------- | :------------------: | :----------: | :------------------: | :------------------: |
| **Avg Recall**    |        61.1%         |    56.6%     |        57.5%         |      **53.5%**       |
| **Avg Precision** |        20.2%         |    32.8%     |        25.6%         |      **32.7%**       |
| **Avg F1**        |        24.8%         |    33.2%     |        28.6%         |      **36.6%**       |
| Full (≥80%)       |          5           |      5       |          5           |        **4**         |
| Wrong (<30%)      |          3           |      4       |          4           |        **5**         |
| **⏱ 실행 시간**   |        ~20분         |   6분 12초   |         ~8분         |       **~1분**       |

> M-TROY+Hybrid = M-TROY + includeDescendants hybrid policy (ancestors/climb→false). **P +20.7pp, F1 +17.3pp.**  
> M-GOLD+Hybrid = GOLD input + hybrid policy. **P +10.7pp, F1 +13.3pp.**  
> M-TROY = TROY v3.4 CS name → Agent 2 직접 + ancestor_climb. Agent 1 미사용 → 완전 결정적.  
> M-GOLD = GOLD CS name (v1.1+v3.4 merge) → Agent 2 직접 + climb.  
> D v6 = NCT+PDF → Agent 1 (IR 캐시) → Agent 2 + drug guardrail.

---

## 3. Per-Rule 비교 (R⏐P = Recall⏐Precision)

|  #  | TROY Rule            | TROY  | **M-TROY+Hybrid** |  **M-TROY**  |    M-GOLD    |   **M-SUPP**   | **M-SUPP-fast** | **A+Climb**  |
| :-: | -------------------- | :---: | :---------------: | :----------: | :----------: | :------------: | :-------------: | :----------: |
|  1  | HbA1C ≥ 7 %          |   1   |   ✅ 100%⏐100%    | ✅ 100%⏐100% | ✅ 100%⏐100% |  ✅ 100%⏐50%   |   ✅ 100%⏐50%   | ✅ 100%⏐50%  |
|  2  | prior CV disease     | 4,642 |    🟠 26%⏐28%     |  🟠 41%⏐19%  |  🟠 58%⏐43%  |   🟠 57%⏐43%   |   🟠 37%⏐42%    |  🟠 79%⏐47%  |
|  3  | No T1DM              |  25   |   ✅ 100%⏐100%    | ✅ 100%⏐100% | ❌ 19%⏐100%  |  ❌ 19%⏐100%   |   ❌ 19%⏐100%   |  🟠 76%⏐95%  |
|  4  | No calcitonin        |   2   |     🟠 50%⏐7%     |  🟠 50%⏐6%   |  🟠 50%⏐6%   |   🟠 50%⏐6%    |    🟠 50%⏐6%    |  🟠 50%⏐6%   |
|  5  | No GLP1-RA/DPP-4     | 3,310 |    ✅ 100%⏐74%    | ✅ 100%⏐74%  | ✅ 100%⏐74%  |  ✅ 100%⏐74%   |   ✅ 100%⏐74%   | ✅ 100%⏐71%  |
|  6  | No insulin           | 8,449 |    ✅ 97%⏐77%     |  ✅ 97%⏐77%  |  ✅ 97%⏐77%  |   ✅ 97%⏐77%   |   ✅ 97%⏐77%    |  ✅ 97%⏐77%  |
|  7  | No acute decomp.     |   8   |    ✅ 100%⏐92%    | ✅ 100%⏐62%  | ✅ 100%⏐62%  |  ❌ **0%⏐0%**  |  ❌ **0%⏐0%**   |   ❌ 0%⏐0%   |
|  8  | No acute coronary    |  876  |    ❌ 14%⏐12%     |  ✅ 87%⏐9%   |  ❌ 12%⏐39%  |   ❌ 16%⏐43%   |   ❌ 13%⏐42%    |  ❌ 12%⏐37%  |
|  9  | No CHF               |  164  |  ✅ 100%⏐**96%**  |  ✅ 100%⏐7%  |  ✅ 100%⏐7%  | ✅ **80%⏐98%** | ✅ **80%⏐98%**  |  ❌ 20%⏐91%  |
| 10  | No renal replacement |  126  |    ✅ 87%⏐39%     |  ✅ 87%⏐33%  |  ✅ 87%⏐33%  | 🟠 **59%⏐25%** | 🟠 **59%⏐25%**  |  🟠 48%⏐72%  |
| 11  | No eGFR <30          |  38   |  ✅ 95%⏐**86%**   | ✅ 100%⏐24%  | ✅ 100%⏐24%  |  ✅ 100%⏐24%   |   ✅ 100%⏐14%   |  ❌ 8%⏐33%   |
| 12  | No ESLD              |  770  |    🟠 60%⏐36%     |  🟠 33%⏐28%  |  🟠 31%⏐31%  |   🟠 33%⏐28%   |   🟠 32%⏐31%    |  ❌ 15%⏐48%  |
| 13  | No transplant        |  319  |    ❌ 18%⏐88%     |  ❌ 18%⏐88%  |  ❌ 20%⏐88%  |   ❌ 19%⏐92%   |   ❌ 19%⏐92%    | ❌ 17%⏐100%  |
| 14  | No malignant         | 5,310 |    ✅ 92%⏐100%    | ✅ 100%⏐100% | ✅ 100%⏐100% |  ✅ 92%⏐100%   |  ✅ 100%⏐100%   |  ✅ 95%⏐41%  |
| 15  | No MEN2/FMTC         |   6   |  ✅ 100%⏐**60%**  |  ✅ 100%⏐0%  |  ✅ 100%⏐0%  |   ✅ 100%⏐0%   |   ✅ 100%⏐0%    |  ✅ 100%⏐0%  |
| 16  | No drug dependence   |  241  |    ✅ 100%⏐80%    | ✅ 100%⏐80%  | ✅ 100%⏐81%  |  ✅ 100%⏐81%   | ❌ **29%⏐100%** |   ❌ 0%⏐0%   |
| 17  | No pregnant          | 2,253 |   ✅ 100%⏐100%    | ✅ 99%⏐100%  | ✅ 100%⏐100% | ❌ **5%⏐100%** | ❌ **5%⏐100%**  | ✅ 100%⏐100% |
|     | **Avg R⏐P**          |   —   |  **82%⏐74%** 🎉   | **83%⏐53%**  | **75%⏐57%**  |  **60%⏐55%**   |   **55%⏐56%**   | **54%⏐51%**  |
|     | **Avg F1**           |   —   |    **73%** 🎉     |   **56%**    |   **54%**    |    **45%**     |     **41%**     |   **42%**    |

> **M-TROY+Hybrid**: Precision **+20.7pp** (53→74%), Recall -1.6pp (83→82%). **F1 최고 73%** — 종합 최선.  
> **M-TROY→M-SUPP 주요 하락**: pregnant (99→5%), acute decomp (100→0%), CHF (100→80%), renal (87→59%)  
> **M-SUPP에서도 안정적**: HbA1c, GLP1-RA/DPP-4, insulin, eGFR, calcitonin, MEN2, ESLD, malignant  
> **P가 M-SUPP에서 오히려 높은 cases**: CHF (7→98%), coronary (9→43%), transplant (88→92%) — 좁은 검색이 precision 유리

### 3.1 Per-ConceptSet 비교 (M-TROY, Recall 중심)

> per-CS 비교에서 **Precision은 참고값**. Agent2는 rule 단위로 매핑하므로, multi-CS rule의 agent2 출력은 모든 CS의 합집합.  
> 따라서 개별 CS 기준 Precision은 인위적으로 낮아진다. **Recall만 유의미**.

|  #  | Rule                 | ConceptSet                    |  TROY | Recall  |
| :-: | -------------------- | ----------------------------- | ----: | :-----: |
|  1  | HbA1C ≥ 7%           | HbA1c                         |     1 | ✅ 100% |
|  2  | prior CV disease     | Myocardial Infarction (MI)    |   131 | ✅ 100% |
|  3  | prior CV disease     | Stroke, TIAs                  |    96 | 🟠 32%  |
|  4  | prior CV disease     | Revascularization_final       |   673 | ✅ 100% |
|  5  | prior CV disease     | arterial stenosis             |   352 | ✅ 91%  |
|  6  | prior CV disease     | Heart Failure (NYHA II-III)   |   131 | ✅ 100% |
|  7  | prior CV disease     | unstable angina               |    10 | ✅ 100% |
|  8  | prior CV disease     | ischemic heart disease        | 3,301 | ❌ 24%  |
|  9  | prior CV disease     | eGFR                          |     1 | ✅ 100% |
| 10  | prior CV disease     | Coronary artery disease       |    45 | ✅ 100% |
| 11  | prior CV disease     | microalbuminuria/proteinuria  |   128 |  ❌ 0%  |
| 12  | prior CV disease     | LV dysfunction                |     7 | ✅ 100% |
| 13  | prior CV disease     | hypertension                  |   142 | ✅ 99%  |
| 14  | prior CV disease     | LV hypertrophy                |     6 | ✅ 100% |
| 15  | prior CV disease     | PAD                           |   247 | ✅ 100% |
| 16  | prior CV disease     | intermittent claudication     |    12 | ✅ 100% |
| 17  | No T1DM              | Type 1 Diabetes Mellitus      |    25 | ✅ 100% |
| 18  | No calcitonin        | Calcitonin                    |     2 | 🟠 50%  |
| 19  | No GLP1-RA/DPP-4     | GLP-1 receptor agonists       | 1,386 | ✅ 100% |
| 20  | No GLP1-RA/DPP-4     | pramlintide                   |     1 |  ❌ 0%  |
| 21  | No GLP1-RA/DPP-4     | DPP4 inhibitors               | 1,923 | ✅ 100% |
| 22  | No insulin           | Insulin                       | 8,449 | ✅ 97%  |
| 23  | No acute decomp.     | diabetic ketoacidosis         |     8 | ✅ 100% |
| 24  | No acute coronary    | (acute) MI                    |   119 | 🟠 77%  |
| 25  | No acute coronary    | Stroke                        |    84 | ❌ 19%  |
| 26  | No acute coronary    | Revascularization_final       |   673 | ✅ 98%  |
| 27  | No CHF               | Oxygen therapy (NYHA IV)      |    33 | ✅ 100% |
| 28  | No CHF               | Heart Failure (NYHA II-III)   |   131 | ✅ 100% |
| 29  | No renal replacement | ESRD                          |    16 | ✅ 100% |
| 30  | No renal replacement | renal dialysis                |    60 | 🟠 75%  |
| 31  | No renal replacement | kidney transplant (cond)      |    37 | ✅ 95%  |
| 32  | No renal replacement | kidney transplant (proc)      |    13 | ✅ 100% |
| 33  | No eGFR <30          | eGFR                          |     3 | ✅ 100% |
| 34  | No eGFR <30          | CKD 4-5                       |    35 | ✅ 100% |
| 35  | No ESLD              | ESLD                          |   108 | 🟠 31%  |
| 36  | No ESLD              | Total bilirubin               |     1 | ✅ 100% |
| 37  | No ESLD              | liver disease_procedure       |     1 |  ❌ 0%  |
| 38  | No ESLD              | significant liver disease     |   708 | 🟠 33%  |
| 39  | No transplant        | organ transplant_cond         |   115 | 🟠 50%  |
| 40  | No transplant        | transplant_proc               |   204 |  ❌ 0%  |
| 41  | No malignant         | History of malignant neoplasm | 5,310 | ✅ 100% |
| 42  | No MEN2/FMTC         | MEN2                          |     4 | ✅ 100% |
| 43  | No MEN2/FMTC         | MTC                           |     2 | ✅ 100% |
| 44  | No drug dependence   | substance abuse               |   241 | ✅ 100% |
| 45  | No pregnant          | Pregnancy/childbirth finding  | 2,253 | ✅ 99%  |

> **요약**: 45 CS 중 Recall ≥80% = **33개** (73%), Recall <30% = **7개** (16%)  
> **주요 실패 CS**: ischemic heart disease (24%), microalbuminuria (0%), pramlintide (0%), transplant_proc (0%), liver disease_procedure (0%), Stroke (19%), Stroke TIAs (32%)

### 3.2 성능 계산 방법

#### Rule 단위 (§3)

```
TROY_resolved = TROY CS의 모든 concept items를 Circe 규칙대로 resolve
  - includeDescendants=true → concept_ancestor 테이블로 descendants 확장
  - isExcluded=true → 결과에서 제외
  - non-standard → 'Maps to' 관계로 standard 치환

Agent2_raw = Agent2가 반환한 concept_id 목록 (rule 내 모든 CS의 합집합)
Agent2_std = Agent2_raw 중 standard_concept='S'인 것만 필터
Agent2_resolved = Agent2_std + 해당 개념들의 descendants (concept_ancestor)

Recall    = |TROY_resolved ∩ Agent2_resolved| / |TROY_resolved|
Precision = |TROY_resolved ∩ Agent2_resolved| / |Agent2_resolved|
F1        = 2 × Recall × Precision / (Recall + Precision)
Avg       = 각 rule의 metric 산술 평균 (macro average)
```

#### ConceptSet 단위 (§3.1)

```
CS_resolved = 개별 ConceptSet의 items만 위와 동일하게 resolve (소속 rule과 무관)
Agent2_resolved = 해당 rule의 Agent2 전체 출력 (rule 내 모든 CS 합산)

CS_Recall = |CS_resolved ∩ Agent2_resolved| / |CS_resolved|
```

> [!WARNING]
> **Per-CS Precision은 보고하지 않음.** Agent2는 rule 단위로 query를 실행하므로,
> 개별 CS 기준 Precision은 분모가 rule 전체 Agent2 출력이 되어 의미가 없다.
> 예: prior CV disease rule → Agent2 출력 10,003개 vs HbA1c CS → TROY 1개 = Precision 0.01%

**데이터셋 정보:**

| 실험명          | 입력 파일                               | CS name 소스                         |            KG/Climb            | JSON 결과                               |
| --------------- | --------------------------------------- | ------------------------------------ | :----------------------------: | --------------------------------------- |
| **M-TROY**      | `[TROY] Liraglutide (LEADER) v3.4.json` | TROY 원본 약칭 (49 CS 개별)          | ✅ ancestor_climb + full Neo4j | `benchmark_a_direct_20260303_0128.json` |
| **M-GOLD**      | `LEADER_GOLD.json`                      | GOLD (v1.1+v3.4 merge, 18 rule 단위) |         ✅ climb 포함          | `benchmark_a_direct_20260303_2309.json` |
| **M-SUPP**      | `LEADER_GOLD_SUPP.json`                 | Supplement appendix 원문             |  ✅ climb 포함 (auto routing)  | `benchmark_a_direct_20260304_1640.json` |
| **M-SUPP-fast** | `LEADER_GOLD_SUPP.json`                 | Supplement appendix 원문             |       ❌ fast path only        | `benchmark_a_direct_20260304_1841.json` |

> [!NOTE]
> M-TROY v3(구 A_direct v3)는 TROY v3.4 (49 CS, 개별 concept set name 단위 입력)이고, M-GOLD(구 A_direct v2 GOLD)는 18 rule 단위로 정리된 concept set name 입력.  
> **GOLD + climb 조합 (M-TROY v3 상당)은 아직 미실행.**

---

## 4. 핵심 분석

### 4.1 ATC Expansion (RFC-006) — Drug Domain 결정적 개선

| Rule          | Without ATC (B) | With ATC (A/C) |   Delta   |
| ------------- | :-------------: | :------------: | :-------: |
| GLP1-RA/DPP-4 |       42%       |  **99-100%**   | **+58pp** |
| Insulin       |       73%       |    **97%**     | **+24pp** |

ATC ChromaDB (1,315건) → `concept_ancestor` → RxNorm Ingredients 경로가 Drug domain에서 결정적.  
→ [RFC-006: Vocabulary Based Drug Class Expansion](../rfc/RFC-006_Vocabulary_Based_Drug_Class_Expansion.md)

### 4.2 입력 상세도 효과 — Agent 1 분해 능력이 아닌 텍스트 품질

| Rule | A (축약) | B/C (상세) | 원인                               |
| ---- | :------: | :--------: | ---------------------------------- |
| CHF  |   20%    |    79%     | "No CHF" vs "Severe heart failure" |
| eGFR |    8%    |    100%    | 1개 rule vs CKD 4/5 분리           |

B/C가 높은 이유는 **design paper에 criteria가 이미 상세하게 기술**되어 있기 때문. Agent 1의 분해 능력이 아님.

### 4.3 Hierarchical Expansion 효과 (A' vs A)

| Rule           |  A  |    A'    |   Delta   | 원인                                                   |
| -------------- | :-: | :------: | :-------: | ------------------------------------------------------ |
| **Pregnancy**  | 4%  | **100%** | **+96pp** | "pregnant" → ancestor `4088927` → 2,253 desc 전부 커버 |
| Transplant     | 4%  |   17%    |   +13pp   | "transplant" 원본이 넓은 concept 매칭                  |
| CV disease     | 63% |   67%    |   +4pp    | 원본 "prior CV disease"가 ancestor 경로 추가 보완      |
| Acute coronary | 9%  |   12%    |   +3pp    | "acute coronary or cerebrovascular event" 원본 추가    |
| GLP1-RA        | 99% |   100%   |   +1pp    | 원본 compound query 추가                               |

**핵심 발견**: Agent 1이 "No pregnant"를 "Pregnancy"로 분해할 때, 원본 "pregnant"를 버리면 Agent 2가 좁은 concept(`4299535`, 112 desc)만 찾음. 원본을 유지하면 "pregnant" 검색이 넓은 ancestor concept(`4088927`, 2,253 desc)에 매칭되어 TROY와 100% 일치.

> [!IMPORTANT]
> **원본 term 유지는 비용 없이 recall을 개선하는 가장 효과적인 방법.**
> 분해된 하위 용어만 사용하면 OMOP hierarchy의 상위 ancestor가 커버하는 descendants를 놓친다.
> "넓은 그물(원본) + 좁은 그물(분해)" 합집합이 최적.

### 4.4 변하지 않는 한계 — Concept Granularity

| Rule      | 전 실험 R | TROY seed                | Agent 2 seed     | Gap                    |
| --------- | :-------: | ------------------------ | ---------------- | ---------------------- |
| ESLD      |    33%    | `4245975` 계층 상위 사용 | `4245975` 하위만 | ancestor climbing 필요 |
| Malignant |  36-40%   | 5,310 desc               | 2,118 desc       | 계층 부족              |

**해결 방향**: SNOMED keyword-based ancestor climbing  
→ [Domain Expansion Strategy](../issues/ISSUE_domain_expansion_strategy.md)

---

## 5. 도메인별 현황 및 개선 방향

| Domain          | Rules | 현재 Avg R | 전략                                                    |   상태    |
| --------------- | :---: | :--------: | ------------------------------------------------------- | :-------: |
| **Drug**        |   3   |  65-100%   | ATC ChromaDB expansion                                  |  ✅ 완료  |
| **Condition**   |   9   |  27-100%   | Hierarchical expansion (일부), SNOMED climbing (나머지) |  🔶 부분  |
| **Procedure**   |   2   |   0-49%    | SNOMED ancestor climbing                                | ❌ 미구현 |
| **Measurement** |   3   |   36-50%   | LOINC panel expansion                                   | ❌ 미구현 |

→ [Domain Expansion Strategy 상세](../issues/ISSUE_domain_expansion_strategy.md)

---

## 6. Known Issues

| Issue                               | 영향                   | 원인                                     | 해결 방향                 |                  상태                  |
| ----------------------------------- | ---------------------- | ---------------------------------------- | ------------------------- | :------------------------------------: |
| Agent 1 domain 오분류               | "drug dependence" R=0% | "drug" 포함 → `[Drug]` 태그 → ATC 오매칭 | 프롬프트 개선             |                   ❌                   |
| ~~Concept granularity (Pregnancy)~~ | ~~R=4%~~               | ~~ChromaDB 매칭이 좁은 concept~~         | ~~Ancestor climbing~~     | ✅ **Hierarchical expansion으로 해결** |
| CV disease 복합 criteria            | R=60-67%               | 15개 sub-category 중 일부만 커버         | Agent 1 분해 강화         |                   🔶                   |
| Calcitonin 0%                       | R=0%                   | Agent 2 concept 탐색 한계                | Measurement-specific 검색 |                   ❌                   |

→ [V5 Benchmark Known Issues](./BENCHMARK_V5_RESULTS.md#5-known-issues)

---

## 7. Related Documents

| 문서                                                                               | 내용                                                               |
| ---------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| [BENCHMARK_V5_RESULTS.md](./BENCHMARK_V5_RESULTS.md)                               | Exp A 상세 — 6단계 실험 이력, Agent 1 파싱 이슈, timing bottleneck |
| [BENCHMARK_DESIGN_PAPER_VS_TROY.md](./BENCHMARK_DESIGN_PAPER_VS_TROY.md)           | Exp B/C 비교 상세                                                  |
| [RFC-006](../rfc/RFC-006_Vocabulary_Based_Drug_Class_Expansion.md)                 | ATC ChromaDB drug class expansion 설계                             |
| [Domain Expansion Strategy](../issues/ISSUE_domain_expansion_strategy.md)          | 도메인별 concept 확장 전략 분석                                    |
| [Concept Mapping Ground Truth](../issues/ISSUE_no_concept_mapping_ground_truth.md) | TROY 비교 방법론                                                   |

### 데이터 파일

| 파일                                                      | 내용                                     |
| --------------------------------------------------------- | ---------------------------------------- |
| `output/benchmark_v5_20260228_1630.json`                  | Exp A 결과                               |
| `output/benchmark_v5_20260302_1550.json`                  | **Exp A' 결과 (hierarchical expansion)** |
| `output/benchmark_exp_d_v2_20260302_1404.json`            | **Exp D v2 결과**                        |
| `output/benchmark_exp_d_v2_20260302_1705.json`            | **Exp D v3 결과 (batch optimization)**   |
| `output/benchmark_design_paper_20260228_2102.json`        | Exp C 결과                               |
| `data/sample/LEADER/ARTEMIS_LEADER_design_paper_e2e.json` | Exp B 입력 (prebuilt Circe JSON)         |

### 스크립트

| 스크립트                             | 용도                                             |
| ------------------------------------ | ------------------------------------------------ |
| `scripts/benchmark_v5.py`            | Exp A/A' 실행 (A'는 hierarchical expansion 적용) |
| `/tmp/compare_artemis_troy.py`       | Exp B 비교                                       |
| `/tmp/benchmark_design_paper_e2e.py` | Exp C 실행                                       |

---

## 8. Multi-Document Enrichment (2026-03-01)

### 8.1 배경

Exp A/B/C 모두 **NCT registry + design paper 본문**만 사용. TROY의 18개 규칙 중 상당수는 **Supplementary Appendix**에만 있는 상세 criteria에서 유래. Agent 1의 입력 텍스트 품질이 benchmark 성능의 근본 병목.

### 8.2 구현 내용

| 변경                     | 파일             | 내용                                                                     |
| ------------------------ | ---------------- | ------------------------------------------------------------------------ |
| **NCT 파싱 수정**        | `nct_fetcher.py` | `_parse_items` regex — inline dash-separated criteria 분리               |
| **PDF enrichment**       | `parser.py`      | `_enrich_from_pdf` — pdftotext 기반 PDF → text → criteria 추출           |
| **papers_dir 자동 탐색** | `parser.py`      | `data/papers/{NCT_ID}/` 디렉토리 자동 발견, 다중 PDF 순회                |
| **섹션 추출**            | `parser.py`      | `_extract_eligibility_section` — eligibility 섹션만 정밀 추출 (TOC 스킵) |
| **프롬프트 완전성**      | `prompts.py`     | Rule #3: "COMPLETENESS IS MANDATORY — 모든 criterion별 개별 rule 필수"   |
| **Coverage check**       | `parser.py`      | 입력 criteria수 vs 출력 rules수 비교 경고                                |
| **Silent fallback 제거** | `parser.py`      | `_enrich_from_pubmed`에서 `warnings.warn` 명시적 사용                    |

### 8.3 디렉토리 구조

```
data/papers/
├── NCT01179048/  (LEADER)
│   ├── NEJMoa1603827.pdf           # main paper
│   └── nejmoa1603827_appendix.pdf  # supplementary ← eligibility criteria p.39
├── NCT01730534/  (DECLARE-TIMI 58)
│   ├── NEJMoa1812389.pdf
│   └── nejmoa1812389_appendix.pdf  # Section C: Study Eligibility Criteria
└── NCT01131676/  (EMPA-REG OUTCOME)
    ├── NEJMoa1504720.pdf
    └── nejmoa1504720_appendix.pdf  # Section D: Exclusion criteria
```

### 8.4 Enrichment Pipeline 결과 (LEADER)

```
NCT JSON:         4 inc,   3 exc
+Main paper:     13 inc, 144 exc   ← full-text fallback (no section heading)
+Appendix:       19 inc, 154 exc   ← section extraction (2,295 chars from 196K)
Agent 1 LLM IR:   8 inc,  13 exc = 21 rules
```

|    이전 (NCT only)     |   이후 (NCT + papers_dir)    |   TROY   |
| :--------------------: | :--------------------------: | :------: |
| 4 inc, 3 exc = 7 rules | 8 inc, 13 exc = **21 rules** | 18 rules |

### 8.5 새롭게 추출된 Criteria (Appendix 기여)

| 항목                         | Domain      | 이전 | 이후 |
| ---------------------------- | ----------- | :--: | :--: |
| eGFR < 60                    | Measurement |  ❌  |  ✅  |
| Calcitonin ≥ 50 ng/L         | Measurement |  ❌  |  ✅  |
| Microalbuminuria/Proteinuria | Measurement |  ❌  |  ✅  |
| Hypertension + LVH           | Condition   |  ❌  |  ✅  |
| ABI < 0.9                    | Measurement |  ❌  |  ✅  |
| Acute decompensation         | Condition   |  ❌  |  ✅  |
| Planned revascularization    | Procedure   |  ❌  |  ✅  |
| CHF NYHA IV                  | Condition   |  ❌  |  ✅  |
| Continuous renal replacement | Procedure   |  ❌  |  ✅  |
| End-stage liver disease      | Condition   |  ❌  |  ✅  |
| Solid organ transplant       | Condition   |  ❌  |  ✅  |
| Malignant neoplasm           | Condition   |  ❌  |  ✅  |
| MEN2/Medullary thyroid       | Condition   |  ❌  |  ✅  |

### 8.6 주요 기술 결정

1. **섹션 추출 vs 전체 파싱**: 전체 PDF 파싱 → 7,379 junk exclusion. 섹션 추출 → 154 정상 항목. TOC(목차) 스킵 로직으로 실제 본문 위치 탐지.
2. **Merge 전략**: main paper 먼저 → appendix 나중 (union + dedupe, 유사도 0.7 이상 중복 스킵).
3. **LLM 누락 방지**: 프롬프트에 "COMPLETENESS IS MANDATORY" 규칙 추가 → Calcitonin 복원됨.
4. **자동 vs 수동 다운로드**: NEJM/Lancet/JAMA paywall로 자동 다운로드 불가. `data/papers/{NCT_ID}/`에 수동 배치 후 자동 탐색.

→ [RFC-007: Multi-Document Enrichment](../rfc/RFC-007_Multi_Document_Enrichment.md)

---

## 9. Exp D v2 결과 분석 (2026-03-02)

### 9.1 실험 설계

- **Input**: NCT JSON + `data/papers/NCT01179048/` (main paper + appendix)
- **Agent 1**: Full IR 생성 (10 inclusion + 13 exclusion = 23 rules)
- **Agent 2**: 각 rule → concept mapping (+ATC, **Drug compound split**)
- **TROY 매칭**: **N:1 per-group union** (모든 Agent 1 rule이 각 TROY rule에 기여 가능)

### 9.2 v2 개선 내용 (Lab Meeting 합의)

|  #  | 개선                                                           | 효과                                                     |
| :-: | -------------------------------------------------------------- | -------------------------------------------------------- |
|  1  | **Drug compound split** — `, or` 분리 → 개별 sub-query → union | GLP1-RA 58→100%, Insulin 50→97%                          |
|  2  | **N:1 TROY matching** — 1:1 greedy 제거, per-group union       | CV disease 3→76%, acute coronary 14→41%                  |
|  3  | ~~ABSENCE/PRESENCE penalty~~                                   | **비활성화** — TROY InclusionRules 전부 Type=0 (ABSENCE) |

### 9.3 핵심 개선 (vs D v1 / Exp A)

| TROY Rule         |  A  | D v1 | **D v2** | 원인                       |
| ----------------- | :-: | :--: | :------: | -------------------------- |
| GLP1-RA/DPP-4     | 99% | 58%  | **100%** | 🎉 Drug compound split     |
| Insulin           | 97% | 50%  | **97%**  | 🎉 Drug compound split     |
| prior CV disease  | 63% |  3%  | **76%**  | 🎉 N:1 matching (12 rules) |
| acute coronary    | 9%  | 14%  | **41%**  | N:1 matching               |
| renal replacement | 48% | 48%  | **58%**  | N:1 개선                   |
| ESLD              | 33% | 33%  | **39%**  | N:1 개선                   |
| malignant         | 40% | 40%  | **43%**  | N:1 개선                   |
| transplant        | 4%  | 17%  | **24%**  | N:1 개선                   |

### 9.4 잔존 한계

- **Empty TROY 2개**: acute decompensation, drug dependence — Agent 2 concept이 TROY concept과 겹침 없음
- **No pregnant 4%**: concept granularity 문제 (Agent 2가 하위 concept, TROY가 상위 concept)
- **Precision 하락 (59.7→20.2%)**: N:1 union이 모든 Agent 1 concepts를 합산하므로 분모 증가
- **eGFR 21%**: measurement concept만 매칭, CKD stage condition 미포함

### 9.5 결론

Exp D v2는 **완전 자동화 end-to-end 파이프라인**으로 **Avg R=61.1%** 달성 — 4개 실험 중 **최고 Recall**. Drug compound split과 N:1 matching이 핵심 동력. Precision 하락은 union-based 매칭의 구조적 특성이며, recall-focused 평가에서는 유의미한 진전.

→ [Exp D v2 Report JSON](../../output/benchmark_exp_d_v2_20260302_1404.json)

---

## 10. Exp D v3/v4 — Agent 2 Batch Optimization + Determinism Fix (2026-03-02)

### 10.1 배치 최적화 변경 (v3)

Agent 2 파이프라인의 순차 병목 5개를 ThreadPoolExecutor 기반 병렬/배치 처리로 전환.

|  #  | 병목                             | 위치             | 변경                                                            |
| :-: | -------------------------------- | ---------------- | --------------------------------------------------------------- |
|  1  | `_slow_path` UMLS synonym search | `workflow.py`    | synonym별 순차 `retriever.search` → `ThreadPoolExecutor` 병렬   |
|  2  | `_slow_path_batch` 불완전        | `workflow.py`    | UMLS + `rerank_topn_batch` + KG + Critic 전체 파이프라인 재구현 |
|  3  | `_kg_expand_and_critique`        | `workflow.py`    | seed별 순차 `kg.expand()` → 병렬 + 캐시 지연 저장               |
|  4  | `process_batch` fast path        | `workflow.py`    | 순차 for 루프 → `ThreadPoolExecutor` 병렬                       |
|  5  | KG `_save_cache()`               | `kg_expander.py` | concept마다 디스크 쓰기 → 배치 완료 후 1회 저장                 |
|  6  | `rerank_topn_batch`              | `reranker.py`    | LangChain `.batch()` 병렬 LLM 호출 신규 추가                    |

### 10.2 `as_completed` 비결정성 버그 발견 및 수정 (v4)

초기 구현에서 `concurrent.futures.as_completed()`를 사용 → **완료 순서대로 결과 수집** → candidates 리스트 순서가 매 실행마다 변동 → reranker 프롬프트 텍스트 변경 → `temperature=0`이어도 **다른 seed concept 선택** → recall 대폭 변동.

```python
# ❌ as_completed: 비결정적 순서
for future in as_completed(futures):  # 먼저 끝나는 것부터
    candidates.extend(future.result())

# ✅ ordered list: 제출 순서 보존 (결정적)
futures = [pool.submit(fn, arg) for arg in args]
for future in futures:  # 제출 순서대로
    candidates.append(future.result())
```

추가로 Codex CLI 3회 리뷰를 통해 발견된 이슈 수정:

- KG cache `threading.Lock` 추가 (read/write 모두 보호)
- `save_cache()` 호출 위치 정리 (단건: 즉시, 배치: 완료 후 1회)
- `_slow_path_batch`에 `domain_hint` 전달 누락 수정
- silent `except: pass` → `logger.warning` 로깅 추가

→ [ADR-016: ThreadPoolExecutor Deterministic Ordering](../adr/ADR-016_ThreadPoolExecutor_Deterministic_Ordering.md)

### 10.3 결과

| 지표            |   D v2    | D v3 (batch) | D v4 (determinism fix) | **D v5 (+ Agent 1 cache)** |
| --------------- | :-------: | :----------: | :--------------------: | :------------------------: |
| Avg Recall      |   61.1%   |    56.6%     |         57.3%          |         **57.5%**          |
| Avg Precision   |   20.2%   |    32.8%     |         25.7%          |         **25.6%**          |
| Avg F1          |   24.8%   |    33.2%     |         28.7%          |         **28.6%**          |
| Full(≥80%)      |     5     |      5       |           5            |           **5**            |
| Wrong(<30%)     |     3     |      4       |           4            |           **4**            |
| **⏱ 실행 시간** | **~20분** | **6분 12초** |        **~8분**        |          **~8분**          |

> D v4→v5: Recall 57.3%→57.5% — Agent 2 LLM non-determinism에 의한 미세 차이. Agent 1 출력은 캐시로 고정됨 ✅

### 10.4 핵심 인사이트

1. **실행 시간 60% 이상 단축**: 벤치마크 반복 실험 용이성 대폭 개선 (20분→6~8분)
2. **Agent 2 내부 결정성 확보**: ordered futures로 동일 입력 → 동일 출력 보장
3. **Agent 1 비결정성 해결**: `temperature=0.0` + `seed=42`로도 Azure API가 비결정적 → prompt hash 기반 IR 캐시로 해결 ([ADR-017](../adr/ADR-017_Agent1_Role_Reduction.md))
4. **Agent 1 역할 축소 결정**: Data fetching(NCT/PubMed/PDF) 분리 → Agent 1은 IR 구성 + sub-criteria 분해만 담당

→ [Exp D v3 Report JSON](../../output/benchmark_exp_d_v2_20260302_1705.json)  
→ [Exp D v4 Report JSON](../../output/benchmark_exp_d_v2_20260302_1811.json)  
→ [Exp D v5 Report JSON](../../output/benchmark_exp_d_v2_20260302_1847.json)

---

## 11. Exp A' — Hierarchical Expansion (2026-03-02)

### 11.1 문제 정의

Exp A에서 Agent 1이 rule name을 분해할 때, **원본 term을 버리고 분해된 하위 용어만 Agent 2에 전달**하는 문제가 있었다. OMOP concept hierarchy 특성상, 넓은 상위 용어 1개가 descendants 확장을 통해 수천 개의 concept을 커버하는 반면, 구체적 하위 용어 여러 개는 각자의 좁은 subtree만 커버하여 합집합을 취해도 전체를 채우지 못한다.

```
예: "No pregnant"
  Agent 1 분해: "Pregnancy" (하위)
  Agent 2 매칭: concept 4299535 → 112 descendants → Recall 4%

  + 원본 유지: "pregnant" (상위)
  Agent 2 매칭: concept 4088927 → 2,253 descendants → Recall 100% ✅
```

### 11.2 변경 내용

[benchmark_v5.py](../../scripts/benchmark_v5.py)의 `invoke_agent1()` 함수에 **Hierarchical Expansion** 적용:

```python
# Agent 1이 분해한 sub-criteria에 원본 rule name이 없으면 자동 추가
decomposed_texts = {sc["entity_text"].lower() for sc in sub_criteria}
if clean_name.lower() not in decomposed_texts:
    sub_criteria.insert(0, {
        "entity_text": clean_name,
        "domain": primary_domain,
        "name": f"[ORIGINAL] {clean_name}",
    })
```

### 11.3 결과 요약

| 지표          | A (기존) | **A' (hier)** |   Delta    |
| ------------- | :------: | :-----------: | :--------: |
| Avg Recall    |  41.3%   |   **48.0%**   | **+6.7pp** |
| Avg Precision |  61.5%   |     56.6%     |   -4.9pp   |
| Avg F1        |  39.1%   |   **43.5%**   | **+4.4pp** |
| Full (≥80%)   |    4     |     **5**     |     +1     |
| Wrong (<30%)  |    8     |     **7**     |     -1     |

### 11.4 규칙별 변화

| Rule               |    A → A'     |   Delta   | 원인                                                 |
| ------------------ | :-----------: | :-------: | ---------------------------------------------------- |
| 🎉 **No pregnant** | 4% → **100%** | **+96pp** | "pregnant" → ancestor concept `4088927` (2,253 desc) |
| 🎉 No transplant   |   4% → 17%    |   +13pp   | "transplant" → wider procedure hierarchy             |
| CV disease         |   63% → 67%   |   +4pp    | "prior CV disease" → broader condition ancestor      |
| Acute coronary     |   9% → 12%    |   +3pp    | "acute coronary or cerebrovascular event" 원본       |
| GLP1-RA            |  99% → 100%   |   +1pp    | Compound query 원본 추가                             |
| 나머지 12개        |   변화 없음   |    0pp    | 원본과 분해 결과가 동일 ancestor에 매칭              |

### 11.5 핵심 인사이트

1. **Pregnancy 해결**: 이전까지 모든 실험(A/B/C/D)에서 4-13%로 "concept granularity 문제"로 분류되었던 것이, 단순히 **원본 term을 유지하는 것만으로 100% 해결됨**. SNOMED ancestor climbing 같은 복잡한 후처리 없이도, 원래 검색어가 올바른 계층의 concept에 직접 매칭되는 경우가 있다.

2. **비용 없는 개선**: Precision은 -4.9pp 하락하지만, 이는 추가 query에 의한 불가피한 noise. Recall 관점에서 +6.7pp 개선이 훨씬 가치 있음.

3. **원본 유지 원칙**: Agent 1이 criteria를 분해할 때, 원본 용어를 반드시 유지해야 한다. 분해 = 대체가 아니라 분해 = **확장**이어야 한다.

→ [Exp A' Report JSON](../../output/benchmark_v5_20260302_1550.json)

---

## 12. Ancestor Climb Variant 비교 (M-TROY v3, 2026-03-03)

Neo4j full transitive closure 로딩 후, ancestor_climb 통합 방식을 3가지 variant로 비교.

### 12.1 Variant 요약 비교

| 지표              | **C (기본)** | **B (kg↑)** | **A (2×Critic)** |
| ----------------- | :----------: | :---------: | :--------------: |
| **Avg Recall**    |    83.1%     |  **84.5%**  |      84.0%       |
| **Avg Precision** |  **53.3%**   |    48.1%    |      49.6%       |
| **Avg F1**        |  **55.8%**   |    50.2%    |      54.5%       |
| Full (≥80%)       |      13      |     13      |        13        |
| Partial (30-80%)  |      3       |      3      |        3         |
| Wrong (<30%)      |      1       |      1      |        1         |
| Critic 호출       |      1×      |     1×      |      **2×**      |
| kg_limit          |    15-40     |   **100**   |      15-40       |
| climb_limit       |     100      |     100     |       100        |

### 12.2 Variant C — 기본 (Combined Critic)

**ancestor_climb 진화 이력**:

| 단계                | 시기   |    ancestor_climb 함수     |              workflow 연결              | 데이터                                       | Avg Recall |
| ------------------- | ------ | :------------------------: | :-------------------------------------: | -------------------------------------------- | :--------: |
| **v0** (Exp A~D v1) | ~02-28 | ✅ `kg_expander.py`에 존재 |      ❌ 미연결 — `expand()`만 호출      | Neo4j sep 1-3 (1.2M rels)                    |   41~61%   |
| **v2** (M-TROY v2)  | 03-02  |          ✅ 존재           |     ✅ workflow Step 1b로 최초 연결     | Neo4j sep 1-3 (1.2M rels, 불완전)            |   79.3%    |
| **v3** (M-TROY v3)  | 03-03  |        ✅ 로직 개선        | ✅ 연결 + Disorder filter + top-K union | **Neo4j 전체** (19.57M rels) + PG desc_count | **83.1%**  |

> v0→v2: `_kg_expand_and_critique()`에 ancestor_climb 호출을 추가한 것 자체가 핵심 변경.  
> v2→v3: 함수가 의존하는 데이터(Neo4j graph 완전성)와 ancestor 선택 로직을 개선.

kg expand + ancestor_climb 결과를 합쳐서 하나의 Critic call로 평가.

**인프라**:

- **Neo4j**: `artemis-neo4j` (full transitive closure, `concept_ancestor` 전체 로딩)
  - 2.75M Concept nodes + 19.57M IS_ANCESTOR_OF rels
  - CSV bulk import (`neo4j-admin database import full`) — 20초
  - concept_id: string 타입 (CSV import 특성) → Python에서 `str()`/`int()` 변환
- **PostgreSQL**: descendant count 조회용 (IC 계산의 정확성 보장)

**2-Phase KG Pipeline** (`_kg_expand_and_critique`):

```
Phase 1a: KG Expansion (per seed, parallel)
  kg.expand(seed_id, mode="clinical", sep=3, limit=kg_limit)
  → descendants, siblings, maps_to

Phase 1b: Ancestor Climb (per seed, parallel, Condition/Procedure only)
  kg.ancestor_climb(seed_id, max_sep=3, ic_threshold=8.0, climb_limit=100)
  → IC 기반 ancestor 선택 → ancestor의 descendants 수집

Phase 2: LLM Critic (single call)
  critic.evaluate(query, seeds, expand+climb 합집합)
  → 관련 concept만 필터링
```

**Adaptive kg_limit** (Phase 1a):

| Domain               | kg_limit | 근거                                   |
| -------------------- | :------: | -------------------------------------- |
| Drug, Measurement    |    15    | 좁은 도메인: 특정 분자/검사            |
| Condition (seed ≤ 2) |    40    | 넓은 condition, 적은 seed → aggressive |
| 기타                 |    20    | 기본값                                 |

**Ancestor Climb 전략** (Phase 1b):

| 요소              | 설정                     | 설명                                                                   |
| ----------------- | ------------------------ | ---------------------------------------------------------------------- |
| max_sep           | 3                        | seed에서 최대 3 hop 상위                                               |
| IC threshold      | 8.0                      | Information Content ≥ 8.0인 ancestor만                                 |
| Vocab filter      | `SNOMED`                 | SNOMED vocabulary만 허용                                               |
| Class filter      | `Disorder`               | concept_class_id = 'Disorder'만 (Injury, Morphologic Abnormality 제외) |
| 선택 방식         | **Top-K union**          | single-best 대신 모든 valid ancestor의 descendants를 합집합            |
| 정렬              | min sep → max desc_count | 가까운 ancestor 중 broadest 우선                                       |
| climb_limit       | 100                      | ancestor당 최대 100 descendants                                        |
| desc_count source | PostgreSQL               | Neo4j 아닌 PG에서 정확한 descendant count 조회                         |

→ [ADR-018](../adr/ADR-018_Neo4j_Full_Transitive_Closure.md) | [workflow.py:412-516](../../src/agents/agent2/workflow.py) | [kg_expander.py](../../src/agents/agent2/kg_expander.py)

| TROY Rule               | TROY  | Recall  | Precision |  F1  |
| ----------------------- | :---: | :-----: | :-------: | :--: |
| HbA1C ≥ 7%              |   1   | ✅ 100% |   100%    | 100% |
| prior CV disease        | 4,642 | 🟠 41%  |    19%    | 26%  |
| No T1DM                 |  25   | ✅ 100% |   100%    | 100% |
| No calcitonin           |   2   | 🟠 50%  |    6%     | 11%  |
| No GLP1-RA/DPP-4        | 3,310 | ✅ 100% |    74%    | 85%  |
| No insulin              | 8,449 | ✅ 97%  |    77%    | 86%  |
| No acute decompensation |   8   | ✅ 100% |    62%    | 76%  |
| No acute coronary       |  876  | ✅ 87%  |    9%     | 17%  |
| No CHF                  |  164  | ✅ 100% |    7%     | 13%  |
| No renal replacement    |  126  | ✅ 87%  |    33%    | 47%  |
| No eGFR <30             |  38   | ✅ 100% |    24%    | 38%  |
| No ESLD                 |  770  | 🟠 33%  |    28%    | 30%  |
| No transplant           |  319  | ❌ 18%  |    88%    | 30%  |
| No malignant            | 5,310 | ✅ 100% |   100%    | 100% |
| No MEN2/FMTC            |   6   | ✅ 100% |    0%     |  0%  |
| No drug dependence      |  241  | ✅ 100% |    80%    | 89%  |
| No pregnant             | 2,253 | ✅ 99%  |   100%    | 99%  |

→ [C Report (JSON)](../../output/benchmark_a_direct_20260303_0128.json) | [**상세 리포트**](./BENCHMARK_A_DIRECT_V3_RESULTS.md)

### 12.3 Variant B — kg_limit=100

| TROY Rule               | TROY  |   Recall   | Precision |  F1  |   Δ vs C   |
| ----------------------- | :---: | :--------: | :-------: | :--: | :--------: |
| HbA1C ≥ 7%              |   1   |  ✅ 100%   |   100%    | 100% |     —      |
| prior CV disease        | 4,642 |   🟠 41%   |    30%    | 35%  |     P↑     |
| No T1DM                 |  25   |  ✅ 100%   |    52%    | 68%  |     P↓     |
| No calcitonin           |   2   |   🟠 50%   |    2%     |  3%  |    P↓↓     |
| No GLP1-RA/DPP-4        | 3,310 |  ✅ 100%   |    74%    | 85%  |     —      |
| No insulin              | 8,449 |   ✅ 97%   |    77%    | 86%  |     —      |
| No acute decompensation |   8   |  ✅ 100%   |   100%    | 100% |     P↑     |
| No acute coronary       |  876  |   ✅ 87%   |    18%    | 29%  |     P↑     |
| No CHF                  |  164  |  ✅ 100%   |    7%     | 13%  |     —      |
| No renal replacement    |  126  | ✅ **99%** |    22%    | 36%  | **R+12pp** |
| No eGFR <30             |  38   |  ✅ 100%   |    20%    | 34%  |     —      |
| No ESLD                 |  770  | 🟠 **62%** |    1%     |  3%  | **R+29pp** |
| No transplant           |  319  |   ❌ 18%   |    88%    | 30%  |     —      |
| No malignant            | 5,310 |   ✅ 98%   |   100%    | 99%  |   R-2pp    |
| No MEN2/FMTC            |   6   |   ✅ 83%   |    83%    | 83%  |   R-17pp   |
| No drug dependence      |  241  |  ✅ 100%   |    81%    | 89%  |     —      |
| No pregnant             | 2,253 |  ✅ 100%   |  **2%**   |  3%  |    P↓↓↓    |

→ [B Report](../../output/benchmark_a_direct_20260303_0921.json)

### 12.4 Variant A — 2× Critic

| TROY Rule               | TROY  |   Recall   | Precision |  F1  |   Δ vs C   |
| ----------------------- | :---: | :--------: | :-------: | :--: | :--------: |
| HbA1C ≥ 7%              |   1   |  ✅ 100%   |   100%    | 100% |     —      |
| prior CV disease        | 4,642 |   🟠 43%   |    19%    | 27%  |   R+2pp    |
| No T1DM                 |  25   |  ✅ 100%   |    52%    | 68%  |     P↓     |
| No calcitonin           |   2   |   🟠 50%   |    6%     | 11%  |     —      |
| No GLP1-RA/DPP-4        | 3,310 |  ✅ 100%   |    74%    | 85%  |     —      |
| No insulin              | 8,449 |   ✅ 97%   |    77%    | 86%  |     —      |
| No acute decompensation |   8   |  ✅ 100%   |    62%    | 76%  |     —      |
| No acute coronary       |  876  |   ✅ 87%   |    9%     | 17%  |     —      |
| No CHF                  |  164  |  ✅ 100%   |    7%     | 13%  |     —      |
| No renal replacement    |  126  |   ✅ 87%   |    33%    | 47%  |     —      |
| No eGFR <30             |  38   |  ✅ 100%   |    24%    | 38%  |     —      |
| No ESLD                 |  770  | 🟠 **46%** |    34%    | 39%  | **R+13pp** |
| No transplant           |  319  |   ❌ 19%   |    66%    | 30%  |   R+1pp    |
| No malignant            | 5,310 |  ✅ 100%   |   100%    | 100% |     —      |
| No MEN2/FMTC            |   6   |  ✅ 100%   |    0%     |  0%  |     —      |
| No drug dependence      |  241  |  ✅ 100%   |    80%    | 89%  |     —      |
| No pregnant             | 2,253 |   ✅ 99%   |   100%    | 99%  |     —      |

→ [A Report](../../output/benchmark_a_direct_20260303_0932.json)

### 12.5 핵심 분석

| 관점       |     Best      | 설명                                                   |
| ---------- | :-----------: | ------------------------------------------------------ |
| **Recall** | **B** (84.5%) | kg_limit↑ → ESLD +29pp, renal +12pp. Precision 큰 하락 |
| **F1**     | **C** (55.8%) | 균형 잡힌 recall/precision. 실무 기본값                |
| **ESLD**   |  **B** (62%)  | kg_limit↑으로 liver hierarchy 확대 커버                |
| **비용**   |     **C**     | Critic 1회. A는 2회로 latency/비용 2×                  |

**Codex 견해**: A가 recall 최선, C가 실무 안전 기본값. B는 Precision 희생이 큼.

**의사결정**: **C variant 유지** (현재 코드). ESLD/transplant 개선이 필요하면 rule-specific kg_limit 조절 검토.

### 12.6 실패 패턴 분석: Under-expansion vs Over-expansion

전 variant 공통으로 2가지 대조적 실패 유형이 관찰됨:

|                 | **No transplant** (R=18%, P=88%)                                                              | **No MEN2/FMTC** (R=100%, P=0%)                              |
| --------------- | --------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| **패턴**        | Under-expansion                                                                               | Over-expansion                                               |
| **수치**        | TROY=319, Agent2=65, Overlap=57                                                               | TROY=6, Agent2=5,597, Overlap=6                              |
| **문제**        | 못 찾음 (R↓)                                                                                  | 너무 많이 찾음 (P↓)                                          |
| **원인**        | KG hierarchy 탐색 부족 — transplant의 다양한 하위 유형(bone marrow, corneal, liver 등) 미도달 | ancestor_climb 폭발 — 6개만 필요한데 내분비 질환 전체로 확장 |
| **Cohort 영향** | 포함해야 할 환자 누락 (false inclusion)                                                       | 제외하면 안 될 환자 제외 (false exclusion)                   |
| **개선 방향**   | transplant-specific KG depth 확대                                                             | rare/small concept set은 climb 제한 또는 건너뛰기            |

> **핵심 인사이트**: TROY concept set **규모**가 전략 결정의 핵심 변수.
>
> - 소규모(≤10): climb 불필요 → seed descendants만으로 충분
> - 중규모(~300): hierarchy depth 확대 필요
> - 대규모(≥1000): 현재 전략 적합

---

## 13. M-TROY vs M-SUPP Evaluation (2026-03-04)

### 13.1 배경

Agent2 벤치마크(M 계열)에서 입력 텍스트의 소스가 성능에 미치는 영향을 정량화.

- **TROY**: 전문가 약칭 concept set name (`"ACS"`, `"DPP4 inhibitors"`, `"ESLD"`)
- **SUPP**: supplement appendix 원문 entity text (`"Acute coronary syndrome"`, `"DPP-4 inhibitor"`, `"End-stage liver disease"`)
- **SUPP fast**: SUPP + fast path only (no LLM reranking)

### 13.2 실험 설계

`LEADER_GOLD_SUPP.json` 생성: 56개 concept set name + 18개 rule name을 supplement 원문으로 교체. Concept IDs(정답)는 TROY 그대로.

| 실험            | 입력              | Routing   | 측정 대상                  |
| --------------- | ----------------- | --------- | -------------------------- |
| **M-TROY**      | TROY cs name      | Auto      | Agent2 상한선              |
| **M-SUPP**      | Supplement entity | Auto      | 실전 파이프라인 시뮬레이션 |
| **M-SUPP-fast** | Supplement entity | Fast only | Athena-only 매핑           |

### 13.3 결과

| 조건        |  Recall   | Precision |    F1     |  Full  | Partial | Wrong |
| ----------- | :-------: | :-------: | :-------: | :----: | :-----: | :---: |
| **M-TROY**  | **75.0%** |   56.6%   | **53.5%** | **11** |    3    |   3   |
| M-SUPP      |   60.4%   |   55.3%   |   45.4%   |   7    |    5    |   5   |
| M-SUPP-fast |   55.3%   |   56.0%   |   41.4%   |   6    |    5    |   6   |

### 13.4 Bottleneck 분해

| 비교                 |   ΔRecall   | 의미                            |
| -------------------- | :---------: | ------------------------------- |
| M-TROY → M-SUPP      | **-14.6pp** | 입력 텍스트 스타일 영향         |
| M-SUPP → M-SUPP-fast | **-5.1pp**  | Slow path (UMLS+reranking) 기여 |
| M-TROY → M-SUPP-fast | **-19.7pp** | 전체 gap                        |

### 13.5 핵심 발견

1. **전문가 용어 우위**: TROY 약칭이 OMOP vocabulary/ChromaDB와 더 잘 매칭 → Recall 14.6pp 유리
2. **Precision 불변**: M-TROY / M-SUPP / M-SUPP-fast 3조건 모두 55~56% → False positive은 입력 스타일 무관
3. **Slow path 기여 제한**: UMLS+reranking이 5.1pp만 추가 → 용어 표준화가 더 큰 레버
4. **논문 Contribution**: "자연어 기반 파이프라인은 terminology normalization 전략이 필요"

### 13.6 코드 변경

- `LEADER_GOLD_SUPP.json`: 56 CS + 18 rules supplement 원문 교체
- `workflow.py`: `FORCE_FAST_PATH` 환경변수 추가

→ [Lab Meeting](../lab_meetings/2026-03-04_troy_vs_supp_evaluation.md) | [SUPP Report](../../output/benchmark_a_direct_20260304_1640.json) | [SUPP fast Report](../../output/benchmark_a_direct_20260304_1841.json)

---

## 14. Exp D v6 — Precision Recovery (2026-03-04)

### 14.1 문제

ADR-020 (main paper skip) 적용 후 Agent1이 broad drug entity_text 생성 → Agent2 over-expand → Precision 급락 (39.8% → 26.0%).

### 14.2 변경 사항

| 변경                                      | 파일         | 효과                 |
| ----------------------------------------- | ------------ | -------------------- |
| `_normalize_drug_entity_text()` guardrail | `parser.py`  | 괄호/vague 표현 제거 |
| Rule #11 verbatim preservation            | `prompts.py` | Drug name 보존 지침  |

### 14.3 결과

| 지표             | D v5 (before) | main skip only | **D v6 (+guardrail)** |
| ---------------- | :-----------: | :------------: | :-------------------: |
| Recall           |     57.5%     |     55.4%      |       **53.5%**       |
| **Precision**    |     25.6%     |     26.0%      |  **32.7% (+6.7pp)**   |
| **F1**           |     28.6%     |     28.6%      |  **36.6% (+8.0pp)**   |
| Insulin resolved |    10,638     |    138,964     |       **6,258**       |

→ [Daily Note](../daily/2026-03-04.md) | [Lab Meeting](../lab_meetings/2026-03-04_exp_d_precision_recovery.md)

---

## 15. includeDescendants Hybrid Policy (2026-03-10)

### 15.1 문제

M-TROY v4.3(ConceptSetRefiner) 기준 Precision 52.4%가 한계. 주원인: KG expansion으로 추가된 ancestor/ancestor_climb concept이 `includeDescendants=true`로 descendants까지 확장되어 과다 생성.

### 15.2 접근: Relationship-aware Hybrid Policy

`concept_set_refiner.py` Pass 2 로직 변경:

| Relationship       | includeDescendants | 근거                               |
| ------------------ | :----------------: | ---------------------------------- |
| seed               |        true        | 원본 seed — granularity 보존       |
| sibling            |        true        | seed와 같은 세밀도                 |
| maps_to            |        true        | cross-vocab 매핑, 동일 granularity |
| **ancestor**       |     **false**      | broader → descendants 폭발 원인    |
| **ancestor_climb** |     **false**      | broader → descendants 폭발 원인    |

### 15.3 3-way Ablation 결과

| #        | Policy                             | Avg Recall | Avg Precision | Avg F1    | 상태                      |
| :------- | :--------------------------------- | :--------- | :------------ | :-------- | :------------------------ |
| #11      | seeds-only (ALL non-seed→false)    | 72.4%      | 72.8%         | 66.3%     | ❌ 폐기 (R -16.5pp)       |
| **#11a** | **hybrid (ancestors/climb→false)** | **81.5%**  | **74.0%**     | **73.1%** | ✅ **채택**               |
| #11b     | + ancestor 1-hop limit             | 81.5%      | 70.9%         | 69.5%     | ❌ revert (additive 없음) |

### 15.4 주요 규칙별 변화 (vs M-TROY v4.3 baseline, P=52.4%)

| Rule              | R before | R after | P before | P after | 분석                                        |
| :---------------- | :------- | :------ | :------- | :------ | :------------------------------------------ |
| No CHF            | 100%     | 100%    | 6%       | **96%** | ancestor broad 차단 → descendants 대폭 감소 |
| No eGFR           | 100%     | 95%     | 7%       | **86%** | 동일 패턴                                   |
| No MEN2           | 100%     | 100%    | 0%       | **60%** | rare disease의 generic ancestor 차단        |
| No acute decomp.  | 100%     | 100%    | 47%      | **92%** | Precision 회복                              |
| prior CV disease  | 41%      | **26%** | 19%      | 28%     | ⚠️ R 하락 — Revascularization seed 부족     |
| No acute coronary | 87%      | **14%** | 9%       | 12%     | ⚠️ R 하락 — Stroke/Revasc 등 ancestor 차단  |

### 15.5 남은 문제 (low recall)

| Rule              | Recall | 근본 원인                                                    | 개선 방향                      |
| :---------------- | :----- | :----------------------------------------------------------- | :----------------------------- |
| prior CV disease  | 26%    | 15개 sub-query 중 Revascularization 등 Procedure seed 미발견 | Fix A: Procedure ancestor 예외 |
| No acute coronary | 14%    | broad cerebrovascular ancestor 차단으로 stroke 계열 손실     | Fix B: Top-N 확대 (3→5)        |

→ [Lab Meeting](../lab_meetings/2026-03-10_low_recall_cv_coronary.md) | [Ablation Study #11a](./ABLATION_STUDY.md) | [Daily Note](../daily_notes/2026-03-10_include_descendants_policy.md)
