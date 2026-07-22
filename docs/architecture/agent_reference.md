# ARTEMIS Agent Reference

> 최종 업데이트: 2026-03-20  
> 실행 순서: **Trial Agent** → **Mapping Agent** → **Assembly/Validator** → **Extraction Agent** → **Analysis Agent** → **Reporting Agent**

---

## 파이프라인 흐름

```
NL Query / NCT ID
     │
     ▼
┌──────────────────────── Supervisor Agent (LangGraph) ────────────────────────┐
│                                                                              │
│  [Trial Agent]      NL/NCT → IR → sub-criteria 분해                         │
│      │                                                                       │
│      ├─ review_trial()                                                       │
│      │                                                                       │
│  [Mapping Agent]    Entity text → OMOP mappings → register                   │
│      │             (내부: Mapper → Audit → Consolidator → Registry)          │
│      ├─ review_mapping()                                                     │
│      │    └─ SELECTIVE_RETRY → plan_mapping_remediation                      │
│      │                           → execute_mapping_remediation               │
│      │                                                                       │
│  [Assembly Agent]   IR + ConceptSets → Circe JSON → validation               │
│      │             (내부: Agent3 + Agent4)                                   │
│      ├─ review_assembly()                                                    │
│      │                                                                       │
│  [Extraction Agent] Circe JSON → SQL/WebAPI → Patient DataFrame              │
│      ├─ review_extraction()                                                  │
│      │                                                                       │
│  [Analysis Agent]   Patient DataFrame → PSM/IPTW → Cox PH                    │
│      ├─ review_analysis()                                                    │
│      │                                                                       │
│  [Reporting Agent]  Results → Visualizations → HTML/PDF report               │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 운영 규칙

- `ESCALATE`는 **즉시 종료 신호가 아니다**. 현재 distribution 브랜치에서는 `escalate_reason`만 상태에 기록하고 파이프라인은 다음 단계로 계속 진행한다.
- `SELECTIVE_RETRY`는 Mapping 단계에서만 발생하며, remediation 후 다시 `review_mapping()`으로 돌아간다.
- `domain_mismatch`는 **2단계 정책**을 사용한다.
  - 1차: 원래 `domain_hint` 유지 + `force_slow_path`
  - 2차+: 강한 증거가 있을 때만 corrected `domain_hint`

---

## Agent 1: Trial Agent (Logic Decomposer)

| 항목          | 내용                                                                                           |
| ------------- | ---------------------------------------------------------------------------------------------- |
| **역할**      | NL/NCT 프로토콜 → 구조화된 IR (ARTEMISRequest) + sub-criteria 분해                             |
| **입력**      | NL 질문 또는 NCT ID                                                                            |
| **출력**      | `ARTEMISRequest` (target/comparator cohort, inclusion/exclusion rules + sub_criteria, outcome) |
| **LLM 사용**  | ✅ Azure GPT-4o (IR 생성, criteria 분해)                                                       |
| **주요 기능** | NCT 파싱, PubMed/PDF enrichment, domain 분류, composite criteria → sub-criteria 분해           |

내부적으로 2개 컴포넌트로 구분:

| 컴포넌트               | 역할                                            |
| ---------------------- | ----------------------------------------------- |
| **Parser** (Step 1)    | NL/NCT → `ARTEMISRequest` IR 생성               |
| **Planner** (Step 1.5) | Composite criteria → granular sub-criteria 분해 |

### 구현 파일

| 파일                                  | 역할                                         |
| ------------------------------------- | -------------------------------------------- |
| `src/agents/agent1/parser.py`         | 메인 — `parse()`, `parse_nct()`              |
| `src/agents/agent1/prompts.py`        | LLM 프롬프트 (IR 생성, criteria 분해)        |
| `src/agents/agent1/nct_fetcher.py`    | ClinicalTrials.gov API NCT 파싱              |
| `src/agents/agent1/pubmed_fetcher.py` | PubMed API 논문 검색                         |
| `src/agents/agent1/pubmed_linker.py`  | NCT → PubMed PMID 연결                       |
| `src/agents/agent1/enricher.py`       | PDF enrichment (appendix 텍스트 추출)        |
| `src/agents/planner/__init__.py`      | Planner — `get_planner()`, sub-criteria 분해 |

### 관련 ADR/RFC

- [ADR-014: C2Q Agent 1 Prompt Strategy](./adr/ADR-014_C2Q_Agent1_Prompt_Strategy.md)
- [ADR-017: Agent 1 Role Reduction](./adr/ADR-017_Agent1_Role_Reduction.md)

---

## Mapping Agent

| 항목          | 내용                                                           |
| ------------- | -------------------------------------------------------------- |
| **역할**      | Entity text → OMOP Concept IDs → Circe JSON 조립               |
| **입력**      | `ARTEMISRequest` IR의 entity list + domain_hint                |
| **출력**      | `AssemblyResult` (circe_json, heal_log, comparator_circe_json) |
| **LLM 사용**  | ✅ Reranker (LLM Judge), Critic (LLM evaluator)                |
| **주요 기능** | 용어 매핑, 품질 검사, ConceptSet 병합, Circe JSON 조립         |

내부적으로 4개 컴포넌트로 구분:

| 컴포넌트         | Step | 역할                                                     |
| ---------------- | ---- | -------------------------------------------------------- |
| **Mapper**       | 2    | Entity text → OMOP Concept IDs (fast/slow path, KG, ATC) |
| **Supervisor**   | 2.1  | 매핑 품질 검사 + query rewrite retry (RFC-012)           |
| **Consolidator** | 2.5  | 동일 parent_rule 내 sibling ConceptSet 병합              |
| **Assembler**    | 3    | IR + ConceptSets → Circe-be JSON, self-heal              |

### Mapper 구현 파일

| 파일                                         | 역할                                                                        |
| -------------------------------------------- | --------------------------------------------------------------------------- |
| `src/agents/agent2/workflow.py`              | **메인 워크플로우** — `process()`, `process_with_details()`, fast/slow path |
| `src/agents/agent2/retriever.py`             | ChromaDB 벡터 검색                                                          |
| `src/agents/agent2/reranker.py`              | LLM 기반 concept reranking                                                  |
| `src/agents/agent2/critic.py`                | LLM 기반 concept 평가/필터링                                                |
| `src/agents/agent2/kg_expander.py`           | Neo4j KG expansion + ancestor climbing                                      |
| `src/agents/agent2/umls_synonym_expander.py` | UMLS API synonym 확장                                                       |
| `src/agents/agent2/drug_class_expander.py`   | ATC vocabulary 기반 drug class 확장                                         |
| `src/agents/agent2/concept_set_refiner.py`   | ConceptSet 후처리 (overbroad 감지)                                          |
| `src/agents/agent2/complexity_router.py`     | Fast/Slow path 라우팅 결정                                                  |
| `src/agents/agent2/abbreviation_expander.py` | 약어 확장                                                                   |
| `src/agents/agent2/rule_extractor.py`        | 규칙 기반 concept 추출                                                      |
| `src/agents/agent2/regex_rules.py`           | Regex 매칭 규칙                                                             |
| `src/agents/agent2/logic.py`                 | 로직 분해 (combination drug 등)                                             |
| `src/agents/agent2/agent2_cache.py`          | 매핑 결과 캐시                                                              |

### Supervisor 구현 파일

| 파일                         | 역할                                        |
| ---------------------------- | ------------------------------------------- |
| `src/pipeline/supervisor.py` | `PipelineSupervisor` — quality gate + retry |

### Consolidator 구현 파일

| 파일                                  | 역할                     |
| ------------------------------------- | ------------------------ |
| `src/agents/consolidator/__init__.py` | `ConceptSetConsolidator` |

### Assembler 구현 파일

| 파일                             | 역할                                     |
| -------------------------------- | ---------------------------------------- |
| `src/agents/agent3/assembler.py` | `assemble()`, self-heal, Circe JSON 빌더 |
| `src/agents/agent3/mappings.py`  | 도메인 → Circe criteria type 매핑        |

### 관련 ADR/RFC

- [RFC-006: ATC Drug Class Expansion](./rfc/RFC-006_Vocabulary_Based_Drug_Class_Expansion.md) ✅
- [RFC-010: Reranker Cross-Branch Recall](./rfc/RFC-010_Reranker_Cross_Branch_Recall.md)
- [RFC-012: Post-Agent2 Supervisor](./rfc/RFC-012_Post_Agent2_Supervisor.md) ✅
- [ADR-012: UMLS Synonym Expansion](./adr/ADR-012_UMLS_Synonym_Expansion.md)
- [ADR-015: MedCPT Embedding Integration](./adr/ADR-015_MedCPT_Embedding_Integration.md)
- [ADR-016: ThreadPoolExecutor Deterministic Ordering](./adr/ADR-016_ThreadPoolExecutor_Deterministic_Ordering.md)
- [ADR-018: Neo4j Full Transitive Closure](./adr/ADR-018_Neo4j_Full_Transitive_Closure.md)

---

## Validator

| 항목          | 내용                                                     |
| ------------- | -------------------------------------------------------- |
| **역할**      | Circe JSON 구문/의미 검증                                |
| **입력**      | Circe JSON dict                                          |
| **출력**      | `ValidationResult` (valid, errors, warnings)             |
| **LLM 사용**  | ❌                                                       |
| **주요 기능** | Schema check, CodesetId 참조 무결성, temporal logic 검증 |

### 구현 파일

| 파일                             | 역할                                   |
| -------------------------------- | -------------------------------------- |
| `src/agents/agent4/validator.py` | `agent4.validate()`, `format_report()` |

### 관련 ADR

- [ADR-019: Integration Verification 필수화](./adr/ADR-019_Integration_Verification.md)

---

## Extraction Agent

| 항목          | 내용                                                           |
| ------------- | -------------------------------------------------------------- |
| **역할**      | Circe JSON → SQL 쿼리 생성 → OMOP CDM 실행 → Patient DataFrame |
| **입력**      | Validated Circe JSON + CDM 연결 설정                           |
| **출력**      | Target/Comparator Patient DataFrame                            |
| **LLM 사용**  | ❌                                                             |
| **주요 기능** | ConceptSet 파싱, SQL 빌드, descendant 확장, fallback 진단      |

내부적으로 2개 컴포넌트로 구분:

| 컴포넌트           | 역할                                 |
| ------------------ | ------------------------------------ |
| **CohortExecutor** | Circe JSON 파싱 → SQL 빌드 → 실행    |
| **OMOPConnector**  | CDM 연결, descendant 확장, 진단 쿼리 |

### 구현 파일

| 파일                              | 역할                                        |
| --------------------------------- | ------------------------------------------- |
| `src/pipeline/cohort_executor.py` | `CohortExecutor` — Circe → SQL → Patient DF |
| `src/analysis/omop_connector.py`  | CDM 연결, 쿼리 실행, concept 검증           |
| `src/pipeline/webapi_client.py`   | OHDSI WebAPI 연동 (cohort generation)       |

### 관련 RFC

- [RFC-005: Pipeline Feedback Loops](./rfc/RFC-005_Pipeline_Feedback_Loops.md) (Loop 4-5: Extraction retry)

---

## Analysis Agent

| 항목          | 내용                                                        |
| ------------- | ----------------------------------------------------------- |
| **역할**      | Patient DataFrame → 인과추론 분석 (PSM/IPTW, Cox PH)        |
| **입력**      | Target/Comparator Patient DataFrame                         |
| **출력**      | Analysis results (HR, KM data, covariate balance)           |
| **LLM 사용**  | ❌                                                          |
| **주요 기능** | Large-scale covariate extraction, propensity score matching |

### 구현 파일

| 파일                            | 역할            |
| ------------------------------- | --------------- |
| `src/agents/agent5/workflow.py` | 분석 워크플로우 |

---

## Reporting Agent

| 항목          | 내용                                      |
| ------------- | ----------------------------------------- |
| **역할**      | 분석 결과 → 시각화 + PDF 임상 보고서 생성 |
| **입력**      | Analysis results                          |
| **출력**      | PDF report, Forest Plot, KM Curve         |
| **LLM 사용**  | ✅ (보고서 요약 생성)                     |
| **주요 기능** | WeasyPrint PDF, matplotlib 시각화         |

### 구현 파일

| 파일                            | 역할                   |
| ------------------------------- | ---------------------- |
| `src/agents/agent6/workflow.py` | 보고서 생성 워크플로우 |

---

## Pipeline Orchestration

| 파일                              | 역할                                                     |
| --------------------------------- | -------------------------------------------------------- |
| `src/pipeline/orchestrator.py`    | **최상위 진입점** — `run_supervisor()` 호출              |
| `src/pipeline/supervisor_agent.py`| **메인 오케스트레이터** — LangGraph 6-agent supervisor   |
| `src/pipeline/supervisor.py`      | Cohort-definition 하위 오케스트레이터 + quality gate     |
| `src/pipeline/cohort_pipeline.py` | backward compat thin wrapper                             |
| `src/pipeline/cohort_executor.py` | Circe JSON → 환자 추출 실행                              |
| `src/pipeline/webapi_client.py`   | OHDSI WebAPI 연동                                        |

### Selective Retry 구성요소

| 파일                                | 역할                                                                    |
| ----------------------------------- | ----------------------------------------------------------------------- |
| `src/pipeline/mapping_retry.py`     | selective retry planning 정책, staged domain correction, env thresholds |
| `src/agents/agent2/map_entity.py`   | single-entity mapping 진입점, `force_slow_path` 처리                    |
| `src/pipeline/supervisor_agent.py`  | retry queue 생성, remediation 실행, retry telemetry 관리                |

---

## 기술 스택 요약

| 컴포넌트            | 기술                                                       |
| ------------------- | ---------------------------------------------------------- |
| **LLM**             | Azure GPT-4o (Agent 1, Planner, Reranker, Critic, Agent 6) |
| **Vector DB**       | ChromaDB (MedCPT embeddings)                               |
| **Knowledge Graph** | Neo4j (OMOP concept_ancestor, full transitive closure)     |
| **용어 서비스**     | UMLS API, Athena SQLite                                    |
| **CDM**             | PostgreSQL (Synthea OMOP CDM)                              |
| **분석**            | lifelines, sklearn, causalml                               |
| **PDF**             | WeasyPrint, matplotlib                                     |
