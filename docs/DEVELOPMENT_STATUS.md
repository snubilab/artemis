# ARTEMIS 3.1 개발 현황 보고서

**작성일**: 2026-02-20 (최종 검증: 2026-02-27)  
**실행 순서**: Supervisor → Trial → Mapping → Extraction → Analysis → Reporting

---

## 파이프라인 현황 요약

```
NL Query ──▶ [Trial Agent] ──▶ [Mapping Agent] ──▶ [Extraction Agent] ──▶ [Analysis Agent] ──▶ [Report Agent]
               IR 생성           Concept 매핑        Cohort 추출+조립       인과 추론           보고서 생성
               🟡 80%             🟡 75%              🟢 85%               🟡 60%              🟡 65%
```

| Agent | 진행률 | 핵심 역할 | 코드 규모 |
|-------|:------:|----------|:--------:|
| **Trial Agent** | 80% | NL/NCT → 구조화된 IR | 7파일, 43K |
| **Mapping Agent** | 75% | Text → OMOP Concept ID | 14파일, 120K |
| **Extraction Agent** | **85%** | IR+Concepts → Circe JSON → DB 쿼리 | 8파일, 60K |
| **Analysis Agent** | 60% | PSM/IPTW + Cox PH | 9파일, 47K |
| **Report Agent** | 65% | 시각화 4종 + HTML/PDF | 8파일, 30K |

---

## 1. Trial Agent (Agent 1 + Planner)

> **NL 질문 or NCT ID → ARTEMIS IR (Internal Representation)**

### ✅ 완료된 것
- **NL Query 파싱**: LLM → JSON → Pydantic IR 모델 (`ARTEMISRequest`)
- **NCT Protocol 파싱**: ClinicalTrials.gov API 연동 + 캐싱
- **PubMed Design Paper 보강**: NCT → PMID 탐색 → 적격기준 자동 보강
- **C2Q 전략** (ADR-014): 구조화된 프롬프트로 속성 분리 (entity/domain/value)
- **Planner**: Composite criteria → 실행 가능한 단위로 분해
- **Value Constraint 검증**: Measurement에 value_constraint 없으면 경고

### ⚠️ 알려진 문제
- Composite criteria 분해 시 OR/AND 그룹핑 누락 발생 (lab meeting 2/17)
- HbA1c 같은 측정값 규칙의 operator/value 파싱이 불안정 (>=7 vs >=10)
- Exit strategy 파싱이 기본값 의존

### 📋 TODO
| 우선순위 | 항목 | 난이도 |
|:-------:|------|:-----:|
| P1 | Composite criteria (OR/AND) 분해 정확도 개선 | 중 |
| P1 | Measurement value/operator 파싱 정밀화 | 중 |
| P2 | Exit strategy (약물 중단 기반) 파싱 개선 | 하 |
| P2 | Multi-arm trial 지원 (현재 2-arm만) | 상 |

---

## 2. Mapping Agent (Agent 2 + Consolidator)

> **텍스트 용어 → OMOP Standard Concept IDs**

### ✅ 완료된 것
- **Complexity Router**: 난이도 판별 → Fast Path (규칙 기반) / Slow Path (LLM)
- **Vector Search**: ChromaDB retriever + BioLinkBERT 임베딩
- **LLM Reranker**: Top-N 후보 재평가 (The Judge)
- **KG-RAG Expansion**: Neo4j 그래프 탐색 → 관련 concept 확장 + LLM Critic
- **UMLS Synonym Expansion** (ADR-012): Multi-query 동의어 검색
- **Drug Class Expansion**: 복합제 분해 (e.g., "Liraglutide" → GLP-1 RA)
- **Abbreviation Expansion**: 약어 → 전체명 변환
- **Concept Boosting** (ADR-011): DB 빈도 기반 가중치 자동 생성
- **Consolidator**: 형제 ConceptSet 병합

### 📊 벤치마크 진행상황 (LEADER trial 기준)

| 버전 | 측정 방식 | 결과 |
|:----:|----------|------|
| V1 | 1:1 Concept ID 비교 | Baseline |
| V2 | Resolved set (includeDescendants 반영) | 개선 |
| V3 | Semantic fingerprint | Domain confusion 패턴 발견 |
| **V4** | **N:1 parent-level** | **61.9% recall** |
| **V5** | **Dual-Track (미구현)** | [Lab Meeting 2/27](lab_meetings/2026-02-27_mapping_v5_benchmark.md) |

### 📋 TODO
| 우선순위 | 항목 | 난이도 |
|:-------:|------|:-----:|
| **P0** | 벤치마크 V5 (Dual-Track: Design Paper GT + TROY diagnostic) → [합의](lab_meetings/2026-02-27_mapping_v5_benchmark.md) | 중 |
| P1 | **KG²RAG 적용** — Grouped Context + Smart Expansion (Lab Meeting 2/19) | 상 |
| P1 | Domain confusion 감소 (Condition↔Procedure) | 중 |
| P2 | Non-standard vocab coverage (ICD9Proc, OPCS4) | 하 |

---

## 3. Extraction Agent (Agent 3 + Agent 4 + Cohort Executor)

> **IR + Concepts → Circe JSON 조립 → 검증 → DB 코호트 추출**

이 Agent는 세 단계로 구성됨:
1. **Assembler** (Agent 3): IR + ConceptSets → Circe-be JSON
2. **Validator** (Agent 4): Circe JSON 구문/의미 검증
3. **Cohort Executor**: Circe JSON → OMOP CDM SQL → 환자 DataFrame

### ✅ 완료된 것

**조립 (Agent 3)**:
- ConceptSet → Circe 변환 (includeDescendants, includeMapped)
- InclusionRule 조립 (Occurrence, StartWindow, ValueConstraint)
- DemographicCriteria (Age, Gender) 분리 처리
- Self-Heal Loop 1 — KEEP/PARTIAL/SKIP 결정 + HealAction 로그
- Window 정규화 — IR offset→Circe Coeff 변환, inversion 감지+교정
- Fuzzy ConceptSet 매칭
- Composite sub-criteria (CriteriaGroup, CriteriaList)

**검증 (Agent 4)** — ✅ 완료:
- Schema 검증, ConceptSet 참조 무결성, 의미적 검증
- Actionable error 분류 (LOOP_1_REMAP / LOOP_2_REASSEMBLE)

**코호트 추출**:
- Drug exposure 기반 treatment/comparator 추출
- Covariate 추출 (age, gender)
- Zero-patient 진단 (Loop 4) + Fallback 모드 (RFC-005)
- Broadsea synthea100k 스키마 연결 (ADR-010)
- ✅ **WebAPI SQL 연동 완료** (`webapi_client.py`, 346줄) — Circe JSON → `POST /cohortdefinition/sql` → SQL 생성 → cohort 실행 → polling → 결과 반환
- ✅ **CohortExecutor V2** (`cohort_executor.py`, 370줄) — WebAPI-first + fallback 모드 (`auto`/`always`/`never`)
- ✅ **CohortTableReference** 패턴 — `results_schema.cohort` 테이블 참조를 Analysis Agent에 전달

### ✅ E2E 검증 결과 (2026-02-27)

| 테스트 | 결과 |
|-------|------|
| WebAPI Health | ✅ v2.15.1 정상 |
| SQL Generation (`POST /cohortdefinition/sql`) | ✅ 5,624 chars (T2DM) |
| T2DM Cohort 생성 (SYNTHEA100K) | ✅ **8,155 patients, 2.8초** |
| TROY LEADER Cohort 생성 | ⚠️ 0 patients (아래 참조) |

**TROY LEADER 0환자 원인 분석:** → [상세 리포트](issues/LEADER_synthea100k_cohort_feasibility.md)
- Step 3 "Prior CV disease" 규칙에서 전멸 (1,238 → 272 → 272 → **0**)
- 개별 최대 킬러: "No insulin" 단독 적용 시 100% 전멸
- Synthea 구조적 한계: HbA1c 0건, Lira=Insulin 동반 처방

**4-Trial 약물 가용성 비교:** → [종합 리포트](issues/SUMMARY_all_analyses.md)
- LEADER (Liraglutide): ✅ 존재 | PLATO (Ticagrelor): ❌ | EMPA-REG (Empagliflozin): ❌ | DECLARE (Dapagliflozin): ❌
- 상세: [PLATO](issues/PLATO_synthea100k_cohort_feasibility.md) · [EMPA-REG/DECLARE](issues/EMPAREG_DECLARE_synthea100k_cohort_feasibility.md)

**SYNTHEA23M (2.7M) 추가 검증:** → [23M 리포트](issues/ALL_TRIALS_synthea23m_cohort_feasibility.md)
- Liraglutide 28,738명, EraStartDate 제거 시 Entry=14,397 → +Age≥50=2,343 → +CV disease=**9명**
- 23M에서도 구조적으로 희소 — simplified eligibility 필요

**발견된 버그:** → [BUG 리포트](issues/BUG_conceptset_stripping_silent_failure.md)
- WebAPI ConceptSet Stripping 시 Silent 0-Patient Failure
- ConceptSets 49개를 전부 유지해야 정상 동작

### ⚠️ 현재 병목
- Synthea 데이터 희소성: 4 Trial 중 LEADER만 약물 존재, Full TROY 적용 시 23M에서 **9명**
- HDPS 공변량 추출 (Analysis Agent)과의 연결: `CohortTableReference` → `FeatureExtractor` 조인 미구현

### 📋 TODO
| 우선순위 | 항목 | 난이도 |
|:-------:|------|:-----:|
| ~~**P0**~~ | ~~**InclusionRule → SQL 변환**~~ | ✅ WebAPI 위임으로 해결 |
| ~~**P0**~~ | ~~Circe JSON → WebAPI SQL Generation 연동~~ | ✅ 완료 (`webapi_client.py`) |
| **P1** | TROY simplified cohort 비교 (entry-only, exclusion 제외) | 중 |
| P1 | Drug Era / Custom Era 변환 지원 | 중 |
| P1 | Window inversion 자동 경고 (Agent 4) | 하 |
| P2 | 대규모 코호트 페이지네이션 | 중 |

---

## 4. Analysis Agent (Agent 5)

> **환자 DataFrame → 인과 추론 (PSM/IPTW + Cox PH)**

### ✅ 완료된 것
- **Propensity Score 모델**: Logistic Regression
- **IPTW**: Stabilized weights
- **PSM**: Nearest-neighbor matching
- **Cox PH 회귀**: `lifelines` 기반 Hazard Ratio + CI + p-value
- **Covariate Balance**: Before/After SMD 계산
- Survival data 생성 (합성 fallback 포함)

### ⚠️ 핵심 병목 (P0)
- **Feature Extraction이 age/gender 2개만** — 인과추론 최소 요건은 공변량 수십~수백 개
- HDPS (High-Dimensional PS) 미구현으로 실 분석 신뢰도 부족

### 📋 TODO
| 우선순위 | 항목 | 난이도 |
|:-------:|------|:-----:|
| **P0** | **HDPS 대규모 공변량 자동 추출** (condition, drug, procedure 이력) | 상 |
| P1 | Sensitivity Analysis (E-value, unmeasured confounding) | 중 |
| P1 | 실 DB 데이터 end-to-end 검증 (fallback 없이) | 중 |
| P2 | Subgroup analysis | 중 |
| P2 | Bootstrapped CI | 하 |

---

## 5. Report Agent (Agent 6)

> **분석 결과 → 시각화 + 임상 보고서**

### ✅ 완료된 것
- **Forest Plot**: HR, 95% CI 시각화
- **Kaplan-Meier Curve**: lifelines 기반 생존 곡선
- **Love Plot**: Before/After SMD 비교
- **PS Distribution**: Treated vs Control 분포
- **HTML Report**: 템플릿 기반 보고서
- PDF Report: WeasyPrint 기반 (불안정)

### 📋 TODO
| 우선순위 | 항목 | 난이도 |
|:-------:|------|:-----:|
| P1 | Study summary 섹션 자동 생성 (LLM 기반) | 중 |
| P1 | Table of Results (HR/CI/p-value 표) | 하 |
| P2 | CONSORT Patient Flow Diagram | 중 |
| P2 | PDF 안정화 (`fpdf2` 대안 검토) | 중 |
| P2 | 보고서 템플릿 커스터마이징 | 하 |

---

## 전체 P0 우선순위 (순서)

```
1. ✅ Extraction Agent: InclusionRule → SQL 변환
   └─ WebAPI 위임으로 해결 완료 (2026-02-27 검증)

2. Analysis Agent: HDPS 대규모 공변량 자동 추출
   └─ age/gender 2개론 인과추론 신뢰도 0
   └─ CohortTableReference → FeatureExtractor 조인 구현 필요

3. Mapping Agent: 벤치마크 V5 (Dual-Track)
   └─ TROY GT 품질 문제(88건) → Design Paper GT 전환 합의됨
   └─ 정확한 pipeline 평가 기준 없이는 개선 방향 불명

4. ⚠️ Synthea 데이터 한계 (2026-02-27 확인)
   └─ 4 Trial 중 LEADER만 약물 존재 (PLATO/EMPA-REG/DECLARE ❌)
   └─ LEADER Full TROY: 100K=0명, 23M=9명 (CV disease 희소)
   └─ Simplified eligibility (CV/Insulin 제외) 시 2,343명 확보 가능
   └─ 상세: docs/issues/SUMMARY_all_analyses.md
```

---

## Synthea100K 데이터 가용성 (2026-02-27 확인)

| 항목 | 결과 |
|------|------|
| 전체 환자 수 | 235,222명 |
| T2DM 환자 | 8,150명 |
| Liraglutide 노출 | **1,238명** (concept_id=42902992) |
| T2DM + Liraglutide | 1,238명 |
| Metformin 노출 | 있음 (24HR 500mg ER) |
| Insulin 노출 | 있음 (isophane, lispro) |
| TROY LEADER 전체 조건 충족 | **0명** (exclusion 과다) |

**WebAPI Source 설정:**

| sourceId | source_name | source_key |
|:--------:|-------------|------------|
| 1 | OHDSI Eunomia Demo Database | EUNOMIA |
| 2 | Synthea CDM (11.7K patients) | SYNTHEA |
| 3 | Synthea 100K (235K patients) | SYNTHEA100K |
| 4 | Synthea 23M (2.7M patients) | SYNTHEA23M |

---

## 관련 문건

| 유형 | 수량 | 주요 내용 |
|------|:----:|----------|
| ADR | 7 | KG-RAG, DB연결, Boosting, UMLS, TROY 재정의, C2Q, MedCPT |
| RFC | 5 | TROY Gap, EHR Navigator, KG-RAG, Multi-Concept, Feedback Loops |
| Lab Meeting | 10 | Benchmark V3, HbA1c, KG²RAG, Pipeline 품질, E2E 우선순위, TROY 재설계 |
| Tests | 31개 | Agent별 단위+통합 테스트 |
| **Issue Reports** | **9** | [종합](issues/SUMMARY_all_analyses.md) · [LEADER 100K](issues/LEADER_synthea100k_cohort_feasibility.md) · [PLATO](issues/PLATO_synthea100k_cohort_feasibility.md) · [EMPA/DECLARE](issues/EMPAREG_DECLARE_synthea100k_cohort_feasibility.md) · [23M](issues/ALL_TRIALS_synthea23m_cohort_feasibility.md) · [BUG](issues/BUG_conceptset_stripping_silent_failure.md) |
