# ARTEMIS 에이전트 기능 문서

## 1. 이 문서에 대해

기준 커밋은 `main` `7595486` (2026-09-23)이다. 이 문서의 모든 `path:line` 인용은
이 커밋 기준이다. 코드 인용은 `path:line` 형식(예: `src/agents/agent1/parser.py:262`)을
쓰고, 최근 변경 사항은 `commit-hash`(예: `a17a11e`)로 인용한다.

독자는 OMOP CDM, CIRCE/Atlas 코호트 정의, 임상시험 적격 기준에
익숙하지만 이 코드베이스와 그 히스토리는 처음 본다고 가정한다. 이 문서는 어떤 동작이
코드 어디에 있는지, 그리고 무엇이 최근에 바뀌었는지 찾는 용도다.

이 프로젝트가 판단하는 질문은 하나다. 자연어 적격 기준을 CIRCE JSON으로 **정확하게**
변환하는가, 그리고 그 JSON이 **논리적 결함이 없는가**다. 이 질문은 프로토콜 원문과
산출된 JSON만 있으면 답할 수 있고, 데이터베이스가 필요하지 않다. 기준 판정은
`data/gold/<TRIAL>/`(TROY v1.1)와 적격 기준 1건 대 1건으로, macro-averaged로
비교한다. 로컬 CDM에서 나온 환자 수는 품질 신호가 아니다 — 이 호스트의 모든 CDM은
합성 데이터이기 때문이다(`ajou_cdm`/`donga_cdm`/`keimyung_cdm`은
`scripts/synthesize_site_cdm.py --persons 10000`으로 만든 것이고, `synthea_cdm`은
생성기 출력이다). 로컬 카운트는 "이 데이터베이스에 무엇이 있는가"를 답할 뿐,
"프로토콜을 올바르게 읽었는가"는 답하지 않는다.

## 2. 전체 흐름

이 코드베이스에는 두 개의 서로 다른 코호트 조립 경로가 있다. 실제 병원에
전달되는 CIRCE는 **운영 API 경로**에서 나오고, Agent 3의 `CohortAssembler`를 쓰지
않는다.

| 경로 | 진입점 | CIRCE 조립 | 사용처 |
|---|---|---|---|
| **운영 API 경로** | `src/api/tte.py` → `TTEService`(`src/services/tte_service.py`) | `TTEService` 자체 인라인 빌더 — `_build_seeded_target_circe`(tte_service.py:5305), `_build_combined_treatment_circe`(tte_service.py:6018), `_materialize_seeded_*`(tte_service.py:4589/4633/4776) | Atlas UI, `scripts/export_seeded_cohorts.py`(전달용 내보내기 스크립트) |
| **별도 파이프라인(LangGraph)** | `src/pipeline/orchestrator.py`(`ArtemisPipeline`) → `src/pipeline/supervisor_agent.py` / `supervisor.py` | `src/agents/agent3/assembler.py`의 `CohortAssembler.assemble()`(assembler.py:69/74) + `src/agents/agent4/validator.py`의 `CirCeValidator.validate()` | `scripts/e2e_full_pipeline.py`, `scripts/run_e2e_synthea23m.py`, `scripts/benchmark_v6_cohort.py`, `scripts/verify_leader_design_e2e.py`, 벤치마크·검증 테스트 |

`src/api/main.py`는 `tte_router`(`src/api/tte.py`)와 `conceptset_router`만 마운트하고
`src/pipeline/orchestrator.py`를 참조하지 않는다(main.py:8,29-37). `CohortAssembler()`
또는 `agent3.assemble`을 호출하는 곳은 `src/agents/agent3/__init__.py`,
`assembler.py` 자체, `src/pipeline/supervisor.py:616`,
`src/pipeline/supervisor_agent.py:223`뿐이고 `tte_service.py`에서는 호출되지 않는다.
`value_constraint.py:868`, `circe_lint.py:535`에 나오는 `CohortAssembler` 언급은
주석일 뿐 실제 import가 아니다.

### 2.1 실행 순서 단계표(운영 API 경로)

| # | 단계 | 담당 | 산출물 |
|---|---|---|---|
| 1 | 임상시험 텍스트 획득 | `LogicDecomposer.parse_nct`(`src/agents/agent1/parser.py:262-528`) — NCT API → PDF → PMC 부록 → PMC 전문 → 저널 직접 다운로드 → PubMed 초록, 고정 우선순위 | `TrialData` |
| 2 | Agent 1 추출 | `LogicDecomposer.parse_nct` 본체 — LLM 1회 호출 + 고정 순서의 후처리 복구 체인 | `ARTEMISRequest`(IR) |
| 3 | Planner(`Agent 1.5`) | `CriteriaPlanner.plan`(`src/agents/planner/decomposer.py:293`) | 세부 기준으로 분해된 `ARTEMISRequest` |
| 4 | Agent 2 매핑 | `Agent2Workflow.process_with_details`(`src/agents/agent2/workflow.py:314`), `TTEService.process_eligibility`(tte_service.py:1687) | 기준별 OMOP concept set |
| 5 | `TTEService` CIRCE 조립(제한 기준 재진술 처리, 값 조건 포함) | `_build_seeded_target_circe` 등, `restated_clusters.py`/`restated_distinctness.py`/`value_constraint.py` | `structuredExpression`, 시드된 코호트 CIRCE |
| 6 | 내보내기 | `scripts/export_seeded_cohorts.py` | `output/circe_be/<date>/*.circe.json` |
| 7 | 전달 게이트(`delivery gate`) | `scripts/verify_circe_delivery.py` | (a)-(s) 체크 결과 |
| 8 | 발송 확인 시 출처 증명 기록 | `scripts/verify_delivery_provenance.py` + `deliveries/INDEX.json` + git 태그 | 복구 가능한 발송 기록 |

### 2.2 컴포넌트별 연결 상태

| 컴포넌트 | 상태 | 근거 |
|---|---|---|
| Agent 1(`LogicDecomposer`) | 운영 경로 | `tte_service.py:11648`이 `get_agent1(...).parse_nct(nct_id)` 호출(`_parse_trial_agent_ir_from_nct`) |
| Planner(`CriteriaPlanner`) | 운영 경로 | `tte_service.py:11650-11653`이 `get_planner(...).plan(ir)` 호출 |
| Agent 2(`Agent2Workflow`) | 운영 경로 | `tte_service.py`, `src/api/map_entity.py`가 `process_with_details` 호출 |
| `RFC-001` `ConceptSetRecommender` | 운영 경로(단, 최후 폴백 tier로만) | `tte_service.py:8460`이 `_recommend_seeded_concept_set_rag_fallback`(tte_service.py:8474-8562) 호출, 이 함수가 `self._get_seeded_concept_set_recommender().recommend(...)`(tte_service.py:8482) 호출 |
| Agent 3(`CohortAssembler`) | 별도 파이프라인 전용 | `rg`로 `tte_service.py`에서 참조 없음 확인 |
| Agent 4(`CirCeValidator`) | 운영 경로(단, `validate_design` capability만) | `TTEService.validate_design`(1599) → `_run_validator_on_study`(3822) → `agent4.validate()`(3825-3827) |
| Agent 5(`Agent5Workflow`) | 운영 경로 | `TTEService._run_agent5_analysis_wrapper`(8926) |
| Agent 6(보고) | 운영 경로(가져온 사본 우선, 내부 사본은 폴백) | `TTEService._build_agent6_workflow`(9302-9313) |
| `ConceptSetConsolidator` | 별도 파이프라인 전용 | `src/pipeline/supervisor.py`(`PipelineSupervisor.run`)와 검증 스크립트 3개에서만 인스턴스화, `tte_service.py`에서 참조 없음 |
| `threshold_classifier.py`(`ADR-032` 2단계) | 미연결 | `classify_criterion`/`classify_criteria`의 호출자는 자기 재귀 호출과 `scripts/eval_threshold_classifier.py`뿐 |
| `drug_name_normalizer.py`(PubChem) | 미연결(의도적) | 유일한 호출자는 `scripts/build_pubchem_synonym_db.py`(빌더)와 테스트뿐 |

## 3. Agent 1 — 선정·제외 기준 추출

### 3.1 `LogicDecomposer` — `src/agents/agent1/parser.py`(2518줄)

자연어 질의 또는 가져온 임상시험 프로토콜을 ARTEMIS IR(`ARTEMISRequest`)로 변환한다.
LLM 1회 호출로 원시 규칙 트리를 만든 뒤, 고정된 순서의 결정적인
후처리 복구를 적용한다.

**진입점**
- `LogicDecomposer.parse(query: str) -> ARTEMISRequest` — parser.py:236. 자유 텍스트
  경로(프로토콜 가져오기 없음). NCT/TTE 흐름에서는 쓰지 않는다.
- `LogicDecomposer.parse_nct(nct_id, json_path=None, enrich_from_pubmed=True, design_paper_pdf=None, papers_dir=None, verify_thresholds=True) -> ARTEMISRequest` — parser.py:262-528. **운영 진입점.**
- `get_agent1(model_name=None) -> LogicDecomposer` — parser.py:2504, 지연 초기화 싱글턴.
- 호출자: `TTEService._parse_trial_agent_ir_from_nct`(`tte_service.py:11647-11648`),
  한 줄짜리 위임 `return get_agent1(model_name=model_name).parse_nct(nct_id)`. 또한
  `TTEService._parse_trial_agent_ir`(11644-11645)이 자유 텍스트 경로용 `.parse(description)`을
  호출한다. `parse_nct`는 `src/pipeline/supervisor.py:282`, `src/pipeline/supervisor_agent.py:149`
  (별도 파이프라인 오케스트레이터)에서도 호출된다.

**입출력**
- 입력: `TrialData`(nct_fetcher.py) — `nct_id, title, conditions[], interventions[], inclusion_criteria[str], exclusion_criteria[str], primary_outcomes[], study_type, phase`.
- 출력: `ARTEMISRequest{target: CohortDefinition, comparator: CohortDefinition, outcome: CohortOutcome, concept_sets: []}`.
- `CohortDefinition{primary_criteria, inclusion_rules: [Criteria], exclusion_rules: [Criteria], exit_strategy, repair_accounting: [dict]}` — `src/models/ir.py:258-281`.
- `Criteria`(기준별 IR 노드), `src/models/ir.py:152-222` — 필드: `name, domain, entity_text, concept_set_id, source_text, source_span, logic_type("PRESENCE"|"ABSENCE"), window, value_constraint, value_constraint_error, sub_criteria: [Criteria], group_type("ALL"|"ANY"), conditional: bool`.
- `ValueConstraint`, `src/models/ir.py:59-149` — `op: "gt"|"lt"|"eq"|"gte"|"lte"|"bt"`, `value: float`, `value_high: Optional[float]`(`bt`에만), `reference_bound: "absolute"|"uln"|"lln"`, `unit_text`, `unit_concept_id`. `model_validator(mode="before")`(ir.py:90)가 모델이 내는 `{"op":"between","value":[lo,hi]}` 형태를 `op="bt", value=lo, value_high=hi`로 정규화한다. `model_validator(mode="after")`(ir.py:125)가 `value_high` 없는 `bt`와 역전된 범위(`value_high < value`)를 거부한다.

### 3.2 임상시험 텍스트 획득 — 우선순위 체인(`parse_nct` 스텝 1-2, parser.py:262-528)

1. `fetch_or_load_trial_data` 또는 `load_trial_data_from_file`(parser.py:298-301)로
   NCT 등록정보를 가져오기/불러오기.
2. 보강을 우선순위대로 시도, 하나가 성공할 때까지(parser.py:303-362):
   - 우선순위 1: `papers_dir`(명시 지정 또는 `data/papers/{NCT_ID}/`에서 자동 탐색) →
     `_discover_pdfs`(parser.py:866) → 파일별 `_enrich_from_pdf`(parser.py:983).
   - 우선순위 2: 단일 `design_paper_pdf`(하위 호환).
   - 우선순위 3: `enrich_from_pubmed=True`이면 `_enrich_from_pubmed`(parser.py:1121).

`_enrich_from_pubmed` 내부는 아래 4개 모듈이 담당하는 우선순위 체인이다
(`_enrich_from_pubmed`, parser.py:1121-1345):

1. **`PMID` 획득** — `pubmed_linker.py`. `extract_pmids_from_nct`(19행,
   `protocolSection.referencesModule.references[].pmid` 읽음), 폴백
   `search_pubmed_for_nct`(48행, PubMed `E-utilities` `esearch`),
   `get_design_paper_pmids`(81행, `BACKGROUND` 타입 참조를 `RESULT` 타입보다 우선).
2. **우선순위 A: PMC 부록/보충자료** — `pmc_supplement.py`.
   `download_pmc_supplements(pmcid, nct_id, output_dir=None)`(96행)가 `PMC Open Access`를
   조회(`PMC_OA_URL`, 19행), `.tar.gz` 번들(`_download_from_tgz`, 150행)을 직접
   PDF(`_download_direct_pdf`, 201행)보다 선호. 추출 파일은 `classify_supplement`(60행,
   파일명 키워드 매치로 `supplement`/`appendix`/`main`/`other` 분류, 미매치 파일은 `main`으로
   기본 처리)로 분류.
3. **우선순위 B: PMC 전문** — `pmc_fetcher.py`. `get_pmc_eligibility(pmid)`(189행)가
   `pmid_to_pmcid`(34행) → `fetch_pmc_fulltext`(70행, XML 정규식 제거) →
   `extract_eligibility_section`(116행) → `extract_eligibility_from_text`
   (pubmed_fetcher.py에서 `import`)로 이어짐.
4. **우선순위 C: 저널 직접 다운로드** — `paper_url_mapper.py`.
   `download_papers_for_doi(doi, nct_id, papers_dir=None)`(228행) →
   `build_paper_urls`(111행, DOI 접두어 기준 NEJM/Lancet/JAMA/BMJ/Annals용 저널별 URL
   템플릿, `_JOURNAL_MAP`, 19행) → `try_download_paper`(173행, `downloaded`/
   `paywalled`(401/403)/`unavailable`(404)/`error` 구분).
5. **우선순위 D**(parser.py 자체) — `fetch_pubmed_abstract`(pubmed_fetcher.py)로 PubMed
   초록 폴백.

이 체인의 모든 네트워크 호출은 `try/except`로 감싸 `None`/`[]`/타입이 있는 실패 상태를
반환한다(raise하지 않음). 단 `parser.py`의 `_enrich_from_pubmed`는 각 폴백 경계마다
`warnings.warn`을 낸다(오케스트레이션 레벨에서는 침묵하지 않음). 개별 가져오기 함수
자체는 `print()`로만 기록하는 경우가 있다(예: `pmc_fetcher.py` 54/60/66행은
`logger`/`warnings`가 아니라 다른 수식 없이 `print`).

**`eligibility_section.py`** — PDF의 `pdftotext` 원문에서 적격 기준 구간을 분류해
표/그림/저자목록이 LLM에 기준으로 들어가지 않게 한다. `extract_eligibility_section(full_text) -> Found|Truncated|Missing`
(110행), `LogicDecomposer._enrich_from_pdf`(parser.py:1037)에서 호출. `_is_contents_entry`
(82-107행)는 CARMELINA 부록이 점 리더 없이 목차를 나열하는 문제(목차 항목을 본문으로
오인해 20000자 캡처하고 기준 0건 추출)를 막기 위한 가드다.

**`enricher.py`** — `NCT-API` 소스와 논문(PDF/PMC/PubMed) 소스를 세 가지 전략 중 하나로
병합/대체한다. `enrich_trial_data(trial_data, pubmed_criteria, strategy) -> TrialData`(27행).
전략: `replace`(`_pick_richer`, 72행, 기준 수가 많은 쪽 선택하되 어느 한쪽이라도
`[OR-GROUP]`을 담고 있으면 병합으로 전환), `merge`(`_merge_criteria`, 105행,
`structural_verdict`로 중복 확인 후 `SequenceMatcher` 유사도 0.7 이상이면 스킵, 마지막에
`prune_superseded`로 이미 OR-GROUP에 흡수된, 그룹 없이 나열된 항목 제거), `supplement_priority`
(`_supplement_priority_merge`, 153행, PDF/부록이 기준 소스, NCT 항목은 유사도 0.5 미만일
때만 추가). `_strategy_for_role`(parser.py:921-929)는 `supplement_priority`를 role이
`{"protocol","supplement"}`인 경우로 제한한다 — 분류되지 않은(`main`) 논문은 병합만
허용하는데, 요약/결과 논문을 동등하게 병합하면 공유 기준이 중복되고 Circe는
`InclusionRules`를 AND로 결합하기 때문이다(문서화된 실패 사례: ARISTOTLE의 `one or more
of X`가 다시 AND로 바뀜, parser.py:908-915).

**`nct_fetcher.py`** — ClinicalTrials.gov API v2에서 임상시험 프로토콜을 가져와 캐시하고 파싱.
`fetch_or_load_trial_data`(178행, 캐시 우선) → `fetch_trial_data`(128행, 네트워크) 또는
`load_trial_data_from_file`(93행). `DEFAULT_CACHE_DIR = data/nct_cache/`(15행).
`_parse_criteria_text`/`_parse_items`(206-272행)가 API의 단일 `eligibilityCriteria`
문자열을 inclusion/exclusion 리스트로 분리하며, `18 - 60 years` 같은 숫자 범위가
쪼개지지 않도록 부정 전방탐색 정규식을 쓴다(259행 주석에
`Codex` 리뷰를 거쳤다고 기록).

**`pubmed_fetcher.py`**(1187줄) — PubMed 초록 fetch와, PDF/PMC/PubMed 공통으로 쓰는 자유
텍스트→기준 파서 두 역할을 한 파일에서 담당한다. `extract_eligibility_from_text(text) ->
{"inclusion": [...], "exclusion": [...]}`(410행)가 `_best_section_match` → `_parse_criteria_items`
순으로 처리한다: `_strip_running_header_lines`(351행)로 페이지 반복 헤더 제거 →
`_best_section_match`(156행)가 inclusion/exclusion 헤딩 패턴에 대해 목차/문장 중간
언급을 걸러낸 뒤 **살아남은 블록을 문자 오프셋 순으로 전부 `union`**(218행,
`sorted(blocks, key=lambda b: b[1])`) → `_parse_criteria_items`(750행)가 계층형
그룹을 `[OR-GROUP]` 문자열로 접고(`_collapse_hierarchical_groups`, 516행) 정규식
분리(`_regex_parse_criteria`, 832행) → 정규식이 200자 넘는 구간에서 5개 미만 항목만
낼 때 LLM 검증 패스가 도는데(787행), `CONSORT` 참가자 흐름표로 판정되면
(`_is_participant_flow_table`, 1009행) 이 패스는 명시적으로 거부되고 로그로 남는다
(`LLM_PASS_REFUSED_MARKER`, `LLM_PASS_EMPTY_MARKER`와 구분). `rejoin_stranded_superscripts`
(306행)는 `pdftotext`가 지수 단위를 별도 줄로 떼어내는 문제를 복구하며, 조건 세 개가
모두 성립할 때만 복구를 실행하고 애매하면 그대로 둔다.

### 3.3 처리 단계 전체 순서(`parse_nct`, parser.py:262-528)

1. 임상시험 데이터 가져오기/불러오기(§3.2 1단계).
2. 보강, 우선순위 순(§3.2 2단계).
3. `_normalize_trial_data_for_stable_hash`(parser.py:65) — 공백/NBSP 정리, 정확히
   일치하는 중복 제거. **의도적으로 정렬하지 않는다**(§3.11 참고).
4. `_format_criteria`(parser.py:555)로 각 줄에 결정적으로 파싱한 값 조건을 주석 달아
   NCT 전용 프롬프트(`NCT_DECOMPOSITION_PROMPT`, prompts.py:484) 구성.
5. `(model_key, system_prompt, prompt)`로 키를 만드는 디스크 캐시를 거쳐 LLM 호출 —
   `_ir_cache_key`(parser.py:531), 캐시 디렉터리 `data/cache/agent1_ir/`, 파일명
   `{nct_id}_{model_key}_{hash}.json`. `_ir_cache_enabled()`(parser.py:56)가
   `AGENT1_IR_CACHE_ENABLED` 환경변수(기본 on)로 게이트.
6. `_build_artemis_request`(parser.py:1394) → `_build_cohort_definition`(parser.py:1438)
   → `_build_criteria`(parser.py:2323)가 LLM JSON에서 `Criteria` 트리를 재귀적으로 구성.
7. `inclusion_rules`에 대한 후처리 복구(고정 순서, 각 스텝 직후 `assert_repairs_accounted`로
   게이트, parser.py:1463-1536) — §3.4 참고.
8. `_validate_measurement_rules`(parser.py:1972) — inclusion/exclusion 양쪽에 로그만,
   변형 없음.
9. 커버리지 갭 경고(parser.py:453)와 값-조건 커버리지 경고(parser.py:478) — 둘 다
   `warnings.warn`, raise하지 않음.
10. `verify_thresholds=True`(기본값)이면 `_llm_review_value_constraints`(parser.py:621,
    2번째 LLM 호출) 후 `_repair_threshold_misses`(parser.py:690, 미해결 항목마다
    `_llm_match_dropped_threshold`로 3번째 LLM 호출, parser.py:797).
11. `ARTEMISRequest` 반환. `self.last_paper_status`는 호출자가 별도로 조회한다
    (`TTEService._get_last_paper_status`, tte_service.py:11536-11541).

### 3.4 값 조건과 범위 처리, 후처리 복구 체인(고정 순서)

`ValueConstraint.op="bt"`가 도입되기 전에는 모델이 낸 모든 범위(예: CAROLINA의
`eGFR 30-59`)가 파싱 시점에 거부되고, 이후 단계에서 LLM이 값 조건을 누락한 것으로
오진단됐다(ir.py:66-72 `docstring`). 아래는 범위를 온전히 재구성하는 복구 체인이며,
순서는 코드에 명시돼 있다(parser.py:1477-1502): inclusive-upper-bound가 split-band보다
먼저(상한이 `gt`로 교정돼야 병합 가능), split-band가 band-tier보다 먼저(band가 온전해야
대안으로 인식 가능), 셋 다 `Pattern E`보다 먼저(그룹 없이 나열된 목록을 그룹으로 재작성하는 단계).

| 순서 | 복구 함수 | 적용 범위 | 내용 |
|---|---|---|---|
| a | `_repair_inclusive_upper_bounds`(parser.py:1571-1680) | inclusion만 | 프로토콜 줄이 명시적 상한을 담고 있을 때(`inclusive_upper_bounds(source_text)`, parser.py:161-187, `source_text`만 읽고 `name`은 읽지 않음) `gte`/`lte`로 인코딩된 `ABSENCE` 기준을 교정. `gte`는 경계를 1만큼 이동(`NOT(>=X)`=`<X`이지 `<=X`가 아니므로), `lte`는 부호를 뒤집음(`NOT(<=X)`=`>X`). 둘 다 `De Morgan` 상 올바른 `gt`로 재작성. |
| b | `_repair_split_bands`(parser.py:1843-1970) | inclusion만 | 동일 analyte·줄·domain의 인접한 `PRESENCE`-`gte`/`ABSENCE`-`gt` 쌍(`_band_key`, parser.py:1811-1841)을 하나의 `bt` 기준으로 병합. Circe의 `inclusive` `bt` 형태인 `[gte lo, gt hi]`만 병합하고, `half-open` 쌍은 병합하지 않고 그대로 둔다(parser.py:1918-1929). |
| c | `_repair_band_tiers`(parser.py:2165-2260 부근) | inclusion만 | 하나의 analyte에서 인접한 대안 `CLOSED` `band`(`op=="bt"`)를 `ANY` 그룹으로 병합. 키는 domain/analyte/단위/reference_bound/logic_type/시간창(`window`)이고, 의도적으로 `source_text`는 키에 넣지 않는다(CAROLINA의 HbA1c 3개 tier가 각각 다른 줄을 갖기 때문). |
| d | `_repair_pattern_e`(parser.py:2260) | inclusion만 | 그룹 없이 나열된 목록을 그룹 구조로 재작성. |
| e | `_repair_protocol_windows`(parser.py:1682) | inclusion과 exclusion 모두 | §3.7 참고. |

**Planner 쪽 가드 — `_torn_range_declined`**(`src/agents/planner/decomposer.py:192-279`)는
동일 수정(커밋 `a17a11e`)의 두 번째 절반이며 Agent 1이 아니라 Planner에 있다. Planner의
LLM이 제안한 분해가 (a) 모두 같은 부모 analyte를 지칭하고, (b) 모두 한쪽 방향 경계값
(`gt/gte/lt/lte`)을 갖고, (c) 모두 같은 단위를 쓸 때 분해를 거부한다. 거부되면 기준은
Agent 1이 추출한 그대로 남는다(`sub_criteria` 없음, `group_type` 그대로). 이는
CARMELINA #12/#13 결함과 정확히 같은 모양이다 — 모델이 `HbA1c`를 상위 개념으로 취급해
자신의 범위를 두 개로 쪼개고, 각 멤버가 자기 연산자와 반대되는 것을 이름으로 갖게 되는
경우다. `_decompose_criterion`(decomposer.py:458)에서 멤버 구성 후, `criterion.sub_criteria`
할당 전에 호출된다.

**테스트**: `tests/test_range_split_and_lte_upper_bound.py`(12개, `_torn_range_declined`와
`lte` 상한 케이스), `tests/test_repair_accounting_and_inclusive_bounds.py`(21개),
`tests/test_value_constraint_range_operand.py`(25개).

### 3.5 `repair_accounting.py` — `RepairLedger`와 게이트

`parser.py`의 모든 후처리 복구가 기록을 남기는 `RepairLedger`이자, 그 기록을 강제하는 게이트다.
`RepairLedger` 클래스(96행)에 `.departed()`(114행), `.demoted()`(133행),
`.rewritten()`(145행)가 있고, `assert_repairs_accounted(before, after, ledger, role)`
(184행)이 **미기록으로 사라진 기준이 있으면 `UnaccountedDepartureError`를 `raise`**한다
(도메인·이름·프로토콜 줄 prefix를 명명해서). `_build_cohort_definition`(parser.py:1463-1536)에서
각 복구 스텝 직후 호출된다.

세 가지 처리 분류(`KNOWN_DISPOSITIONS`, 53행): `departure`(트리에서 사라짐 — 생존
기준에 병합되거나 폐기됨), `demotion`(트리에는 남지만 최상위에서 합성 그룹 내부로
이동 — `accounted_ids()`(164-178행)에서 "처리됨"으로 세지 않는다, 나중 복구가 demotion을
근거로 실제 삭제를 설명하지 못하게 하기 위해), `rewrite`(기준은 남고 의미가 바뀜 — 예:
연산자 부호 반전). `REPAIR_ACCOUNTING_KEY = "_repairAccounting"`(45행)은 스토어
작성자, 적용 경로 이월, 전달 게이트 스크립트가 공유하는 단일 스펠링이다.

### 3.6 `temporal_grounding.py` — 시간창(window) 검증

기준의 `window`(index 대비 시작/종료 일수)를 그 프로토콜 줄이 실제로 말하는 바와
대조해, 단위 미변환·크기 오류·방향 반전 세 가지 결함을 교정한다(모듈 `docstring`
5-16행). `stated_interval(source_text, name) -> (Interval|None, how)`(236행)가
`parser._repair_protocol_windows`(parser.py:1738)에서 호출되는 메인 함수다.
`_UNIT_DAYS`(39행: `hour=1/24, day=1, week=7, month=30, year=365`)와
`_UNIT_DAYS_UPPER`(52행, `month`는 30 또는 31, `year`는 365 또는 366을 허용)를 쓴다.
`_BACKWARD`/`_FORWARD` 단어 목록(70-84행)이 근접성으로 방향을 판정한다(CAROLINA가
한 줄에 과거 방향 lookback과 미래 방향 `planned within` 절을 모두 갖고 있음). **의도적으로
보수적**이다 — 이 기준에 붙일 수 없는 구간은 그대로 둔다(122개 IR 캐시 / 5092개 시간창
중 557개만 판정, 4535개는 보류, 모듈 `docstring` 24-28행).

### 3.7 Planner(`Agent 1.5`) — `CriteriaPlanner`

**파일**: `src/agents/planner/decomposer.py`(522줄). 클래스 `docstring`(284행)에 따르면
"Agent 1의 IR 출력에서 각 기준을 분석해 복합/상위 개념 용어를 구체적인 세부 기준으로
분해"하며, 파이프라인 위치는 `Agent 1 → [Planner] → Agent 2`다.

**진입점**: `CriteriaPlanner.plan(ir) -> ARTEMISRequest`(293행) → `_process_cohort`
(314행, target과 comparator 각각) → `_decompose_criterion`(337행, 최상위 규칙별).
`get_planner(model_name=None)`(510행, 지연 싱글턴). 호출자:
`TTEService._plan_trial_agent_ir`(tte_service.py:11650-11653).

**처리(`_decompose_criterion`, 337-491행)**
1. `entity_text`가 None이거나 `sub_criteria`가 이미 있으면 스킵(345행).
2. `DECOMPOSITION_PROMPT`(planner/prompts.py:48)를 `name, entity_text, domain, logic_type,
   source_text`로 구성(`source_text`가 없으면 `entity_text` 대신 빈 문자열 — `entity_text`가
   이미 정규화되어 손실된 paraphrase일 수 있기 때문, 주석 349-356행).
3. LLM 호출(`self.llm.invoke`, 371행) → `_extract_json`(493행, JSON 파싱 실패 시
   `{"decompose": False}`로 **조용히 폴백** — §3.9 참고).
4. `decompose=True`고 `sub_criteria`가 비어있지 않으면: `_exception_kept_whole`을 먼저
   확인(379행) — 이 조건이 성립하면 `criterion.entity_text`만 재작성하고 sub_criteria는
   만들지 않고 반환.
5. 아니면 각 `Criteria` 서브 객체를 구성 — `value_constraint`는 멤버 자신의
   `value_constraint_text`에서 파싱(`parse_value_constraint`, 절대 부모에게서 상속하지
   않음, 주석 396-403행); `source_span`은 `_grounded_span`(41행)으로 검증.
6. `_torn_range_declined`(458행) — §3.4 참고. 성립하면 기준을 변경 없이 반환.
7. 그 외에는 `sub_criteria`와 `group_type`을 확정.

**가드(적용 순서)**
- `_grounded_span`(41-96행) — 클레임된 서브텀 명명 span이 `source_text`의 실제
  substring이면서(`_comparison_form`, 대소문자·공백·백슬래시 허용) 그 서브텀과 명명
  단어를 공유하는지 두 단계로 검증(CAROLINA에서 진짜 substring이지만 상위 개념을
  가리키는 경우를 2번째 게이트가 잡음).
- `_exception_kept_whole`(99-180행) — `X except for Y` 형태의 분해를 거부해
  `resolve_entity_exception`(§4)이 뺄셈을 수행하게 함. 118개 코퍼스 분해 그룹 중
  1건에서 발동.
- `_torn_range_declined`(192-279행, §3.4 참고).

### 3.8 재진술/중복 기준 — SPEC-INFRA-003/004(`src/services/`, 범위 밖이지만 필수 참조)

이 처리는 Agent 1/Planner가 아니라 `src/services/`에 있고 Agent 2 매핑 **이후**에
작동한다(§5.3에서 상세 설명). `src/services/restated_clusters.py`(`SPEC-INFRA-003`
`REQ-005`)는 측정만 하고, `src/services/restated_demographics.py`가 첫 번째 통합
수정(Demographics 도메인 한정), `src/services/restated_distinctness.py`(`SPEC-INFRA-004`)가
모든 도메인으로 일반화한 버전이다. `criteria_dedup.py`(§3.9)는 이와 다른, 추출 이전
단계의 텍스트 레벨 중복 판정이다.

### 3.9 중복 기준 판정 — `criteria_dedup.py` / `criteria_dedup_judge.py`

**`criteria_dedup.py`**(어휘 기반) — 사전 IR, 순수 문자열, `[OR-GROUP]`을 인식하는
중복 판정. 여러 병합 지점에 흩어져 있던 4개의 독립적인 `difflib` 비교를 "이 기준이
이미 대표됐는가"라는 하나의 답으로 통합(모듈 `docstring` 1행). `structural_verdict(item,
existing_items) -> DROP|KEEP|UNDECIDED`(437행)가 매 병합 지점이 우선 호출해야 하는
함수다. `dedup_enabled()`(49행)가 `ARTEMIS_DISABLE_ORGROUP_DEDUP` 환경변수를 읽으며
"폴백이 아니라, 이 기능을 끄고 비교하려고 이름 붙인 스위치"라고 명시한다(40행), 기본 on.

**`criteria_dedup_judge.py`**(LLM 기반) — 같은 질문에 대한 대안적 답으로, 어휘 기반
방식을 대체하려는 것이 아니라 라벨된 표 위에서 점수를 비교하려고 만들어졌다(모듈
`docstring` 1-13행). `judge_or_group_restatement(candidate, items) -> JudgeResult`
(407행). `ARTEMIS_ORGROUP_JUDGE` 환경변수(`lexical`(기본)/`llm`/`off`)로 모드를 선택.
설계상 보장 3가지: (1) gold를 읽지 않음, (2) 단어 목록을 쓰지 않고 모든 의미 판단을
모델에 위임, (3) **조용한 폴백 없음** — LLM 오류나 파싱 불가 응답은 `is_restatement=None`인
`ERROR` 판정을 내고, 절대 `False`로 대체하지 않는다(폴백이 `False`라면 "모델이 유지하라고
답했다"로 잘못 읽힐 수 있기 때문).

이와 대조적으로 Planner의 `_extract_json`(decomposer.py:493-504)은 JSON 파싱 실패 시
`print()`만 하고 `{"decompose": False, "sub_criteria": []}`를 조용히 반환한다(기준을 원자적인
것으로 취급) — parser.py 자체의 `_extract_json`(parser.py:1380)이 raise하는 것과 다르다.

### 3.10 `threshold_classifier.py`(470줄, `ADR-032` 2단계, 운영 경로 미연결)

모듈 `docstring`(1-19행)에 따르면 임계값 처리를 3단계로 나눈 파이프라인의 2단계다 — `decompose`(LLM,
Agent 1) → **`classify`(LLM, 이 모듈)** → `structure`(코드, `src/services/value_constraint.py`).
`classify_criterion`/`classify_criteria`의 유일한 외부 호출자는 자기 재귀 호출과
`scripts/eval_threshold_classifier.py`뿐이다(저장소 전체 `rg` 확인, 테스트 제외). `parser.py`와
`tte_service.py`는 이 모듈의 분류기를 전혀 호출하지 않는다. `decomposer.py`(Planner)는
순수 헬퍼 `deescape`(129행)만 import한다. 실제 임계값 주석은
`src/services/value_constraint.py`(`annotate_value_constraints`/`parse_value_constraints`,
정규식 기반)를 거친다. 테스트는 41개로 충실하지만, 전용 `eval` 스크립트와 테스트 스위트
바깥에서는 쓰이지 않는다.

### 3.11 `ConceptSetConsolidator` — Consolidator(`src/agents/consolidator/consolidator.py`, 192줄)

모듈/클래스 `docstring`(1-25행)에 따르면 형제 `ConceptSet`을
`concept_ancestor`를 통해 최소공통조상(LCA)으로 병합하며, 파이프라인 위치는
`Agent 2 → [Consolidator] → Registry`다. `ConceptSetConsolidator(ontology_search=None,
max_separation=5)`(27행), `.find_lowest_common_ancestor(concept_ids) -> Optional[int]`
(51행), `.consolidate(mapped_sets) -> list[dict]`(99행, `parent_rule`로 그룹핑해
LCA가 존재하는 2개 이상 그룹을 병합). **이 클래스는 `src/pipeline/supervisor.py`(별도
파이프라인)와 검증 스크립트 3개에서만 인스턴스화되고, `src/services/tte_service.py`에서는
`import`도 호출도 되지 않는다**(§2 참조). 두 모드: 기본(`max_separation=5`, 공통 상위 개념이
있으면 항상 병합)과 적극(`KG_CONSOLIDATOR_AGGRESSIVE=true`, `max_separation=8` +
`information-content` 가드).

### 3.12 문서 순서 파괴 — Agent 1 실행 전 정렬 문제

`_normalize_trial_data_for_stable_hash`(parser.py:65-107)는 docstring에서 정렬이
결함으로 밝혀져 제거됐다고 설명하며, 현재 코드는 정렬하지 않는 것으로 확인된다(§3.3
스텝 3). 업스트림 `pubmed_fetcher.py`의 `_best_section_match`(218행)는 블록을 문자
오프셋 순으로 정렬해 보강된 목록이 문서 순서로 §3.3에 도달하게 한다. 중복 제거는
`seen` set으로 하며 정렬이 필요 없다.

### 3.13 IR 필드 요약과 구성

| 필드 | 값 |
|---|---|
| `ARTEMISRequest` | `target: CohortDefinition, comparator: CohortDefinition, outcome: CohortOutcome, concept_sets: []` |
| `CohortDefinition` | `primary_criteria, inclusion_rules: [Criteria], exclusion_rules: [Criteria], exit_strategy, repair_accounting: [dict]` (`src/models/ir.py:258-281`) |
| `Criteria` | `name, domain, entity_text, concept_set_id, source_text, source_span, logic_type, window, value_constraint, value_constraint_error, sub_criteria, group_type, conditional` (`src/models/ir.py:152-222`) |
| `ValueConstraint` | `op, value, value_high, reference_bound, unit_text, unit_concept_id` (`src/models/ir.py:59-149`) |

### 3.14 설정(환경변수)

| 변수 | 기본값 | 효과 | 위치 |
|---|---|---|---|
| `AGENT1_IR_CACHE_ENABLED` | on | IR 온디스크 캐시 읽기/쓰기 게이트 | parser.py:56-62 |
| `LLM_MODEL` | `"gpt-4o"` | `model_name`을 명시하지 않은 모든 `get_llm()` 호출의 모델 | `src/settings.py:40` |
| `ARTEMIS_DISABLE_ORGROUP_DEDUP` | `off` | `criteria_dedup.py` 어휘 dedup을 끄고 비교하는 스위치 | criteria_dedup.py:46-51 |
| `ARTEMIS_ORGROUP_JUDGE` | `"lexical"` | `criteria_dedup_judge.py`의 모드 선택자: `lexical`\|`llm`\|`off` | criteria_dedup_judge.py:69-78 |

### 3.15 LLM 사용(parser.py 범위)

1. 메인 추출 — `NCT_SYSTEM_PROMPT`+`NCT_DECOMPOSITION_PROMPT`(또는 `.parse()`의 경우
   `SYSTEM_PROMPT`+`DECOMPOSITION_PROMPT`), `_invoke_and_extract`(parser.py:1346),
   `temperature=0.0, response_format={"type":"json_object"}`(parser.py:223-227).
2. 스텝 10 임계값 재검토 — `THRESHOLD_REVIEW_PROMPT`(prompts.py:797),
   `_llm_review_value_constraints`(parser.py:621).
3. 스텝 10 임계값 복구 매칭 — `THRESHOLD_MATCH_PROMPT`(prompts.py:822),
   `_llm_match_dropped_threshold`(parser.py:797).

### 3.16 가드/폴백 요약

- `_build_criteria`(parser.py:2323) — `value_constraint`가 검증 실패하면 `None`으로
  설정하고 사유를 `value_constraint_error`에 기록(`logger.warning`으로 기록, 예외는
  전파되지 않음).
- `_extract_json`(parser.py:1380) — JSON 디코드 오류 시 `print()` 후 `ValueError` `raise`.
- `_invoke_and_extract`(parser.py:1346) — 파싱 전에 `raise_if_truncated`를 확인해
  토큰 상한에 잘린 응답을 `LLMTruncationError`로 명확히 `raise`.
- `_build_artemis_request`(parser.py:1394) — LLM이 `{target, comparator, outcome}`
  대신 그룹 없이 나열된 목록을 반환하면 문서화된 폴백으로 감싼다(로그 있음).
- `repair_accounting.assert_repairs_accounted` — §3.5 참고. 진짜 오류를 내고 멈추는 메커니즘.
- **조용한 폴백으로 표시**: `CriteriaPlanner._extract_json`(§3.7/3.9), `_enrich_from_pubmed`의
  개별 네트워크 가져오기 함수(§3.2, 오케스트레이션 레벨은 조용하지 않음).

### 3.17 테스트

`test_agent1.py` 13, `test_agent1_ir_cache_key.py` 6, `test_agent1_pattern_e_repair.py` 8,
`test_llm_threshold_review.py` 16, `test_repair_accounting_and_inclusive_bounds.py` 21,
`test_range_split_and_lte_upper_bound.py` 12, `test_value_constraint_range_operand.py` 25,
`test_protocol_time_windows.py` 12, `test_mapper_seed_drops_window_expressed_temporal.py` 9,
`test_stranded_group_threshold_refuses_the_member.py` 21,
`test_threshold_repair_role_scoping.py` 7,
`test_group_label_value_constraint_propagation.py` 22,
`test_criterion_protocol_line_provenance.py` 25, `test_extraction_truncation.py` 16,
`test_pdf_enrichment_log.py` 8, `test_protocol_line_grounding.py` 10,
`test_stored_group_label_constraint_reaches_circe.py` 9, `test_parser_paper_status.py` 5,
`test_atc_class_distance_threshold.py` 3(`def test_` 함수 개수, `parametrize` 확장 개수는
집계하지 않음). `test_pmc_fetcher.py` 16, `test_pmc_supplement.py` 16,
`test_07_pubmed_linker.py` 5, `test_paper_url_mapper.py` 49, `test_pmc_integration.py` 13,
`test_09_enricher.py` 4, `test_pdf_eligibility_section.py` 10,
`test_08_pubmed_fetcher.py` 7, `test_parse_criteria_items.py` 32,
`test_corpus_regression.py` 2, `test_pdf_hierarchy_preservation.py` 9,
`test_or_group_header_trigger.py` 7, `test_pdf_text_repair.py` 10,
`test_planner_domain_guidance.py` 5, `test_planner_entity_exception_split.py` 10,
`test_planner_source_span_grounding.py` 18, `test_planner_value_constraint_inheritance.py` 5,
`test_threshold_classifier.py` 41, `test_criteria_dedup.py` 20,
`test_criteria_dedup_judge.py` 24, `test_06_consolidator.py` 5.

## 4. Agent 2 — 개념 매핑

### 4.1 두 개의 병행 시스템

| | 프로덕션 경로 | `RFC-001` `ConceptSet Recommendation System` |
|---|---|---|
| 진입점 | `Agent2Workflow.process_with_details`(`src/agents/agent2/workflow.py:314`) | `ConceptSetRecommender.recommend`(`src/agents/conceptset/recommender.py:124`) |
| 구동 | `src/services/tte_service.py`(Agent 1 → Agent 2 → CIRCE), 기준별 | 자체 FastAPI 라우터 `POST /api/conceptset/recommend`, **그리고** 메인 파이프라인의 최후 폴백 단계(§4.6) |
| 후보 소스 | ChromaDB(`agent2/retriever.py`) | ChromaDB(`conceptset/rag_search.py`) **+** SQL `LIKE`(`conceptset/ontology_search.py`), RRF로 결합 |
| 확장 | Neo4j KG(`agent2/kg_expander.py`) | `PHOEBE` 동시발생 테이블(`conceptset/phoebe_client.py`) |
| 선택 | LLM reranker(`agent2/reranker.py`) → LLM critic(`agent2/critic.py`) | 의도 분리(`conceptset/nlu_router.py`) → cross-encoder/LLM/score reranker(`conceptset/clinical_reranker.py`) |
| 집계 | `agent2/logic.py`(`ConceptLogician`) → `conceptset/expression_builder.py` | `conceptset/expression_builder.py`(공유) |

두 시스템은 `expression_builder.py` 하나만 공유한다. `conceptset/` 아래
nlu_router/ontology_search/phoebe_client/clinical_reranker/stage1_pipeline/
stage2_pipeline/rag_search/rank_fusion/recommender/api.py는 모두 `RFC-001` 시스템이며,
§4.6에서 설명하는 폴백을 제외하면 `Agent-1`→`Agent-2`→CIRCE 운영 경로에 있지 않다.

### 4.2 후보 검색

**`ConceptRetriever`(프로덕션)** — `src/agents/agent2/retriever.py`. ChromaDB를 조회한
뒤 사람이 조정한 휴리스틱으로 재점수화한다(어휘 선호, 정확 매치 `boost`, `class` 선호,
도메인 불일치 `penalty`, 표준 개념 선호, 개념별 `weight` `boost`). 진입점:
`ConceptRetriever.search(query_text, n_results=20, domain_hint=None)`(retriever.py:220),
`ConceptRetriever.batch_search(query_texts, n_results=60, domain_hints=None,
max_batch_size=50)`(retriever.py:385). `_score_candidates`(retriever.py:273-383)는
Chroma에서 `n_results*3`(최소 60)을 가져와(retriever.py:234-241) `_distance_unit`(후보
집합의 평균 거리, retriever.py:132-164)으로 L2 거리를 무차원 비율로 정규화한 뒤 각종
`modifier`를 더한다. 개념 `weight`는 `_load_concept_weights`(retriever.py:180-218)가
`resources/concept_priority_defaults.json`(8개 항목, 수작업)과
`resources/concept_priority_db.json`(1097줄, Synthea/MIMIC 통계 자동 생성)을 병합한다.

가드: `search()`는 Chroma 쿼리 예외를 잡아 `print()`(로그 아님) 후 `[]`를 반환한다
(retriever.py:242-244) — **빈 결과로 조용한 폴백**. `batch_search()`도 도메인 그룹별
청크 단위로 예외를 잡아 경고 로그 후 `continue`(retriever.py:438-440) — 역시 조용하다.
`BatchSearchResults`(retriever.py:19-81)는 실제 발생했던 버그를 기록한다 — 같은 텍스트를
다른 `domain_hint`로 두 번 질의하면 `plain dict` view에서 충돌해 한쪽 후보가 덮어써졌다
(`by_index`/`by_pair` 추가로 수정, `plain-dict` view는 하위호환을 위해 남겨두고 `first-wins`).

**`RAGSearch`(`RFC-001`)** — `src/agents/conceptset/rag_search.py:24-117`. 같은 ChromaDB
컬렉션을 쓰되 후처리 점수화 없이 `score = 1/(1+distance)`만 쓴다. 출력 타입
`ConceptCandidate`(rag_search.py:13-21)는 `retriever.py`의 `CandidateConcept`와 이름은
비슷하지만 별개 `Pydantic` 모델이며, 점수가 높을수록 좋은지 낮을수록 좋은지가 반대다.
가드: 모든 예외를 잡아 `print()` 후 `[]` 반환(rag_search.py:73-75).

**`OntologySearch`(`RFC-001`)** — `src/agents/conceptset/ontology_search.py:25-198`.
임베딩 없이 `{schema}.concept`에 대한 SQL `LIKE '%text%'` 검색과, `concept_ancestor`를
통한 `get_descendants`/`get_ancestors`. `search_by_name(query_text, n_results=20,
domain_filter=None)`(43행). 모든 메서드가 DB 오류 시 `print()` 후 빈 리스트 반환.

**Rank fusion** — `src/agents/conceptset/rank_fusion.py`. `reciprocal_rank_fusion`
(13-61행)과 `weighted_reciprocal_rank_fusion`(64-109행)이 표준 RRF를 구현
(`score += 1/(k+rank)`, k=60).

### 4.3 재순위화와 critic

**`ConceptReranker`(프로덕션)** — `src/agents/agent2/reranker.py`. LLM 단일선택(`rerank`)과
`top-N` 다중선택(`rerank_topn`, `rerank_topn_batch`)을 제공. `rerank_topn(user_query,
candidates, top_n=3)`(reranker.py:154)이 `Agent2Workflow._slow_path`(workflow.py:799)에서
호출된다. 모델: `get_llm(temperature=0.0, json_mode=True)`(reranker.py:84), `LLM_MODEL`을
따른다. 프롬프트: `TOPN_SYSTEM_PROMPT`(reranker.py:43-56, 단일 정규 프롬프트 — 과거에
`rerank_topn`과 `rerank_topn_batch` 사이에 프롬프트가 복제돼 있어서 배치용 사본만
실제로 쓰이는 버그가 있었다고 주석에 기록).

`_refused(response)`(reranker.py:59-67) — `query_has_match: false` 응답은 "모델이
아무것도 고르지 않기로 했다"는 의미로 처리되며, 오류가 아니라 호출자는 `[]`를 그대로
받는다(`top-1` 강제 선택으로 대체하지 않음). "아무것도 고르지 않는 것이 옳은 답일 수
있다"고 프롬프트가 few-shot으로 명시한다(과거 `superlative-only` 프롬프트가 무의미한
쿼리 `qqzzxx nonexistent clinical term`에도 MI 개념 3개를 매치시킨 사례가 있었음).

`rerank_topn`은 체인 `invoke` 예외를 잡아 경고 후 단일선택 `rerank()`로 폴백
(reranker.py:202-205); `rerank_topn_batch`는 배치 내 항목별 예외를 잡아 로그 후
`results[orig_idx] = []`로 넘어간다(reranker.py:349-351). `Agent2Workflow._seeds_after_rerank`
(workflow.py:157-180)는 reranker의 `top-N`이 `retriever` 1위 후보를 빠뜨렸으면 재삽입하되,
reranker가 명시적으로 빈 리스트를 반환한 경우는 그대로 신뢰한다.

**`ConceptCritic`(`src/agents/agent2/critic.py`)** — KG로 확장된 후보(벡터 검색이 처음 고른 개념(`seed_concept_ids`) + KG 개념)에
대한 LLM 다중선택, 선택적 2-pass `self-reflection` 포함. `evaluate(query, seed_concept_ids,
kg_concepts, context=None, domain_hint=None, kg_concept_ids=None)`(critic.py:401)가
`Agent2Workflow._kg_expand_and_critique`(workflow.py:1009-1016)에서 호출되며,
`KG_EXPAND_MODE=clinical_anchor`(기본)이고 `anchor` 개수 > 10일 때, 또는 예전 방식의 `clinical`
모드에서 무조건 실행된다. 모델 선택은 `select_critic_model(domain_hint)`(critic.py:82-132)이
`AGENT2_CRITIC_MODEL_TIER` 환경변수로 결정 — `"follow"`(기본, `LLM_MODEL`을 그대로 씀),
`"auto"`(도메인별 단계: `{Condition,Drug,Measurement}`는 `gpt-4o-mini`, 그 외는
`gpt-4o`), 그 외 문자열은 모델 id로 직접 사용. `boolean` 유사 값(`none|null|off|false|true|0|1|no|yes|disable|disabled`)은 `LLMConfigurationError`로 거부한다.

캐싱: `CriticCache`가 `sha256(query|domain|resolve_model()|critic_signature())`로 키를
만든다(critic_cache.py:66-87). `critic_signature()`(critic.py:55-79)는 `_CRITIC_PROMPT_VERSION
= "2026-08-10-per-candidate"`(critic.py:52)를 손으로 관리하는 상수로 키에 접어넣는데,
프롬프트를 수정할 때 이 값을 같이 올리지 않으면 캐시가 새 프롬프트 아래에서 옛 답을
그대로 재생한다(2026-08-11 스키마 실험에서 이런 근접 실패가 문서화됨).

가드: KG 개념이 전혀 없으면 LLM 호출 없이 `seed_concept_ids`를 그대로 반환
(critic.py:430-432). LLM이 아무것도 선택하지 않으면 경고 로그 후 `seed_concept_ids`로
폴백하고, **이 폴백 결과 자체가 캐시된다**(critic.py:536-540). `openai.APIStatusError`가
`{401,403,404}` 상태(critic.py:44)면 `LLMConfigurationError`를 raise해 오류를 내고 멈추고,
그 외(일시적 오류)는 `ERROR` 로그 후 `seed_concept_ids`로 폴백한다(critic.py:546-558) —
이는 **결과적으로 조용한 폴백**이다: 호출자(`workflow.py`)는 정상적으로 보이는 반환값을
받으며 critic이 실제로 실패했다는 표시가 없다. `_default_llm`의 `max_tokens=4096`
(critic.py:300-306)은 무한 `truncation`(과거 최대 25분 `hang`)을 빠르고 눈에 띄는 JSON 파싱
실패로 바꾸기 위한 것이라고 문서화되어 있다.

### 4.4 Neo4j 지식그래프 확장 — `KGExpander`(`src/agents/agent2/kg_expander.py`)

처음 고른 OMOP 개념을 OMOP 어휘를 그대로 복제한 Neo4j 그래프를 통해 확장한다(`descendants`, `siblings`,
`maps_to`, `ancestors`, IC 기반 `ancestor_climb`). 진입점: `expand(concept_id,
strategy="clinical", max_sep=3, limit=50, domain_filter=None)`(kg_expander.py:191)가
`Agent2Workflow._kg_expand_and_critique`(workflow.py:899,923)에서 처음 고른 개념별로 호출되며,
`strategy`는 `KG_EXPAND_MODE` 환경변수(기본 `"clinical_anchor"`)로 결정된다.

모드: `clinical_anchor`(기본) — `get_ancestors(max_sep=2)` + `siblings` + `maps_to` +
`ancestor_climb`, **가공하지 않은 `descendants` 없음**(자손 확장은 CIRCE 자체의
`includeDescendants: true`에 위임). `descendants`/`clinical`(예전 방식) — 전체
`get_descendants`(또는 말단인 처음 고른 개념용 2-hop 폴백 `expand_from_ancestors`) + `siblings` +
`maps_to` + 별도 `ancestor_climb` + `get_ancestors`.

IC(Information Content): `compute_ic(descendant_count) = -log2(descendant_count /
2_750_364)`(kg_expander.py:174-189, `TOTAL_STANDARD_CONCEPTS`는 일회성 `SELECT COUNT(*)`로
하드코딩). `IC_THRESHOLD = 8.0`(kg_expander.py:47); `ancestor_climb`은 동적 임계값
`max(8.0, seed_ic - 2.5)`(kg_expander.py:568-573)를 쓴다.

가드: `_verify_neo4j()`(kg_expander.py:122-132)는 `KGExpander.__init__`에서 Neo4j에
연결할 수 없으면 URI와 `docker start telos-neo4j` 힌트를 담아 **`RuntimeError`를
`raise`**해 오류를 내고 멈춘다. `_get_pg_descendant_counts`(kg_expander.py:698-700)는 Postgres
오류를 잡아 경고 후 `{}`를 반환하는데 — 빈 dict는 모든 개념의 IC가 최댓값(20.0)으로
계산됨을 의미하므로, Postgres 장애 시 `ancestor_climb`의 IC 필터가 아무것도 걸러내지
않게 된다(`fail-open`이며 "안전한" 방향과 반대). `Agent2Workflow._kg_expand_and_critique`는
`kg.expand(...)` 호출 전체를 try/except로 감싸며, 어떤 예외든 `(seed_ids, [], False)`
(workflow.py:967-969)로 조용히 폴백한다.

### 4.5 개념집합(concept set) 구성

**`ConceptSetRefiner`(`src/agents/agent2/concept_set_refiner.py`)** — KG 확장/critic
이후 정밀도 필터. `refine(seed_ids, kg_concepts, query_text, domain_hint=None)`
(concept_set_refiner.py:138), `ENABLE_REFINER`(기본 `"1"`)로 게이트. 2단계:
(1) **상위 개념 포함관계 제거** — `_find_subsumed_ancestors`(326-367행)가
`concept_ancestor`를 배치 조회해 보유 집합에 이미 포함된 자손을 가진 상위 개념을 제거.
(2) **`includeDescendants` 정책** — `INCLUDE_DESC_SEEDS_ONLY`(기본 `"1"`)로 관계-인식
모드(자손 수가 1~50000 사이일 때만 포함, Drug 도메인은 예외로 항상 포함)와
예전 방식의 정적 임계값 모드(`REFINER_FOOTPRINT_THRESHOLD`, 기본 3000)를 선택. 롤백 가드
(302-312행): 제거 결과 원래 처음 고른 개념 수보다 적어지면 그 호출의 제거와 `overbroad_ids` 표시를 전부
취소하고 전체 후보를 반환(`ROLLBACK` 경고).

**`ExpressionBuilder`(`src/agents/conceptset/expression_builder.py`)** — 그룹 없이 나열된
`ConceptCandidate` 리스트를 ATLAS/CIRCE `ConceptSetExpression`으로 변환(상위 개념으로 합치기, 표준
개념 검증, `includeDescendants`/`isExcluded` 태깅). **두 시스템 모두 공유**한다.
`build_expression(candidates, roll_up=True, default_logic="INCLUDE", criterion_name=None,
seed_concept_ids=None)`(expression_builder.py:129). `_roll_up`(366-424행) 순서:
(1) `_drop_non_seed_ancestors`(296-364행, 커밋 `f53b71a` — §9 참고), (2)
`_filter_overbroad`(241-294행, `AGENT2_ROLLUP_MAX_DESCENDANTS`(기본 500) 초과 시
제거, 전부 제거되면 원본 유지), (3) 표준 `subsumption` 상위 개념으로 합치기.
`_validate_standard_concepts`(201-239행)는 `standard_concept='S' AND invalid_reason
IS NULL`로 필터링하며, `QueuePool` `timeout` 시 2초 대기 후 한 번 재시도하고 다른 예외는
"모두 유효한 것으로 간주"로 폴백한다(주석: `Fallback: assume all valid` — 조용함).

**`ConceptLogician`(`src/agents/agent2/logic.py`)** — 선택 후 도메인별 교정. 모든
메서드가 `_check_db()`(66-100행)로 DB 접근 게이트되며, DB가 없으면 입력을
변경 없이 반환한다. `_check_db()`는 성공은 프로세스 수명 동안 캐시하고, 실패는
`LOGICIAN_DB_PROBE_RETRY_SECONDS`(기본 60초) 후 재시도한다(커밋 `3b1a287` — §9 참고).
- `roll_up_to_rxnorm_ingredients(concept_ids)`(233-378행) — `concept_ancestor`
  조회, 이름 기반 폴백(`_resolve_ingredient_by_name`), 마지막 안전망(결과에 Ingredient급
  RxNorm 개념이 하나도 없으면 결과 전체를 대상으로 재시도).
- `drop_qualitative_findings(concept_ids)`(119-182행) — Measurement 도메인 전용,
  `concept_class_id='Clinical Finding'` 멤버 제거(전부 제거되면 원본 유지).
- `drop_wrong_entity_class_for_condition(concept_ids)`(390-496행) — Condition
  도메인 전용, LOINC Survey/Question `class`, Procedure 도메인, `history-of` Observation
  개념 제거(전부 wrong-entity면 빈 리스트를 반환 — 의도적).
- `drop_wrong_entity_class_for_observation(concept_ids)`(503-621행) — Observation
  도메인 전용(`SPEC-INFRA-005`), SNOMED Substance/Procedure class는 무조건 제거, LOINC
  Survey/Question `class`는 경쟁 후보가 있을 때만 제거.
- `prune_empty_concepts(concept_ids)`(623-630행) — **`passthrough` 스텁**. 주석에
  `TODO: Implement domain-aware pruning when DB is available`라고 적혀 있지만 `workflow.py`
  여러 곳에서 필터링하는 것처럼 계속 호출된다.

### 4.6 이름 해소 우선순위와 폴백 단계

`AGENTS.md`의 `NAME RESOLUTION OWNERSHIP` 절에 따르면, 소유권은
`TTEService._recommend_seeded_concept_set`(`src/services/tte_service.py`, 이 범위
밖)이며 모든 기준/target 문자열을 고정 우선순위로 흘려보내고 첫 번째로 `None`이
아닌 단계가 이긴다:

```
정확한 RxNorm ingredient
  → trial-MeSH alias
  → 기준 캐시
  → Agent2Workflow(QueryExpander 큐레이션 확장 → ATC drug-class → ConceptRetriever.batch_search → reranker)
  → RAGSearch 폴백(= RFC-001 ConceptSetRecommender 전체)
```

`tte_service.py:8460`이 `_recommend_seeded_concept_set_rag_fallback`을 호출하고, 이
함수(tte_service.py:8474-8562)가 `self._get_seeded_concept_set_recommender().recommend(...)`
(tte_service.py:8482)를 호출한다 — 즉 `RFC-001` `ConceptSetRecommender` 전체 파이프라인이
메인 파이프라인의 최후 폴백 단계다.

이 우선순위에서 세 가지 메커니즘은 완전히 구현·테스트되었지만 이 환경에서는 꺼져 있다:

| 단계 | 위치 | 꺼진 이유 |
|---|---|---|
| `trial-MeSH alias` | `tte_service.py`(범위 밖) | `trialMetadata.interventionMeshTerms`가 필요하고, 원본 임상시험 등록정보 payload가 포함된 스터디에서만 기록됨 |
| `QueryExpander` UMLS 조회 | `src/agents/agent2/query_expander.py:95-128` | 라이선스된 `MRCONSO.RRF`→`SQLite`(`data/umls/mrconso.sqlite`)가 필요한데 `data/umls/` 디렉터리 자체가 이 호스트에 없음(2026-09-23 확인). 수작업 4행 테이블(`_CURATED_EXPANSIONS`)은 `UMLS` 없이도 작동: `eGFR`, `NSTEMI`, `TIA`, `Stroke` |
| `abbreviation_expander.py` | `src/agents/agent2/abbreviation_expander.py:1-24` | 아무 동작도 하지 않는 함수 두 개로 대체됨(위 항목에 의해 대체) |

### 4.7 비교군(comparator) 선정 — `src/agents/comparator/`

ADR-028에 따라, 임상시험의 comparator 군(arm)이 위약(placebo)이면 실세계 위약 코호트가
없으므로 문헌 근거를 갖춘 심혈관계 중립적 활성 comparator를 제안한다. 항상 제안만
만들고 사람 검토를 거쳐야 하며 자동 적용은 절대 하지 않는다.

`literature.py`는 수집만 담당한다. `acquire_evidence(treatment_drug, indication,
outcome, *, candidates, ...)`(literature.py:121-189)가 후보 drug class마다 PubMed
`esearch` 쿼리 3건을 `src.agents.agent1.pubmed_fetcher.fetch_pubmed_abstracts`(Agent 1의
`fetcher` 재사용)로 실행한다. `_esearch`는 모든 예외를 잡아 경고 후 `[]`를 반환(조용함).

`recommender.py`는 두 진입점을 갖지만 하나만 연결돼 있다. `recommend_comparator`
(141-212행, 원래 `ADR-028` 파이프라인)는 `rg` 확인 결과 프로덕션 호출자가 없고
자기 `__main__` self-check에서만 쓰인다. `recommend_from_literature`(282-342행,
`ADR-028 revised`)가 실제로 연결된 함수다 — 후보 class를 미리 열거하지 않고 이전
에뮬레이션들이 문헌에서 `class`를 이름 짓게 한다(단일 LLM 추출). 검색된 문서는
`data/comparator_literature/<slug>.json`(`COMPARATOR_EVIDENCE_DIR`)에 스냅샷되어
재현 가능하며, `use_cache=True`(기본)는 저장된 스냅샷을 재생한다.

**다운스트림 소비(이 범위 밖이지만 결정적)**: `tte_service.py:_build_recommended_placebo_comparator_circe`
(약 tte_service.py:6812-6862)가 `recommend_from_literature`를 호출한 뒤,
**무조건** `self._record_pending_comparator_recommendation(result)`(로그/기록만)를
호출하고 `self._build_disease_based_comparator_circe(...)`(질환 기반, 기존의 파생
comparator)를 반환한다 — **LLM이 무엇을 추천했든 상관없이**. 해당 코드의 주석은
"ADR-028은 추천이 comparator를 실제로 바꾸기 전에 제안 + 사람 승인을 요구한다... 아직
HITL(`Human-In-The-Loop`) 검토 채널이 연결되지 않았다... 가시성을 위해 로그만 남기고,
안전한 파생 comparator를 항상 대신 쓴다"고 명시한다. 이것은 **결함이 아니라
의도된 동작**이다 — comparator를 결정하는 채널이 아직 배선되지 않았기 때문에
ADR-028이 요구하는 사람 승인 게이트가 열릴 때까지 문헌 추천을 적용하지 않도록 만든
설계다. 문헌 추천 결과는 현재 전달되는 어떤 CIRCE 코호트에도 영향을 미치지 않는다.

LLM: `COMPARATOR_LLM_MODEL`(미설정이면 `LLM_MODEL` 따름). `_vllm_reachable`
(recommender.py:76-90)로 `settings.VLLM_BASE_URL`에 `raw TCP` 접속을 먼저 확인하고,
접속 불가면 두 진입점 모두 `verdict="unknown"`인 `evidence-only` 출력으로 우아하게
저하될 뿐 raise하지 않는다.

### 4.8 최근 반영된 매핑 수정(요지, §9에서 상세)

- **`f53b71a`** — reranker가 뽑지 않은 개념(KG 상위 개념 확장으로만 추가된 개념)이
  reranker가 뽑은, 처음 고른 개념을 `_roll_up`에서 대체하지 못하도록 함(`_drop_non_seed_ancestors`,
  §4.5).
- **`0eba22f`** — `PRESENCE`형 기준만 읽는 concept set에서 혼동 유발 멤버를 제거(이 파일 범위 밖, `src/services/confusable_member_repair.py`).
- **`f42a7c7`** — concept set이 자기 이름과 다른 analyte를 담고 있으면 거부하는 검사
  추가(범위 밖, `src/utils/circe_lint.py`).

### 4.9 설정(환경변수) 요약

| 변수 | 기본값 | 효과 |
|---|---|---|
| `AGENT2_MAX_WORKERS` | 16 | KG 확장/UMLS 다중쿼리/배치 reranking용 `ThreadPoolExecutor` 크기 |
| `AGENT2_MAX_CRITIC_CANDIDATES` | 30(`len(kg_concepts)>40`이면 50) | Critic LLM에 보내는 후보 수 상한 |
| `KG_EXPAND_MODE` | `clinical_anchor` | KG 확장 전략 |
| `AGENT2_KG_CLIMB_LIMIT` | 40 | `ancestor_climb` 최대 결과 수 |
| `NEO4J_URI`/`NEO4J_USER`/`NEO4J_PASSWORD` | `bolt://localhost:7687`/`neo4j`/`artemis_neo4j` | Neo4j 접속, 미접속 시 부팅 시점 `RuntimeError` |
| `ENABLE_REFINER` | `"1"` | Critic/anchor-skip 이후 `ConceptSetRefiner` 실행 여부 |
| `INCLUDE_DESC_SEEDS_ONLY` | `"1"` | `includeDescendants` 정책(관계-인식 vs 예전 방식의 정적) |
| `AGENT2_ROLLUP_MAX_DESCENDANTS` | `"500"` | `_filter_overbroad` 임계값 |
| `AGENT2_CRITIC_MODEL_TIER` | `"follow"` | Critic 모델 단계 선택 |
| `AGENT2_CRITIC_SELF_REFLECT` | `"true"` | Critic 2-pass `self-reflection` |
| `DOMAIN_PRECHECK` | `"0"` | ChromaDB `top-1` 도메인 `override` 실험, 기본 꺼짐(6건 실측 해로운 `override`로 인해) |
| `FORCE_SLOW_PATH`/`FORCE_FAST_PATH` | `""`/`""` | 경로를 끄고 비교하려는 `override` — §4.10 참고, 실질적으로 무의미 |
| `COMPARATOR_LLM_MODEL` | 미설정→`LLM_MODEL` | CV-중립성 분류 모델 |

### 4.10 테스트와 남은 사항

주요 테스트: `test_seed_displacement_rollup.py` 4(`f53b71a` 자체 테스트),
`test_confusable_concept_set_lint.py` 21, `test_expression_builder.py` 21,
`test_wrong_entity_class_is_dropped.py` 20, `test_observation_entity_class_is_dropped.py` 22,
`test_llm_routing_guard.py` 32, `test_defect_b_exact_ingredient_gate.py` 30,
그 외 다수(전체 목록은 원본 조사 기록 참고).

`Agent2Workflow.process_batch`(workflow.py:579-668), `_fast_path`(workflow.py:670-701),
`_slow_path_batch`(workflow.py:1042-1147)는 프로덕션에서 도달 불가능하다.
`process_with_details`(`workflow.py:488`)가 `route_path = "slow"`를 무조건 대입하며,
주석은 `Fast path disabled: all queries go through slow path`라고 명시한다.
`ComplexityRouter.route`는 여전히 계산되지만(workflow.py:471) 아무 효과가 없다.
`rg -n "process_batch\("`는 정의부 외 호출 지점을 0건 반환한다.

## 5. `TTEService` — CIRCE 조립과 저장소

### 5.1 `TTEService`(`src/services/tte_service.py`, 12,246줄)

`/tte/*` API 라우트 전체 뒤에 있는 단일 오케스트레이션/서비스 클래스다. 생성자:
`TTEService.__init__(self, store: TTEStore)`(tte_service.py:1023).
`self._preview_cache: dict[tuple[int,str], dict] = {}`(tte_service.py:1025)는 인메모리
(비영속) 캐시다(§5.2).

### 5.2 파이프라인 단계표(스터디가 일반적으로 통과하는 순서)

| # | 단계 | 메서드(`path:line`) | 내용 |
|---|---|---|---|
| 1 | 자유 텍스트 초안 | `generate_draft`(1340), `run_generate_draft`(1375) | LLM 기반(Agent 1) 초안 |
| 2 | NCT 초안 | `run_generate_from_nct`(1464) | 임상시험 등록정보 + 논문 가져오기 → 초안 |
| 3 | 설계 검증 | `validate_design`(1599) → `_run_validator_on_study`(3822) → `_study_to_provisional_circe`(3896) → `agent4.validate()`(3825) | Agent 4 구조 검증(§6.2) |
| 4 | 적격 기준 제안 | `suggest_eligibility`(1679) | LLM 기반 기준 제안 |
| 5 | **적격 기준 처리** | `process_eligibility`(1687) → `_build_process_eligibility_artifact_payload`(4096) → `_build_seeded_target_circe`(5305) | 기준별 concept set 매핑(Agent 2) + `structuredExpression` 조립. `ThreadPoolExecutor`로 기준별 매핑을 병렬화(5309), 공유 `Agent2Workflow` 인스턴스(5317-5321, `try/except Exception: shared_workflow = None`으로 조용히 폴백) |
| 6 | Treatment/outcome 제안 | `suggest_treatment`(1762), `suggest_outcomes`(1770) | LLM 기반 |
| 7 | **시드된 코호트 생성/미리보기/등록** | `generate_seeded_cohorts`(1778), `preview_seeded_cohorts`(6956), `register_seeded_cohorts`(7003) → `_build_seeded_cohort_artifact_payload`(4455) → `_materialize_seeded_target_cohort`(4589)/`_materialize_seeded_treatment_cohorts`(4633)/`_materialize_seeded_outcome_cohorts`(4776) | 전체 군 CIRCE 조립. `eligibility.structuredExpression`이 없으면 **`ValueError`로 거부**(1787-1791, 6959-6960) |
| 8 | 분석 전략 평가 | `evaluate_analysis_strategy`(1847) | PS 방법/공변량/추적기간 추천 |
| 9 | 실행(카운트 생성) | `execute_study`(2779) → `_execute_via_webapi`(3126) | WebAPI로 CDM 대상 코호트 생성 실행 |
| 10 | 적용(`apply`) | `apply_artifact` | `draft` artifact를 `apply_artifact(artifact_id, target_sections, base_study_version)`로 확정, `study.version` 증가(낙관적 동시성 가드) |
| 11 | **분석 실행** | `run_analysis`(2588) → `_build_analysis_artifact_payload`(8849) → `_run_agent5_analysis_wrapper`(8926) → Agent 5(§6.3) | PSM/IPTW/MAHALANOBIS + Cox. `results` 있으면 자동 적용, `stale-version` race의 `ValueError`는 `logging.warning`으로 삼킴(2648-2650, 공개된 폴백) |
| 12 | **리포트 요약** | `generate_report_summary`(2677) → `_run_agent6_summary_wrapper`(9214) → Agent 6(§6.4) | 서술 + 미리보기 메타데이터 |
| 13 | HTML/PDF 내보내기 | `export_report_html`(2731), `export_report_pdf`(2750) | Agent 6 클래스로 렌더링 |
| 14 | 전체 파이프라인 | `run_full_pipeline`(2854) | 9→10→11→10→12만 연결(1-8 재실행 안 함) |
| 15 | CIRCE 디스크 내보내기(API 밖) | `scripts/export_seeded_cohorts.py` | §8.1 |
| 16 | 전달 게이트 | `scripts/verify_circe_delivery.py` | §8.2 |
| 17 | 출처 증명 게이트 | `scripts/verify_delivery_provenance.py` + `deliveries/INDEX.json` | §8.3 |

### 5.3 영속 저장소 — `TTEStore`(`src/services/tte_store.py`, 435줄)

JSON 파일 기반 저장소로, 단일 JSON 문서가 `{"next_id", "next_artifact_id", "next_job_id",
"studies": [...], "artifacts": [...], "jobs": [...]}`를 갖는다(tte_store.py:175-183).
데이터베이스가 아니라 매 읽기/쓰기마다 전체 파일을 `json.load`/`json.dump`한다.

- **경로**: `TTE_STORE_PATH` 환경변수, 기본 `/app/tmp/tte/studies.json`(`src/api/tte.py:48`,
  `@lru_cache(maxsize=1)`이 걸린 `get_tte_service()` 안).
- **캐시되는 것**: `study["eligibility"]["structuredExpression"]`이 스텝 5(`process_eligibility`)가
  만드는 CIRCE 형태의 IR이다. 스텝 7이 이것을 **필수로 요구**하고(§5.2), `_build_combined_treatment_circe`
  (tte_service.py:6018-6042)는 이것을 "고비용 Agent 2 매핑 파이프라인 재실행을 피하는
  빠른 경로"로 명시적으로 사용한다(주석, tte_service.py:6028-6029) — `structuredExpression`에
  `PrimaryCriteria` 키가 없을 때만 `_build_seeded_target_circe`로 전체 재구성한다
  (tte_service.py:6037-6042). 이것이 "스토어가 이미 조립된 CIRCE 표현을 캐시하며,
  재export는 저장된 규칙을 재생하고, 오직 캐시 없는 재추출만 빌드 경로의 수정을
  실제로 검증한다"는 프로젝트 관례의 코드 레벨 근거다. `scripts/export_seeded_cohorts.py:332`도
  같은 필드를 직접 읽어 게이트 체크의 기대 진입 concept set을 계산한다.
- **두 번째, 인메모리 전용 캐시**: `TTEService._preview_cache`(tte_service.py:1025)가
  기준별로 완성된 CIRCE dict를 `preview_seeded_cohorts`(작성, 6980-6987)와
  `register_seeded_cohorts`(소비 후 삭제, 7010-7020) 사이에 보관한다. 30분 뒤 만료
  (`now - v["timestamp"] > 1800`, 7006), `studies.json`에 영속되지 않으며 프로세스
  재시작에서 사라진다. 만료/누락 시 `KeyError`(7013).
- **파일 I/O**: 임시파일 + `Path.replace`로 원자적 쓰기(tte_store.py:200-205). 잠금:
  `filelock.FileLock`가 있으면 사용, 없으면 `fcntl.flock`, 둘 다 없으면 경고 한 번 남기는
  **아무 동작도 하지 않는 `lock`**(`_NoopFileLock`, tte_store.py:64-77) — 공개된 저하이지만, `filelock`과
  `fcntl` 모두 없으면 프로세스 간 상호배제가 전혀 없다는 뜻이다.
- **조용한 폴백(강조)**: `TTEStore._read()`(tte_store.py:185-198)는 `JSONDecodeError`를
  0.1초 간격으로 3회 재시도하고, 3회 모두 실패하면 `_log.error(...)` 후
  **`return self._initial_state()`**(샘플 스터디 1개만 있는 초기 상태)를 반환한다.
  `studies.json`이 손상되면(크래시 중 쓰기, 잠금 없는 동시 `writer` 등) 다음 읽기에서
  저장된 모든 스터디/artifact/job이 조용히 샘플 스터디로 대체된다. `_log.error` 한 줄만
  남고 raise도 API 에러 노출도 없다.

`resolve_store_path`(`src/utils/store_resolution.py:44-68`)는 `export_seeded_cohorts.py`/
`verify_circe_delivery.py`가 쓰는 가드다 — 명시적 `--store` 경로가 필수이고, 주변
`TTE_STORE_PATH` 환경변수와 다르면 조용히 하나를 고르지 않고 **`StoreMismatchError`로
중단**한다. 2026-08-31에 스크래치 스크립트 3개가 이 값을 조용히 컨테이너의
`TTE_STORE_PATH`로 읽어 오래된 스토어에서 내보낸 사고 때문에 생긴 가드다.

### 5.4 재진술 클러스터와 값 조건 — Agent 1/Planner 이후, Agent 2 이후

`src/services/restated_clusters.py`(`SPEC-INFRA-003` `REQ-005`, 측정만)가 `domain`,
`valueConstraint`가 `null`인 것, 동일한 `description stem`(후미 괄호 제거)을 공유하는
최상위 CIRCE 기준(매핑 후, `dict` 형태) 2건 이상의 클러스터를 찾는다(162개 기준·3개 임상시험에서
10개 클러스터 검증, 오탐 0). `src/services/restated_demographics.py`가 Demographics
도메인 한정 첫 통합 수정이고, `src/services/restated_distinctness.py`(`SPEC-INFRA-004`)가
`(sourceText, valueConstraint, logicType)` 동치 판정으로 모든 도메인으로 일반화한
버전이다 — 그룹 전체에서 하나가 아니라 동치 클래스마다 하나씩 남긴다(EMPA-REG의
6-기준 `Liver-disease` 그룹이 3개로 줄어들어야 하는 것처럼). 두 통합 경로 모두
`TTEService`의 tte_service.py:5391, 5698, 5990-6014 부근에서, 이미 매핑/저장된 CIRCE
기준을 대상으로 스터디 생성/재생성 시점에 호출된다 — 즉 Agent 1과 Planner **이후**다.

값 조건은 `src/services/value_constraint.py`(`annotate_value_constraints`/
`parse_value_constraints`, 정규식 기반)가 담당하며, `resolve_group_member_constraint`가
그룹 라벨의 임계값을 단위 무관(비율형)일 때만 멤버로 하향 전파한다(§9 커밋
`9cd0bff` 참고).

## 6. Agent 3·4·5·6

### 6.1 Agent 3 — `Cohort Assembler`(`src/agents/agent3/`, 별도 파이프라인 전용)

`ARTEMISRequest` IR + 해소된 `RegisteredConceptSet` 목록을 `CIRCE-be` JSON으로 조립한다.
**§2에서 설명한 대로 운영 TTE API가 아니라 별도 LangGraph 파이프라인에서만 쓰인다.**
파일: `assembler.py`(919줄), `mappings.py`(88줄). 진입점: `CohortAssembler.assemble(ir,
concept_sets)`(assembler.py:74), 싱글턴 `agent3 = CohortAssembler()`(assembler.py:919).

처리: `_build_concept_sets`(assembler.py:324-357)로 `ConceptSets` 구성 → 설계 갈림
(`USE_DISEASE_BASED_PRIMARY = True`, 하드코딩 상수, assembler.py:34)이
`ir.target.primary_criteria.domain == "Drug"`이면 `_assemble_disease_based`
(assembler.py:155-286)로 질환 기반 `primary` + drug `PRESENCE`/`ABSENCE`(9999일 `lookback`,
"환자가 이 약을 복용한 적이 있는가"를 묻는 것이므로 도메인 기본 시간창 테이블을
의도적으로 따르지 않음) → 아니면 예전 방식의 `drug-based` 경로. 각 규칙은
`_build_inclusion_rule`(assembler.py:593-805) → `_validate_and_heal`
(assembler.py:439-500)을 거친다.

가드: `_validate_and_heal`은 `CodesetId == 0`인 규칙을 SKIP/PARTIAL/KEEP으로 분류하고
매번 경고 로그를 남긴다(공개된 폴백). `_find_concept_set_id`(assembler.py:873-915)는
정확 매치 → substring/word-overlap `fuzzy` 매치 → **`CodesetId=0` 폴백**(경고 로그, 공개됨,
다운스트림 `_validate_and_heal`이 잡음). `Composite` 브랜치는 세 가지 거부 채널
(`resolve_group_member_constraint(...).refusal_reason`, `unreadable_value_attributes`,
`unstated_absolute_unit`)이 로그 후 continue한다(멤버가 emit되지 않음, raise하지 않음).

설정: 없음(`env var` 없음). `USE_DISEASE_BASED_PRIMARY`는 하드코딩 상수. LLM 사용: 없음
(이미 해소된 IR + concept set 위의 순수 결정적 변환). 테스트: `tests/test_agent3.py`
10개 + 간접 커버리지.

### 6.2 Agent 4 — Circe Validator(`src/agents/agent4/validator.py`, 321줄)

`CIRCE-be` JSON dict의 구조/의미 검증(스키마 형태, 중복/dangling `CodesetId`, 빈-기준
규칙, `registry` 존재 여부). 읽기 전용, 변형하지 않음. 진입점: `CirCeValidator.validate(circe_json)
-> ValidationResult`(validator.py:36). **운영 API에서는 `validate_design` capability에만
연결돼 있다**(§5.2 스텝 3) — 시드된 코호트 생성 경로에는 연결돼 있지 않다.

처리 순서(validator.py:36-81): `_validate_schema`(83-111, 필수 최상위 키) →
`_validate_concept_sets`(113-154, 필드 존재·중복 id) → `_validate_references`(156-191,
`CodesetId`가 선언된 ConceptSet에 해소되는지) → `_validate_semantic`(193-246,
`CodesetId == 0` 재귀 탐지, `DemographicCriteriaList` 오용 경고, 빈 기준 오류) →
`_validate_registry_integrity`(248-264, `in-process` `src.registry.store.registry`
싱글턴 존재 여부 경고 — 이 `registry`는 `TTEStore`/`studies.json`과 무관한 프로세스
로컬 상태이므로, `export_seeded_cohorts.py`처럼 새 프로세스에서 실행하면 모든
ConceptSet에 대해 경고가 뜬다). `get_actionable_errors`(266-292)는 예전 방식의 파이프라인용
피드백 루프 라우팅(`LOOP_1_REMAP`/`LOOP_2_REASSEMBLE`)이고, 운영 경로의 소비자가 읽는지는
확인되지 않았다. 테스트: `tests/test_agent4.py` 7개.

### 6.3 Agent 5 — `Analysis Agent`(`src/agents/agent5/workflow.py`, 430줄, 운영 경로)

인과추론 오케스트레이션 — `propensity scoring`, `matching`/`weighting`, `covariate balance`,
`Cox regression`. 진입점: `Agent5Workflow.configure(...)`(workflow.py:46) →
`.run(data=...)`(workflow.py:70). 운영 경로 호출자: `TTEService._run_agent5_analysis_wrapper`
(tte_service.py:8926).

입력: `AnalysisConfig`(workflow.py:14-22) — `target_cohort_id, comparator_cohort_id,
outcome_concept_ids, outcome_window_days`(기본 365), `analysis_method`(기본 `"IPTW"`,
`"PSM"`/`"MAHALANOBIS"`도 허용), `ps_model_covariates`(기본 `["age","gender"]`).
출력: `hazard_ratio`, `balance`, `ps_scores`, `weights`, `treatment`, `analysis_method`,
`survival_data`, `n_target`, `n_comparator`, PSM/MAHALANOBIS면 추가로 `n_matched_pairs`.

가드: `PSM caliper widening`(0.2 → 0.5 시도, 실패 또는 매치 0쌍 시 IPTW로 폴백하며
`analysis_method`를 `"IPTW (PSM fallback)"`로 재명명, workflow.py:210-247, 매 브랜치
경고 로그, 공개됨). MAHALANOBIS는 매치 0쌍이면 `ValueError`를 raise한다(폴백하지
않음, workflow.py:313-314). `_safe_cox_covariates`(workflow.py:358-382)는 분산이
낮은(`< 0.005`) 공변량을 제거해 `lifelines`의 `ConvergenceError`를 피한다(경고 로그).

`TTEService._run_agent5_analysis_wrapper`(tte_service.py:8926-9060)는 전체 워크플로
호출을 try/except로 감싸며, **실패 시 모든 필드가 `null`인 payload에
`status="error"`를 붙이고 주석으로 "가짜 HR/CI/p-값으로 대체하지 말 것 — 호출자는
`status="error"`를 unavailable로 취급해야 한다"고 명시한다(tte_service.py:9018-9020)** —
이것은 오류를 내고 멈추는 방식이며 조용한 폴백이 아니다.

테스트: `tests/test_agent5_workflow.py` 15, `tests/test_agent5_psm_fallback.py` 3,
`tests/analysis/test_agent5_psm_fallback.py` 10(동일 파일명이 다른 디렉터리에 존재,
중복 여부는 diff되지 않음), `tests/test_agents_5_6.py` 8.

### 6.4 Agent 6 — 보고 Agent(운영 경로, 3중 사본)

Agent 5의 분석 결과를 Forest/KM/Love/PS-distribution plot과 HTML/PDF 리포트로 바꾼다.
**거의 동일한 사본이 세 개 존재**하고, 어느 것이 실행되는지는 요청 시점에 결정된다.

| 사본 | 경로 | `_encode_plot_base64`/`_build_balance_summary` |
|---|---|---|
| 내부(이 범위) | `src/agents/agent6/workflow.py`(247줄) | 있음(141-173) |
| 가져온(vendored) | `src/vendors/reporting_handoff/agents/agent6/workflow.py`(약 220줄) | 없음(diff로 확인) |

`TTEService._build_agent6_workflow`(tte_service.py:9302-9313)는 **가져온 클래스를
우선**하고, `import` 실패 시에만, 또는 가져온 워크플로의 생성/실행이
`try: ... except Exception: pass`(tte_service.py:9305-9308)에서 예외를 던지면
**조용히** 내부 클래스로 폴백한다 — 왜 실패했는지 로그가 전혀 남지 않는다. 가져온
사본이 필요한 세 메서드를 모두 갖고 있으므로(`grep '^    def ' ...`로 확인) 가져온
사본이 매 요청마다 이긴다 — 즉 내부 사본은 운영 경로에서 사실상 죽은 코드다.
바깥의 `_run_agent6_summary_wrapper`는 `status="ok"`/`"fallback"`을 사유와 함께
보고하지만(공개됨), 그 사유는 **내부** 클래스 생성이 실패한 이유이지 원래 가져온
실패의 이유가 아니다.

`generate_plots(output_dir)`(workflow.py:61-139)는 `Forest`(hazard_ratio) →
`PS-distribution`(치료군 0/1) → `Love plot`(`balance` dict의 smd_before/smd_after,
없으면 공유 `smd` 키로 조용히 0 폴백, 로그 없음) → `KM curve`(`lifelines`
`KaplanMeierFitter`) 순으로 만든다. `generate_report`/`generate_html_report`는
`ReportData`(`src.reporting.models`)를 만들어 `PDFGenerator`에 넘기며, `weasyprint`는
실제 PDF 렌더링 시에만 지연 import된다(`generate_html_only()`는 이를 피함).

테스트: `*agent6*` 이름의 전용 테스트 파일은 없다(`test_agents_5_6.py` 8개가 공유).
플롯/PDF 기계는 간접적으로 `tests/test_reporting_pdf.py`(29개), `tests/test_reporting_plots.py`
(10개)가 커버한다.

## 7. HTTP API — `src/api/`

`create_app()`(main.py:11-48): FastAPI 앱, 허용적 `CORS`(`allow_origins=["*"]`,
main.py:19), `tte_router`(main.py:29)를 마운트하고 `conceptset_router`는 best-effort로
마운트한다(main.py:31-37, **조용한 폴백**: `except Exception: pass`, 주석 `Keep the
TTE MVP bootable even when optional conceptset dependencies are unavailable`). `/health`는
`{"status":"ok"}`(main.py:25-27). `COHORT_ENGINE=spark`일 때만 `Spark` 전제조건을
부팅 시점에 검증한다(main.py:39-46).

`router = APIRouter(prefix="/tte", tags=["TTE"])`(tte.py:41). 모든 핸들러는
`get_tte_service()`(tte.py:46-49, `@lru_cache(maxsize=1)`)를 통해 서비스를 얻고,
`KeyError`→404 / `ValueError`→400 또는 409 / `WebAPIError`→502로 변환하는 얇은
래퍼다. 라우트 데코레이터는 총 **40개**다(`@router.get/post/put/patch/delete` 카운트).

| 메서드 | 경로 | 핸들러(`path:line`) | 목적 |
|---|---|---|---|
| `GET` | `/tte/models` | `get_available_models`(52) | UI 셀렉터용 LLM 모델 목록 |
| `POST` | `/tte/generate` | `generate_protocol`(59) | 자유 텍스트 초안(스터디 없이) |
| `POST` | `/tte/studies/{id}/generate-draft` | `generate_draft_for_study`(64) | 기존 스터디에 초안 |
| `POST` | `/tte/studies/{id}/generate-from-nct` | `generate_from_nct_for_study`(74) | NCT id로 초안 |
| `POST` | `/tte/studies/{id}/validate` | `validate_design`(90) | Agent 4 검증(§6.2) |
| `POST` | `/tte/studies/{id}/suggest-eligibility` | `suggest_eligibility`(98) | — |
| `POST` | `/tte/studies/{id}/process-eligibility` | `process_eligibility`(105) | `thread executor`로 동기 작업 실행(113-114) |
| `GET` | `/tte/studies/{id}/process-eligibility-progress` | `process_eligibility_progress`(119) | 최신 `job`의 `meta.progress` 폴링 |
| `GET` | `/tte/studies/{id}/criteria/{cid}/mapping-candidates` | `get_mapping_candidates`(150) | 최신 `eligibility_processing` artifact에서 매핑 메타데이터 읽음, 예전 방식의 artifact용 폴백 2가지(170-199) |
| `POST` | `/tte/studies/{id}/criteria/{cid}/re-recommend` | `re_recommend_criterion`(218) | 기준 1건 재매핑(`run_mapping_pipeline_for_query`), 저장된 표현은 수정하지 않음 |
| `POST` | `/tte/studies/{id}/suggest-treatment` | `suggest_treatment`(291) | — |
| `POST` | `/tte/studies/{id}/suggest-outcomes` | `suggest_outcomes`(299) | — |
| `POST` | `/tte/studies/{id}/generate-seeded-cohorts` | `generate_seeded_cohorts`(307) | 스텝 7 |
| `POST` | `/tte/studies/{id}/preview-seeded-cohorts` | `preview_seeded_cohorts`(319) | 스텝 7(미리보기) |
| `POST` | `/tte/studies/{id}/register-seeded-cohorts` | `register_seeded_cohorts`(333) | 스텝 7(미리보기 캐시에서 확정) |
| `POST` | `/tte/studies/{id}/run-analysis` | `run_analysis`(345) | 스텝 11 |
| `POST` | `/tte/studies/{id}/evaluate-analysis-strategy` | `evaluate_analysis_strategy`(353) | 스텝 8 |
| `POST` | `/tte/studies/{id}/generate-report-summary` | `generate_report_summary`(368) | 스텝 12 |
| `GET` | `/tte/studies/{id}/export-report-html` | `export_report_html`(376) | 스텝 13 |
| `GET` | `/tte/studies/{id}/export-report-pdf` | `export_report_pdf`(386) | 스텝 13 |
| `GET` | `/tte/sources` | `list_sources`(396) | 사용 가능한 CDM 소스 |
| `GET` | `/tte/studies` | `list_studies`(404) | — |
| `POST` | `/tte/studies` | `create_study`(410) | — |
| `GET` | `/tte/studies/{id}` | `get_study`(416) | — |
| `PUT` | `/tte/studies/{id}` | `update_study`(425) | — |
| `DELETE` | `/tte/studies/{id}` | `delete_study`(434) | — |
| `DELETE` | `/tte/studies` | `clear_studies`(443) | — |
| `DELETE` | `/tte/purge` | `purge_all_data`(449) | — |
| `POST` | `/tte/studies/{id}/copy` | `copy_study`(455) | — |
| `POST` | `/tte/studies/{id}/execute` | `execute_study`(464) | 스텝 9 |
| `POST` | `/tte/studies/{id}/run-full-pipeline` | `run_full_pipeline`(476) | 스텝 14 |
| `GET` | `/tte/studies/{id}/artifacts` | `list_artifacts`(488) | — |
| `GET` | `/tte/artifacts/{artifact_id}` | `get_artifact`(496) | — |
| `POST` | `/tte/artifacts/{artifact_id}/apply` | `apply_artifact`(504) | 스텝 10 |
| `GET` | `/tte/jobs/{job_id}` | `get_job`(516) | — |
| `DELETE` | `/tte/cache/criterion-mapping` | `clear_criterion_cache`(524) | Agent 2 기준 캐시 삭제 |
| `GET` | `/tte/cache/criterion-mapping/stats` | `get_criterion_cache_stats`(539) | — |
| `POST` | `/tte/papers/{nct_id}/upload` | `upload_paper`(550) | PDF 업로드, 비-PDF/잘못된 role은 400 |
| `GET` | `/tte/papers/{nct_id}/status` | `get_paper_status`(582) | 로컬 파일 → NCT `PMID` 조회 → PubMed `esearch` 폴백 → `DOI` → 다운로드 URL, NCT API 실패는 `logger.warning(exc_info=True)`로 공개된 폴백 |
| `GET` | `/tte/papers/{nct_id}` | `list_papers`(687) | 로컬 업로드 PDF 목록 |

설정: `PAPERS_DIR = Path(__file__).resolve().parents[2] / "data" / "papers"`(tte.py:43).
테스트: `tests/test_tte_api.py` — 95개.

## 8. CIRCE export와 전달 게이트

### 8.1 내보내기 — `scripts/export_seeded_cohorts.py`(545줄)

모듈 `docstring`: "병원/사이트 전달용, 유일하게 승인된 군별 CIRCE 내보내기"(2행).
2026-08-31에 `TTE_STORE_PATH`를 조용한 폴백으로 읽어 오래된 스토어에서 내보냈던
임시 스크립트 3개를 대체한다.

처리(`main`, 264-541행):
1. `resolve_drug_anchored_entry()`(272행, `src/utils/delivery_mode.py`)로 `drug-anchored`
   진입 모드를 해소하고 `print()`로 출력, `DeliveryModeConflictError`면 중단.
2. `resolve_store_path(args.store)`(279행) — 명시적 `--store` 필수, `TTE_STORE_PATH`
   불일치나 파일 없음이면 중단(§5.3).
3. `src.services`/`src.pipeline`/`src.utils.circe_lint` import는 스텝 2 **이후**에만
   실행(의도적 순서, `TTE_STORE_PATH`를 고정하기 전에 아무것도 읽지 않게 함).
4. `mapping_flags_summary()`(314행)로 9개 매핑 관련 환경변수를 매니페스트에 기록.
5. `--study-id`별로 `service._build_seeded_cohort_artifact_payload(study_id, study)`
   (356행)를 호출하되 `WebAPIClient.create_cohort_definition`을 `unittest.mock.patch`로
   **가로채서**(350-356행) 실제 WebAPI에 등록하지 않고 `(name, expression)`을
   캡처한다. 캡처된 표현마다 `prune_unused_concept_sets`를 적용(346행).
6. 각 군을 `<out>/<slug>_<role>.circe.json`에 기록(368-370행).
7. 파일당 인라인으로 6가지 검사(아무 것도 걸러내지 못하는 규칙, 진입 concept id 일치, 기준 `accounting`,
   `missing_arm_roles`를 통한 전체 배치 군 완결성)를 수행하고 위반을 모으며,
   **위반이 하나라도 있으면 `manifest.json`을 쓰지 않고 `exit 1`**(514-526행) —
   개별 군 파일은 검사용으로 디스크에 남지만 위반이 있는 export는 전달 대상이
   아니다(`docstring` 38-40).
8. 위반이 없으면 `manifest.json`을 작성(`build_manifest`, 132-173행) — `store_sha256`,
   `store_mtime`, `env_TTE_STORE_PATH`, `TTE_DRUG_ANCHORED_ENTRY`+소스, `mapping_env`,
   `git_head`, 스터디/파일별 행(`dropped_criterion_count`는 `payload` 자체의
   `_droppedCriteria` 키에서 가져오지, 별도로 재계산하지 않음, 471-473행).

전달 위치 관례(`AGENTS.md § WHERE A DELIVERY LIVES`, `docs/agent-briefing-facts.md`):
`output/circe_be/<date>/`가 유일한 준비된 내보내기 위치다. 기본 전달 대상은 **3개
스터디**(CARMELINA, CAROLINA, `EMPA-REG`)다. 거기 파일이 있는 것 자체는 발송의 증거가
아니다 — 발송은 사용자의 명시적 확인이 있어야 하고, 그 뒤 `deliveries/<date>/` +
`deliveries/INDEX.json` + 주석이 달린 git 태그 `delivery/<date>`로 기록된다(§8.3).

`scripts/export_circe_from_store.py`(152줄)는 명시적으로 **잘못된** 스크립트다 —
`*_circe.json`을 쓰는데 `verify_circe_delivery.py`는 이 파일명을 읽지 않는다.

### 8.2 전달 게이트 — `scripts/verify_circe_delivery.py`(2485줄), `src/utils/circe_lint.py`(3364줄)

모듈 `docstring`: "`export_seeded_cohorts.py`가 만든 디렉터리에 대해 실행한다... 아무것도
쓰거나 고치지 않는다 — 검사와 보고만 한다." 19개 표시 검사(a)-(s)(일부 문자는 건너뜀)가
있다.

| 검사 | 규칙 | 함수(`module:line`) | 검사하지 **않는** 것 |
|---|---|---|---|
| (a) | 아무 것도 걸러내지 못하는 exclusion 규칙 0건 | `noop_exclusion_rules`(circe_lint.py:68) | — |
| (b) | 파일의 `InclusionRules` 이름 = 스토어 규칙 이름(`multiset`, 해당 군의 약물 규칙 1개 추가만 허용) | `reconcile_dropped_rules`(verify_circe_delivery.py:638) | 기록 안 된 누락 규칙은 여전히 실패 |
| (c) | 파일의 `PrimaryCriteria` 진입 concept id = 스토어 진입, 또는 승인된 comparator 교체 | `entry_matches_expected`(circe_lint.py:176) | comparator의 `ConditionOccurrence` 진입이 *올바른* condition인지는 검사 안 함 — 그건 (h) |
| (h) | `disease-anchored` comparator의 진입은 임상시험 자신의 등록된 condition이어야 함 | 인라인(verify_circe_delivery.py:2249-2267) | 등록된 condition이 없는 스터디는 검사를 건너뛰지 않고 실패 |
| (d) | `manifest.json` 존재 시 md5/`store_sha256` 일치 | 인라인(2419-2430) | `manifest` 없으면 실행 안 됨 |
| (g) | 기준의 concept set이 그 기준이 읽는 CDM 테이블과 OMOP 도메인을 공유 | `domain_mismatched_criteria`(circe_lint.py:3097) | 이 검사가 생기기 전에는 아무것도 이걸 잡지 않았다 — CAROLINA가 이 모양으로 (a)-(f)를 통과해 발송됨 |
| (i) | 파일 자체의 `_generationCensus`/`_unmappedCriteria`/`_skippedCriteria` 균형 | `criterion_accounting`(verify_circe_delivery.py:1492) | (b)로는 구조적으로 잡을 수 없음(양쪽 다 같은 기준이 빠져 있으므로) |
| (j) | Measurement 기준의 이름이 경계값을 주장하는데 값 조건이 없는 경우 없음 | `asserted_bound_missing_criteria` | 이름이 경계값을 주장하지 않는 기준은 (l) 담당 |
| (k) | 스토어 자체의 `_repairAccounting` 기록이 스토어 자체 기준과 일치 | `repair_ledger_violations`(verify_circe_delivery.py:1344) | 스토어에 쓰이기 전에 복구가 제거한 기준은 다른 모든 검사에 보이지 않음 |
| (l) | Measurement `ABSENCE` 규칙에 값 필터가 전혀 없는 경우 없음 | `unfiltered_measurement_absence_criteria` | (j)를 보완: (j)는 이름이 경계값을 약속했는데 없는 경우, (l)은 약속조차 없이 걸러지는 경우 |
| (m) | 한 파일 안 두 concept set이 다른 이름으로 동일한 멤버를 보유하지 않음 | `aliased_concept_sets` | 다른 이름의 동일 멤버가 필요; 자기 이름 아래 잘못된 멤버 하나는 (r) |
| (n) | 같은/멤버-동일 concept set에 대한 필수 `PRESENCE` + 필수 `ABSENCE`가 겹치는 시간창에 공존하지 않음 | `contradictory_presence_absence_criteria` | (f)는 코호트 자체의 진입 집합에 대한 `ABSENCE`만 검사 |
| (o) | 프로토콜 줄이 `disjunction`으로 말한 대안을 `ALL`(`conjunction`)로 `emit`하지 않음 | `conjoined_disjunction_rules` | — |
| (q) | 단위가 선언 안 된 수치 경계값이 없음(unit을 읽을 Measurement/Observation 테이블에서) | `unitless_value_bound_criteria` | `RangeHighRatio`는 예외(비율은 단위가 상쇄됨); `ankle-brachial` index는 concept id로 예외 |
| (r) | 이름-vs-analyte 검사: concept set이 자기 NAME이 말하는 analyte가 아닌 개념을 보유하지 않음 | `confusable_concept_sets`(circe_lint.py:1834) | `CONFUSABLE_ANALYTES` 테이블(3항목: `LDL cholesterol`, HbA1c, `systolic BP`)의 범위로만 한정 |
| (s) | 필수 기준 전부가 다른 곳의 필수 `zero-occurrence` 기준에 의해 원천 금지되는 `PRESENCE` 규칙을 거부(커밋 `1d9ad6a`) | `unsatisfiable_presence_rules`(circe_lint.py:2229) | `ANY` 아래의 `ABSENCE`, 한 disjunct만 남아도 여전히 충족 가능한 경우, 경계값이 정확히 일치가 아니라 겹치기만 하는 경우는 의도적으로 미포함 |
| (p) | 기준의 `protocolLine`이 그 기준의 주장을 뒷받침하지 않는 경우 | `ungrounded_criteria`(verify_circe_delivery.py:2408) | **보고만 하고 판정하지 않음** — 21건 발동 중 9건만 실제 결함(2026-09-14 전달 기준) |
| (e) | 파일 간 군 완결성 — 선언된 모든 치료/비교 군이 파일을 냈는지 | `missing_arm_roles`(circe_lint.py:261) | — |

### 8.3 출처 증명 — `scripts/verify_delivery_provenance.py`(117줄) + `deliveries/INDEX.json`

게이트 `docstring`: "`deliveries/INDEX.json`에 기록된 모든 발송은 git에서 복구 가능해야
한다... 아무것도 쓰거나 고치지 않는다." `sent_confirmed_by_user: true`인 발송마다
4가지 검사(F1/F2/F3/T1):
- **F1** `deliveries/INDEX.json`이 명명한 모든 파일이 `deliveries/<date>/` 아래 존재.
- **F2** 파일 바이트가 `deliveries/INDEX.json`에 기록된 md5와 일치.
- **F3** 파일이 git에 `tracked`(`git ls-files --error-unmatch`).
- **T1** 주석이 달린 태그 `delivery/<date>`가 존재하고(`git cat-file -t`가
  `"tag"`를 반환해야 함, `"commit"`이 아니라) 그 태그의 파일 blob이 같은 md5를 해시함.

`sent_confirmed_by_user: true`인 발송만 검사하며(42행), 그런 발송이 하나도 없는
`deliveries/INDEX.json`은 그 자체로 `FAIL`이다("발송은 사용자의 말로만 기록된다", 44행).

`deliveries/INDEX.json`은 `_rule`(경고 문구)과 `sends` 배열을 가진다. 읽은 시점 기준
`sends`는 4건이다. 각 발송 레코드는 `date, tag, sent_confirmed_by_user, studies,
sent_zip, head_at_send, content_code_version, version_note, file_count, files`를
가진다. 이 필드를 이용한 발송-코드 버전 대응은 §9.2에 있다.

## 9. 최근 반영 사항(2026-08-25 ~ 2026-09-23)

이 기간에는 main에는 작성일 기준 145회, 커밋일 기준
141회의 `non-merge` 커밋이 있다. 이 절은 작성일 기준을 쓴다. 타입 접두어별로는 `fix` 83,
`docs` 29, `feat` 23, `chore` 4, `test` 3, `wip` 1, `style` 1, `refactor` 1이다. 그중 33개(`docs` 29 +
`test` 3 + `style` 1)는 프로덕션 코드 동작을 바꾸지 않는다.

### 9.1 커밋 그룹별 동작 변경

아래 표는 프로덕션 동작을 바꾼 커밋을 컴포넌트별로 묶은 것이다. 각 행은 커밋 해시,
날짜, 그리고 diff가 실제로 하는 일 한두 문장이다.

**Agent 1 추출(`src/agents/agent1/`, `src/agents/planner/`)**

| 커밋 | 날짜 | 변경 |
|---|---|---|
| `72233b6` | 08-25 | `src/services/restated_demographics.py` 신규 — 4개 구조 gate가 모두 성립할 때 중복 최상위 Demographics 기준을 1개만 남기고 하나로 합친다. 참조 스토어에서 정확히 3개(스터디, `role`) 그룹에 발동(CARMELINA 제외 {11,12,18}, CAROLINA 제외 {21,53}, `EMPA-REG` 제외 {27,28}). |
| `bdd7da2` | 08-25 | 위 모듈을 `TTEService`에 연결, `_record_skip`으로 폐기 기록, `_restatedDemographicsCollapse` 필드 추가. |
| `3e38b64` | 08-25 | `pubmed_fetcher.py` `_regex_parse_criteria`의 열거 마커 정규식이 `leading paren`(`(a)`, `(b)`, `(c)`)을 인식하도록 수정. PLATO 논문에서 `(b)`, `(c)`, `(d)`가 `(a)`에 붙어 `Age>=60` 값 조건 텍스트가 손상되던 것을 교정. |
| `aef2986` | 08-25 | `src/services/restated_distinctness.py`(`SPEC-INFRA-004` M2) 신규, 이 커밋 자체는 측정만(동작 변경 없음). |
| `1ccfbba` | 08-25 | 위 통합을 모든 OMOP 도메인으로 일반화. `(sourceText, valueConstraint, logicType)` 정확 동치 키로, 설명 stem이 같아도 관련 없는 기준은 병합하지 않음(`EMPA-REG` `Cardiovascular Disease` 클러스터). Demographics 경로와 상호 배타적으로 배선(`REQ-013`). |
| `745ea83` | 08-27 | Planner `decomposer.py`/`prompts.py`(`SPEC-INFRA-007`) — (1) 분해 프롬프트에 OMOP 도메인 배정 가이던스 추가, (2) 서브 기준의 `value_constraint`를 부모에서 무조건 상속하지 않고 각자의 `value_constraint_text`에서 개별 파싱. 파싱 실패나 `source_text` 없음은 `value_constraint=None`으로 fail-open. |
| `a2fb858` | 09-12(§9.3 재수록) | `_normalize_trial_data_for_stable_hash`의 `sorted(...)` 호출 제거 — 캐시 키뿐 아니라 모델이 실제로 읽는 프롬프트 순서였다. LEADER의 최상위 규칙 20개가 알파벳 순으로 흩어져 빈 코호트가 되던 결함을 교정. Agent 1 IR 캐시 키가 모든 임상시험에서 무효화됨(6개 스터디 재추출 ~132분). |
| `c4aedcc` | 09-10(§9.3 재수록) | `ValueConstraint`에 `op: "bt"`(양 끝을 포함하는 범위) + `value_high` 도입, `{"op":"between","value":[lo,hi]}` 형태를 받아들이는 validator 추가. `_repair_split_bands` + `_repair_band_tiers`를 `Pattern E` 전에 실행하도록 추가. |
| `9ec4b3a` | 09-11 | `src/agents/agent1/repair_accounting.py` 신규(`RepairLedger`, `assert_repairs_accounted`) — 기록 안 된 복구는 즉시 `raise`. `_repair_inclusive_upper_bounds`가 `<=`/`=<`/`≤`/`≦`/범위 표현을 `name`이 아니라 `source_text`에서만 읽도록 수정. |
| `a17a11e` | 09-19(§9.3 재수록) | `_repair_inclusive_upper_bounds`를 `gte`뿐 아니라 `lte`에도 적용, `_torn_range_declined`(decomposer.py) 신규 — 같은 부모 analyte를 한쪽 bound씩 restate하는 분해를 거부. |
| `a2ecba6` | 09-12 | `src/agents/agent1/temporal_grounding.py` 신규 — 시간창을 프로토콜 줄의 실제 숫자와 대조해 단위 미변환/크기 오류/방향 반전 3종 결함을 교정. 5092개 시간창 중 557개만 판정, 4535개는 보류. |
| `e8daa37`/`646dbf8` | 09-12 | `rejoin_stranded_superscripts`를 섹션 추출 전에 실행하도록 이동. `_best_section_match`가 블록을 합치는 순서를 문서 순서 엄격 준수로 변경(가장 무거운 블록 우선에서 전환). 후속 커밋이 관련 가드를 과잉 복잡성으로 되돌림. |
| `c75085c`/`d0ee924` | 09-12 | `src/services/entity_exception.py`+`entity_subtraction.py` 신규 — `X other than Y` 기준에서 Y를 별도로 매핑해 X의 `isExcluded` 멤버로 적용. Planner `_exception_kept_whole`이 이 처리가 가능하도록 분해를 보류. |
| `c0df6db` | 09-12 | `parentGroupId` 필드 신규(중첩 그룹 지원, 이전엔 1단계만 평탄화하고 그 아래는 버려짐 — 6개 임상시험 캐시 IR에서 58개 기준을 담은 25개 중첩 노드 확인) + `list-cardinality` 그룹을 Circe `AT_LEAST`/`Count:N`으로 `emit`(이전엔 전체 코드베이스에서 `AT_LEAST` `emit` 지점 0건). |

**Agent 2 매핑(`src/agents/agent2/`, `src/agents/conceptset/`)**

| 커밋 | 날짜 | 변경 |
|---|---|---|
| `56f5c68` | 09-09 | `retriever.py` `BatchSearchResults` 신규 — `(text, domain_hint)` 대신 text만으로 키를 잡던 결함을 수정. 같은 텍스트를 다른 `domain_hint`로 조회하면 뒤에 온 `domain` 그룹이 앞의 것을 조용히 덮어써, 도메인 불일치 penalty가 발동해야 할 자리에서 발동하지 않았다. |
| `3b1a287` | 09-09 | `logic.py` `_check_db()` — 실패한 Postgres probe를 프로세스 수명 동안 영구 캐시하던 것을 `LOGICIAN_DB_PROBE_RETRY_SECONDS`(기본 60초) 후 재시도로 수정. 일시적 연결 오류가 영구적으로 모든 도메인 필터를 fail-open으로 만들던 결함. |
| `5f5c8dc` | 08-26(`SPEC-INFRA-005`) | `logic.py` `drop_wrong_entity_class_for_observation` 신규 — Observation 도메인에 `entity-class` 필터가 전혀 없던 것을 교정(SNOMED Substance/Procedure는 무조건 제거, LOINC Survey/Question은 경쟁 후보가 있을 때만). |
| `350501a` | 09-18 | `src/services/overbroad_absence_repair.py` 신규 — 단일 멤버 `ABSENCE` concept set을 이름이 정확히 일치하는 표준 개념으로 좁힘(CARMELINA/CAROLINA `Type 1 diabetes mellitus` 결함, §9.3). |
| `f53b71a` | 09-18 | `expression_builder.py` — 처음 고른 개념이 아닌 후보(KG 상위 개념 확장으로만 추가)가 `_roll_up`에서 처음 고른 개념 후보를 대체하지 못하도록 수정(§4.5, §9.3). |
| `0eba22f` | 09-18 | `src/services/confusable_member_repair.py` 신규 — `PRESENCE`형 기준만 읽는 concept set에서만 혼동 유발 멤버를 실제로 제거(`f42a7c7`의 `report-only` 결정을 뒤집음, §9.3). |

**CIRCE 내보내기 / 전달 게이트(`scripts/export_seeded_cohorts.py`, `scripts/verify_circe_delivery.py`, `src/utils/circe_lint.py`)**

| 커밋 | 날짜 | 변경 |
|---|---|---|
| `8e0ada3` | 09-05 | 정식 전달 파이프라인 도입 — `export_seeded_cohorts.py`, `verify_circe_delivery.py`, `circe_lint.py`(첫 검사 `noop_exclusion_rules`), `store_resolution.py`. 2026-08-31 전달이 137개 규칙 중 62개(45%)가 아무 효과가 없었던 결함의 직접적 수정. |
| `c5630d2` | 09-06 | `_build_seeded_target_circe`가 기준 목록을 두 번 순회(선택용 1회, 매핑 결과 페어링용 1회)하며 재유도된 필터가 SPEC-INFRA-003/004 `drop` 도입 후 첫 순회와 `desync` — 마커 없이 실패(`concept-set` 개수는 여전히 맞았음). 매퍼 자신의 반환 인덱스로 페어링하도록 수정. `expected_arm_roles`/`missing_arm_roles`, `contradictory_absence_rules` 게이트 추가. |
| `6eb2ed5` | 09-06 | `domain_mismatched_criteria` + `CRITERIA_TYPE_DOMAINS` 신규 — 기준의 CIRCE 타입이 자신이 읽는 concept set의 OMOP 도메인과 불일치하면 `flag`(체크 (g)). |
| `0865a49` | 09-06 | `_refuse_domain_contradiction` 신규 — 매퍼가 반환한 도메인이 기준의 선언된 CDM 테이블과 다르면 조용히 emit하지 않고 `raise`, `_unmappedCriteria`로 기록. |
| `1e7d709` | 09-06 | `src/utils/disease_anchor.py` 신규 — 하드코딩된 `per-NCT` 테이블을 임상시험 자신의 등록된 `conditionsModule.conditions`로 대체(체크 (h)). |
| `9cd0bff` | 09-08 | `resolve_group_member_constraint`/`is_reference_relative` 신규 — 그룹 라벨의 임계값을 단위 무관(비율형)일 때만 멤버에 전파, 절대 경계값은 전파 안 함. |
| `b6df569` | 09-08 | `src/utils/delivery_mode.py`(`resolve_drug_anchored_entry`) 신규 — `TTE_DRUG_ANCHORED_ENTRY`를 내보내기/verify 스크립트가 직접 해소. |
| `8a6d16e` | 09-08 | `src/utils/mapping_flags.py` 신규 — 매핑 결과를 좌우하는 9개 환경변수를 매니페스트에 기록, `CriterionResultCache` 키에도 반영. |
| `2e48636` | 09-09 | `unreadable_value_attributes` + 테이블 신규 — CDM 테이블이 읽지 못하는 값 필터(예: `DrugExposure`+`ValueAsNumber`)를 더 이상 병합하지 않음. |
| `a2cb087`/`997da1b` | 09-09 | 그룹-라벨 임계값을 안전하게 상속 못 하는 멤버를 `emit-and-log` 대신 실제로 `refuse`(`CriterionRefused`, `code` `stranded-group-threshold`)로 변경. |
| `0e410be` | 09-09 | `PERMITTED_REFUSAL_CODES` 신규 — 오직 `unmappable-placeholder`만 허용, 나머지 `refusal code`는 게이트를 실패시킴. `asserted_bound_missing_criteria`(체크 (j)) 신규. |
| `3506dff` | 09-12 | `aliased_concept_sets`(체크 (m)), `contradictory_presence_absence_criteria`(체크 (n)) 신규. LEADER `insulin` concept set이 서로 다른 이름으로 동일 26개 개념을 보유해 exclusion=inclusion이 된 결함을 잡음. |
| `c1cb2c0`/`72a16b8` | 09-10 | `DEFAULT_WINDOW_START_DAYS_BY_DOMAIN` 단일 테이블 신규(Condition -9999, Drug -365, Measurement -180, Procedure -9999) — 내보내기 빌더와 Agent 3 빌더가 각자 다른, 도메인 구분 없는 365일 기본값을 쓰던 것을 통일. |
| `fa0b5d5` | 09-10 | `protocolLine` 필드 신규 — 기준이 추출된 원문 줄을 저장(`sourceText`와 구분). |
| `b3f81ab` | 09-12 | `scripts/verify_atlas_renderable.py` 신규(위키 기록의 `defect C`) — Atlas UI 렌더링에 필요한 7개 필드 누락을 검사. `entity_subtraction.py`의 `isExcluded` 멤버가 concept_id만 담던 것을 전체 7필드로 수정. |
| `520d41c` | 09-16 | `scripts/verify_entry_exclusion_conflict.py` 신규 — 진입 이벤트 concept set 전체가 다른 곳의 필수 `ABSENCE` 규칙에 덮이면 거부(`EMPA-REG` `#14` 결함, §9.3). |
| `686c9cb` | 09-17 | `src/services/entry_exclusion_repair.py` 신규(위키 기록의 `defect B`) — 내보내기 시점 복구로 진입 concept set을 문제의 `ABSENCE` set에 `isExcluded`로 반영. |
| `2f95aac` | 09-17 | `src/services/presence_unit_repair.py`+`presence_unit_allowlist.py` 신규(위키 기록의 `defect A`) — allowlist된 analyte의 `PRESENCE`형 Measurement 기준에서 `Unit` 필터를 "누락만 일으킬 수 있고 잘못 포함시킬 수 없을 때" 제거. |
| `ab0c2a7` | 09-18 | `scripts/run_fix_verification.sh`+`verify_fix_reflection.py` 신규 — 커밋된 수정이 캐시 없는 재추출 + export까지 실제로 반영되는지 확인하는 4가지 판정 도구(PASS/FAIL/UNVERIFIABLE/CONTROL-BROKEN). |
| `4bf73ec` | 09-18 | `src/services/range_disjunction_repair.py` 신규(위키 기록의 `defect E`) — `ANY(gte LOW, lte HIGH)`(사실상 "아무 값이나")를 `bt LOW..HIGH`로 병합. |
| `f42a7c7` | 09-18 | `circe_lint.confusable_concept_sets`(체크 (r)) 신규(위키 기록의 `defect F` 1부) — 자기 이름과 다른 analyte를 보유한 concept set 탐지. 초기엔 report-only. |
| `1d9ad6a` | 09-19 | `circe_lint.unsatisfiable_presence_rules`(체크 (s)) 신규 — 모든 disjunct가 다른 곳의 필수 `zero-occurrence` 기준에 의해 금지되는 `PRESENCE` 규칙 거부. |
| `37d519c` | 09-19 | `src/services/restated_absence_repair.py` 신규 — 형제 `PRESENCE` 규칙의 정확한 논리적 여집합인 inclusion 규칙을 내보내기 시점에 제거(CARMELINA #12/#13, §9.3). |
| `849dba5` | 09-19 | `verify_circe_delivery.py`의 `reconcile_dropped_rules`가 `_restatedAbsenceRemovals` 채널도 인식해 위 제거를 합법으로 조정. |
| `4de5e93` | 09-22 | `run_fix_verification.sh` 환경 게이트가 `.env`가 아니라 실제로 실행에 쓰일 백엔드(`exported` 환경변수 우선)를 확인하도록 수정. |

**`TTEService` / API / 기타(`src/services/tte_service.py`, `src/api/`, `src/utils/llm.py`)**

| 커밋 | 날짜 | 변경 |
|---|---|---|
| `3c0192e` | 08-26 | `GenerateRequest.model`/`NCTGenerateRequest.model`이 로컬 vLLM 모델 이름만 허용하도록 validator 추가(HTTP 422) — 원격 프로바이더로 무제어 라우팅되던 경로 차단. |
| `36cbdfb` | 09-07 | `LLMTruncationError` 신규 — 토큰 상한에 잘린 완료가 JSON 파싱 오류로 오진단되던 것을 명확한 에러로 교정. `_heuristic_draft`가 comparator/outcome/population이 전부 없으면 빈 초안을 `status="completed"`로 반환하는 대신 `ValueError`로 raise하도록 수정. |
| `d363bef`/`3e771d2`/`11712b3` | 09-07 | 로깅 설정 결함(핸들러 없어 `logger.info`가 조용히 사라지던 문제) 교정, 멱등 핸들러 가드, PDF `enrichment` 성공/실패를 하나의 `print()` 채널로 통일. |
| `d0ee924`, `45fa9d6` | 09-10, 09-12 | Planner의 `span-grounding` 강화(`_grounded_span` 2-gate). |
| `3d860e9`/`5c683b0` | 09-07 | `_build_seeded_target_circe`의 positional/`bare-id` 폴백을 제거 — 6개 콜드 런 스터디에서 두 폴백이 총 20건의 "틀린 답 20, 맞는 답 0"을 만들던 것을 확인 후 제거. |

**전달 및 출처 증명(`deliveries/`, `scripts/verify_delivery_provenance.py`)**

| 커밋 | 날짜 | 변경 |
|---|---|---|
| `b047f31` | 09-14 | `scripts/verify_delivery_provenance.py` 신규 — `sent_confirmed_by_user: true`인 발송이 파일 존재/md5/git tracked/annotated 태그로 복구 가능한지 검사. 이 커밋 자체가 `delivery/2026-08-31`과 `delivery/2026-09-12` 태그를 소급 생성했다(§9.2). |

**벤치마크/평가(`scripts/model_eval/`, `scripts/extract_criteria_benchmark.py`)**

| 커밋 | 날짜(병합일) | 변경 |
|---|---|---|
| `3f25a29`(→`3c07f83`로 09-23 병합) | 07-30 | `scripts/extract_criteria_benchmark.py` `_extract_concept_ids`가 `isExcluded` 플래그를 무시하던 결함 수정 — 전문가가 의도적으로 제거한 개념이 정답으로 취급되던 문제. 2109개 gold concept id 중 596개(28.3%)가 제외된 개념이었고, 242개 문항 중 33개에 영향, 3개 문항은 100% 제외됨. 이 커밋 이후의 벤치마크 점수는 이전 점수와 직접 비교할 수 없다. |
| `c7b7a89` | 09-23 | `scripts/model_eval/` 검증 도구를 은퇴한 worktree에서 본 트리로 이동. `run_model.py`는 죽은 vLLM 서버 대상 실행에서 174건 전부가 `APIConnectionError`였는데도 `completed`로 기록된 사례를 근거로 자체 LLM 호출 오류율(`MAX_LLM_ERROR_RATE = 0.25`)을 계산하도록 함. |

### 9.2 최근 반영 사항과 발송 대응

| 발송일 | 코드 버전(`content_code_version`) | 비고 |
|---|---|---|
| 2026-06-24 | 없음(null) | 저장소가 아직 없던 시점 |
| 2026-08-31 | 없음(null) | INDEX.json 자체가 내보내기 시점 스토어가 08-13 이전 내용이었음을 명시 — HEAD `745ea83`(08-27)는 실제로 영향을 주지 않았다 |
| 2026-09-12 | `d50bf8c` | 8개 커밋 연관(`623e663 a2ecba6 141ecb7 a2fb858 c75085c d0ee924 c0df6db e8daa37`, 모두 이 창 안) |
| 2026-09-23 | `849dba5` | 캐시 없는 재추출이 `849dba5`에서 시작됨(09-22 16:38). `head_at_send`는 `4de5e93`(내보내기 경로에 영향 없는 `run_fix_verification.sh`만 차이) |

`849dba5` 이후 main에 추가된 커밋 — `4de5e93`(백엔드 검증 대상 수정), `affdd23`(09-23
발송 기록), `c7b7a89`(`model-eval` 검증 도구 이동), `ca81faa`(README에 "git이 담지 않는 것"
절 추가), `3c07f83`(`3f25a29` 병합 — 벤치마크 점수 비교 불가 시점), `7595486`(사용
안 하는 `notebook` 제거) — 이들은 09-23 발송의 내보내기 경로에 영향을 주지 않는다.

`2f95aac`부터 `affdd23`까지, 양끝 포함 **13개 커밋**이 2026-09-23 병합 배치를
이룬다(`ab0c2a7 4bf73ec f42a7c7 350501a f53b71a 0eba22f 1d9ad6a a17a11e 37d519c
849dba5 4de5e93 affdd23` + `2f95aac` 자신).

### 9.3 위키 기록 `note-026` ~ note-032가 측정한 것

**`note-026`**(09-17, 완료) — `defect B`: `EMPA-REG` `Endocrine disorder (excluding T2DM)`
제외 규칙이 T2DM을 실제로 배제하지 않던 결함을 내보내기 시점 복구로 수정(`686c9cb`).
24개 발송 파일에 재적용해 정확히 1개 파일(`2026-09-12/empa-reg_comparator`)만
바뀌었고(`codeset` 29, 41개 concept set 중 이것만, 기존 멤버 23개 보존, `201826`/
`44793113` 2개 추가), 그 파일의 게이트가 FAIL→PASS로 바뀌었다. 65개 테스트 통과.
`defect A`(inclusion 규칙의 단위 조건)는 승인만 되고 미커밋, 브랜치
`fix/unit-condition-presence`에 있는 상태였다.

**`note-027`**(09-18 03:00, 완료) — `ab0c2a7`로 `run_fix_verification.sh`/
`verify_fix_reflection.py` 도입. 09-12 발송이 시작된 스토어(md5 `04d959e6`)에서 HEAD
`2f95aac`로 3개 임상시험(EMPA-REG/CARMELINA/CAROLINA) 캐시 없는 재추출. `defect C`(concept
필드) PASS, `defect A`(inclusion 규칙 단위) PASS(12개 단위 제거/12개 export에서 거부/재적용
후 잔여 0). `defect B`는 FAIL — 복구는 한 번 발동했지만 **새 인스턴스**가 나타남
(CARMELINA comparator `codeset` 14 `Type 1 diabetes mellitus`가 실제로는 상위 개념
`4130526`만 보유, 진입 `closure` 16개 멤버의 100%를 덮음).

**`note-028`**(09-18 12:00, 완료) — `defect E`: CARMELINA 규칙 #12가 `ANY(HbA1c>=6.5,
HbA1c<=10.0)`("사실상 아무 HbA1c 기록이나 통과")였던 것을 `bt 6.5..10.0`으로 병합
(`4bf73ec`). `defect F`: 이름과 다른 멤버를 가진 concept set 5종은 allowlist로 처리하고,
`HDL-in-LDL`, `HbA1-in-HbA1c`, `blood-pressure-panel-in-systolic` 3종은 새 검사
(`f42a7c7`)로 탐지하되 자동 제거는 하지 않음("매핑 수정이라 내보내기 시점 복구가 할
일이 아니다"). `Type 1 diabetes mellitus` 제외 집합이 `4130526`으로 과확장된 재추출
회귀도 `350501a`로 교정. 한 내보내기 실행에서 `ABSENCE` 집합 좁히기 복구 4회, 진입-제외
복구 1회, 범위 병합 복구 2회, inclusion-rule-단위 제거 14회(8회는 거부) 발동.
새 lint는 두 코퍼스 각각에서 8건씩 발견(빈 `allowlist` 대조군은 0건). 이 `note-028`의 매퍼
비결정성 진단은 note-029에서 정정된다.

**`note-029`**(09-18 21:00, 완료) — note-028의 `Type 1 diabetes mellitus` 실패를 매퍼
비결정성으로 본 진단을 정정: **결정적인, 상위 개념으로 합치는 과정의 결함**이다. 근본 원인:
`KGExpander.get_ancestors(max_sep=2)`가 상위 개념 후보 `4130526`을 추가하고,
`ExpressionBuilder._filter_overbroad`가 그 180개 자손 수가 500 미만이라 유지하며,
`_roll_up`이 처음 고른 개념 `201254`(25개 자손)를 다른 후보의 자손이라는 이유로 삭제. `f53b71a`로
처음 고른 개념이 아닌 상위 개념 후보가 처음 고른 개념을 대체하지 못하도록 수정, `0eba22f`로 혼동 유발 멤버
제거를 모든 규칙이 presence일 때만 적용하는 것으로 좁혀 재적용. 3-way 어휘집 확인:
처음 고른 개념이 없는 입력 → `[4130526]`(결함 재현), 처음 고른 개념 `[201254]` → `[201254]`(수정 확인), 양쪽
두 후보 모두 처음 고른 개념으로 주면 → `[4130526]` 유지(정당한 상위 개념 합치기는 안 깨짐). verify4 캐시 없는 재추출(1시간
19분): `defect C` PASS, `defect B` PASS(복구 1회 발동, 탐지기 `exit 0`), `defect A`
PASS(단위 20개 제거, 2개 거부), `Type 1 diabetes mellitus` 집합이 4개 파일 전부에서
`201254`. 29건의 이름/내용 불일치 거부 중 12건은 정당한 동음이의(다른 OMOP 도메인,
올바른 매핑)로 종결, 1건(`Dyslipidemia`)은 미해결로 남음. 매퍼는 여전히 `4130526`을
후보로 제안한다(이기지만 못하게 됐을 뿐, 제안 자체는 막히지 않음).

**`note-030`**(09-22 18:30, 완료) — 근본 원인 규명: Dong-A의 CARMELINA 두 군이 0명인
이유는 (초기 가설이던) 규칙 #2 하나가 아니라, 규칙 #12와 #13이 논리적 여집합이라
CIRCE가 AND 결합해 0이 되기 때문이다. `#12 = ANY(HbA1c 1건 이상 gte 6.5, HbA1c 1건
이상 lte 10)`("HbA1c 값이 하나라도 존재")와 `#13 = ALL(HbA1c gte 6.5 0건, HbA1c lte 10
0건)`("HbA1c 값이 전혀 없음")는 어떤 CDM에서도 동시에 만족할 수 없다. 외부 증거: `Dong-A`
comparator 진입 92,304 = #12 14,509 + #13 77,795; `Dong-A` 치료군 진입 7,317 = #12
6,160 + #13 1,157; Ajou comparator 진입 38,664 = #12 0 + #13 38,664; Ajou 치료군
진입 8,837 = #12 0 + #13 8,837 — 4개 군 전부에서 #12+#13 합이 진입 인원과 정확히
일치해 두 규칙이 모집단을 분할하고 AND 결합이 그것을 0으로 만든다는 것을 증명한다.
2단계 근본 원인: Agent 1이 `inclusive-side` 연산자(`op: lte, value: 10.0`)로 `ABSENCE`
기준을 emit했는데 `_repair_inclusive_upper_bounds`가 `gte`에만 게이트돼 있어 `lte`가
빠져나갔고, `_repair_split_bands`도 `{gt,gte}`만 상한으로 찾아 이 쌍을 병합/집계하지
못했다. 3단계 수정: `a17a11e`(업스트림), `37d519c`(내보내기 시점 — 스토어가 빌드된
표현을 캐시하므로 재발송 경로용), `849dba5`(게이트 — `missing=1` 실패 대신 재분류).
verify5 측정: 범위 병합 2→0, `mixed-member-removal` 8→8(불변), 단위 제거/거부
20/2→20/2(불변), 새 게이트 2종 6개 파일 전부 0. `defect D`(CARMELINA #2 `background-medication`
규칙)는 실제 프로토콜 불일치이지만 0-코호트의 원인은 아니었다 — 미수정.

**`note-032`**(09-23 11:21, 완료) — 수정이 아니라 **전사 기록**이다.
2026-09-12 발송의 Ajou(12) + `Dong-A`(4) `Atlas Inclusion Report` 스크린샷 16장을 텍스트
표로 옮겼을 뿐 "해석은 없다". 6개 코호트 스크린샷의 규칙 수/순서가
`deliveries/2026-09-12/<cohort>.circe.json`의 `InclusionRules` 수와 정확히 일치:
carmelina_comparator 23, carmelina_treatment 22, carolina_comparator 26,
carolina_treatment 26, empa-reg_comparator 21, empa-reg_treatment 20. 유일한 차이는
CAROLINA 규칙 #7/#8의 `naive` vs `naïve` 발음 구별 부호뿐. 0-N 행 예: CARMELINA #12
(Ajou 0/38,664 comparator; 0/8,837 치료군), CAROLINA #2 BMI(Ajou 0/21,199;
0/8,837), CAROLINA #7 `HbA1c-range`(Ajou 0/21,199; 0/8,837), `EMPA-REG` #4 HbA1c(Ajou
0/38,664; 0/5,891), `EMPA-REG` #14 `Endocrine-disorder`(Ajou 0/38,664 비교군, 874/5,891
=14.84% 치료군; `Dong-A` 0/92,304 비교군, 786/3,820=20.58% 치료군).

**`note-031`**(09-23 14:00, 완료) — 2026-09-23 발송(CARMELINA/CAROLINA/EMPA-REG, 파일
6개, `output/circe_be/tte_circe_2026-09-23.zip`, md5 `a38f574706ce824c36fdeadb1f7a2a62`,
태그 `delivery/2026-09-23`, 커밋 `affdd23`)은 09-12 Atlas inclusion report가 지목한
0-환자 규칙 **7건 전부**를 해소했다: Ajou CARMELINA #12 HbA1c(단위 조건) → `#3 bt
6.5..10` 단위 없음; `Dong-A` CARMELINA 0(논리적 여집합 #12/#13) → 한 규칙으로 병합;
Ajou CAROLINA #2 BMI(단위) → `lte 45` 단위 없음; Ajou CAROLINA #7 HbA1c(단위) →
`bt 6.5..8.5` 단위 없음; Ajou `EMPA-REG` #4 HbA1c(단위 + HbA1 혼입) → `#6` 단위 없음;
양쪽 사이트 `EMPA-REG` #14 `Endocrine`(T2DM 미제외) → `#15`가 이제 T2DM 개념 2개 제외;
`Dong-A` CAROLINA(Atlas 렌더링 실패) → 6/6 렌더링. 측정: zip-vs-검증-출력 md5 6/6 일치,
WebAPI SQL 변환 6/6 성공, `isExcluded` 멤버 12개, SQL IS NULL exclusion `join` 파일당
36-89개, Atlas 렌더링 6/6, `unsatisfiable` 규칙 0. 스토어 무관 검사, 09-12→09-23
(각 6개 파일): `unsatisfiable_presence_rules` 2→0, `confusable_concept_sets` 8→0,
`aliased_concept_sets` 6→4, `asserted_bound_missing_criteria` 2→2(불변),
`unfiltered_measurement_absence_criteria` 2→2(불변), 나머지 5종 검사 0→0. 치료
군 기준 `census`(total/mapped/unmapped/skipped): `EMPA-REG` 65/40/3/21 → 63/40/3/19;
CARMELINA 63/35/4/22 → 60/35/4/19; CAROLINA 115/84/4/25 → 117/86/4/25. **전달 게이트
전체는 6개 파일 모두 여전히 FAIL** — 매핑 안 된 기준(파일당 3-4건, `Nursing` 등
`investigator-judgement` 텍스트)이 코호트를 넓히고, CARMELINA 규칙 이름이 실제 조건에
없는 경계값(`Impaired renal function (UACR)`)을 참조하며, `EMPA-REG` `thyroid hormone`
제외 규칙에 값 필터가 없다. `defect D`(CARMELINA #2)는 여전히 미수정(Ajou comparator
통과율 3.25%, `Dong-A` comparator 0.86%). CARMELINA와 EMPA-REG의 comparator 설계 문제
(first-T2DM-diagnosis를 `active-comparator` drug 대신 사용, TROY v1.1 gold 기준과 다름,
`ADR-027`)는 사람 승인이 필요해 명시적으로 미구현 상태다. CAROLINA(실제 `active`
comparator를 쓰는 1단계)는 이 설계 문제에서 자유롭다. 어느 사이트에서도 병원
결과는 아직 수신되지 않았다.

### 9.4 열린 문제(`note-026` ~ 032 종합)

1. CARMELINA `#2` `background-medication` 규칙이 프로토콜과 불일치(`defect D`) — 미수정.
2. CARMELINA·`EMPA-REG` comparator 설계 — first-T2DM-diagnosis를 comparator 진입점으로
   씀(`ADR-027` 2단계, `CV-neutral` `active class`로 전환, 사람 승인 대기, 미구현).
3. CAROLINA `LDL` 단위로 걸러진 inclusion 규칙(`#9`, 양쪽 군) — 멤버 `3035009`에 단위
   변환이 없어 여전히 단위 제거 복구에서 거부됨.
4. `Dyslipidemia` concept set — 같은 도메인 안에서 더 넓은 개념으로 정당하게 합쳐진 것,
   좁히면(`PRESENCE` 규칙이므로) 선택 환자가 바뀌어 미해결.
5. 파일당 매핑 안 된 기준 3-4건, 규칙 이름-조건 불일치(`Impaired renal function
   (UACR)`에 경계값 없음) — 둘 다 코호트를 넓힘. `EMPA-REG` `thyroid hormone` 제외
   규칙은 값 필터가 없어 코호트를 좁힘.
6. 2026-09-23 발송 6개 파일 전부 전달 게이트 FAIL — 코호트는 생성되지만 정의가
   프로토콜에서 어딘가 벗어나 있다는 뜻이다.
7. 매퍼는 여전히 `Type 1 diabetes mellitus`에 대해 `4130526`을 상위 개념으로 합치는 후보로
   제안한다 — 이기지 못하게만 됐다.
8. 추출 시점 커버리지 갭 경고(`59 input criteria → 29 output rules`)가 여전히
   남아 있음 — 그룹핑 경계를 넘어 과다 집계하는 구조적 문제이며 note-028/029 수정과
   무관하다.
9. 2026-09-23 발송에 대해 아직 병원 확인을 받지 못함.
10. 어떤 note도 환자 수 효과를 측정하지 않았다 — 모든 로컬 CDM이 합성이기 때문이다.

## 10. 알려진 결함과 한계

아래 항목은 정적 코드 읽기로 발견된 것이며 **수정되지 않았다**.

**Agent 1/Planner/Consolidator**
- Planner `_extract_json`(decomposer.py:493-504)이 JSON 파싱 실패 시 조용히
  `atomic, 분해 없음`으로 기본 처리한다 — parser.py 자체의 `_extract_json`은 `raise`한다.
- `threshold_classifier.py`(`ADR-032` 2단계)의 LLM 분류기가 완전히 구현·테스트(41개
  테스트)됐지만 프로덕션 호출자가 없다.
- `ConceptSetConsolidator`가 `TTEService`에서 도달 불가능하고, 별도 파이프라인
  오케스트레이터와 검증 스크립트 3개에서만 쓰인다. 클래스 자체 docstring은 파이프라인
  위치를 `Agent 2 → [Consolidator] → Registry`로 적어 모든 스터디에서 실행되는 것처럼
  암시하지만, 운영 경로의 `NCT-import` 호출 체인은 이를 호출하지 않는다.
- 이 코드베이스에는 `supervisor`라는 이름을 공유하는 두 개의 서로 다른 개념이
  있다 — `src/pipeline/supervisor.py`의 `PipelineSupervisor`(전체 `Agent1-4` 오케스트레이터)와
  `tte_service.py`의 `SupervisorHooks`/`SupervisorHookPoint`(사람 검토 `hook` 메커니즘,
  tte_service.py:64-65, 2905-2991)는 서로 무관하다.
- `enricher.py`의 직접 테스트 커버리지(`test_09_enricher.py`, 4개)가 그 중심성
  (모든 PDF/PMC/PubMed 보강 경로가 이 파일을 거침)에 비해 얇다.

**Agent 2**
- `Agent2Workflow.process_batch`, `_fast_path`, `_slow_path_batch`, `ComplexityRouter.route`의
  실제 fast/slow 판정, `RuleExtractor`가 모두 프로덕션에서 도달 불가능하다
  (`process_with_details`가 `route_path = "slow"`를 무조건 대입, §4.10).
- `ConceptLogician.prune_empty_concepts`(logic.py:623-630)가 아무 동작도 하지 않는 스텁(`Currently a
  passthrough`)이지만 여러 곳에서 필터링하는 것처럼 계속 호출된다.
- `ConceptCritic.evaluate`의 예외 폴백(critic.py:546-558)이 호출자에게 조용하다 —
  일시적 LLM 실패는 `seed_concept_ids`를 반환하며 `critic이 처음 고른 개념을 골랐다`와 `critic이
  실패해 처음 고른 개념을 썼다`를 구분할 필드가 없다.
- `src/api/main.py:31-35`가 `conceptset` 라우터 마운트 전체를 무조건 `except Exception:
  pass`로 삼켜서, 그 아래 모듈 중 하나라도 import에 실패하면 `/api/conceptset/*`
  엔드포인트가 로그 한 줄 없이 사라진다 — 이는 §4.6에서 설명한 메인 파이프라인의
  최후 폴백 단계이기도 하다.
- `RAGSearch`의 `ConceptCandidate`(점수 높을수록 좋음)와 `retriever.py`의
  `CandidateConcept`(거리 낮을수록 좋음)가 이름은 비슷하지만 점수의 방향이 반대인 별개
  `Pydantic` 모델이며, 이를 뒤섞지 않도록 강제하는 장치가 없다.
- 비교군 추천은 계산되지만 절대 적용되지 않는다: `_build_recommended_placebo_comparator_circe`가
  항상 `recommend_from_literature`의 출력을 버리고 파생 `disease-based` comparator를
  쓴다. 이것은 **결함이 아니라 ADR-028이 요구하는, 아직 배선되지 않은 사람 승인
  게이트를 기다리는 의도된 상태**다(§4.7).

**`TTEService` / API**
- `TTEService._build_agent6_workflow`(tte_service.py:9302-9313)가 가져온 Agent 6
  워크플로가 import는 성공했지만 생성/실행 중 실패하면 로그 없이 내부 클래스로
  폴백한다. 바깥 wrapper가 보고하는 실패 사유는 **내부** 클래스 생성 실패의 사유이지,
  원래 가져온 실패의 사유가 아니다.
- `TTEStore._read()`(tte_store.py:185-198)가 JSON 디코드 3회 실패 후 실제 콘텐츠를
  전부 버리고 샘플 스터디 1개짜리 초기 상태를 반환한다 — `_log.error` 한 줄만 남고
  raise도 API 노출도 없다.
- `_build_seeded_target_circe` 내부 `shared_workflow = None`(tte_service.py:5317-5321)이
  `Agent2Workflow()` 생성 실패를 로그 한 줄 없이 삼킨다.
- 중복 `PSM-fallback` 테스트 파일: `tests/test_agent5_psm_fallback.py`(3개)와
  `tests/analysis/test_agent5_psm_fallback.py`(10개)가 같은 파일명을 다른 디렉터리에
  갖고 있으며 겹치는지 diff되지 않았다.

**전달 게이트**
- 체크 (p) `ungrounded_criteria`(verify_circe_delivery.py:2392-2417)는 설계상
  보고 전용이다 — `any_fail`에 기여하지 않으므로 전달 리포트의 `grounding` 행을
  pass/fail 신호로 오독하기 쉽다.

## 11. 참고 문서

아래 기존 문서는 마지막 수정일이 **2026-07-22**이며, §9의 변경 사항보다 앞선다.
동작 설명을 확인할 때는 이 문서보다 위 §3-§9의 `path:line`/커밋 인용을 우선한다.

- `docs/mapping_agent_explanation.md`
- `docs/extraction_agent_diagram_guide.md`
- `docs/user_guide.md`
- `docs/DEVELOPMENT_STATUS.md`
- `docs/README.md`

관련 ADR: `ADR-027`(comparator 설계, 활성 비교군 전환 2단계), `ADR-028`(comparator
추천은 제안일 뿐, 사람 승인 전까지 미적용), `ADR-032`(임계값 처리를 3단계로 나눈 파이프라인,
2단계는 §3.10 참고).

프로젝트 표준 사실: `docs/agent-briefing-facts.md` — 합성 CDM 경고, 프롬프트/캐시
경제성, 평가 원칙, 전달 위치 관례의 단일 출처다.
