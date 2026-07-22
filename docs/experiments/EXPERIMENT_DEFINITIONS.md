# ARTEMIS 실험 기준 및 파이프라인 정의

## 1. 실제 파이프라인 (Production)

```
NCT ID (e.g., NCT01179048)
  │
  ▼
┌─────────────── Agent 1 (Trial Agent) ───────────────┐
│ parse_nct(nct_id)                                    │
│   1. nct_fetcher.py: ClinicalTrials.gov API v2 fetch │
│      → eligibility criteria 텍스트 추출              │
│   2. enricher.py: PubMed abstract enrich             │
│   3. _enrich_from_pdf(): supplement/design paper PDF │
│      → data/papers/{NCT_ID}/ 에서 자동 발견          │
│   4. LLM (NCT_SYSTEM_PROMPT) → ARTEMISRequest IR    │
│      → 캐시: data/cache/agent1_ir/{NCT}_{hash}.json  │
└─────────────────────────────────────────────────────┘
  │
  ▼  IR: inclusion_rules[] + exclusion_rules[]
     각 rule에 entity_text, domain, sub_criteria 포함
  │
  ▼
┌──────────── Agent 2 (Mapping Agent) ─────────────┐
│ 각 criterion/sub_criterion별로:                   │
│   1. UMLS synonym expansion (mrconso.sqlite)     │
│      + MRSTY domain filtering                    │
│   2. ChromaDB vector retrieval → candidates      │
│   3. LLM reranker → top seeds                    │
│   4. KG expansion (Neo4j) → ancestors/siblings   │
│   5. LLM Critic → final concept selection        │
│   6. ConceptSetRefiner → overbroad gating        │
│                                                   │
│ Output: concept_ids[] + overbroad_concept_ids[]  │
└──────────────────────────────────────────────────┘
  │
  ▼
┌────── Agent 3 (Assembler) ──────┐
│ Circe JSON 조립                  │
│ overbroad → includeDescendants=f │
└─────────────────────────────────┘
```

### 주요 코드 위치

| 모듈             | 파일                                         | 역할                           |
| :--------------- | :------------------------------------------- | :----------------------------- |
| NCT Fetcher      | `src/agents/agent1/nct_fetcher.py`           | ClinicalTrials.gov API fetch   |
| Enricher         | `src/agents/agent1/enricher.py`              | PubMed/PDF criteria enrich     |
| Trial Parser     | `src/agents/agent1/parser.py`                | `parse_nct()`, `parse()`       |
| Mapping Workflow | `src/agents/agent2/workflow.py`              | Agent 2 전체 흐름              |
| UMLS Expander    | `src/agents/agent2/umls_synonym_expander.py` | UMLS synonym + MRSTY filter    |
| Drug Class       | `src/agents/agent2/drug_class_expander.py`   | MRREL/ATC drug class expansion |
| Refiner          | `src/agents/agent2/concept_set_refiner.py`   | includeDescendants 정책        |
| Assembler        | `src/agents/agent3/assembler.py`             | Circe JSON 조립                |

---

## 2. 벤치마크 실험 분류

### Gold Standard (정답)

TROY Circe JSON을 `resolve_concept_set()`으로 풀어낸 concept 집합.

- `includeDescendants`, `isExcluded` 플래그를 Circe 스펙대로 적용
- Non-standard → standard 매핑 포함

### Tier 1: A_direct (Agent 2 단독)

Agent 1 건너뛰고, TROY concept_set_name을 Agent 2에 직접 전달.

```
TROY concept_set_name (e.g., "ESLD", "insulin")
  → Agent 2 → concept_ids
  → resolve_concept_set() → 비교
```

- **스크립트**: `scripts/benchmark_a_direct.py`
- **측정 대상**: Agent 2의 vocabulary retrieval 성능만
- **입력 예시**: `"ESLD"`, `"insulin"`, `"DPP4 inhibitors"`

### Tier 2: E2E_TROY (Agent 1 + Agent 2, 힌트 포함)

TROY rule name + concept_set_name 힌트를 Agent 1에 전달.

```
"rule_name: cs_name1, cs_name2, ..."
  → Agent 1 (parse) → sub-criteria
  → Agent 2 → concept_ids
  → resolve_concept_set() → 비교
```

- **스크립트**: `scripts/benchmark_v5.py`
- **주의**: TROY concept_set_name이 입력에 포함되므로 **정답 leak**. 낙관적 지표.
- **입력 예시**: `"No ESLD: ESLD, Total bilirubin, liver disease_procedure"`

### Tier 3: E2E_SUPP (실제 파이프라인, 정보 leak 없음)

NCT ID로 실제 파이프라인을 실행. Agent 1이 NCT API + supplement에서 criteria 추출.

```
NCT ID (e.g., NCT01179048)
  → Agent 1 parse_nct() → IR (inclusion/exclusion rules)
  → 각 rule → Agent 2 → concept_ids
  → N:1 TROY matching (IR rule ↔ TROY rule 매칭)
  → resolve_concept_set() → 비교
```

- **스크립트**: `scripts/benchmark_exp_d.py --troy GOLD.json --nct-id NCT01179048`
- **측정 대상**: 실제 파이프라인 성능. **가장 현실적 지표**.
- **입력**: NCT ID만. papers는 `data/papers/{NCT_ID}/`에서 자동 발견.
- **N:1 매칭**: Agent 1의 IR rule 1개가 TROY rule 여러개에 걸칠 수 있음 → `full_union` 또는 `overlap_density` 전략 사용.

---

## 3. 데이터 파일

| Trial    | NCT ID      | GOLD JSON                               | Papers                        | SUPP Mapping                       |
| :------- | :---------- | :-------------------------------------- | :---------------------------- | :--------------------------------- |
| LEADER   | NCT01179048 | `data/gold/LEADER/LEADER_GOLD.json`     | `data/papers/NCT01179048/` ✅ | `agent1_troy_mapping_supp.json` ✅ |
| EMPA-REG | NCT01131676 | `data/gold/EMPA-REG/EMPA_REG_GOLD.json` | `data/papers/NCT01131676/` ✅ | `agent1_troy_mapping_supp.json` ✅ |
| PLATO    | NCT00391872 | `data/gold/PLATO/PLATO_GOLD.json`       | `data/papers/NCT00391872/` ✅ | `agent1_troy_mapping_supp.json` ✅ |

### 파일 설명

- **GOLD JSON**: TROY v3.4 기반 Circe JSON. 벤치마크 정답.
- **Papers**: NEJM design paper + appendix/supplement PDF. `parse_nct()`가 auto-discover.
- **SUPP Mapping**: NCT criteria 원문 → TROY concept_set_name 수동 매핑. `benchmark_exp_d.py`의 `--explicit-mapping` 옵션에 사용.

---

## 4. 주의사항 및 교훈

### Agent 1의 두 가지 메서드

| 메서드                     | 용도                | 입력        | 기능                                   |
| :------------------------- | :------------------ | :---------- | :------------------------------------- |
| `agent1.parse(text)`       | 텍스트 분해만       | 자유 텍스트 | LLM으로 sub-criteria 분해              |
| `agent1.parse_nct(nct_id)` | **실제 파이프라인** | NCT ID      | NCT API + PubMed + PDF enrich + LLM IR |

- `benchmark_v5.py`는 `parse()`만 사용 → E2E_TROY, E2E에 해당
- `benchmark_exp_d.py`는 `parse_nct()`를 사용 → **E2E_SUPP에 해당**

### E2E_SUPP의 IR↔TROY 매칭 문제

`parse_nct()`는 **전체 trial criteria를 한번에** IR로 변환. 이 IR의 rule과 TROY rule이 1:1로 대응하지 않음.

- 예: IR `"High cardiovascular risk"` 1개 → TROY `"prior CV disease"` 내 8개 concept set에 분산
- 해결: N:1 매칭 (`full_union` 전략) + 수동 매핑 파일 (`agent1_troy_mapping_supp.json`)

### benchmark_v5.py `--supp` 플래그의 한계

`--supp` 플래그는 `parse()`에서 CS name 힌트만 제거 — TROY rule name을 그대로 입력으로 사용. 이것은 **진짜 E2E_SUPP가 아님**. 실제 E2E_SUPP는 반드시 `benchmark_exp_d.py`를 사용.

---

## 5. 최신 성능 (2026-03-14)

### A_direct

| Trial    | R     | P     | F1    |
| :------- | :---- | :---- | :---- |
| LEADER   | 63.3% | 61.0% | 57.3% |
| EMPA-REG | 53.4% | 60.4% | 52.4% |
| PLATO    | 57.7% | 13.9% | 19.0% |

### E2E_TROY

| Trial    | R     | P     | F1    |
| :------- | :---- | :---- | :---- |
| LEADER   | 75.8% | 58.3% | 54.6% |
| EMPA-REG | 46.6% | 54.0% | 39.2% |
| PLATO    | 56.4% | 20.2% | 22.2% |

### E2E_SUPP (`benchmark_exp_d.py`)

| Trial    | Eval | Empty | R     | P     | F1    |
| :------- | :--- | :---- | :---- | :---- | :---- |
| LEADER   | 14   | 3     | 36.3% | 57.2% | 31.7% |
| EMPA-REG | 11   | 2     | 24.8% | 21.7% | 16.8% |
| PLATO    | 1    | 4     | 41.2% | 79.2% | 54.2% |

> PLATO: 5개 TROY rule 중 4개 empty (N:1 매칭 실패). ACS rule만 평가됨.

---

## 6. E2E_SUPP Regression 분석 (2026-03-14)

### 문제

이전(03-02) Exp D v2 LEADER R=61.1% → 현재(03-14) R=36.3% (**-24.8pp**)

### Ablation: Agent 1 vs Agent 2 원인 분리

OLD IR 캐시(`e57e`, 03-02, 28 rules)를 현재 Agent 2 코드에 넣어 실행하여 원인 분리:

| 실험         | Agent 1 IR         | Agent 2 코드 | R         | P         | 결론               |
| :----------- | :----------------- | :----------- | :-------- | :-------- | :----------------- |
| 이전 (03-02) | OLD (28 rules)     | OLD          | **61.1%** | 20.2%     | baseline           |
| **ablation** | **OLD (28 rules)** | **현재**     | **37.6%** | **65.1%** | **Agent 2가 원인** |
| 현재 (03-14) | NEW (30 rules)     | 현재         | 36.3%     | 57.2%     |                    |

- OLD→NEW IR 차이: **1.3pp** → Agent 1 변경은 거의 무관
- OLD→현재 Agent 2 차이: **-23.5pp R, +44.9pp P** → **Agent 2 코드 변경이 주 원인**

### 원인: Agent 2의 Precision 최적화가 Recall을 trade-off

03-02 이후 적용된 Agent 2 변경사항:

| 변경                             | 날짜   | 효과                                             |
| :------------------------------- | :----- | :----------------------------------------------- |
| MRSTY semantic type 필터링       | 03-13  | 무관한 domain concept 제거 → R↓ P↑               |
| Drug domain ancestor gating skip | 03-14  | Drug의 overbroad gating 완화 → 일부 R 복원       |
| ConceptSetRefiner overbroad 정책 | 03-09~ | 넓은 concept에 includeDescendants=false → R↓ P↑  |
| Neo4j v2 migration               | 03-03~ | KG expansion 경로 변경, IS_A/MAPS_TO 관계 미존재 |

### Per-Rule Deep Dive (LEADER, OLD vs NEW Agent 2)

| Rule                 | OLD R | NEW R | Δ         | 패턴                           |
| :------------------- | :---- | :---- | :-------- | :----------------------------- |
| No T1DM              | 100%  | 19%   | -81pp     | Agent 2가 좁은 concept만 반환  |
| No GLP1-RA/DPP-4     | 100%  | 42%   | -58pp     | Drug class expansion 범위 축소 |
| No calcitonin        | 50%   | 0%    | -50pp     | Measurement KG expansion 약화  |
| No renal replacement | 58%   | 8%    | -50pp     | Procedure descendants 축소     |
| No CHF               | 40%   | 4%    | -36pp     | N:1 contributor 감소 (3→1)     |
| No ESLD              | 39%   | 8%    | -31pp     | N:1 contributor 감소 (4→1)     |
| HbA1c                | 50%   | 100%  | **+50pp** | 📈 개선                        |
| No malignant         | 43%   | 92%   | **+49pp** | 📈 개선                        |

### Agent 1 IR 캐시 이력 (NCT01179048)

| 캐시 hash | 생성일      | Rules | 해당 실험           |
| :-------- | :---------- | :---- | :------------------ |
| `e57e...` | 03-02       | 28    | Exp D v2 (R=61.1%)  |
| `e4c0...` | 03-04 00:13 | 19    | enricher 로직 변경  |
| `5453...` | 03-04 00:53 | 31    | enricher 로직 변경  |
| `0540...` | 03-04 14:04 | 30    | 현재 사용 (R=36.3%) |

> 캐시 hash가 바뀌는 이유: `_enrich_from_pdf()` 로직 변경 → criteria 텍스트 변경 → prompt 변경 → hash 변경 → MISS → LLM 재호출. LLM 자체의 비결정성이 아님.
