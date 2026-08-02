# ARTEMIS Agent Reference

> **최종 업데이트:** 2026-07-31  
> **범위:** `artemis/src/agents/**` + 파이프라인 오케스트레이션에 묶인 Extraction 경로  
> **원칙:** FE/제품 계약은 capability 용어를 쓰고, 이 문서는 backend 내부 agent 번호·역할을 기록한다.

관련 문서:

- 개념/상세 Living Doc: [Trial Agent](../trial_agent_explanation.md), [Mapping Agent](../mapping_agent_explanation.md)
- TTE capability 정렬: [`docs/tte_agent/05_agent_role_aligned_plan.md`](../../../docs/tte_agent/05_agent_role_aligned_plan.md)
- 인벤토리 스냅샷(결과): [`docs/tte_agent/32_agent_inventory_2026-07-31.md`](../../../docs/tte_agent/32_agent_inventory_2026-07-31.md)
- MOC: [`docs/MOC.md`](../MOC.md)

---

## 1. 한눈에 보기

| # | 내부 이름 | 제품/역할 이름 | 패키지 | 핵심 진입점 | LLM |
| --- | --- | --- | --- | --- | --- |
| 1 | Trial Agent | Logic Decomposer | `agent1/` | `get_agent1().parse()` / `parse_nct()` | ✅ |
| 1.5 | Planner | Criteria Decomposer | `planner/` | `get_planner().plan(ir)` | ✅ |
| 1.x | Threshold Classifier | Value/span classifier (ADR-032) | `agent1/threshold_classifier.py` | `classify_*` | ✅ |
| 2 | Mapping Agent (Mapper) | Intelligent Mapper | `agent2/` | `get_agent2().process(_with_details)` | ✅ (rerank/critic) |
| 2.5 | Consolidator | ConceptSet LCA merger | `consolidator/` | `ConceptSetConsolidator.consolidate()` | ❌ |
| 3 | Assembly Agent | Circe Assembler | `agent3/` | `agent3.assemble(ir, concept_sets)` | ❌ |
| 4 | Validator | Circe Validator | `agent4/` | `agent4.validate(circe_json)` | ❌ |
| — | Extraction Agent | Cohort Executor | `pipeline/` (+ `analysis/omop_connector.py`) | WebAPI / CohortExecutor | ❌ |
| 5 | Analysis Agent | Causal Analysis | `agent5/` | `Agent5Workflow.configure(...).run()` | ❌ |
| 6 | Reporting Agent | Report Generator | `agent6/` | `Agent6Workflow.set_results(...).generate_report()` | △ (요약 경로 확장 가능) |
| — | Comparator Recommender | Active-comparator proposal | `comparator/` | `recommend_comparator(...)` | ✅ (vLLM, degradable) |
| — | ConceptSet Recommender | Standalone CS recommender | `conceptset/` | `get_recommender().recommend()` / FastAPI | ✅ |

파이프라인 순서 (Supervisor LangGraph):

```
NL Query / NCT ID
     │
     ▼
┌──────────────────── Supervisor Agent (LangGraph) ────────────────────┐
│                                                                      │
│  [1 Trial]     NL/NCT → ARTEMISRequest IR                            │
│      │                                                               │
│  [1.5 Planner] composite criteria → sub_criteria                     │
│      │                                                               │
│  [2 Mapper]    entity_text → MappingResult → Registry                │
│      │         (+ post-Agent2 quality gate / selective retry)        │
│  [2.5 Consol.] sibling ConceptSets → LCA merge                       │
│      │                                                               │
│  [3 Assembly]  IR + RegisteredConceptSets → Circe JSON               │
│  [4 Validate]  Circe schema / refs / semantic checks                 │
│      │                                                               │
│  [Extraction]  Circe → WebAPI/SQL → patient / cohort counts          │
│  [5 Analysis]  features → PS (IPTW/PSM/Mahalanobis) → Cox HR         │
│  [6 Report]    plots + PDF/HTML                                      │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

부가 경로 (메인 체인 밖):

- **Comparator Recommender** — placebo trial을 active-comparator new-user로 바꿀 때 HITL proposal
- **ConceptSet Recommender** — Atlas/ConceptSet UI용 독립 추천 API (Agent 2 파이프라인과 별개)
- **Threshold Classifier** — eligibility 수치/기간 span 분류 (Agent 1 이후 Circe 구조화 전)

### 운영 규칙 (Supervisor)

- `ESCALATE`는 **즉시 종료가 아니다**. `escalate_reason`만 기록하고 다음 단계로 진행할 수 있다.
- `SELECTIVE_RETRY`는 Mapping 단계에서만 발생한다 → remediation 후 `review_mapping()`으로 복귀.
- `domain_mismatch`는 2단계 정책: (1) 원래 `domain_hint` + `force_slow_path`, (2) 강한 증거가 있을 때만 domain 교정.

---

## 2. 공유 데이터 계약 (IR)

정의 위치: `src/models/ir.py`, `src/registry/models.py`

| 타입 | 의미 | 주요 필드 |
| --- | --- | --- |
| `ARTEMISRequest` | 스터디 IR 루트 | `target`, `comparator`, `outcome`, `concept_sets` |
| `CohortDefinition` | Target/Comparator 코호트 | `primary_criteria`, `inclusion_rules`, `exclusion_rules`, `exit_strategy` |
| `Criteria` | 포함/제외 규칙 | `name`, `domain`, `entity_text`, `logic_type` (PRESENCE/ABSENCE), `window`, `value_constraint`, `sub_criteria`, `group_type` (ALL/ANY), `conditional`, `source_text` |
| `PrimaryCriteria` | Index event | domain/entity + observation window |
| `CohortOutcome` | Outcome + TAR | `entity_text`, `time_at_risk` |
| `MappingResult` | Agent 2 출력 | `concept_ids`, `overbroad_concept_ids`, `gap_report`, `route_path`, `atc_expanded`, `critic_skipped`, `processing_time_ms` |
| `RegisteredConceptSet` | Registry 엔트리 | `id`, `name`, `concepts[]`, `source_entity_text`, `hash` |
| `AssemblyResult` | Agent 3 출력 | `circe_json`, `comparator_circe_json`, `treatment_circe_json`, `heal_log` |
| `ValidationResult` | Agent 4 출력 | `valid`, `errors`, `warnings`, counts |
| `ProvisionalStudyIR` | TTE FE→backend 임시 IR | section별 eligibility/treatment/outcomes 텍스트 소스 |

---

## 3. Agent 1 — Trial Agent (`LogicDecomposer`)

| 항목 | 내용 |
| --- | --- |
| **역할** | 자연어 임상 질문 또는 NCT 프로토콜을 구조화 IR(`ARTEMISRequest`)로 변환 |
| **제품 capability** | `generate_draft` (Planner와 함께), eligibility/treatment/outcome 제안의 IR 소스 |
| **클래스** | `src.agents.agent1.parser.LogicDecomposer` |
| **팩토리** | `get_agent1(model_name=None)` |

### 입력

| API | 인자 | 설명 |
| --- | --- | --- |
| `parse(query)` | `query: str` | 자연어 임상 질문 |
| `parse_nct(...)` | `nct_id`, optional `json_path`, `enrich_from_pubmed`, `design_paper_pdf`, `papers_dir` | ClinicalTrials.gov + 논문 enrichment |

Enrichment 우선순위 (`parse_nct`):

1. `papers_dir` (또는 `data/papers/{NCT}/` 자동 발견) — supplement 있으면 main paper skip (ADR-020)
2. 단일 `design_paper_pdf`
3. PubMed abstract fallback

### 출력

- `ARTEMISRequest`
- side channel: `self.last_paper_status` (`PaperStatus`) — enrichment 출처/수동 다운로드 필요 여부
- NCT 경로: IR JSON 캐시 `data/cache/agent1_ir/{nct}_{model}_{hash}.json` (+ `.meta.json`)

후처리:

- exclusion `logic_type` 강제 ABSENCE
- Drug `entity_text` 정규화 (괄호/“or other …” 제거 → Agent 2 over-expansion 방지)
- Pattern E repair: 같은 CV/risk 클러스터의 flat inclusion을 ANY 그룹으로 병합
- coverage gap warning: 출력 규칙 수 < 입력 criteria의 50%

### 주요 서브모듈

| 파일 | 역할 |
| --- | --- |
| `parser.py` | `parse` / `parse_nct`, IR 빌드, Pattern E |
| `prompts.py` | SYSTEM / DECOMPOSITION / NCT prompts |
| `nct_fetcher.py` | ClinicalTrials.gov fetch + `TrialData` |
| `pubmed_fetcher.py` / `pubmed_linker.py` | PubMed 검색·NCT↔PMID |
| `pmc_fetcher.py` / `pmc_supplement.py` | PMC / supplement |
| `enricher.py` | PDF 텍스트 enrichment |
| `paper_url_mapper.py` | 논문 URL 매핑 |
| `threshold_classifier.py` | ADR-032 span 분류 (별도 단계, 아래 §3.1) |

### LLM / 의존성

- `get_llm(..., temperature=0.0, json_mode=True)`
- 캐시로 deterministic replay 지원

---

### 3.1 Threshold Classifier (ADR-032)

| 항목 | 내용 |
| --- | --- |
| **역할** | eligibility 문장에서 수치/기간/용량 등 **span**을 분류해 Circe 구조화에 넘김 |
| **위치** | `agent1/threshold_classifier.py` |
| **파이프라인** | (1) Agent1 decompose → (2) **classify spans** → (3) `value_constraint` 구조화 |
| **입력** | criterion / source_text (+ taxonomy prompt) |
| **출력** | span list: class ∈ `{MEASUREMENT_VALUE, AGE, TEMPORAL_WINDOW, STATE_DURATION, DRUG_DOSE, SCORE_GRADE, EVENT_QUANTITY, REVIEW, NON_CRITERION}` |
| **설계 포인트** | 모델 self-confidence 폐기; 게이트 실패는 전부 `REVIEW`. numeral recall이 load-bearing |

---

## 4. Planner — Agent 1.5 (`CriteriaPlanner`)

| 항목 | 내용 |
| --- | --- |
| **역할** | Agent 1 IR의 composite/umbrella criteria를 OMOP-검색 가능한 sub-criteria로 분해 |
| **위치** | `src/agents/planner/decomposer.py` |
| **팩토리** | `get_planner(model_name=None)` |
| **파이프라인 위치** | Agent 1 → **Planner** → Agent 2 |

### 입력 / 출력

- **In:** `ARTEMISRequest`
- **Out:** 동일 타입, `Criteria.sub_criteria` 채움 + `group_type` 설정
  - `logic_type == ABSENCE` → `group_type = ALL` (De Morgan: 모든 하위 부재 필요)
  - 그 외 → `group_type = ANY`
- 이미 `sub_criteria`가 있거나 `entity_text` 없으면 skip
- LLM 실패 시 원본 유지

### LLM

- `PLANNER_SYSTEM_PROMPT` + `DECOMPOSITION_PROMPT` (`planner/prompts.py`)

---

## 5. Agent 2 — Mapping Agent (`Agent2Workflow`)

| 항목 | 내용 |
| --- | --- |
| **역할** | 임상 entity text → OMOP Concept ID 목록 (+ gap / overbroad 메타) |
| **제품 capability** | `suggest_eligibility`, `suggest_treatment`, `suggest_outcomes` (IR + Mapping) |
| **클래스** | `src.agents.agent2.workflow.Agent2Workflow` |
| **팩토리** | `get_agent2()` |
| **단건 래퍼** | `map_entity.py` — supervisor selective retry / `force_slow_path` |

### 입력

| API | 인자 | 반환 |
| --- | --- | --- |
| `process(query_text, context=None, domain_hint=None)` | 임상 용어 | `List[int]` concept IDs |
| `process_with_details(..., force_slow_path=False, pre_fetched_candidates=None)` | 동일 + 옵션 | `MappingResult` |
| `process_batch(queries, contexts=None)` | 배치 | 집계 `MappingResult` |

`domain_hint`: Agent 1이 준 OMOP domain (`Drug`, `Condition`, …). ATC expansion 게이트·retriever 필터에 사용.

### 출력 (`MappingResult`)

| 필드 | 의미 |
| --- | --- |
| `concept_ids` | 최종 OMOP IDs |
| `overbroad_concept_ids` | Assembler가 `includeDescendants=false`로 둬야 하는 ID |
| `gap_report` | 매핑 실패 항목 |
| `route_path` | `'fast'` / `'slow'` / `'atc'` (현재 기본은 slow 강제) |
| `atc_expanded` | ATC early-return 여부 |
| `critic_skipped` | Critic LLM skip 여부 |
| `domain_overridden` | domain pre-check가 힌트를 바꿨을 때 원본 |
| `processing_time_ms` | 소요 시간 |

### 내부 처리 순서 (현재 구현)

1. (옵션) Domain pre-check — `DOMAIN_PRECHECK=1`일 때만; 기본 OFF
2. Abbreviation expansion → UMLS query pre-expansion (`AGENT2_QUERY_EXPAND`)
3. **ATC drug-class expansion** — `domain_hint == "Drug"`이면 vocab lookup 후 early return
4. Complexity router — **현재 fast path 비활성**, 항상 slow
5. Slow path: ChromaDB retrieve → LLM rerank → (UMLS synonyms) → Neo4j KG expand → Critic → ConceptSet refiner
6. Drug (또는 domain unknown)면 RxNorm ingredient roll-up

### 서브모듈

| 파일 | 역할 |
| --- | --- |
| `workflow.py` | 메인 오케스트레이션 |
| `retriever.py` | ChromaDB / MedCPT 검색 |
| `reranker.py` | LLM concept rerank |
| `critic.py` (+ `critic_cache.py`) | LLM multi-select / 필터 |
| `kg_expander.py` | Neo4j ancestor/sibling expansion |
| `umls_synonym_expander.py` / `query_expander.py` | UMLS 동의어·약어 |
| `drug_class_expander.py` | ATC class → ingredients |
| `drug_name_normalizer.py` | 약물명 정규화 |
| `concept_set_refiner.py` | overbroad 감지 |
| `complexity_router.py` | fast/slow (현재 slow 고정) |
| `abbreviation_expander.py` | 약어 사전 |
| `rule_extractor.py` / `regex_rules.py` | 규칙·코드 패턴 |
| `logic.py` | combination drug / ingredient roll-up |
| `agent2_cache.py` / `criterion_cache.py` | 결과 캐시 |
| `map_entity.py` | entity 단위 진입 + retry hooks |

### 환경 변수 (대표)

| 변수 | 효과 |
| --- | --- |
| `AGENT2_MAX_WORKERS` | 스레드 풀 (기본 16) |
| `AGENT2_MAX_CRITIC_CANDIDATES` | Critic 후보 cap |
| `DOMAIN_PRECHECK` | domain override on/off |
| `FORCE_SLOW_PATH` / `FORCE_FAST_PATH` | 라우팅 강제 |
| `AGENT2_QUERY_EXPAND` | UMLS query pre-expand |

### 관련 ADR/RFC

RFC-006 (ATC), RFC-010 (reranker), RFC-012 (post-Agent2 supervisor), ADR-011/012/015/016/018/022

---

## 6. Consolidator — Step 2.5 (`ConceptSetConsolidator`)

| 항목 | 내용 |
| --- | --- |
| **역할** | 동일 parent rule 안에서 over-decomposed sibling ConceptSet을 OMOP LCA로 병합 |
| **위치** | `src/agents/consolidator/consolidator.py` |
| **파이프라인** | Agent 2 → **Consolidator** → Registry → Agent 3 |

### 입력 / 출력

- **In:** `List[Dict]` mapped sets (`concept_ids`, parent rule 메타 등)
- **Out:** 병합된 mapped set 리스트
- `find_lowest_common_ancestor(concept_ids)` — ontology_search 기반
- Aggressive mode (`KG_CONSOLIDATOR_AGGRESSIVE=true`): `max_separation=8`, IC < 6.0 LCA 거부

---

## 7. Agent 3 — Assembly Agent (`CohortAssembler`)

| 항목 | 내용 |
| --- | --- |
| **역할** | IR + RegisteredConceptSets → Circe-be JSON (ATLAS/WebAPI 호환) |
| **제품 capability** | `validate_design`의 조립 단계 |
| **싱글톤** | `from src.agents.agent3.assembler import agent3` |
| **API** | `assemble(ir, concept_sets) -> AssemblyResult` |

### 입력

- `ARTEMISRequest`
- `List[RegisteredConceptSet]`

### 출력 (`AssemblyResult`)

| 필드 | 의미 |
| --- | --- |
| `circe_json` | Target (또는 disease-based Target) Circe |
| `treatment_circe_json` | Disease-based 모드: Target + DrugEra PRESENCE |
| `comparator_circe_json` | Comparator 코호트 Circe |
| `heal_log` | 규칙별 KEEP/SKIP/HEAL (`HealAction`) |
| `failed_entities` / `has_failures` | SKIP된 entity 요약 |

### 조립 모드

1. **Disease-based primary** (`USE_DISEASE_BASED_PRIMARY = True`, Drug primary일 때)  
   - Primary = 첫 Condition inclusion  
   - Treatment = Target + drug PRESENCE  
   - Comparator = Target + drug ABSENCE  
2. **Legacy drug-based primary** — target/comparator 각각 PrimaryCriteria에 약물

기타:

- `conditional=True` 규칙은 Circe에서 SKIP
- exclusion → inclusion + ABSENCE occurrence
- `includeMapped=True`, overbroad면 descendants 정책 반영
- EndStrategy: OBSERVATION_END / FIXED_DURATION / CUSTOM_ERA
- 도메인→Circe criteria 타입: `agent3/mappings.py`

---

## 8. Agent 4 — Validator (`CirCeValidator`)

| 항목 | 내용 |
| --- | --- |
| **역할** | Circe JSON 구문·참조·의미 검증 (ATLAS 호환) |
| **제품 capability** | `validate_design` |
| **싱글톤** | `agent4` |
| **API** | `validate(circe_json) -> ValidationResult` |

### 검사 항목

1. Schema — `ConceptSets`, `PrimaryCriteria` 필수
2. ConceptSet 필드 완전성
3. CodesetId 참조 무결성
4. Semantic — CodesetId=0, empty criteria, domain 일관성
5. Registry integrity (경고)

### 출력

- `valid: bool` (error 없을 때 True)
- `errors[]` / `warnings[]` (`field`, `message`, `severity`)
- `concept_set_count`, `inclusion_rule_count`

LLM 없음.

---

## 9. Extraction Agent (파이프라인, agents/ 밖)

| 항목 | 내용 |
| --- | --- |
| **역할** | Validated Circe → WebAPI cohort generation 및/또는 SQL 실행 → 환자/카운트 |
| **제품 capability** | `execute_study` |
| **주요 구현** | `src/pipeline/webapi_client.py`, `cohort_executor.py`, `src/analysis/omop_connector.py` |
| **Supervisor 노드** | `extraction_node` / `review_extraction` |

### 입력 / 출력

- **In:** Circe JSON (+ source key, CDM 연결)
- **Out:** cohort generation info, counts, patient DataFrame (경로에 따라)
- LLM 없음
- WebAPI generation cache 이슈는 workspace GENERATED-GOLD CACHE RULE 참고

---

## 10. Agent 5 — Analysis Agent (`Agent5Workflow`)

| 항목 | 내용 |
| --- | --- |
| **역할** | Target/Comparator 코호트에 대한 인과추론 분석 |
| **제품 capability** | `run_analysis` |
| **클래스** | `src.agents.agent5.workflow.Agent5Workflow` |

### 입력

```text
configure(
  target_cohort_id: int,
  comparator_cohort_id: int,
  outcome_definition: {concept_ids, window_days}? ,
  analysis_method: "IPTW" | "PSM" | "MAHALANOBIS"
)
run(data: Optional[DataFrame] = None)
```

- `data` 없으면 connector로 feature extract (`_extract_features`)
- 기대 컬럼: `person_id`, `treatment`, `time`, `event` + covariates

### 출력 (dict)

| 키 | 내용 |
| --- | --- |
| `hazard_ratio` | Cox HR 결과 객체 |
| `balance` | covariate별 SMD before/after |
| `ps_scores` / `weights` / `treatment` | PS 관련 배열 |
| `analysis_method` | 실제 사용된 방법 (PSM 실패 시 `"IPTW (PSM fallback)"`) |
| `survival_data` | KM용 times/events |
| `n_target` / `n_comparator` | 표본 수 |
| `n_matched_pairs` | PSM/Mahalanobis일 때 |

LLM 없음. 통계는 `src/analysis/{propensity,balance,cox}.py`.

---

## 11. Agent 6 — Reporting Agent (`Agent6Workflow`)

| 항목 | 내용 |
| --- | --- |
| **역할** | 분석 결과 → 시각화 + PDF/HTML 보고서 |
| **제품 capability** | `generate_report_summary` |
| **클래스** | `src.agents.agent6.workflow.Agent6Workflow` |

### 입력 (`set_results`)

- `study_title`, `hazard_ratio`, `target_n`, `comparator_n`
- optional: `balance`, `ps_scores`, `treatment`, `survival_data`

### 출력

| API | 반환 |
| --- | --- |
| `generate_plots(output_dir)` | `{forest, ps_dist, love, km}` → PNG path |
| `generate_report(output_path)` | PDF path (WeasyPrint) |
| `generate_html_report(output_path)` | HTML path |

플롯: Forest, PS distribution, Love (SMD), Kaplan–Meier.  
구현 위임: `src/reporting/{plots,pdf_generator,models}.py`.

---

## 12. Comparator Recommender (부가)

| 항목 | 내용 |
| --- | --- |
| **역할** | Placebo-controlled trial을 RWD에서 에뮬할 때 **CV-neutral active comparator** 제안 (HITL only) |
| **ADR** | ADR-027 / ADR-028 |
| **진입점** | `recommend_comparator(treatment_drug, indication, outcome, candidates, trial_name=?)` |
| **위치** | `comparator/recommender.py`, `literature.py` |

### 입력

- treatment / indication / outcome
- `candidates: list[{drug_class, ingredients}]` — CDM ATC siblings 등 **필수** (내장 리스트 없음)

### 출력 (`RecommendationArtifact`)

| 필드 | 의미 |
| --- | --- |
| `status` | 항상 `"proposed"` (auto-apply 금지) |
| `candidates` | `ClassVerdict` (verdict, confidence, PMIDs, caveat) |
| `recommendation` | top neutral class + rationale + alternatives |
| `evidence` | PubMed `LiteratureBundle` provenance |
| `caveats` | vLLM down 시 evidence-only 등 |

vLLM 불가 시 verdict=`unknown`으로 degrade, evidence는 유지.

---

## 13. ConceptSet Recommender (부가 / API)

| 항목 | 내용 |
| --- | --- |
| **역할** | 자연어 → include/exclude Intent → Circe ConceptSet expression 추천 |
| **진입점** | `ConceptSetRecommender.recommend(query, top_k, ...)` / FastAPI `conceptset/api.py` |
| **Agent 2와의 관계** | **별도 제품 표면**. 공유 인프라(Chroma/ontology)는 있을 수 있으나 supervisor 체인 필수 단계는 아님 |

### 파이프라인

1. NLU Router — include/exclude 분리 (`nlu_router.py`)
2. Stage1/Stage2 search (`rag_search`, `ontology_search`, Phoebe)
3. Clinical rerank + rank fusion
4. Expression builder (`includeDescendants` roll-up)
5. Semantic cache

### API 요청 예

```json
{
  "query": "Heart Failure but exclude TZD",
  "options": { "top_k": 10, "include_descendants": true, "domains": ["Condition", "Drug"] }
}
```

---

## 14. Pipeline Orchestration

| 파일 | 역할 |
| --- | --- |
| `src/pipeline/orchestrator.py` | 최상위 — `run_supervisor()` |
| `src/pipeline/supervisor_agent.py` | LangGraph 6-stage + review_* + selective retry |
| `src/pipeline/supervisor.py` | Cohort-definition 하위 오케스트레이션 + `post_agent2_check` |
| `src/pipeline/mapping_retry.py` | selective retry 정책 / domain correction |
| `src/pipeline/cohort_pipeline.py` | backward-compat thin wrapper |
| `src/services/tte_service.py` | TTE HTTP capability → agent 체인 경계 |

Supervisor 노드: `trial_node` → `mapping_node` → `assembly_node` → `extraction_node` → `analysis_node` → `reporting_node` (+ 각 `review_*`).

---

## 15. TTE Capability ↔ Agent 매핑

| Capability (FE) | Backend owners |
| --- | --- |
| `generate_draft` | Trial Agent + Planner |
| `suggest_eligibility` | Trial IR + Mapping Agent (+ threshold classifier 경로) |
| `suggest_treatment` / `suggest_treatment_arms` | Trial IR + Mapping (+ Comparator Recommender when placebo) |
| `suggest_outcomes` | Trial IR + Mapping |
| `validate_design` | Assembly + Validator + Supervisor signals |
| `execute_study` | Extraction (WebAPI/SQL) |
| `run_analysis` | Analysis Agent |
| `generate_report_summary` | Reporting Agent |

FE는 agent 번호를 알지 않는다 (`docs/tte_agent/05_agent_role_aligned_plan.md`).

---

## 16. 기술 스택 요약

| 영역 | 기술 |
| --- | --- |
| LLM | Azure/OpenAI 또는 vLLM (`get_llm`); Comparator는 `COMPARATOR_LLM_MODEL` / `VLLM_BASE_URL` |
| Vector | ChromaDB + MedCPT embeddings |
| KG | Neo4j (`concept_ancestor` transitive closure) |
| Vocab | UMLS API, Athena/CDM PostgreSQL (ATC) |
| CDM | PostgreSQL OMOP (예: Synthea) |
| Cohort runtime | OHDSI WebAPI + Circe-be |
| Stats | lifelines, sklearn, (causalml where used) |
| Report | matplotlib plots, WeasyPrint PDF / HTML |

---

## 17. 디렉터리 맵 (`src/agents/`)

```text
agents/
├── agent1/          # Trial / Logic Decomposer (+ threshold_classifier)
├── planner/         # Criteria decomposition (1.5)
├── agent2/          # OMOP Intelligent Mapper
├── consolidator/    # Post-mapping LCA merge
├── agent3/          # Circe assembler
├── agent4/          # Circe validator
├── agent5/          # Causal analysis
├── agent6/          # Reporting
├── comparator/      # Active-comparator HITL recommender
└── conceptset/      # Standalone ConceptSet recommendation API
```

Extraction은 `src/pipeline/` + `src/analysis/omop_connector.py`에 위치한다.
