# ARTEMIS Documentation MOC (Map of Content)

> 최종 업데이트: 2026-07-31
> 프로젝트 전체 문서 탐색 → [docs/MOC.md](../../docs/MOC.md)

---

## TTE 통합 현황

| 문서 | 내용 |
|------|------|
| [TTE Current Status](../../docs/tte_agent/07_current_status.md) | 최신 TTE 통합 작업 상태 |
| [SPEC-UI-003 구현 일지](./daily_notes/2026-03-28_spec_ui_003_hitl_concept_mapping.md) | HITL 개념 매핑 전체 구현 (2026-03-28) |
| [SPEC-UI-002 리뷰 & E2E](./daily_notes/2026-03-27_spec_ui_002_review_and_e2e.md) | 코드리뷰 + Playwright E2E (2026-03-27) |
| [Spark 프로덕션 통합](./daily_notes/2026-03-27_spark_production_integration.md) | 코호트 생성 ~10x 성능 (2026-03-27) |

---

## 📐 Architecture & Design

| 문서                                                     | 내용                                 |
| -------------------------------------------------------- | ------------------------------------ |
| [README.md](./README.md)                                 | 문서 개요                            |
| [System Overview](./architecture/01_system_overview.md)  | 시스템 아키텍처                      |
| [ROADMAP.md](./ROADMAP.md)                               | 개발 로드맵                          |
| [DEVELOPMENT_STATUS.md](./DEVELOPMENT_STATUS.md)         | 현재 개발 상태                       |
| [User Guide](./user_guide.md)                            | 사용자 가이드                        |
| [Mapping Agent 설명서](./mapping_agent_explanation.md)   | Agent 2 상세 설명 (Living Doc)       |
| [**Agent Reference**](./architecture/agent_reference.md) | **전체 Agent 역할/입출력/파일 정리 (2026-07-31 전면 갱신)** |
| [Agent Inventory Snapshot](../../docs/tte_agent/32_agent_inventory_2026-07-31.md) | 구현 상태 인벤토리 (Result doc) |
| [Trial Agent 설명서](./trial_agent_explanation.md)       | Agent 1 상세 설명 (Living Doc)       |

---

## 📋 RFC (Request for Comments)

|                                RFC                                | 제목                                            |    상태    |
| :---------------------------------------------------------------: | ----------------------------------------------- | :--------: |
|    [RFC-001](./rfc/RFC-001_TROY_TELOS_Gap_Closing_Strategy.md)    | TROY-TELOS Gap Closing Strategy                 |     -      |
|         [RFC-002](./rfc/RFC-002_EHR_Navigator_Pattern.md)         | EHR Navigator Pattern                           |     -      |
|    [RFC-003](./rfc/RFC-003_KG_RAG_Agent2_Concept_Expansion.md)    | KG+RAG Agent 2 Concept Expansion                |     -      |
|        [RFC-004](./rfc/RFC-004_Multi_Concept_Expansion.md)        | Multi Concept Expansion                         |     -      |
|        [RFC-005](./rfc/RFC-005_Pipeline_Feedback_Loops.md)        | Pipeline Feedback Loops                         |     -      |
| [RFC-006](./rfc/RFC-006_Vocabulary_Based_Drug_Class_Expansion.md) | **Vocabulary Based Drug Class Expansion (ATC)** |  ✅ 구현   |
|       [RFC-007](./rfc/RFC-007_Multi_Document_Enrichment.md)       | Multi Document Enrichment                       |     -      |
|           [RFC-008](./rfc/RFC-008_UMLS_CUI_Bridging.md)           | UMLS CUI Bridging                               |     -      |
|    [RFC-009](./rfc/RFC-009_Lightweight_Critic_Distillation.md)    | **Lightweight Critic Distillation**             | 🆕 검토 중 |
|     [RFC-010](./rfc/RFC-010_Reranker_Cross_Branch_Recall.md)      | **Reranker Cross-Branch Concept Recall**        | 🆕 검토 중 |
|       [RFC-011](./rfc/RFC-011_ExpD_Runtime_Optimization.md)       | **Exp D Runtime Optimization**                  |  🆕 제안   |
|        [RFC-012](./rfc/RFC-012_Post_Agent2_Supervisor.md)         | **Post-Agent2 Supervisor Quality Gate**         |  ✅ 구현   |

---

## 📜 ADR (Architecture Decision Records)

|                                  ADR                                  | 제목                                      |
| :-------------------------------------------------------------------: | ----------------------------------------- |
|      [ADR-002](./adr/ADR-002_KG_RAG_Implementation_Strategy.md)       | KG+RAG Implementation Strategy            |
|          [ADR-010](./adr/ADR-010_Broadsea_DB_Connection.md)           | Broadsea DB Connection                    |
|      [ADR-011](./adr/ADR-011_Agent2_Common_Concept_Boosting.md)       | Agent 2 Common Concept Boosting           |
|          [ADR-012](./adr/ADR-012_UMLS_Synonym_Expansion.md)           | UMLS Synonym Expansion                    |
|         [ADR-013](./adr/ADR-013_TROY_Is_Not_Ground_Truth.md)          | TROY Is Not Ground Truth                  |
|        [ADR-014](./adr/ADR-014_C2Q_Agent1_Prompt_Strategy.md)         | C2Q Agent 1 Prompt Strategy               |
|       [ADR-015](./adr/ADR-015_MedCPT_Embedding_Integration.md)        | MedCPT Embedding Integration              |
| [ADR-016](./adr/ADR-016_ThreadPoolExecutor_Deterministic_Ordering.md) | ThreadPoolExecutor Deterministic Ordering |
|           [ADR-017](./adr/ADR-017_Agent1_Role_Reduction.md)           | Agent 1 Role Reduction                    |
|       [ADR-018](./adr/ADR-018_Neo4j_Full_Transitive_Closure.md)       | **Neo4j Full Transitive Closure**         |
|         [ADR-019](./adr/ADR-019_Integration_Verification.md)          | **Integration Verification 필수화**       |
|         [ADR-020](./adr/ADR-020_Skip_Main_Paper_With_Supplement.md)   | Skip Main Paper With Supplement           |
|         [ADR-021](./adr/ADR-021_Database_Configuration_Fix.md)        | Database Configuration Fix                |
|         [ADR-022](./adr/ADR-022_ATC_Threshold_And_Concept_Metadata_Lookup.md) | ATC Threshold & Concept Metadata  |
|         [ADR-023](./adr/ADR-023_Supervisor_Orchestrator_Promotion.md) | Supervisor Orchestrator Promotion         |
|         [ADR-024](./adr/ADR-024_Benchmark_First_Development.md)       | Benchmark-First Development               |
|         [ADR-025](./adr/ADR-025_Cohort_Level_Evaluation_Shift.md)     | Cohort-Level Evaluation Shift             |
|         [ADR-026](./adr/ADR-026_Benchmark_Vocab_Subset.md)            | Benchmark Vocab Subset                    |

---

## 🧪 Experiments & Benchmarks

| 문서                                                                            | 내용                                                        |    날짜    |
| ------------------------------------------------------------------------------- | ----------------------------------------------------------- | :--------: |
| ⭐ [**Multi-Trial GOLD**](./experiments/BENCHMARK_MULTI_TRIAL_GOLD_20260311.md) | **3-Trial GOLD: A_direct + E2E, Drug Class Refactoring**    | 2026-03-11 |
| ⭐ [**종합 보고서**](./experiments/BENCHMARK_CONSOLIDATED_REPORT.md)            | **M-TROY R=83.1% + A+Climb R=53.8% + per-CS 비교 + 계산법** | 2026-03-04 |
| [**실험 명명 규칙**](./experiments/EXPERIMENT_NAMING_CONVENTION.md)             | M/A/A+Climb/D/B/C 계열 정의, 레거시 매핑, 버전 규칙         | 2026-03-04 |
| [**A_direct v3 상세**](./experiments/BENCHMARK_A_DIRECT_V3_RESULTS.md)          | Per-rule breakdown: queries, counts, timing, 실패 분석      | 2026-03-03 |
| [**Ablation Study**](./experiments/ABLATION_STUDY.md)                           | 기능 추가/제거별 성능 변화 (ATC, KG, Climb, kg_limit)       | 2026-03-03 |
| [**TROY 버전 비교 + GOLD**](./experiments/LEADER_GOLD_STANDARD.md)              | v3.4 vs v1.1 vs Design Paper + **GOLD: R=77.3%, F1=51.5%**  | 2026-03-03 |
| [**Exp D vs A_direct Gap**](./experiments/EXP_D_VS_A_DIRECT_GAP_ANALYSIS.md)    | **Agent1 polarity 손실 분석, ΔR=-16.6pp 원인 분석**         | 2026-03-03 |
| [V7 Combined (A vs C)](./experiments/BENCHMARK_V7_COMBINED.md)                  | Exp A/C Two-Way: Rule Name vs Design Paper 비교             | 2026-02-28 |
| [V7 Hierarchical (A)](./experiments/BENCHMARK_V7_HIERARCHICAL.md)               | Exp A: Rule Name → Agent 1 → Agent 2 계층 상세              | 2026-02-28 |
| [V7 Design Paper (C)](./experiments/BENCHMARK_V7_DESIGN_PAPER_HIERARCHICAL.md)  | Exp C: Design Paper 38 criteria → Agent 2 계층 상세         | 2026-02-28 |
| [V7 Exp B (PDF→Agent1)](./experiments/BENCHMARK_V7_EXP_B_HIERARCHICAL.md)       | Exp B: PDF → Agent 1 → Agent 2 E2E                          | 2026-03-01 |
| [Agent2 T1DM 분석](./experiments/Agent2_T1DM_Pipeline_Analysis.md)              | T1DM case study: Reranker cross-branch 탈락 추적            | 2026-03-03 |
| [Agent2 T1DM Slides](./experiments/slides_agent2_t1dm.md)                       | T1DM 파이프라인 분석 Slidev 슬라이드                        | 2026-03-03 |
| [V5 Results](./experiments/BENCHMARK_V5_RESULTS.md)                             | Exp A: TROY rule name → Agent 1 → Agent 2 (6단계 이력)      | 2026-02-28 |
| [Design Paper vs TROY](./experiments/BENCHMARK_DESIGN_PAPER_VS_TROY.md)         | Exp B/C: Design paper → TROY 비교                           | 2026-02-28 |
| [V4 Benchmark](./experiments/benchmarks/benchmark_v4_20260220.md)               | V4 이전 결과                                                | 2026-02-20 |
| [Agent 2 Benchmark](./experiments/agent2_benchmark_report.md)                   | Agent 2 단독 벤치마크                                       |     -      |
| [2026-01-27](./experiments/2026-01-27.md)                                       | 초기 실험 기록                                              | 2026-01-27 |

---

## 🔍 Issues & Analysis

### Concept Mapping

| 문서                                                                              | 내용                                                     |
| --------------------------------------------------------------------------------- | -------------------------------------------------------- |
| [**Domain Expansion Strategy**](./issues/ISSUE_domain_expansion_strategy.md)      | 도메인별(Drug/Condition/Procedure/Measurement) 확장 전략 |
| [Concept Mapping Ground Truth](./issues/ISSUE_no_concept_mapping_ground_truth.md) | TROY 비교 방법론 분석                                    |
| [TROY Data Quality Audit](./troy_data_quality_audit.md)                           | TROY 데이터 품질 감사                                    |
| [ConceptSet Stripping Bug](./issues/BUG_conceptset_stripping_silent_failure.md)   | ConceptSet 파싱 silent failure                           |

### Cohort Feasibility

| 문서                                                                                | Trial            | Dataset             |
| ----------------------------------------------------------------------------------- | ---------------- | ------------------- |
| [Summary](./issues/SUMMARY_all_analyses.md)                                         | **전체 요약**    | -                   |
| [ALL_TRIALS 23M](./issues/ALL_TRIALS_synthea23m_cohort_feasibility.md)              | ALL              | Synthea 23M         |
| [LEADER 100K](./issues/LEADER_synthea100k_cohort_feasibility.md)                    | LEADER           | Synthea 100K        |
| [EMPA-REG/DECLARE 100K](./issues/EMPAREG_DECLARE_synthea100k_cohort_feasibility.md) | EMPA-REG/DECLARE | Synthea 100K        |
| [PLATO 100K](./issues/PLATO_synthea100k_cohort_feasibility.md)                      | PLATO            | Synthea 100K        |
| [23M Runtime Report](./issues/check_23m_tobe_runtime_report_2026-02-27.md)          | -                | Synthea 23M runtime |

### Slides

| 문서                                                                      |
| ------------------------------------------------------------------------- |
| [ALL_TRIALS Slides](./issues/ALL_TRIALS_synthea23m_slides.md)             |
| [LEADER Slides](./issues/LEADER_synthea100k_slides.md)                    |
| [EMPA-REG/DECLARE Slides](./issues/EMPAREG_DECLARE_synthea100k_slides.md) |
| [PLATO Slides](./issues/PLATO_synthea100k_slides.md)                      |

---

## 🗓️ Lab Meetings

| 문서                                                                                                        | 안건                                              |    날짜    |
| ----------------------------------------------------------------------------------------------------------- | ------------------------------------------------- | :--------: |
| [Benchmark V3 설계](./lab_meetings/2026-02-16_benchmark_v3_design.md)                                       | 2단계 평가 + Semantic Fingerprinting              | 2026-02-16 |
| [다음 우선순위 결정](./lab_meetings/2026-02-16_benchmark_next_steps.md)                                     | C(Hotfix) → B → C(Deep) → A                       | 2026-02-16 |
| [C-Hotfix 구체 설계](./lab_meetings/2026-02-16_c_hotfix_design.md)                                          | Window 정규화, Name Fuzzy, Greedy 1:1             | 2026-02-16 |
| [HbA1c 규칙 분기 분석](./lab_meetings/2026-02-17_artemis_hba1c_divergence.md)                               | TROY L2=512 vs ARTEMIS L2=0 원인 + C2Q 3.0 개선   | 2026-02-17 |
| [파이프라인 품질 개선](./lab_meetings/2026-02-17_pipeline_quality_improvement.md)                           | Agent 3 안정화 → Agent 2 가드 기반 개선           | 2026-02-17 |
| [RFC-001 Feedback Loops 검토](./lab_meetings/2026-02-18_rfc001_feedback_loops.md)                           | 5개 Loop 타당성 + Agent 3 Silent Drop 발견        | 2026-02-18 |
| [KG²RAG 적용 방안](./lab_meetings/2026-02-19_kg2rag_artemis_adaptation.md)                                  | Grouped-by-Relationship Context 채택              | 2026-02-19 |
| [E2E 최우선 개발 요소](./lab_meetings/2026-02-20_e2e_priority_analysis.md)                                  | InclusionRule→SQL → HDPS → V4 우선순위            | 2026-02-20 |
| [TROY 벤치마크 재설계](./lab_meetings/2026-02-20_troy_benchmark_redesign.md)                                | Dual-Track (Design Paper + TROY Diagnostic)       | 2026-02-20 |
| [Mapping V5 Benchmark 전략](./lab_meetings/2026-02-27_mapping_v5_benchmark.md)                              | GT schema 합의, TROY→Agent2 대안 벤치마크         | 2026-02-27 |
| [Benchmark Evaluation Strategy](./lab_meetings/2026-03-02_benchmark_evaluation_strategy.md)                 | 2-Tier 벤치마크 체계 확정 (Mapping vs Emulation)  | 2026-03-02 |
| [Exp D TROY Matching 전략](./lab_meetings/2026-03-02_exp_d_troy_matching.md)                                | Drug compound split + N:1 matching + soft penalty | 2026-03-02 |
| [prior CV disease Recall](./lab_meetings/2026-03-02_prior_cv_disease_analysis.md)                           | Domain-Gated Ancestor Climbing 합의               | 2026-03-02 |
| [Ancestor Climb & Critic Distillation](./lab_meetings/2026-03-03_ancestor_climb_and_critic_distillation.md) | **A/B/C variant 비교, LLM Critic 대체 전략**      | 2026-03-03 |
| [Exp D Precision Recovery](./lab_meetings/2026-03-04_exp_d_precision_recovery.md)                           | **Drug guardrail, F1 28.6%→37.7% 회복**           | 2026-03-04 |
| [TROY vs SUPP Evaluation](./lab_meetings/2026-03-04_troy_vs_supp_evaluation.md)                             | **입력 텍스트 스타일 영향 정량화, ΔR=-14.6pp**    | 2026-03-04 |

---

## 📓 Daily Notes

### 최근 (TTE 통합 시대)

| 문서 | 내용 | 날짜 |
|------|------|:----:|
| [spec_ui_003_hitl_concept_mapping](./daily_notes/2026-03-28_spec_ui_003_hitl_concept_mapping.md) | SPEC-UI-003 HITL 개념 매핑 전체 구현 | 2026-03-28 |
| [spec_ui_002_review_and_e2e](./daily_notes/2026-03-27_spec_ui_002_review_and_e2e.md) | SPEC-UI-002 코드리뷰 + Playwright E2E | 2026-03-27 |
| [spark_production_integration](./daily_notes/2026-03-27_spark_production_integration.md) | Spark ~10x 성능 프로덕션 통합 | 2026-03-27 |
| [fe_be_contract_audit_and_fixes](./daily_notes/2026-03-26_fe_be_contract_audit_and_fixes.md) | FE-BE 계약 감사 및 수정 | 2026-03-26 |
| [cohort_generation_performance_optimization](./daily_notes/2026-03-26_cohort_generation_performance_optimization.md) | ETL 성능 최적화 | 2026-03-26 |
| [agent2_seeded_mapping_integration](./daily_notes/2026-03-25_agent2_seeded_mapping_integration.md) | Agent2 Seeded Mapping 통합 | 2026-03-25 |
| [eligibility_editor_and_adapter_fix](./daily_notes/2026-03-25_eligibility_editor_and_adapter_fix.md) | Eligibility Editor & Adapter 수정 | 2026-03-25 |
| [window_and_process_ux](./daily_notes/2026-03-25_window_and_process_ux.md) | Window & Process UX | 2026-03-25 |
| [chromadb_infra_eligibility_metadata](./daily_notes/2026-03-24_chromadb_infra_eligibility_metadata.md) | ChromaDB 인프라 & Eligibility Metadata | 2026-03-24 |
| [tte_integration_progress](./daily_notes/2026-03-20_tte_integration_progress.md) | TTE 통합 진행 | 2026-03-20 |

### 파이프라인 연구 시대 (2026-03)

| 문서                                | 내용                                                                      |    날짜    |
| ----------------------------------- | ------------------------------------------------------------------------- | :--------: |
| [2026-03-02](./daily/2026-03-02.md) | Exp D v2, A_direct v2, batch optimization, ancestor_climb, A/B/C 비교     | 2026-03-02 |
| [2026-03-03](./daily/2026-03-03.md) | Force Slow Path ablation, GOLD 정리, Exp D GOLD, polarity 분석            | 2026-03-03 |
| [2026-03-04](./daily/2026-03-04.md) | ABSENCE 태깅, 캐시, main skip, Precision Recovery, TROY vs SUPP           | 2026-03-04 |
| [2026-03-11](./daily/2026-03-11.md) | **Drug Class Refactoring, 4 Ablation ❌, Supervisor Phase 0 ✅ (+4.9pp)** | 2026-03-11 |

---

## 💬 Conversation Notes

| 문서                                                                         | 내용                                              |    날짜    |
| ---------------------------------------------------------------------------- | ------------------------------------------------- | :--------: |
| [TROY GOLD 비교 분석](./conversation_notes/7e02e8f3_TROY_GOLD_Comparison.md) | TROY v1.1/v3.4/GOLD 비교 + T1DM cross-branch 발견 | 2026-03-03 |

---

## 📊 Diagram Guides

| 문서                                                    | Agent   |
| ------------------------------------------------------- | ------- |
| [Trial Agent](./trial_agent_diagram_guide.md)           | Agent 1 |
| [Mapping Agent](./mapping_agent_diagram_guide.md)       | Agent 2 |
| [Extraction Agent](./extraction_agent_diagram_guide.md) | Agent 5 |
| [Analysis Agent](./analysis_agent_diagram_guide.md)     | Agent 6 |

---

## 🎬 Slides

| 문서                                                       | 내용                                    |
| ---------------------------------------------------------- | --------------------------------------- |
| [Incremental Exclusion](./slides/incremental_exclusion.md) | TROY LEADER Cohort Feasibility (Slidev) |

---

## 📦 Implementation Plans

| 문서                                                                                     |  Phase  |
| ---------------------------------------------------------------------------------------- | :-----: |
| [Phase 1 Semantic Intelligence](./implementation_plans/phase_1_semantic_intelligence.md) |  W1-W3  |
| [Phase 1 Detailed](./implementation_plans/phase_1_detailed.md)                           |  W1-W3  |
| [Phase 2 Assembler & Registry](./implementation_plans/phase_2_assembler_registry.md)     |  W4-W6  |
| [Phase 2 Detailed](./implementation_plans/phase_2_detailed.md)                           |  W4-W6  |
| [Phase 3 Analysis Engine](./implementation_plans/phase_3_analysis_engine.md)             | W7-W10  |
| [Phase 3 Detailed](./implementation_plans/phase_3_detailed.md)                           | W7-W10  |
| [Phase 4 Reporting & Validation](./implementation_plans/phase_4_reporting_validation.md) | W11-W13 |
| [Phase 4 Detailed](./implementation_plans/phase_4_detailed.md)                           | W11-W13 |

---

## 🏗️ Task Directories

| 디렉토리                                                    | 내용                                        |
| ----------------------------------------------------------- | ------------------------------------------- |
| [agent1_enhancement/](./agent1_enhancement/000_ARCH_MAP.md) | Agent 1 개선 작업 (NCT→PMID, PubMed parser) |
| [anchor_climb/](./anchor_climb/000_ARCH_MAP.md)             | Ancestor climbing 구현 작업                 |

---

## 📖 기타

| 문서                                                | 내용                     |
| --------------------------------------------------- | ------------------------ |
| [OHDSI Data Collection](./ohdsi_data_collection.md) | OHDSI 데이터 수집 가이드 |
