# 2026-03-18: PLATO Gold 합성/ETL/WebAPI handoff

> Current-state note:
> This document remains the detailed historical handoff log for the March 18 work.
> For the consolidated current interpretation across PLATO / LEADER / ARISTOTLE and the SQL translation path split, see:
> `artemis/docs/debugging/2026-03-22_generated_gold_sql_translation_current_state.md`

## 오늘 확인한 핵심

- 기준 파일은 **`artemis/data/gold/PLATO/PLATO_GOLD.json`**
- `artemis_plato.json` 같은 수동 seed 모듈이 아니라, **Gold 기반 compiler 산출물** `artemis_plato_gold.json`으로 진행함
- 목표는:
  1. PLATO Gold에 어느 정도 맞는 환자 생성
  2. OMOP ETL 적재
  3. WebAPI cohort에서 실제 `personCount > 0` 확인

## 현재 상태 요약

### 이미 해결한 것

- `generate_synthea_from_gold.py`로 `artemis_plato_gold.json` 생성 가능
- Synthea fat jar 재빌드 완료
- `artemis_plato_gold`로 3,000명 생성 가능
- native benchmark schema load 가능
- benchmark ETL은 DB 설정 조정 후 재시도하면 통과 가능
- PLATO Gold entry의 첫 병목이던 `DrugEra length >= 7`는 compiler patch로 해결함

### 아직 남은 것

- direct SQL로는 PLATO `entry-only`가 **140명**
- direct SQL로는 PLATO `full`도 **139명**
- WebAPI는 `entry-only`는 prune 후 **140명**까지 복구됨
- 그런데 WebAPI `full`은 여전히 **0명**

즉 현재 blocker는:

> **WebAPI full execution path가 direct SQL 139명을 0명으로 만드는 이유**

## 쉽게 설명

- `entry-only`는 이미 통과했다.
  - 약만 보면 SQL도 `140명`, WebAPI도 `140명`
- `full`도 SQL로 직접 돌리면 통과한다.
  - full logic을 SQL로 세면 `139명`
- 그런데 같은 full logic을 WebAPI로 돌리면 `0명`이 나온다.

한 줄로 말하면:

> **데이터가 아예 없는 게 아니라, WebAPI가 full cohort를 실행하는 경로에서만 139명을 0명으로 만들고 있다.**

---

## 관련 파일

### Gold / compiler
- `artemis/data/gold/PLATO/PLATO_GOLD.json`
- `artemis/scripts/generate_synthea_from_gold.py`
- `artemis/tests/test_generate_synthea_from_gold.py`
- `data/synthea/synthea/src/main/resources/modules/artemis_plato_gold.json`

### ETL / infra
- `artemis/scripts/load_synthea_benchmark.sql`
- `artemis/scripts/run_etl_benchmark.R`
- `artemis/scripts/create_benchmark_vocab.sql`

### 참고 문서
- `artemis/docs/debugging/2026-03-17_generate_synthea_from_gold_fix_plan.md`
- `artemis/docs/adr/ADR-026_Benchmark_Vocab_Subset.md`
- `artemis/docs/synthea_benchmark_data_pipeline.md`

---

## 오늘 한 일

### 1. PLATO Gold 기반 module 생성

명령:

```bash
python artemis/scripts/generate_synthea_from_gold.py \
  --gold artemis/data/gold/PLATO/PLATO_GOLD.json \
  --out data/synthea/synthea/src/main/resources/modules/artemis_plato_gold.json \
  --name artemis_plato_gold
```

결과:

- module 생성 성공
- `remarks`에
  - `path_count=12`
  - `Unsupported RangeHighRatio constraints are present.`
  가 기록됨

### 2. first run: 3,000명 생성 + ETL

생성 명령:

```bash
cd data/synthea/synthea
java -Xmx2g -jar build/libs/synthea-with-dependencies.jar \
  -m artemis_plato_gold \
  -p 3000 \
  --exporter.csv.export=true \
  --exporter.baseDirectory=output_plato_gold_3000
```

native load 결과:

- `patients.csv` → `3000`
- `encounters.csv` → `33946`
- `conditions.csv` → `3785`
- `medications.csv` → `2780`
- `procedures.csv` → `31`
- `observations.csv` → `87250`
- `organizations.csv` → `472`
- `providers.csv` → `472`

ETL 문제:

- `CreateMapAndRollupTables`에서 shared memory / I/O error 발생
- 아래 DB 설정으로 완화 후 재시도하여 ETL 성공

```sql
ALTER DATABASE ohdsi SET max_parallel_workers_per_gather = 0;
ALTER DATABASE ohdsi SET work_mem = '64MB';
ALTER DATABASE ohdsi SET enable_parallel_hash = off;
ALTER DATABASE ohdsi SET enable_hashagg = off;
```

### 3. first RCA: 왜 entry-only가 0명인가

PLATO Gold PrimaryCriteria:

- `DrugEra.CodesetId = 45`
- `EraStartDate >= 2011-07-22`
- `EraLength >= 7`

확인 결과:

- ticagrelor (`40241186`) 자체는 OMOP `drug_era`에 존재
- 하지만 1차 생성 데이터에서는 `drug_era` 길이가 전부 `0일`

즉 첫 번째 병목은:

> **index drug가 생성되긴 하지만 7일 이상 유지되는 era로 생성되지 않음**

직접 SQL 확인:

- `EraLength >= 7` 포함 → `0명`
- `EraLength >= 7` 제거 → `175명`

### 4. compiler patch: DrugEra length lowering

수정 내용:

- `DrugEra.EraLength`를 읽어 `era_length_days` metadata로 보존
- primary `DrugExposure`에 대해
  - `MedicationOrder`
  - `Delay(7 days)`
  - `MedicationEnd`
  구조를 자동 생성

추가 테스트:

- `test_extract_primary_criteria_paths_preserve_drug_era_min_length`
- `test_build_module_non_strict_adds_medication_end_for_plato_primary_drug_era`

현재 회귀:

```bash
python -m pytest -q artemis/tests/test_generate_synthea_from_gold.py
```

결과:

- `13 passed`

### 5. second run: 3,000명 재생성 + ETL

생성 명령:

```bash
cd data/synthea/synthea
java -Xmx2g -jar build/libs/synthea-with-dependencies.jar \
  -m artemis_plato_gold \
  -p 3000 \
  --exporter.csv.export=true \
  --exporter.baseDirectory=output_plato_gold_3000_v2
```

native load 결과:

- `patients.csv` → `3000`
- `encounters.csv` → `31691`
- `conditions.csv` → `3733`
- `medications.csv` → `330`
- `procedures.csv` → `31`
- `observations.csv` → `87392`
- `organizations.csv` → `476`
- `providers.csv` → `476`

ETL:

- 첫 시도는 again Step 5 I/O error
- 같은 DB 설정 유지 상태에서 **재시도하면 성공**

---

## v2에서 확정된 사실

### 1. DrugEra length patch는 실제 OMOP에 반영됨

SQL:

```sql
select (drug_era_end_date::date - drug_era_start_date::date) as era_days, count(*)
from synthea_cdm_benchmark.drug_era
where drug_concept_id = 40241186
group by 1 order by 1;
```

결과:

- `era_days = 7`
- count = `330`

또한 `drug_exposure`도:

- `days_supply = 7`
- `drug_exposure_end_date = start_date + 7 days`

즉:

> **생성기 패치는 실제 ETL 결과까지 반영되었음**

### 2. direct SQL entry-only는 140명

아래 SQL로 확인:

```sql
with base as (
  select de.person_id, de.drug_era_start_date as start_date, de.drug_era_end_date as end_date
  from synthea_cdm_benchmark.drug_era de
  where de.drug_concept_id = 40241186
    and de.drug_era_start_date >= date '2011-07-22'
    and (de.drug_era_end_date::date - de.drug_era_start_date::date) >= 7
)
select count(*) as rows, count(distinct b.person_id) as persons
from base b
join synthea_cdm_benchmark.observation_period op
  on b.person_id = op.person_id
 and b.start_date >= op.observation_period_start_date
 and b.start_date <= op.observation_period_end_date
where (op.observation_period_start_date + interval '180 day') <= b.start_date
  and (b.start_date + interval '0 day') <= op.observation_period_end_date;
```

결과:

- `persons = 140`

즉:

> **PLATO Gold entry-only는 이제 논리적으로 0명이 아니어야 함**

### 3. 그런데 WebAPI는 still 0명

직접 실행:

- `entry-only` cohort
- `full` cohort
- 새 cohort name 사용
- `_cacheBust`도 추가해서 재시도

결과:

- entry-only: `0명`
- full: `0명`

즉 현재 불일치:

- direct SQL = `140명`
- WebAPI = `0명`

이 결론은 **중간 단계 기준**이다.  
이후 RCA에서 아래처럼 정정되었다:

- `entry-only`는 prune 후 WebAPI도 **140명**
- `full`은 direct SQL로 **139명**
- 따라서 최신 blocker는 `entry-only`가 아니라 **`full` WebAPI path**

---

## 현재 판단

지금은 generator/compiler 쪽 1차 병목은 해결되었다.

현재 blocker는:

> **WebAPI 실행 경로에서 direct SQL 140명이 왜 0명으로 바뀌는가**

이 단계는 더 이상 `generate_synthea_from_gold.py` 문제가 아니라,

- WebAPI SQL generation / execution path
- cohort generation cache / metadata
- source mapping / dialect translation

쪽 RCA다.

---

## 새 창에서 바로 할 것

### 1. direct SQL 140명 재확인

위 SQL 그대로 실행

기대:

- `persons = 140`

### 2. WebAPI가 실제로 쓰는 SQL과 direct SQL 비교

확인 대상:

- `/cohortdefinition/sql`에서 받은 template SQL
- generation 시 실행된 SQL / generation info
- direct SQL 140명 쿼리

목표:

- **정말 같은 predicate인지**
- 혹은 WebAPI 쪽에서 다른 source/result/cached path를 타는지 확인

### 3. 최소 payload로 다시 자르기

우선순위:

1. `DrugEra only`
2. `DrugEra + ObservationWindow`
3. `DrugEra + full entry-only payload`

각 단계에서 direct SQL vs WebAPI count 비교

### 4. source / daimon / result table 재확인

체크:

```sql
select source_id, source_key, source_connection
from webapi.source
where source_id = 5;

select source_id, daimon_type, table_qualifier, priority
from webapi.source_daimon
where source_id = 5
order by daimon_type, priority;
```

현재 기대값:

- source 5 = `SYNTHEA_CDM_BENCHMARK`
- connection = `ohdsi`
- CDM daimon = `synthea_cdm_benchmark`
- results daimon = `synthea_cdm_benchmark_results`

---

## 한 줄 결론

PLATO는 **생성기 패치로 `DrugEra >= 7일` 문제를 해결했고, `entry-only`는 SQL/WebAPI 모두 검증 완료했다.**  
지금 남은 문제는 **`full` cohort에서 direct SQL 139명을 WebAPI가 왜 0명으로 실행하는지**다.

---

## 배운 점

- `direct SQL 140명`과 `WebAPI 0명` 비교는 **동일한 payload 복잡도**에서 해야 한다. 단순 `drug_era.drug_concept_id = 40241186` 수동 SQL과, unused `ConceptSets`가 다수 포함된 실제 WebAPI payload를 바로 비교하면 RCA가 엇나간다.
- PLATO entry-only의 실제 WebAPI 병목은 **unused `ConceptSets`**였다. 같은 `L0 EntryOnly`에서도 `cs=23` 상태로 보내면 `0명`, referenced codeset만 남겨 `cs=2`로 prune하면 `140명`이 나온다.
- 이 케이스에서 WebAPI는 **명시적 에러 없이 `COMPLETE + 0명`**을 반환할 수 있다. 따라서 `0명` 결과는 payload pruning / generated SQL / source mapping을 확인하기 전까지는 신뢰하면 안 된다.
- `_cacheBust` 추가나 cohort name 변경만으로는 해결되지 않았다. payload 자체가 비대하면 해시를 바꿔도 같은 문제를 반복한다.
- Gold/agent Circe JSON을 WebAPI에 보낼 때는 **referenced `CodesetId`만 남기는 `ConceptSets` pruning을 기본 전처리**로 두는 편이 안전하다.
- 앞으로 WebAPI RCA는 아래 순서가 가장 빠르다.
  1. `L0 EntryOnly`를 `no-prune` / `prune` 두 조건으로 바로 비교
  2. direct SQL은 **pruned payload와 동등한 predicate**로 맞춰 확인
  3. 그 다음에만 full payload / InclusionRules / clinical data 부족 여부로 넘어간다

---

## 최신 결론 정정

이 아래는 **최신 RCA 결과**다. 위의 중간 로그보다 이 섹션을 우선해서 보면 된다.

### 1. entry-only는 검증 완료

- direct SQL `entry-only` → **140명**
- WebAPI `entry-only` (`ConceptSets` prune 적용) → **140명**

즉 `entry-only`는 더 이상 blocker가 아니다.

### 2. full도 direct SQL로는 0명이 아니다

WebAPI `template.sql`의 실제 의미를 따라 direct SQL로 다시 세면:

- `entry-only` → **140명**
- `L1` (첫 inclusion rule 포함) → **139명**
- exclusion 적용 후 `full` → **139명**

즉:

> **PLATO full은 SQL 기준으로도 살아 있다. `full = 0`은 데이터 생성 문제로 단정하면 안 된다.**

### 3. full이 WebAPI에서만 0이 된다

최신 사실관계:

- SQL `entry-only` = **140**
- WebAPI `entry-only` = **140**
- SQL `full` = **139**
- WebAPI `full` = **0**

따라서 최신 blocker는:

> **WebAPI full execution path / SQL execution path 쪽 문제**

### 4. 왜 내가 중간에 잘못 봤는가

처음에는 PLATO 첫 inclusion rule을 너무 강하게 요약해서:

- biomarker **또는**
- `Age >= 60` + risk-factor + recent MI/PCI

처럼 해석했었다.

하지만 실제 `template.sql` 기준 L1 semantics는 더 넓다:

- `STEMI` 최근 7일 **또는**
- `ACS (excluding STEMI)` 최근 7일 **+**
  - positive biomarker **또는**
  - DM **또는**
  - PAD **또는**
  - CrCl < 60 **또는**
  - CAD **또는**
  - Age >= 60 **또는**
  - recent MI **또는**
  - recent PCI

이 실제 semantics로 direct SQL을 다시 세면 `139명`이 맞다.

### 5. 지금 의미하는 것

- 생성기 patch는 `entry-only` 검증까지는 성공
- `full`도 데이터 자체는 어느 정도 살아 있음
- 남은 문제는 generator가 아니라 **WebAPI full SQL 실행/translation/splitting 경로**일 가능성이 높음

### 6. 다음 액션

1. PLATO full `template.sql`을 PostgreSQL에서 직접 실행 가능한 형태로 번역해 `139명` 재현
2. 그 결과와 WebAPI `full=0`을 비교해 execution path 차이 확정
3. portable한 구조를 해치지 않도록, core에 Postgres 전용 로직을 박지 말고 adapter/debug path로 분리

---

## Option 1 문서화: tracer가 translated SQL artifact까지 남기기

### 왜 이 옵션이 필요한가

지금 느린 이유는:

- `trace_cohort_attrition.py`가 `payload.json`, `template.sql`까지만 남기고
- 그 다음부터는 사람이 `template.sql`을 읽어 의미를 다시 풀어야 하기 때문이다.

즉 지금 병목은 **실험 자체**보다 **중간 SQL을 사람이 해석하는 수작업**에 있다.

### 이 옵션의 핵심

기존 tracer 흐름은 유지하고,
각 run dir에 `translated.sql` 또는 그에 준하는 **실행 가능한 SQL artifact**를 추가로 남긴다.

즉:

- 지금: `payload.json` + `template.sql`
- 목표: `payload.json` + `template.sql` + `translated.sql`

### 기대 효과

- 같은 level (`L00`, `L01` 등)에 대해 사람이 매번 SQL 의미를 다시 해석하지 않아도 된다
- `template semantics SQL`을 손으로 재구성하는 시간을 줄일 수 있다
- `WebAPI result = 0`일 때 바로 **실행 가능한 SQL**을 따로 돌려 비교할 수 있다
- attrition 실험 반복 속도가 훨씬 빨라진다

### 어디를 바꾸는가

- 대상 스크립트: `artemis/scripts/trace_cohort_attrition.py`

현재 이 스크립트는:

- `payload.json`
- `template.sql`
- `results.jsonl`

을 남긴다.

Option 1에서는 여기에:

- `translated.sql`
- 가능하면 `translation_meta.json`

를 추가로 남기는 것이 목표다.

### 왜 1번이 당장 실용적인가

- 기존 실험 흐름을 거의 안 바꾼다
- artifact 중심이라 재현성과 비교가 좋다
- `entry-only`, `full`, 다른 trial에도 같은 방식으로 재사용 가능하다

### 한계

- 여전히 WebAPI / OHDSI 번역 경로에 일부 의존한다
- WebAPI가 번역된 SQL을 직접 주지 않으면 별도 번역 단계가 필요하다
- 따라서 이 옵션은 **단기 실험 속도 개선용**으로 가장 적합하다

### 한 줄 요약

> **Option 1은 “새 번역기를 core에 넣는 것”이 아니라, 기존 tracer가 실험에 필요한 SQL artifact를 더 완전하게 저장하도록 만드는 빠른 개선안이다.**

---

## 2026-03-18 추가 진행: generated data 10k 기준 RCA로 방향 전환

사용자 지시:

- semantic 세부 해석보다 **생성된 데이터에서 왜 최종 0명이 되는지** 본다.
- **study당 10,000명** 생성한다.
- 모든 진행 과정을 문서로 남긴다.

상세 로그:

- `artemis/docs/debugging/2026-03-18_generated_gold_10k_eval_log.md`

현재까지 잡힌 직접 원인:

1. custom Synthea module이 실제 run에서 `0 loaded` 상태였음
2. benchmark native/results DB target이 `postgres`/`ohdsi` 사이에서 뒤섞여 있었음
3. PLATO generator가 고른 ticagrelor ingredient code는 medication export를 만들지 못했음

현재 상태:

- multi-study harness 추가:
  - `artemis/scripts/evaluate_generated_gold_studies.py`
- 관련 테스트 추가:
  - `artemis/tests/test_evaluate_generated_gold_studies.py`
- PLATO generator patch 후 10k generated CSV 확인:
  - `patients=10000`
  - `conditions=12687`
  - `medications=1125`
  - 즉 **이제는 생성 데이터 자체가 비어서 0명인 상태는 아님**

추가로 확인된 것:

- PLATO 10k v3에서는 `L00 EntryOnly`부터 여전히 `0명`
- direct SQL도 `0명`
- 원인 추적 결과, 첫 ticagrelor override(`1115005`)는 export는 되지만 OMOP에서 **docusate sodium**으로 매핑됨
- 따라서 지금 남은 핵심 이슈는:
  - **Synthea에서 export되고**
  - **OMOP에서 ticagrelor로 들어오며**
  - **generated full module 구조에서도 실제로 medication row가 생기는**
  code path를 고정하는 것

남은 판정:

- ETL 완료 후 `L00 EntryOnly`가 살아나는지
- 그래도 final=0이면 WebAPI execution path와 direct SQL의 차이인지

## 2026-03-18 late update: current code 기준 rerun 결론

### fresh sanity run

- run id: `20260318_plato_300_currentcheck`
- local module은 이제 `1115005`가 아니라 **`1116635`**를 사용
- generated CSV:
  - `patients=300`
  - `conditions=372`
  - `medications=30`
- ETL 후:
  - `drug_exposure=30`
  - `drug_era=30`
- direct SQL primary-drug entry probe:
  - `persons=9`
- attrition:
  - WebAPI `L00 EntryOnly = 0`
  - same run `translated.sql` direct execute = `9`

즉 small rerun에서 이미:

> **데이터 생성/ETL은 살아 있고, WebAPI path와 direct SQL 결과가 갈라진다.**

### fresh 10k rerun

- run id: `20260318_plato_10k_currentcheck`
- generated CSV:
  - `patients=10000`
  - `encounters=105179`
  - `conditions=12705`
  - `medications=1064`
  - `observations=291810`
- ETL 후:
  - `person=10000`
  - `visit_occurrence=105179`
  - `condition_occurrence=12705`
  - `drug_exposure=1064`
  - `drug_era=1064`
  - `measurement=96`

ticagrelor 확인:

- `drug_exposure`:
  - `40241188 / 1116635 / ticagrelor 90 MG Oral Tablet = 1064`
- `drug_era`:
  - `40241186 / 1116632 / ticagrelor / era_days=7 = 1062`
  - `40241186 / 1116632 / ticagrelor / era_days=0 = 2`

entry probe:

- direct SQL primary-drug entry probe:
  - `persons=455`
- attrition:
  - WebAPI `L00 EntryOnly = 0`
  - same run `translated.sql` direct execute = `455`

### handoff conclusion update

이제 확정 가능한 결론은 아래다.

1. generator의 ticagrelor lowering (`1116632 -> 1116635`)은 실제 full module에서 동작한다.
2. fresh generated data는 ETL 후 OMOP에서 ticagrelor exposure/era를 정상적으로 만든다.
3. 따라서 **“데이터가 제대로 생성되지 않는다”는 문제는 fresh rerun 기준으로 해소됐다.**
4. 현재 blocker는:
   - WebAPI execution path
   - 또는 WebAPI 내부 translation / execution divergence

즉 다음 세션에서 이어갈 메인 질문은:

> **왜 WebAPI `EntryOnly=0`인데, 같은 run artifact의 `translated.sql` direct execute는 `455`인가?**

## 2026-03-18 final update: direct root cause identified

질문:

> 왜 WebAPI `EntryOnly=0`인데, direct SQL은 `455`인가?

현재 답:

> **WebAPI가 fresh generation을 하지 않고, stale generation cache의 `0명` 결과를 재사용했기 때문이다.**

### 증거

- `ohdsi-webapi` 로그:
  - `cohort_definition_id=438/439/440`
  - `GenerationCacheHelper`
  - `Using cached generation results for COHORT`
  - `design = -2126980604`
- 즉 ETL로 data를 갈아끼운 뒤에도 WebAPI는 같은 design hash의 옛 결과를 그대로 씀

- `webapi.generation_cache` 확인:
  - `type = COHORT`
  - `source_id = 5`
  - `design_hash = -2126980604`
  - `result_checksum = 0`

- 이 cache row 삭제 후 동일 cohort 재실행:
  - WebAPI `personCount = 455`
  - `synthea_cdm_benchmark_results.cohort`에 실제 `455` row 생성
  - WebAPI 로그도
    - `Cache is absent ... Calculating`
    - `Cached results of COHORT`
    로 바뀜

### practical conclusion

1. generator / ETL / data semantics 쪽은 이제 blocker가 아니다.
2. 현재 문제의 직접 원인은 **WebAPI generation cache invalidation 부재**다.
3. benchmark data를 다시 ETL한 뒤에는, 같은 source + 같은 cohort expression에 대해
   WebAPI가 예전 cache를 재사용할 수 있다.

### code/action update

- `artemis/scripts/evaluate_generated_gold_studies.py`
  - ETL 직후 `webapi.generation_cache`의 해당 source `COHORT` cache를 clear 하도록 수정
  - transient `recovery mode`에 대해서는 retry 추가
- `artemis/tests/test_evaluate_generated_gold_studies.py`
  - 관련 unit test 추가
- markdown summary 렌더러도
  - `webapi_nonzero`에서 `direct_sql=None`일 때 죽지 않도록 수정

### validation

fresh small rerun:

- run id: `20260318_plato_300_cachefixcheck_v2`
- 결과:
  - WebAPI `L00 EntryOnly = 12`
  - final `L05 Rule1to5 = 12`
  - `outcome = webapi_nonzero`

즉 지금 기준으로는:

> **EntryOnly=0의 원인은 stale WebAPI cache였고, cache를 비우면 WebAPI도 nonzero로 돌아온다.**

## 2026-03-18 latest update: PLATO full 10k nonzero confirmed

fresh 10k rerun:

- run id: `20260318_plato_10k_cachefixfinal`

generated / ETL:

- generated CSV:
  - `patients=10000`
  - `encounters=104743`
  - `conditions=12673`
  - `medications=1066`
- ETL 후:
  - `person=10000`
  - `visit_occurrence=104743`
  - `condition_occurrence=12673`
  - `drug_exposure=1066`
  - `measurement=84`

cache clear:

- `webapi_generation_cache_clear`
  - `source_id=5`
  - `deleted_count=6`

attrition:

- `L00 EntryOnly = 436`
- `L01 Rule1to1 = 436`
- `L02 Rule1to2 = 436`
- `L03 Rule1to3 = 436`
- `L04 Rule1to4 = 436`
- `L05 Rule1to5 = 436`
- final = **436**

의미:

1. 이제 PLATO full도 WebAPI 기준으로 nonzero다.
2. stale cache 문제를 제거하면 `EntryOnly=0`, `full=0` 현상은 재현되지 않는다.
3. 현재 generated 10k data에서는 5개 inclusion rule이 추가 attrition을 만들지 않으므로,
   다음 질문은 “왜 0이냐”가 아니라 **“왜 attrition shape가 너무 flat하냐”** 쪽이다.

## 2026-03-18 latest-late update: PLATO 25k manual resume

25k run은 harness가 Postgres recovery 구간에서 끊겼지만,
생성된 CSV를 재사용해 native load → ETL → cache clear → attrition을 수동으로 이어서 완료했다.

run root:

- `artemis/output/generated_gold_eval/20260318_plato_25k_cachefix`

핵심 결과:

- generated CSV:
  - `patients=25000`
  - `encounters=263705`
  - `conditions=31534`
  - `medications=2785`
- ETL:
  - `insert_visit_occurrence` 단독으로 약 `51.8분`
- manual attrition:
  - `L00 EntryOnly = 1068`
  - `L01 Rule1to1 = 1068`
  - `L02 Rule1to2 = 1068`
  - `L03 Rule1to3 = 1068`
  - `L04 Rule1to4 = 1068`
  - `L05 Rule1to5 = 1068`

결론:

- `25k`면 final cohort `1000+` 확보 가능
- 다만 ETL cost가 매우 커서, 현재 환경에서는 `50k`가 과투자일 가능성이 높음

2026-03-22 재확인 메모:

- 산출물 재검증 파일:
  - `artemis/output/generated_gold_eval/20260318_plato_25k_cachefix/plato/attrition_runs/20260318T_manual_25k_attrition/results.jsonl`
- 재확인 결과:
  - `L00 EntryOnly = 1068`
  - final `L05 Rule1to5 = 1068`
- 따라서 `plato_25k_cachefix`는 `0`으로 끝난 run이 아니다.
- 별도 관찰:
  - 위 run이 `plato_25k_cachefix` 아래에 저장되어 있음에도
    `results.jsonl` 내부 `cohort_name` 문자열은 `"[ATTRITION] Gold LEADER ..."`로 기록된다.
  - 현재까지는 count/path 기준으로 PLATO 25k 결과로 해석하는 것이 맞고,
    이 `cohort_name` 값은 라벨링 mismatch 가능성이 높다.

## 2026-03-18 progress update: LEADER / ARISTOTLE

### LEADER 10k retry

run id:

- `20260318_leader_10k_cachefix_retry`

현재까지 확인된 사실:

- 첫 시도(`20260318_leader_10k_cachefix`)는
  - ETL이 실제로 실패했는데
  - 당시 `run_etl_full.sh`가 실패를 nonzero로 올리지 않아
    downstream `0명`처럼 보였음
- 이후 `run_etl_full.sh`가 ETL 실패를 그대로 반환하도록 수정
- retry에서는 ETL이 정상 통과했고,
  WebAPI attrition이 실제로 진행 중인 상태를 확인함

현재까지 관측된 attrition:

- `L00 EntryOnly = 1378`
- `L01 Rule1to1 (Age >= 50) = 1339`
- 이후 level도 계속 진행 중이었음

의미:

- LEADER는 PLATO와 달리 실제 attrition shape가 존재한다
- 즉 generated data가 rule에 따라 실제로 줄어드는 모습을 보인다

### ARISTOTLE 10k

#### first run

- run id: `20260318_aristotle_10k_cachefix`
- Synthea/native load는 완료
- ETL이 `create_source_to_source_vocab_map.sql` 근처에서
  PostgreSQL I/O error로 실패

#### retry run

- run id: `20260318_aristotle_10k_cachefix_retry`
- retry에서는 ETL이 정상 통과
- cache clear도 완료

추가 조치:

- `trace_cohort_attrition.py` 기본 timeout(15분)은 ARISTOTLE EntryOnly에 부족해서
  manual rerun에서 `--timeout-seconds 3600`으로 늘려 재실행함

현재까지 관측된 결과:

- `L00 EntryOnly = 43`

의미:

- ARISTOTLE는 현재 generated 10k data에서 entry 자체가 매우 희귀하다
- 이 상태는 cache/pipeline 문제보다
  **trial semantics를 만족하는 synthetic patient 자체가 적다**는 쪽에 가깝다

### 운영 판단

현재 trial별 상태는 다음처럼 구분된다.

- `PLATO`
  - nonzero 안정화 완료
  - `10k final = 436`
  - `25k final = 1068`
- `LEADER`
  - attrition shape 관찰 중
  - entry와 첫 rule에서 이미 의미 있는 감소 확인
- `ARISTOTLE`
  - timeout 문제는 조정 완료
  - entry scarcity 확인 중

## 2026-03-18 late update: ARISTOTLE generator tuning + FHIR default off

### ARISTOTLE generator patch

ARISTOTLE가 `EntryOnly`에서 지나치게 희귀하게 나오는 원인을 생성기 쪽에서 다시 수정했다.

이번에 넣은 핵심 변경:

1. primary correlated entry path를 non-strict 생성에서 coverage path로 합침
   - `inpatient AF within 7 days`
   - `AF 2회 / 365일`
   를 분기 선택이 아니라 함께 생성하도록 조정
2. 반복 `ConditionOccurrence`가 실제 CSV/OMOP row로 남도록
   generated `ConditionOnset` 뒤에 짧은 `ConditionEnd`를 자동 삽입
3. ARISTOTLE primary `DrugEra`의 `AgeAtStart >= 18`를 extractor에 보존하고
   실제 timeline delay 계산에 반영

회귀 테스트:

- `python -m pytest -q artemis/tests/test_generate_synthea_from_gold.py`
- 결과: `19 passed`

추가된/강화된 검증 포인트:

- ARISTOTLE primary path가 `AgeAtStart`를 보존하는지
- timeline builder가 primary `min_age` metadata를 실제 start delay에 반영하는지
- non-strict ARISTOTLE module이
  - repeated AF state
  - inpatient encounter
  - `ConditionEnd`
  를 실제로 포함하는지

### ARISTOTLE patched 1k validation

새 patched module로 `1k`를 다시 생성하고 native load + OMOP ETL까지 재검증했다.

native CSV load:

- `patients = 1000`
- `encounters = 9706`
- `conditions = 461`
- `medications = 299`

ETL 후 OMOP count:

- `person = 1000`
- `visit_occurrence = 9706`
- `condition_occurrence = 435`
- `drug_exposure = 299`
- `drug_era = 299`

entry direct validation:

- `primary = 107`
- `inpatient_af = 107`
- `recurrent_af = 107`
- `entry_only = 107`

해석:

- 이전 patched-but-incomplete 상태에서 `entry_only = 4`였던 병목이
  primary `AgeAtStart` 반영 후 `107`까지 올라감
- 현재 ARISTOTLE entry scarcity의 주요 병목은
  compiler가 요구 semantics를 충분히 못 심던 쪽이 맞았고,
  이번 패치로 entry는 의미 있게 복구됨

### ARISTOTLE full direct SQL status

patched `1k` OMOP 데이터에 대해
full level(`L15_Rule1to15`) translated SQL을 직접 실행 중이다.

현재 상태:

- PostgreSQL backend는 `active`
- 장시간 `temp_qualified_events` 단계에서 실행 중
- 마지막 확인 시점 기준 query runtime은 `~1h30m`
- `synthea_cdm_benchmark_results.cohort`의 `cohort_definition_id = 15` row는 아직 `0`

의미:

- 현재 문제는 DB crash/recovery가 아니라
  **ARISTOTLE full SQL 자체가 매우 오래 걸리는 것**
- 즉 entry는 복구됐지만,
  full cohort를 끝까지 계산하는 execution cost는 별도 문제로 남아 있음

### FHIR default off

generated-data / benchmark 목적에서는 FHIR bundle이 실제로 사용되지 않으므로
기본 생성에서 FHIR export를 끄도록 변경했다.

변경 위치:

- `data/synthea/synthea/src/main/resources/synthea.properties`
- `artemis/scripts/evaluate_generated_gold_studies.py`
- `artemis/scripts/run_synthea_parallel_and_etl.py`

적용 내용:

- `exporter.fhir.export = false`
- `exporter.hospital.fhir.export = false`
- `exporter.practitioner.fhir.export = false`
- generated-gold / parallel generation script에서도 동일 옵션을 CLI로 강제

이유:

- 현재 OHDSI/Broadsea 경로는 `CSV -> native load -> OMOP ETL -> WebAPI`
- `synthea_output/fhir`는 generated benchmark 평가에 사용되지 않음
- 10k 기준 FHIR folder가 대략 `2.2GB ~ 2.4GB`,
  25k 기준 약 `5.7GB`까지 커져 저장공간 낭비가 큼

## 2026-03-18 summary snapshot: LEADER / PLATO / ARISTOTLE

### LEADER

현재 상태:

- `10k` retry run에서 WebAPI attrition이 정상 진행됨
- final full count는 **`1222`**

해석:

- LEADER는 generated-gold 파이프라인에서 이미 `0명` 문제를 벗어남
- full cohort가 실제로 nonzero로 계산되는 상태
- rule이 추가될수록 실제로 count가 감소하는 attrition shape도 관찰됨

판정:

- **성공 / 사실상 정리**

### PLATO

현재 상태:

- stale WebAPI cache와 ETL/WebAPI execution path 문제 정리 완료
- `10k final = 436`
- `25k final = 1068`

해석:

- generated data → ETL → WebAPI full cohort가 안정적으로 nonzero
- 현 시점에서는 “왜 0이냐” 문제가 아니라
  **“왜 attrition shape가 너무 flat하냐”** 쪽이 다음 질문

판정:

- **성공 / 사실상 정리**

### ARISTOTLE

현재 상태:

- generator patch로 entry semantics를 크게 보강함
- patched `1k` ETL 후 OMOP count:
  - `person = 1000`
  - `visit_occurrence = 9706`
  - `condition_occurrence = 435`
  - `drug_exposure = 299`
  - `drug_era = 299`
- direct validation 기준 `EntryOnly = 107`

해석:

- 이전에는 entry 자체가 지나치게 희귀했지만,
  현재는 generator patch로 entry scarcity는 상당 부분 완화됨
- 다만 full cohort(`L15_Rule1to15`) direct SQL은
  장시간 `temp_qualified_events` 단계에서 실행 중
- 즉 현재 병목은 “환자가 없어서”보다는
  **ARISTOTLE full SQL execution cost가 너무 큰 것**

판정:

- **entry 복구 성공 / full final은 미확정**

### 전체 운영 요약

- `LEADER = 성공`
- `PLATO = 성공`
- `ARISTOTLE = entry 복구 성공, full은 SQL cost 문제로 아직 미완료`

현재 남은 핵심 작업은 사실상 하나다:

- ARISTOTLE `L15_Rule1to15` full final count 확정

## Next Morning Checklist

1. long-running ARISTOTLE `L15_Rule1to15` direct SQL이 완료됐는지 먼저 확인
   - `pg_stat_activity`
   - `synthea_cdm_benchmark_results.cohort where cohort_definition_id = 15`
2. 완료됐다면 final count와 runtime을 바로 기록
3. 아직도 실행 중이면 즉시 중단하고,
   `temp_qualified_events`가 왜 그렇게 오래 걸리는지 execution-path RCA로 전환
4. 시연 전략은 기본적으로
   - `LEADER/PLATO`: live 확인
   - `ARISTOTLE`: warm-cache 결과 확인
   로 고정

## Agent-generated CIRCE JSON compatibility check

원래 목표를 다시 확인하기 위해,
Gold JSON뿐 아니라 **agent가 생성한 CIRCE JSON**도
현재 synthetic generation path에서 동작하는지 간단히 점검했다.

확인한 샘플:

- `artemis/output/leader/circe_cohort.json`
- `artemis/output/notebook_run/circe_cohort.json`

결과:

- 두 파일 모두 `generate_synthea_from_gold.py` 입력으로 module compile 성공
- `leader/circe_cohort.json` 기반 module로 small smoke generation까지 성공

smoke generation 결과 (`p=100`):

- `patients.csv = 100`
- `encounters.csv = 1042`
- `conditions.csv = 13`
- `medications.csv = 113`
- `observations.csv = 2887`

의미:

- 현재 generator path는 Gold JSON 전용으로만 막혀 있는 상태가 아님
- **agent-generated CIRCE JSON도 최소한 module 생성 + Synthea 환자 생성까지는 동작**

남은 과제:

- agent-generated CIRCE JSON으로도
  `CSV -> native load -> ETL -> WebAPI/cohort count`
  까지 이어지는지 확인
- 가능하면 이를 별도 regression test 또는 workflow로 고정

## 2026-03-19 after-midnight update: ARISTOTLE 20k scale-up validation

ARISTOTLE patched generator가 `1k`에서만 우연히 좋아진 것이 아닌지 확인하기 위해
환자 수를 약 `20x`로 올린 `20k` scale-up 검증을 수행했다.

### 20k generation

patched module:

- `data/synthea/synthea/src/main/resources/modules/artemis_aristotle_gold_eval.json`

생성 명령:

```bash
java -Xmx4g -jar build/libs/synthea-with-dependencies.jar \
  -d /tmp/aristotle_patch_module_20k \
  -m artemis_aristotle_gold_eval \
  -p 20000 \
  --exporter.csv.export=true \
  --exporter.baseDirectory=/Users/kyh/Workspace/Broadsea/artemis/output/aristotle_patch_scale20_20k
```

생성 결과:

- `patients.csv = 20000`
- `encounters.csv = 197786`
- `conditions.csv = 9605`
- `medications.csv = 5885`
- `observations.csv = 591187`

### 20k native load + ETL

native load:

- benchmark native schema 적재 성공

ETL:

- 첫 시도는 again `create_source_to_source_vocab_map.sql` 부근에서 I/O error
- DB recovery 후 **같은 native data로 ETL 재시도**
- 재시도에서는 Step 5를 통과하고 최종 event load까지 완료

ETL 후 OMOP count:

- `person = 20000`
- `visit_occurrence = 197780`
- `condition_occurrence = 9044`
- `drug_exposure = 5885`
- `drug_era = 5885`

### 20k entry validation

ARISTOTLE entry direct validation 결과:

- `primary = 2310`
- `inpatient_af = 2308`
- `recurrent_af = 2308`
- `entry_only = 2308`

해석:

- `1k`에서 `EntryOnly = 107`
- `20k`에서 `EntryOnly = 2308`

즉 patched generator는 scale-up 시에도
entry-supporting patient를 거의 비례적으로 잘 늘린다.

### 운영 판단

현재 시점의 의사결정:

1. **생성기(generator) 관점**
   - ARISTOTLE entry scarcity는 의미 있게 해결됨
   - scale-up (`20k`)에서도 재현됨
2. **execution path 관점**
   - 문제는 더 이상 “환자가 없어서”가 아니라
     **full SQL / full attrition execution cost**
3. **실무 판단**
   - `20k generation + ETL + entry validation`은 성공으로 본다
   - 그러나 `20k full direct SQL`까지 같은 방식으로 밀면
     현 환경에서는 너무 무겁다

한 줄 결론:

- **20k까지는 다시 만들어도 된다 / entry는 충분히 늘어난다**
- 하지만 **full 검증 병목은 여전히 SQL execution cost 쪽**이다
