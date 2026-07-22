# V6 Cohort 0-Patient Attrition Debugging Plan (Atomic TODO)

**작성일**: 2026-03-17  
**상태**: IN PROGRESS  
**목적**: Gold LEADER cohort (ID 166)의 `0 PersonCount` 문제가 이미 적용된 수정 이후에도 남아 있는지 증명하고, 남아 있다면 정확히 어느 단계에서 0명으로 떨어지는지 atomic한 디버깅 단위로 좁힌다.

## 1. 문제 재정의

이 문서는 더 이상 "가능한 원인 후보 목록"이 아니다. 현재 시점에서 이미 코드/문서로 확인된 사실과, 아직 런타임으로 증명되지 않은 질문을 분리한다.

### 1-1. 현재까지 확인된 사실

| 항목 | 판정 | 근거 |
|:---|:---|:---|
| Gold JSON에 top-level `AdditionalCriteria`가 존재한다 | 확인 | `artemis/data/gold/LEADER/LEADER_GOLD.json` |
| Gold JSON의 실제 `InclusionRules` 개수는 18개다 | 확인 | `artemis/data/gold/LEADER/LEADER_GOLD.json` |
| `generate_synthea_from_gold.py`는 현재 top-level `AdditionalCriteria`를 읽는다 | 확인 | `artemis/scripts/generate_synthea_from_gold.py` |
| ETL 스크립트들은 현재 `postgres` DB를 타겟으로 한다 | 확인 | `artemis/scripts/run_synthea_parallel_and_etl.py`, `artemis/scripts/run_etl_full.sh`, `artemis/scripts/run_etl_benchmark.R` |
| WebAPI의 `generation_cache`가 과거 0명 결과를 재사용할 수 있다 | 확인 | `artemis/docs/debugging/2026-03-17_v6_cohort_gold_additional_criteria.md` |
| Agent 1 prompt의 one-shot example 제거가 완료되었다 | 미확인 | 실제 `artemis/src/agents/agent1/prompts.py`에는 아직 예시가 남아 있음 |

### 1-2. 아직 증명되지 않은 핵심 질문

1. 캐시를 배제하고 재실행했을 때, Gold 166의 **Entry-only** 코호트는 0명이 아닌가?
2. Entry-only가 통과한다면, **18개 Inclusion Rule 중 어느 규칙**이 첫 번째 치명적 drop-off를 만드는가?
3. Entry-only가 여전히 0명이라면, 원인은 **데이터 부재 / source-schema 불일치 / 캐시 재사용 / WebAPI 실행 경로 문제** 중 무엇인가?

### 1-3. 이 문서의 범위

- **핵심 범위**: Gold 166의 0명 문제를 재현 가능하게 다시 측정하고, 0명으로 떨어지는 지점을 증거 기반으로 특정한다.
- **병렬 범위**: Agent 1 prompt one-shot example 제거.
- **범위 제외**: 프롬프트 튜닝 자체는 Gold 166 0명 RCA의 선행 조건이 아니다. 별도 follow-up으로 분리한다.

## 2. 실행 원칙

1. 한 번에 하나의 가설만 바꾼다.
2. 모든 todo는 하나의 산출물(로그, SQL, JSON, count table, diff)을 남긴다.
3. 모든 WebAPI generate는 **고유한 cohort 이름** 또는 **명시적 cache clear** 중 하나를 반드시 사용한다.
4. `/tmp/*.py` 대신 저장소 내부 스크립트를 우선 사용한다. 디버깅 재현성을 위해 `artemis/scripts/` 아래에 남긴다.
5. "0명"만 기록하지 말고, 항상 **status / source / personCount / SQL size / rule index**를 같이 남긴다.

## 2-1. 현재 판단

- 지금 증거만 보면 `49 ConceptSets + AdditionalCriteria`에서 환자가 안 나오는 문제를 곧바로 "데이터 생성 부족"으로 결론 내릴 수 없다.
- 이유:
  - direct SQL 기준으로 `liraglutide + T2DM + 180일 window + era filters`를 만족하는 환자는 이미 `1479명` 존재한다.
  - source 5는 실제로 `ohdsi` DB의 `synthea_cdm_benchmark`를 바라본다.
  - `synthea23m.concept_ancestor`에는 `ancestor_concept_id`, `descendant_concept_id` 인덱스가 이미 존재한다.
- 따라서 다음 단계의 1차 목표는 **generator를 더 바꾸는 것**이 아니라, **238 vs 239의 payload/SQL 차이 중 무엇이 1093 → 0을 만드는지 자르는 것**이다.
- generator 수정은 아래 비교 실험에서 "진짜로 생성 데이터가 부족하다"는 근거가 나온 뒤에만 한다.

## 3. Atomic TODO Checklist

### 단계 표기 설명

- `1단계 (A)`: 사실 고정 및 문서 정리
- `2단계 (B)`: 런타임 전제조건 검증
- `3단계 (C)`: 재사용 가능한 attrition tracer 준비
- `4단계 (D)`: Entry-only 재검증
- `5단계 (E)`: Inclusion Rule별 attrition 추적
- `6단계 (F)`: Entry 실패 또는 특정 규칙 실패의 RCA
- `7단계 (G)`: 수정 후 회귀 검증
- `8단계 (H)`: 병렬 follow-up

`TODO-A01` 같은 표기는 "1단계(A)의 01번 todo"라는 뜻이다.

### 1단계 (A). 사실 고정 및 문서 정리

- [x] TODO-A01. Gold JSON의 실제 구조 수치를 고정한다.
  Files: `artemis/data/gold/LEADER/LEADER_GOLD.json`
  Verify: `python3 -c "import json; o=json.load(open('artemis/data/gold/LEADER/LEADER_GOLD.json')); print(f\"rules={len(o['InclusionRules'])} cs={len(o['ConceptSets'])} add={isinstance(o.get('AdditionalCriteria'), dict)}\")"`
  Done when: `rules=18 cs=54 add=True`를 작업 로그에 남긴다.
  Findings: `rules=18`, `cs=54`, `add=True` 확인.

- [x] TODO-A02. Entry의 첫 기준과 `AdditionalCriteria`의 codeset/window를 텍스트로 고정한다.
  Files: `artemis/data/gold/LEADER/LEADER_GOLD.json`
  Verify: Gold JSON에서 `PrimaryCriteria.CriteriaList[0]`와 `AdditionalCriteria`를 그대로 발췌해 작업 로그에 기록한다.
  Done when: "Entry drug 기준"과 "추가 correlated criteria"가 각각 무엇인지 한 줄씩 설명할 수 있다.
  Findings: Entry는 `DrugEra CodesetId=32 (liraglutide), EraStartDate>=2010-10-06, EraLength>=7`.
  Findings: AdditionalCriteria는 `ConditionOccurrence CodesetId=91 (T2DM)`가 index 이전 `180일` 이내에 1회 이상 존재해야 한다.

- [x] TODO-A03. `AdditionalCriteria` 파싱 수정이 현재 코드에 존재하는지 확인한다.
  Files: `artemis/scripts/generate_synthea_from_gold.py`
  Verify: `rg -n "AdditionalCriteria|_extract_primary_criteria_reqs" artemis/scripts/generate_synthea_from_gold.py`
  Done when: top-level `gold.get("AdditionalCriteria")`를 읽는 코드 위치를 로그에 남긴다.
  Findings: `artemis/scripts/generate_synthea_from_gold.py:500-501`에서 top-level `gold.get("AdditionalCriteria")`를 읽는다.

- [x] TODO-A04. ETL 경로가 모두 `postgres`를 가리키는지 고정한다.
  Files: `artemis/scripts/run_synthea_parallel_and_etl.py`, `artemis/scripts/run_etl_full.sh`, `artemis/scripts/run_etl_benchmark.R`
  Verify: `rg -n "postgres|ohdsi" artemis/scripts/run_synthea_parallel_and_etl.py artemis/scripts/run_etl_full.sh artemis/scripts/run_etl_benchmark.R`
  Done when: 세 파일 모두 `postgres`를 사용함을 로그에 남긴다.
  Findings: 스크립트 텍스트는 모두 `postgres` DB를 가리킨다.
  Findings: 반면 live benchmark schema는 `postgres`가 아니라 `ohdsi` DB에 존재한다.

- [x] TODO-A05. 기존 문서들의 주장 충돌을 "과거 가설"과 "현재 기준"으로 분리한다.
  Files: `artemis/docs/debugging/2026-03-17_v6_cohort_gold_zero.md`, `artemis/docs/debugging/2026-03-17_v6_cohort_gold_additional_criteria.md`
  Verify: 두 문서에서 서로 충돌하는 진단(ConceptSet/SqlRender vs AdditionalCriteria/DB mismatch)을 한 줄 요약으로 정리한다.
  Done when: 이후 디버깅은 반드시 fresh rerun 결과를 기준으로만 판단하기로 명시한다.
  Findings: 현재 기준에서는 source 5가 실제로 `ohdsi`에 연결되므로 "global DB mismatch"는 주원인 후보에서 내려간다.
  Findings: 남은 축은 `AdditionalCriteria/Gold payload shape`와 `large payload execution cost`다.

- [x] TODO-A06. 프롬프트 튜닝 항목을 core debug에서 분리한다.
  Files: `artemis/src/agents/agent1/prompts.py`
  Verify: `rg -n "One-shot Example|HbA1c lower bound|HbA1c upper bound" artemis/src/agents/agent1/prompts.py`
  Done when: "프롬프트 정리 = 병렬 작업, 0명 RCA blocker 아님"으로 상태를 재분류한다.
  Findings: one-shot example은 아직 남아 있다. 다만 Gold 166 0명 RCA의 선행 blocker는 아니다.

### 2단계 (B). 런타임 전제조건 검증

- [x] TODO-B01. WebAPI에서 실제 사용할 source key / source id / source name을 고정한다.
  Files: `webapi.source`
  Verify: `docker exec broadsea-atlasdb psql -U postgres -d postgres -c "select source_id, source_key, source_name from webapi.source order by source_id;"`
  Done when: 이번 디버깅에서 사용할 source를 하나로 고정한다.
  Findings: 사용 source는 `source_id=5`, `source_key=SYNTHEA_CDM_BENCHMARK`, `source_name='Synthea Benchmark (1.2K)'`.

- [x] TODO-B02. source daimon이 어느 CDM/results schema를 가리키는지 확인한다.
  Files: `webapi.source_daimon`
  Verify: `docker exec broadsea-atlasdb psql -U postgres -d postgres -c "select source_id, daimon_type, table_qualifier, priority from webapi.source_daimon order by source_id, daimon_type, priority;"`
  Done when: CDM, vocabulary, results 스키마가 무엇인지 로그에 남긴다.
  Findings: source 5는 `CDM=synthea_cdm_benchmark`, `Vocabulary=synthea23m`, `Results=synthea_cdm_benchmark_results`.
  Findings: `webapi.source.source_connection`은 `jdbc:postgresql://broadsea-atlasdb:5432/ohdsi?...` 이다.

- [x] TODO-B03. cache 회피 전략을 하나로 정한다.
  Files: `webapi.generation_cache`
  Verify: 실행 전 "고유 cohort 이름 사용" 또는 "generation_cache 삭제" 중 하나를 선택해 문서에 체크한다.
  Done when: 같은 design hash를 재사용하지 않겠다는 운영 규칙이 정해진다.
  Findings: source 5의 `is_cache_enabled=false`.
  Findings: `postgres.webapi.generation_cache` row count는 `0`.
  Findings: 이번 디버깅은 `고유 cohort 이름 사용`을 기본 전략으로 한다.

- [x] TODO-B04. OMOP CDM 기본 row count를 확인한다.
  Files: `synthea_cdm_benchmark.person`, `drug_era`, `condition_occurrence`, `measurement`
  Verify: `docker exec broadsea-atlasdb psql -U postgres -d postgres -c "select 'person' as table, count(*) from synthea_cdm_benchmark.person union all select 'drug_era', count(*) from synthea_cdm_benchmark.drug_era union all select 'condition_occurrence', count(*) from synthea_cdm_benchmark.condition_occurrence union all select 'measurement', count(*) from synthea_cdm_benchmark.measurement;"`
  Done when: 네 테이블 모두 0건이 아님을 확인한다.
  Findings: 이 확인은 `postgres` DB에서 실패했고, 실제 데이터는 `ohdsi` DB에 있었다.
  Findings: `ohdsi.synthea_cdm_benchmark` 기준 row count는 `person=10000`, `drug_era=1496`, `condition_occurrence=3644`, `measurement=5940`.

- [x] TODO-B05. liraglutide + T2DM 조합이 최소한 존재하는지 직접 확인한다.
  Files: `synthea_cdm_benchmark.drug_era`, `condition_occurrence`
  Verify: liraglutide codeset과 T2DM codeset을 기준으로 직접 SQL count를 실행한다.
  Done when: Entry-only 후보 환자가 DB에 실제로 존재하는지 yes/no를 기록한다.
  Findings: `Codeset 32=liraglutide`, `Codeset 91=T2DM`.
  Findings: direct SQL 기준 `liraglutide + T2DM within 180 days + era filters`를 만족하는 distinct person count는 `1479`.

- [x] TODO-B06. 결과 스키마와 캐시 테이블 상태를 초기화 가능한지 확인한다.
  Files: `webapi.generation_cache`, `synthea_cdm_benchmark_results.*`
  Verify: 캐시 삭제 SQL과 결과 테이블 truncate SQL을 dry-run 수준으로 준비한다.
  Done when: rerun 직전에 어떤 SQL을 실행할지 명시되어 있다.
  Findings: central `generation_cache` clear는 현재 필요성이 낮다 (`row count=0`).
  Findings: 결과 스키마 관찰용 SQL은 `select count(*) from synthea_cdm_benchmark_results.cohort;` 및 `select count(*) from synthea_cdm_benchmark_results.cohort_inclusion_stats;`를 사용한다.

### 3단계 (C). 재사용 가능한 attrition tracer 준비

- [x] TODO-C01. 기존 attrition 관련 스크립트들을 inventory 한다.
  Files: `artemis/scripts/attrition_analysis.py`, `artemis/scripts/attrition_v5_patched.py`, `artemis/scripts/attrition_v5b_diagnostic.py`, `artemis/scripts/cohort_via_webapi.py`
  Verify: 각 스크립트의 입력 포맷, HTTP 의존성, 캐시 회피 여부를 1줄씩 표로 정리한다.
  Done when: "재사용 가능 / 부분 재사용 / 폐기" 판정을 각 스크립트에 부여한다.
  Findings: 기존 스크립트들은 TROY/ARTEMIS 전용 인덱스 또는 `requests/psycopg2` 의존성이 있어 Gold 166 재현용으로는 부적합했다.

- [x] TODO-C02. 새 스크립트를 만들지, 기존 스크립트를 패치할지 결정한다.
  Files: `artemis/scripts/`
  Verify: `stdlib only`, `unique cohort names`, `payload dump`, `CSV/JSON 로그 저장` 네 요구사항을 충족하는 베이스를 하나 선택한다.
  Done when: 구현 대상 파일명이 고정된다.
  Findings: 신규 파일 `artemis/scripts/trace_cohort_attrition.py`를 추가했다.

- [x] TODO-C03. tracer는 저장소 내부 파일로 둔다.
  Files: `artemis/scripts/trace_cohort_attrition.py` 또는 기존 스크립트
  Verify: `/tmp/trace_cohort_attrition.py` 대신 repo 내부 경로를 사용한다고 명시한다.
  Done when: 결과 재현에 필요한 스크립트 경로가 버전 관리 대상이 된다.
  Findings: 결과 artifact는 `artemis/output/attrition_runs/<run_id>/` 아래에 저장한다.

- [x] TODO-C04. tracer에 dry-run 모드를 추가한다.
  Files: attrition tracer 스크립트
  Verify: WebAPI 호출 없이 각 레벨 payload를 JSON 파일로만 저장하는 옵션이 존재한다.
  Done when: "payload가 의도한 대로 만들어졌는지"를 API 호출 전에 확인할 수 있다.
  Findings: `--execute`를 주지 않으면 dry-run으로 payload + SQL artifact만 저장한다.

- [x] TODO-C05. tracer에 unique naming 규칙을 추가한다.
  Files: attrition tracer 스크립트
  Verify: cohort 이름에 timestamp 또는 run id가 포함된다.
  Done when: 동일 payload라도 cache collision 없이 반복 실행할 수 있다.
  Findings: cohort 이름은 `[ATTRITION] Gold LEADER <run_id> Lxx <label>` 형식이다.

- [x] TODO-C06. tracer에 결과 로그 출력을 추가한다.
  Files: attrition tracer 스크립트
  Verify: 각 실행마다 `level, rule_count, concept_set_count, status, person_count, cohort_id, source_id`를 CSV 또는 JSONL로 남긴다.
  Done when: rerun 간 비교가 가능해진다.
  Findings: 각 run dir에 `manifest.json`, `levels.json`, `results.jsonl`, `payload.json`, `template.sql`이 남는다.

### 4단계 (D). Entry-only 재검증

- [x] TODO-D01. Gold 166에서 `PrimaryCriteria + AdditionalCriteria`만 포함한 Entry-only payload를 만든다.
  Files: Gold JSON, attrition tracer
  Verify: InclusionRules는 0개이고, `AdditionalCriteria`는 유지된 payload JSON을 저장한다.
  Done when: Entry-only payload 파일이 생성된다.
  Findings: full Entry-only dry-run artifact는 `artemis/output/attrition_runs/20260317T121423Z/`에 저장했다.
  Findings: minimal Entry-only dry-run artifact는 `artemis/output/attrition_runs/20260317T122146Z/`에 저장했다.

- [x] TODO-D02. Entry-only payload의 concept sets를 prune할지 여부를 먼저 결정한다.
  Files: attrition tracer
  Verify: "full concept sets 유지" vs "referenced concept sets만 유지" 중 하나를 선택하고 이유를 적는다.
  Done when: 첫 rerun에서 바뀌는 변수가 하나뿐이 되도록 결정된다.
  Findings: 둘 다 만들었다.
  Findings: full Entry-only는 `ConceptSets=54`, SQL `42329 bytes`; minimal Entry-only는 `ConceptSets=2`, SQL `10613 bytes`.

- [x] TODO-D03. rerun 직전에 cache 처리 전략을 실제 적용한다.
  Files: `webapi.generation_cache`, results schema
  Verify: cache 삭제 SQL 또는 unique naming 사용 여부를 실행 로그에 남긴다.
  Done when: stale result 가능성을 명시적으로 배제했다.
  Findings: rerun은 모두 unique cohort names로 실행했다 (`20260317T121439Z`, `20260317T121900Z`, `20260317T122152Z`).

- [ ] TODO-D04. Entry-only cohort를 generate하고 status/personCount를 기록한다.
  Files: WebAPI, attrition tracer output
  Verify: WebAPI response와 `/info` polling 결과를 저장한다.
  Done when: Entry-only의 `status`, `personCount`, `cohort_id`, `source_id`가 남는다.

- [ ] TODO-D05. Entry-only 결과를 분기점으로 판정한다.
  Files: execution log
  Verify: `personCount > 0`이면 Phase E로, `personCount = 0`이면 Phase F로 진행한다고 체크한다.
  Done when: 다음 액션이 하나로 결정된다.

### Entry-only 실행 메모

- 기존 WebAPI cohort `238 [T4] Both`는 `ConceptSets=1`, `AdditionalCriteria 없음`, `rules=0` 상태에서 `personCount=1093`로 완료되었다.
- 기존 WebAPI cohort `239 [T_A] Gold Entry NoRules`는 `ConceptSets=49`, `AdditionalCriteria 있음`, `rules=0` 상태에서 `personCount=0`으로 완료되었다.
- 기존 WebAPI cohort `240 [T_B] Gold Entry + Rule0 Age`는 `ConceptSets=49`, `AdditionalCriteria 있음`, `rules=1` 상태에서 `personCount=0`으로 완료되었다.
- 새 rerun `20260317T121439Z` (`ConceptSets=54`)는 `cohort_definition_id=249`, `execution_duration=245088ms`, `is_valid=false`, `personCount=null`로 종료됐다. fail message는 `canceling statement due to user request`.
- 새 rerun `20260317T121900Z` (`ConceptSets=3`)는 `cohort_definition_id=250`, `execution_duration=152945ms`, `is_valid=false`, `personCount=null`로 종료됐다. fail message는 `canceling statement due to user request`.
- 새 rerun `20260317T122152Z` (`ConceptSets=2`)는 `cohort_definition_id=251`, `execution_duration=173505ms`, `is_valid=false`, `personCount=null`로 종료됐다. fail message는 `canceling statement due to user request`.

### 다음 실행 계획 (즉시 수행)

목표: `238`과 `239`의 차이를 한 번에 하나씩만 더해 가며, 어떤 요소가 `1093 -> 0` 또는 `실행 폭증`을 만드는지 분리한다.

1. 기준선 artifact 고정
   - 대상: cohort `238`, `239`, `240`, `251`
   - 산출물: 각 cohort의 `payload.json`, `info.json`, `template.sql`, `template_sql_bytes`
   - 판정: 이후 모든 비교는 이 네 개를 기준으로만 수행
   - 진행 현황: baseline artifact를 `artemis/output/attrition_compare/20260317_baseline_compare/`에 저장함

2. delta cohort 실험군 구성
   - `P0`: cohort 238과 동일한 minimal baseline
   - `P1`: `P0 + AdditionalCriteria`만 추가
   - `P2`: `P1 + EndStrategy`
   - `P3`: `P2 + CensoringCriteria`
   - `P4`: `P1 + Gold full ConceptSets`
   - `P5`: `P4 + Rule 1 (Age >= 50)`
   - 규칙: 한 실험군마다 오직 한 축만 더한다

3. 실행 규칙
   - source는 항상 `SYNTHEA_CDM_BENCHMARK`
   - 이름은 매번 unique run id 사용
   - 각 실험군마다 `template.sql`과 `results.jsonl` 저장
   - `pg_stat_activity`와 `cohort_generation_info`를 함께 기록
   - 수동 cancel은 정말 필요한 경우에만 사용하고, cancel 시점과 이유를 로그에 남김

4. 해석 규칙
   - `P1`에서 바로 0이면: `AdditionalCriteria` 또는 entry correlated SQL 해석 문제
   - `P2/P3`에서만 깨지면: `EndStrategy` 또는 `CensoringCriteria` 경로 문제
   - `P4`에서만 깨지면: full ConceptSet expansion / vocabulary expansion 비용 문제
   - `P5`에서 처음 급락하면: 생성 데이터가 rule 1 이후 요구사항을 아직 못 맞춤

5. generator 수정 진입 조건
   - 아래 둘 중 하나가 증명될 때만 `generate_synthea_from_gold.py` 수정
   - 조건 A: `P1` direct SQL에서도 실제 환자 수가 부족함
   - 조건 B: `P5+`에서 특정 rule의 clinical fact가 실제 데이터에 없음
   - 이 조건이 없으면 generator 수정은 보류
   - 수정 범위와 검증 절차는 별도 문서 `artemis/docs/debugging/2026-03-17_generate_synthea_from_gold_fix_plan.md`에 기록한다.

### 5단계 (E). Inclusion Rule별 attrition 추적

- [ ] TODO-E01. 누적 규칙 집합을 `L0`부터 `L18`까지 생성한다.
  Files: Gold JSON, attrition tracer
  Verify: `L0=entry only`, `L1=rule1`, ..., `L18=rule1..18` payload 목록이 생성된다.
  Done when: 각 레벨이 정확히 어떤 규칙을 포함하는지 파일명 또는 메타데이터로 추적 가능하다.

- [ ] TODO-E02. 각 레벨 payload에서 실제 참조되는 concept set count를 기록한다.
  Files: attrition tracer output
  Verify: 레벨별 `concept_set_count`가 로그에 남는다.
  Done when: "규칙 수 증가"와 "concept set 증가"를 분리해서 볼 수 있다.

- [ ] TODO-E03. `L0 -> L18`을 순차 실행한다.
  Files: WebAPI, attrition tracer output
  Verify: 병렬 실행 없이 한 번에 한 레벨만 generate한다.
  Done when: 레벨별 personCount 시계열이 생긴다.

- [ ] TODO-E04. 첫 번째 치명적 drop-off 지점을 찾는다.
  Files: attrition result CSV/JSON
  Verify: `personCount`가 처음으로 0이 되거나 비정상 급락하는 레벨을 표시한다.
  Done when: "문제 규칙 prefix"가 `Lk` 형태로 고정된다.

- [ ] TODO-E05. 문제 prefix의 직전 레벨과 현재 레벨 payload를 diff한다.
  Files: payload JSON artifacts
  Verify: JSON diff에서 새로 추가된 rule과 concept set만 분리한다.
  Done when: 실제로 추가된 변경점이 1개 rule인지, rule+concept set pruning 변화인지 명확해진다.

### 6단계 (F). Entry 실패 또는 특정 규칙 실패의 RCA

- [ ] TODO-F01. 실패한 레벨의 SQL template를 저장한다.
  Files: WebAPI `/cohortdefinition/sql` output
  Verify: SQL 파일 크기(bytes), line 수, 생성 시각을 함께 기록한다.
  Done when: 나중에 SQL 비교가 가능해진다.

- [ ] TODO-F02. 실패한 레벨의 `qualified_events`와 correlated criteria를 직접 읽는다.
  Files: 저장된 SQL
  Verify: `qualified_events`, `#Codesets`, `AdditionalCriteria` 관련 SQL 조각을 발췌한다.
  Done when: 사람 기준으로 "실패 레벨이 실제로 요구하는 임상 조건"을 설명할 수 있다.

- [ ] TODO-F03. 실패 규칙이 참조하는 codeset id / concept set name을 고정한다.
  Files: payload JSON, Gold JSON
  Verify: 해당 rule이 참조하는 codeset 목록을 로그에 남긴다.
  Done when: direct SQL 검증 대상 개념 집합이 결정된다.

- [ ] TODO-F04. direct SQL로 "이 규칙만" 만족하는 환자 수를 센다.
  Files: `synthea_cdm_benchmark.*`
  Verify: entry 통과 후보 집합 위에 문제 규칙 predicate만 추가한 SQL count를 실행한다.
  Done when: WebAPI 문제가 아니라 실제 데이터 부재인지 판정할 수 있다.

- [ ] TODO-F05. 실패 유형을 4분류 중 하나로 라벨링한다.
  Files: RCA notes
  Verify: 아래 4개 중 하나로만 분류한다.
  Done when: `missing_data`, `wrong_concept_set`, `temporal_window_mismatch`, `value_constraint_mismatch` 중 하나가 선택된다.

- [ ] TODO-F06. `missing_data`이면 Synthea 로더에서 필요한 OMOP fact를 생성하도록 요구사항을 적는다.
  Files: `artemis/scripts/generate_synthea_from_gold.py`
  Verify: 어떤 domain fact가 누락됐는지(Condition / Measurement / Drug / Observation)를 한 줄로 명시한다.
  Done when: 생성기 수정 대상이 함수 수준으로 좁혀진다.

- [ ] TODO-F07. `wrong_concept_set`이면 concept set 이름과 resolved concept count를 비교한다.
  Files: Gold JSON, resolved concept query
  Verify: 동일 rule의 기대 concept pool과 실제 concept pool 차이를 출력한다.
  Done when: codeset 자체가 비어 있거나 과도하게 좁다는 근거가 남는다.

- [ ] TODO-F08. `temporal_window_mismatch`이면 days/coefficient 해석을 표로 정리한다.
  Files: failing rule JSON
  Verify: `StartWindow`와 `EndWindow`의 실효 일수를 계산해 로그에 남긴다.
  Done when: "규칙이 생각보다 좁게/반대로 적용됐다"를 증명하거나 기각한다.

- [ ] TODO-F09. `value_constraint_mismatch`이면 operator/value/unit을 DB 사실과 비교한다.
  Files: failing rule JSON, measurement query
  Verify: threshold 바로 위/아래 환자 count를 둘 다 센다.
  Done when: 비교 연산자 또는 단위 mismatch 여부가 판정된다.

### 7단계 (G). 수정 후 회귀 검증

- [ ] TODO-G01. 수정 후 Entry-only를 다시 실행한다.
  Files: attrition tracer output
  Verify: 동일 source, 새로운 run id로 L0를 재실행한다.
  Done when: pre-fix 대비 personCount 변화가 기록된다.

- [ ] TODO-G02. 실패했던 prefix 레벨을 다시 실행한다.
  Files: attrition tracer output
  Verify: 문제를 일으켰던 `Lk`를 동일 조건으로 재실행한다.
  Done when: `Lk`의 personCount가 0이 아닌지 확인된다.

- [ ] TODO-G03. 전체 Gold 166 full run을 다시 실행한다.
  Files: WebAPI, results schema
  Verify: `L18` 또는 full Gold payload를 generate한다.
  Done when: full run의 최종 personCount가 기록된다.

- [ ] TODO-G04. 최종 RCA 문서에 "무엇이 문제였고 어떤 증거로 판정했는지"를 남긴다.
  Files: `artemis/docs/debugging/`
  Verify: 사용한 명령, SQL, counts, failing rule index, 수정 파일을 1페이지로 요약한다.
  Done when: 다음 rerun 없이도 다른 사람이 원인과 수정 효과를 재구성할 수 있다.

### 8단계 (H). 병렬 follow-up

- [ ] TODO-H01. Agent 1 prompt의 one-shot example 제거를 별도 작업으로 처리한다.
  Files: `artemis/src/agents/agent1/prompts.py`
  Verify: `rg -n "One-shot Example|HbA1c lower bound|HbA1c upper bound" artemis/src/agents/agent1/prompts.py`
  Done when: 위 grep 결과가 0건이 된다.

## 4. Exit Criteria

- Entry-only가 0명이 아닌지, 아닌 경우 어떤 증거로 확인했는지 설명할 수 있다.
- 18개 Inclusion Rule 중 어느 규칙 prefix에서 0명 또는 급락이 발생하는지 재현 로그가 있다.
- 문제를 `missing_data / wrong_concept_set / temporal_window_mismatch / value_constraint_mismatch` 중 하나로 분류했다.
- 수정 후 L0, failing prefix, full Gold 166 세 가지가 모두 재실행되었다.

## 5. Risks & Mitigations

- **Risk: stale cache로 인해 잘못된 0명/비0명 판정**
  - Mitigation: unique cohort naming 또는 explicit cache delete를 필수 절차로 강제.
- **Risk: `/tmp` 스크립트 사용으로 재현 불가**
  - Mitigation: 모든 tracer와 산출물 경로를 저장소 내부로 고정.
- **Risk: 한 번에 여러 변수 변경**
  - Mitigation: Entry-only → cumulative rules → failing rule RCA 순서로 한 단계씩만 변경.

## 6. Rollback Plan

1. 새로 추가한 debug 스크립트만 되돌린다.
2. WebAPI에 생성한 임시 cohort definition은 이름 prefix 기준으로 정리한다.
3. 캐시/결과 스키마 정리는 디버깅용 임시 데이터에만 한정한다.
