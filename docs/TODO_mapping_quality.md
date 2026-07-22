# ARTEMIS Mapping Quality TODO

> Lab Meeting 2026-03-11 합의 기준. 모든 작업은 이 문서에서 추적한다.
> 각 항목은 atomic (1-2h 이내 완료 가능) 수준으로 분해.

## 📌 Task Map

| Task                           | 상태 | 관련 문서                                                                                                                                                                                                                                           |
| ------------------------------ | :--: | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **P0** includeDescendants 튜닝 |  ✅  | [include_descendants_gating](../../docs/lab_meetings/2026-03-10_include_descendants_gating.md) · [daily note](./daily_notes/2026-03-10_include_descendants_policy.md) · [precision_improvement](./lab_meetings/2026-03-09_precision_improvement.md) |
| **P1** Procedure/Surgery 매핑  |  🔶  | [RFC-010 Reranker](./rfc/RFC-010_Reranker_Cross_Branch_Recall.md) · [Multi-Trial Benchmark](./experiments/BENCHMARK_MULTI_TRIAL_GOLD_20260311.md) · [ABLATION_STUDY](./experiments/ABLATION_STUDY.md)                                               |
| **P1** Supervisor Quality Gate |  🔶  | [RFC-012 Supervisor](./rfc/RFC-012_Post_Agent2_Supervisor.md) · [ADR-023](./adr/ADR-023_Supervisor_Orchestrator_Promotion.md) · [ADR-024](./adr/ADR-024_Benchmark_First_Development.md) · [agent_reference](./architecture/agent_reference.md)      |
| **P2** Agent 1 Decomposition   |  ❌  | [ADR-017 Agent1 Role Reduction](./adr/ADR-017_Agent1_Role_Reduction.md) · [Consolidated Report §9](./experiments/BENCHMARK_CONSOLIDATED_REPORT.md)                                                                                                  |
| **P3** Drug Class Vocabulary   |  ✅  | [RFC-006 Drug Expansion](./rfc/RFC-006_Vocabulary_Based_Drug_Class_Expansion.md) · [ADR-022 ATC Threshold](./adr/ADR-022_ATC_Threshold_And_Concept_Metadata_Lookup.md) · [Multi-Trial §4](./experiments/BENCHMARK_MULTI_TRIAL_GOLD_20260311.md)     |
| **P4** Precision 개선          |  ❌  | [RFC-009 Critic Distillation](./rfc/RFC-009_Lightweight_Critic_Distillation.md) · [precision_30pp_strategy](../../docs/lab_meetings/2026-03-10_precision_30pp_strategy.md) · [precision_fix_v2](./lab_meetings/2026-03-09_precision_fix_v2.md)      |
| **P5** Pipeline Infrastructure |  ❌  | [RFC-005 Feedback Loops](./rfc/RFC-005_Pipeline_Feedback_Loops.md) · [RFC-011 ExpD Runtime](./rfc/RFC-011_ExpD_Runtime_Optimization.md)                                                                                                             |
| **P6** Gold 데이터 품질        |  ❌  | [gold_data_issues_report](./gold_data_issues_report.md) · [gold_data_remediation_todo](./gold_data_remediation_todo.md) · [gold_data_summary](./gold_data_summary.md)                                                                               |

## 🔥 Current Focus

**상태**: MRSTY + MRREL 통합 완료. PLATO 벤치마크 재실행 완료.
**다음 개선 방향**: ACS seed 품질 개선 (R=0% regression) → Precision 개선 (MRREL expansion 과다)

| 시도 (2026-03-13)       | 결과                  | 판정                         |
| ----------------------- | --------------------- | ---------------------------- |
| §3.1 MRSTY + MRREL 통합 | R +10.6pp, P -18.1pp  | ✅ Recall 대폭 개선          |
| Fibrinolytic (MRREL)    | R=0%→100%             | ✅ MRREL 완전 해결           |
| Anticoagulant (MRREL)   | R=38%→89% (partial)   | ✅ 48 concepts 정상 매핑     |
| ACS                     | R=38%→0% (regression) | ❌ seed 품질 저하 조사 필요  |
| CYP inhibitors          | R=0%→0%               | ❌ combined CUI 없음, 미해결 |

| 시도 (2026-03-11)                   | 결과             | 판정                   |
| ----------------------------------- | ---------------- | ---------------------- |
| §2.10 ATC+UMLS rewrite              | ΔR ~0pp, ΔP ~0pp | ✅ concept 품질만 개선 |
| §2.11 Domain-balanced retrieval     | ΔR -10.3pp       | ❌ revert              |
| §2.12 Pass 3 Footprint Guard (1000) | ΔR -10.9pp       | ❌ default OFF         |
| §2.13 Reranker Top-N 3→5            | ΔR -11.1pp       | ❌ revert              |

---

## P0: includeDescendants 튜닝 (S1) — ✅ 최적화 완료

- [x] ConceptSetRefiner 구현 (overbroad gating)
- [x] cohort_pipeline.py 연동 (`include_descendants=(cid not in overbroad_ids)`)
- [x] ~~Footprint Threshold ablation (1000 / 500)~~ → §2.12 ❌ regression. 현재 hybrid policy가 최적
- [x] ~~ConceptSetRefiner Pass 3 Adaptive Scope Guard~~ → §2.12 ❌ 코드 유지, default OFF
- [ ] IC ratio threshold 조정 (0.6~0.8 범위) → [include_descendants_gating](../../docs/lab_meetings/2026-03-10_include_descendants_gating.md)

## P1: Procedure/Surgery 매핑 품질 (S2)

### 완료

- [x] 근본 원인 진단: embedding confusion (ACS→Acrocephalosyndactyly, fibrinolytic→fibrinogen)
- [x] ATC expander: ingredient count ≤2 reject (`drug_class_expander.py`) (2026-03-11)
- [x] Drug class query → slow path 강제 (`workflow.py`) (2026-03-11)
- [x] UMLS diverse rewrite (slow path에서 다른 root word synonym 검색) (2026-03-11)
- [x] 하드코딩 약어 사전 제거 (`abbreviation_expander.py` → no-op) (2026-03-11)
- [x] ~~Fix B: Reranker Top-N 3→5~~ → §2.13 ❌ cross-branch noise, revert
- [x] ~~Domain-balanced retrieval~~ → §2.11 ❌ minority 도메인 강제 삽입, revert
- [x] Transplant domain_hint 조사 → 벤치마크 정상 (per-CS domain), 버그 아님

### ✅ 완료 (MRSTY 통합, 2026-03-13)

- [x] MRSTY.RRF → SQLite `mrsty` 테이블 추가 (`scripts/build_umls_mrsty.py`) (3.8M rows)
- [x] `umls_synonym_expander.py`: `get_cuis()`에 domain_hint 파라미터 추가 + MRSTY JOIN 필터링
- [x] `umls_synonym_expander.py`: MRSTY JOIN으로 CUI 필터링 구현 (DOMAIN_TO_STY 매핑)
- [x] `workflow.py`: `_slow_path()`에서 expand() 호출 시 domain_hint 전달
- [x] PLATO 벤치마크 재실행: Avg R 47.1%→57.7% (+10.6pp), Full 1→3 (2026-03-13)
- [ ] ACS seed 품질 regression 조사: R=38%→0% (2 raw concepts only → MRSTY 필터링 과도?)

### 미착수 (구조적 변경 필요)

- [x] ~~Fix A: `concept_set_refiner.py` — Procedure domain ancestor 예외~~ → R+1.6pp, P-7pp trade-off. Precision 유지 우선 → revert (2026-03-13)
- [ ] Fix C: Procedure seed template — compound query fallback seed
- [ ] SNOMED Branch Mismatch: EMPA bariatric — Multi-query 생성 필요
- [ ] Transplant: ChromaDB embedding이 procedure/complication 구분 불가 — Embedding 개선 필요
- [ ] Reranker prompt 개선 (RFC-010) — cross-branch concept 선택 방지

## P1: Supervisor Quality Gate (2026-03-11~)

> RFC-012, ADR-023, ADR-024 기반. Benchmark-first 정책 적용.

### 완료

- [x] `pipeline/supervisor.py` 생성 — `PipelineSupervisor`, `SupervisorReport` (2026-03-11)
- [x] `cohort_pipeline.py` Step 2.1 통합 (2026-03-11)
- [x] Hierarchical Expansion production 적용 (`_collect_rule_entities`) (2026-03-11)
- [x] RFC-012 Post-Agent2 Supervisor Quality Gate 작성 (2026-03-11)
- [x] ADR-023 Supervisor → Orchestrator 승격 결정 (2026-03-11)
- [x] ADR-024 Benchmark-First Development Policy (2026-03-12)
- [x] Production supervisor retry → report-only 전환 (ADR-024) (2026-03-12)
- [x] `benchmark_v5.py` Step 3.1 supervisor 통합 — production과 동일 모듈 (2026-03-12)
- [x] Agent Reference 문서 작성 (`docs/architecture/agent_reference.md`) (2026-03-11)
- [x] ADR-023 Phase 2: `supervisor.py`에 `run()` 추가, `cohort_pipeline.py` thin wrapper화 (2026-03-12)

### ✅ 완료 (LangGraph Supervisor Agent, 2026-03-14~15)

- [x] `supervisor.py`: MIN_SEED_COUNT 2→1, dead code 115줄 삭제, `detailed_log` 추가 (2026-03-14)
- [x] `supervisor_agent.py` 생성 — LangGraph StateGraph 기반 6-Agent 오케스트레이터 (2026-03-14)
  - [x] ArtemisState TypedDict, SupervisorDecision dataclass
  - [x] 6 Agent nodes + 5 Review nodes + 5 Routing functions + build_graph()
  - [x] Codex 리뷰 3건 수정 (format crash, assembly escalate, decoupling)
- [x] `orchestrator.py` 교체 (233줄→87줄): LangGraph 위임, backward compat 유지 (2026-03-14)
- [x] Domain Mismatch Gate: `_check_domain_mismatches()` 구현 + `review_mapping` 통합 (2026-03-15)
  - report-only (RETRY 미트리거), registered_sets 메타데이터 활용
- [x] Lab Meeting: LLM 매핑 검증 전략 합의 (전수 LLM Judge 불필요) (2026-03-15)
- [x] `tests/test_supervisor_agent.py` 28개 + `tests/test_supervisor.py` 7개 = 35/35 통과 (2026-03-15)

### TODO

- [x] `supervisor.py` `_step2_map()`: rule_context를 Agent 2에 전달 (reranker/critic 프롬프트 강화) (2026-03-15)
  - [x] parent_rule → context 파라미터로 전달 (workflow.py/reranker.py/critic.py 변경 불필요)
- [x] Agent 2 MappingResult에 path metadata 추가 (route_path/atc_expanded/critic_skipped/domain_overridden) (2026-03-15)
- [x] Mapping Audit Report: 통합 위험 신호 집계 (`audit_mapping_results()`) — severity CLEAN/WARNING/CRITICAL (2026-03-15)
- [x] 깨진 테스트 5건 수정 + Docker 테스트 `@pytest.mark.integration` 마킹 (258 passed/0 failed) (2026-03-15)
- [x] Retry 전략 데이터 검증: 1-seed entity 10건 slow path 재시도 → 0건 개선. v1 policy(empty+mismatch만 retry) 유효 확인 (2026-03-15)
- [x] MIN_SEED_COUNT 적정값 벤치마크: 현행 1 유지 결정 (2=76% 규칙 영향, recall 차이 미미) (2026-03-15)
- [x] Agent 2 호출 통일: `benchmark_v5.py` `invoke_agent2()` ↔ `supervisor.py` `_step2_map()` → `map_single_entity()` 공통 함수 추출 (2026-03-15)
- [x] `loop_results` 실제 populate (LangGraph state에 pipeline telemetry 추가) (2026-03-15)
- [x] High-risk entity audit 프롬프트 설계 + report-only 구현 (2026-03-15) → [llm_mapping_verification](../../docs/lab_meetings/2026-03-15_llm_mapping_verification.md)
- [x] LEADER/PLATO/ARISTOTLE 벤치마크에서 F1/precision 측정 (2026-03-15) → [llm_mapping_verification](../../docs/lab_meetings/2026-03-15_llm_mapping_verification.md)
- [x] Selective Retry Phase 0: Loop 1 `domain_hint`/`rule_context` 누락 수정 — `map_single_entity()` 호출로 교체 (2026-03-15)
- [x] Selective Retry Phase 1: `entity_key` 도입 — `{source}:{section}:{rule_idx}:{sub_idx}` 형식 (2026-03-15)
- [x] Selective Retry Phase 2: `raw_mapped_sets` 보존 — `ArtemisState` + `mapping_node()` (2026-03-15)
- [x] Selective Retry Phase 3: `mapping_retry.py` + `plan/execute_mapping_remediation` LangGraph 노드 + `SELECTIVE_RETRY` 라우팅 (2026-03-15)
- [x] Selective Retry Phase 4: Legacy Loop 1 → shared `mapping_retry.py`로 교체 (2026-03-15)
- [x] Selective Retry Phase 4.5: Option C staged domain correction — same-domain first, corrected-domain gated second (2026-03-20)
- [x] Selective Retry Phase 4.6: domain correction thresholds/env config (`SUPERVISOR_DOMAIN_CORRECTION_*`) 노출 (2026-03-20)
- [x] Supervisor routing rule update: `ESCALATE`는 status-only이며 distribution 브랜치에서 파이프라인 종료를 트리거하지 않음 (2026-03-20)
- [ ] Selective Retry Phase 5 (future): Agent 1 feedback — 벤치마크에서 IR fault 비율 측정 후 결정

## P2: Agent 1 Decomposition 개선 (S3)

- [x] E2E recall gap 분석 (A_direct vs E2E) (2026-03-15)
  - 37 rules 분석: LOW_RECALL_MULTI_SUB 14건, NO_DECOMPOSITION 1건
  - Drug domain 분류 오류### P3: Persistent R=0% Rules Investigation (CYP, Fibrinolytics, ACS)
**Status**: [x] Completed (2026-03-15)
- [x] Analyze `diagnose_r0.py` outputs for CYP inhibitors, Fibrinolytic agents, and oral anticoagulants.
- [x] Fix Agent 2 input bug in `benchmark_v5.py`: Use normalized `name` instead of raw `entity_text` from Agent 1. This restored Fibrinolytics and Anticoagulants which were failing due to noisy text.
- [x] Tune ATC Chrome distance threshold in `drug_class_expander.py` (0.9 -> 0.6) to prevent catastrophic mismatch (CYP -> CDK).
- [x] Implement Stage 0 Custom HITL mapping in `workflow.py` for CYP inhibitors directly to RxNorm ingredients.
- [x] Run E2E benchmark on ARISTOTLE and PLATO to verify R=0% drug class recovery.
## P3: Drug Class Vocabulary Gap (S4) — MRREL 구현 완료

### 완료 (2026-03-13)

- [x] ATC ChromaDB 한계 진단: fibrinolytic→fibrinogen, anticoagulant→ANTITHROMBOTIC 등 embedding 혼동
- [x] OMOP vocabulary 전수 조사: NDF-RT 미적재, SNOMED Substance→RxNorm 0건
- [x] MRREL.RRF → SQLite 적재 (7.4M rows, SAB: MED-RT/MSH/NCI/SNOMEDCT_US/RXNORM)
- [x] `drug_class_expander.py`: `expand_drug_class_via_umls()` 구현 (CUI → MRREL `isa` → RxNorm → OMOP)
- [x] Waterfall: MRREL first → ATC second (양쪽 ≥3 ingredient 검증)
- [x] PLATO benchmark: **fibrinolytic R=0%→100%**, Avg Recall +16pp

### 남은 이슈

- [x] Anticoagulant: A_direct에서 R=89% 달성 (MRREL 48 concepts 정상). E2E에서는 Agent 1 `[Condition]` 분류 문제 잔존
- [ ] CYP inhibitors: "CYP inhibitors and inducers" combined CUI 없음 → MRREL 미매칭 (R=0%)
- [ ] ACS regression: R=38%→0% — MRSTY 필터링이 ACS seed를 걸러냈을 가능성
- [ ] Precision 하락: MRREL expansion이 과다 (fibrinolytic 28K, anticoagulant 25K resolved)
- [ ] 위 이슈 중 ACS/CYP는 **Agent 1 domain 분류 개선** (P2) 또는 seed 품질 개선에서 해결 필요

## P1: Cohort-Level Benchmark 데이터 파이프라인

> Jaccard Similarity 평가를 위한 합성 환자 생성 + ETL. 📄 [synthea_benchmark_data_pipeline](./synthea_benchmark_data_pipeline.md)

### 완료 (2026-03-16)

- [x] Synthea 타겟 모듈 3종 제작: `artemis_leader.json`, `artemis_plato.json`, `artemis_aristotle.json` (2026-03-16)
- [x] ETL SQL 로더 `load_synthea_benchmark.sql` — `providers.csv`/`organizations.csv` 누락 버그 수정 (2026-03-16)
- [x] LEADER 10k 환자 생성 + ETL + `benchmark_v6_cohort.py` 실행 (2026-03-16)
- [x] `visit_occurrence` Empty Join 버그 해결 (INNER JOIN 의존 → providers/organizations 로드) (2026-03-16)

### TODO

- [ ] 🚨 **Synthea 환자 발생 모듈 전면 개편 (LEADER/PLATO/ARISTOTLE)** — T2DM 외에 과거 심근경색(MI), 뇌졸중(Stroke) 등 심혈관계 과거력(CV disease)을 생성하도록 State 보강 (Gold 0명 원인)
- [ ] PLATO 타겟 환자 10k 생성 + ETL + `benchmark_v6_cohort.py` 실행
- [ ] ARISTOTLE 타겟 환자 10k 생성 + ETL + `benchmark_v6_cohort.py` 실행
- [/] Agent 1 파서 Boolean 로직 (AND/OR) 구조적 개선 — Rule 4에서 OR 조건을 AND로 파싱하여 전원 탈락
- [ ] 3개 trial 벤치마크 Jaccard > 0% 달성 확인

## P4: Precision 개선

- [x] ConceptSetRefiner (overbroad gating) 구현
- [x] `benchmark_v5.py`: overbroad gating 반영 — `no_expand_ids` 파라미터 연결 (2026-03-15)
  - `to_meta_dict()`에 overbroad_concept_ids 추가
  - MEN2/FMTC: P=0→27%, thienopyridine: 168K→감소
- [ ] `workflow.py`: Critic skip 조건 정교화 (relationship-aware)
- [ ] KG expansion cap 튜닝 (domain별 limit)
- [ ] Critic threshold 조정
- [ ] 결과 기반 다음 단계 결정 (Semantic Drift / RFC-009 Lite)

## P5: Pipeline Infrastructure (백로그)

> 2026-02 lab meeting 에서 도출. 현재 우선순위 낮음.

- [ ] Agent 4 validator: CodesetId=0 감지, 도메인 불일치, 빈 Criteria
- [ ] Feedback Loop Phase 0: Agent 3 Explicit Failure Report
- [ ] Feedback Loop Phase A~F (ir.py 모델 추가 → Loop 구현)
- [ ] Exp D: Drug compound split + N:1 matching
- [ ] dead code 정리 (`raw = text`)

## P6: Gold 데이터 품질 개선

> 📄 [gold_data_issues_report.md](./gold_data_issues_report.md) 읽어보고 문제 해결하기

- [ ] Orphan ConceptSet 정리 (LEADER 14개, PLATO 3개, EMPA-REG 1개)
- [ ] 중복 CS 통합 (LEADER: LVH, LVD, Revascularization)
- [ ] 미구현 criteria 명시적 문서화 (LEADER E-7, PLATO E-1/5/6)
- [ ] TROY 추가 기준 별도 표시 (substance abuse, pregnancy)
- [ ] Protocol-only baseline 벤치마크 (TROY 추가 기준 제외 후 재측정)
- [ ] LEADER insulin 배제 범위 검토 (NPH/long-acting/premixed 허용 확인)

### Gold Standard 확장 (신규 Trial) → [gold_data_build_checklist](./gold_data_build_checklist.md)

- [ ] ARISTOTLE Gold Standard 구축 (프로토콜 수집 → TROY 확인 → Merge → JSON → 검증 → 벤치마크 등록)
- [ ] ORAL (Tofacitinib) Gold Standard 구축 — ⚠️ RA 적응증 (기존 T2DM/ACS/AF와 다른 도메인)
- [ ] SELECT Gold Standard 구축 — ⚠️ 최신 trial (2020~), TROY 데이터 충분 여부 확인 필요

---

## 완료 아카이브

### 2026-W11 (03-10 ~ 03-16)

- [x] ConceptSetRefiner 구현 및 pipeline 연동 (2026-03-09)
- [x] includeDescendants hybrid policy wiring (2026-03-10)
- [x] Multi-trial benchmark 분석 (LEADER/EMPA-REG/PLATO) (2026-03-11)
- [x] ATC ingredient count 검증 추가 (2026-03-11)
- [x] Drug class → slow path 강제 (2026-03-11)
- [x] UMLS diverse rewrite 추가 (2026-03-11)
- [x] 약어 사전 제거 (2026-03-11)
- [x] Ablation §2.10-2.13: 4개 시도 모두 regression 확인 (2026-03-11)
- [x] Pass 3 Footprint Guard 구현 (default OFF) (2026-03-11)
- [x] Supervisor Phase 0: domain_hint 전달 버그 수정 (2026-03-11)
- [x] Supervisor module 생성 + benchmark/production 통합 (2026-03-12)
- [x] ADR-024 Benchmark-First 정책 수립 (2026-03-12)

- [x] MRSTY.RRF → SQLite mrsty 테이블 추가 (2026-03-13)
- [x] umls_synonym_expander.py domain-aware filtering (2026-03-13)
- [x] workflow.py domain_hint 전달 (2026-03-13)
- [x] MRREL.RRF → SQLite mrrel 적재 (7.4M rows) (2026-03-13)
- [x] drug_class_expander.py MRREL-first waterfall 구현 (2026-03-13)
- [x] PLATO fibrinolytic R=0%→100% (2026-03-13)
- [x] GEMINI.md 하드코딩 금지 룰 추가 (2026-03-13)
- [x] PLATO 벤치마크 재실행: Avg R 47.1%→57.7% (+10.6pp), Full 1→3 (2026-03-13)

### 2026-W12 (03-14 ~ 03-15)

- [x] supervisor.py MIN_SEED_COUNT 2→1, dead code 삭제 (2026-03-14)
- [x] supervisor_agent.py LangGraph StateGraph 오케스트레이터 생성 (2026-03-14)
- [x] orchestrator.py LangGraph 위임 교체 (2026-03-14)
- [x] Domain Mismatch Gate 구현 (review_mapping 통합) (2026-03-15)
- [x] Lab Meeting: LLM 매핑 검증 전략 합의 (2026-03-15)
- [x] test_supervisor_agent.py 28개 + test_supervisor.py 7개 = 35/35 통과 (2026-03-15)
- [x] supervisor.py _step2_map() rule_context 전달 (2026-03-15)
- [x] benchmark_v5.py rule_context AB 옵션 (--no-rule-context) (2026-03-15)
- [x] MappingResult path metadata 추적 (route_path/atc_expanded/critic_skipped/domain_overridden) (2026-03-15)
- [x] Mapping Audit Report 통합 (`audit_mapping_results()`) (2026-03-15)
- [x] 깨진 테스트 5건 수정: stale assertions, missing mocks, integration markers (2026-03-15)
- [x] Selective Retry Phase 0-3 구현: Loop 1 수정 + entity_key + raw_mapped_sets + mapping_retry.py (2026-03-15)
  - 65 tests pass (50 기존 + 6 entity_key + 9 mapping_retry)

---

_마지막 업데이트: 2026-03-17T00:05_
