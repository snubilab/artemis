# 2026-03-18 Generated Gold 10K Eval Log

> Current-state note:
> This document remains the detailed March 18 debugging log.
> For the consolidated current interpretation across PLATO / LEADER / ARISTOTLE and the SQL translation path split, see:
> `artemis/docs/debugging/2026-03-22_generated_gold_sql_translation_current_state.md`

## 목표

- 사용자가 명시한 방향:
  - 세부 semantic 해석보다 **생성된 데이터 기준으로 최종 cohort가 왜 0명인지** 본다.
  - **study당 10,000명** 생성한다.
  - 진행 과정은 문서로 남긴다.

즉 이번 로그의 기준 질문은 다음과 같다.

> Gold JSON 기반 generator가 만든 10k synthetic data에서, WebAPI final cohort가 왜 0명이 되는가?

---

## 평가 루프 설계

새 harness:

- `artemis/scripts/evaluate_generated_gold_studies.py`

study별로 다음을 자동화한다.

1. Gold JSON → Synthea module 생성
2. Synthea 10k 생성
3. native CSV를 benchmark schema로 load
4. OMOP ETL 실행
5. `trace_cohort_attrition.py --execute --stop-after-first-zero`
6. final count가 0이면 `translated.sql` direct execute까지 비교
7. JSON + Markdown summary 저장

관련 테스트:

- `artemis/tests/test_evaluate_generated_gold_studies.py`

---

## 오늘 확인한 직접 원인들

### 1. 처음 10k smoke는 실제 trial module이 로드되지 않았음

증거:

- Synthea 로그에 `Modules: > [0 loaded]`
- custom encounter / custom observation / custom medication이 CSV에 없음

원인:

- `java -jar ... -m ...` 에서 `-m`은 module `name`이 아니라 **relative module path filter**
- 또한 새로 생성한 module JSON은 jar 내부 resource가 아니므로, 외부 dir를 `-d`로 주지 않으면 로드되지 않음

조치:

- harness를 study별 `local_modules/` staging 방식으로 수정
- 실행 형식:

```bash
java -jar build/libs/synthea-with-dependencies.jar \
  -d <study-local-modules-dir> \
  -m <module_stem>
```

현재 상태:

- 수정 후 PLATO 10k 로그에서 `Modules: artemis_plato_gold_eval Module > [1 loaded]` 확인

### 2. benchmark native/results DB target이 잘못되어 있었음

증거:

- 초기 smoke에서 `load_synthea_benchmark.sql` 실행 시:
  - `ERROR: schema "synthea_native_benchmark" does not exist`
- 원인 확인:
  - benchmark native/results schema는 `ohdsi` DB에 있음
  - 기존 load/ETL 경로 일부가 `postgres` DB를 향하고 있었음

조치:

- harness native load를 `ohdsi` DB로 고정
- `psql -v ON_ERROR_STOP=1` 추가
- `run_etl_full.sh`, `run_etl_benchmark.R`에 `ARTEMIS_DB_NAME` 환경변수 지원 추가
- 기본값을 `ohdsi`로 변경

### 3. PLATO는 ticagrelor code 선택이 두 단계로 문제를 일으켰음

#### 3a. 원래 ingredient code(`1116632`)는 generated full module에서 medication export가 비었음

증거:

- local-dir probe 기준:
  - generator 산출 PLATO module: `conditions.csv`는 생기지만 `medications.csv`는 header only
  - 수동 `artemis_plato` module: `medications.csv` 실제 생성됨

비교 결과:

- generated primary drug code:
  - RxNorm `1116632` (`ticagrelor`, Ingredient)
- LEADER / ARISTOTLE / EMPA ingredient 기반 primary drug는 small probe에서 medication export가 생김
- 현재까지 **PLATO ticagrelor ingredient만 특이하게 실패**

#### 3b. 첫 번째 override(`1115005`)는 export는 되지만 OMOP 매핑이 틀렸음

PLATO 10k v3 결과:

- generated CSV
  - `medications.csv`: `1125`
- ETL 후
  - `drug_exposure`: `1125`
- 그런데 OMOP query 결과:
  - `concept_code=1115005` → `40240688 docusate sodium 100 MG Oral Capsule`

즉:

> `1115005`는 ticagrelor가 아니라 **docusate sodium**으로 매핑되므로,
> export가 생겨도 PLATO entry drug를 절대 만족시킬 수 없다.

#### 3c. 현재 후보는 Synthea heart module과 동일한 `1116635`

OMOP candidate query:

- `40241188` `ticagrelor 90 MG Oral Tablet` `concept_code=1116635`

Synthea 기본 heart module도 이 code 사용:

- `data/synthea/synthea/src/main/resources/modules/heart/acs_antiplatelet.json`
- `data/synthea/synthea/src/main/resources/modules/heart/acs_discharge_meds.json`

추가 probe:

- 수동 최소 module + `1116635`
  - `medications.csv` 생성 확인
- 수동 최소 module + `1116635` + `Delay(7 days)` + `MedicationEnd`
  - `medications.csv` 생성 확인

현재 코드 조치:

- `generate_synthea_from_gold.py`
  - RxNorm `1116632` → RxNorm `1116635`

회귀 테스트:

- `test_get_codes_for_codeset_maps_ticagrelor_ingredient_to_synthea_product`

남은 의문:

- generated **full** PLATO module에서 `1116635`가 여전히 비는지, 아니면 10k rerun 후 살아나는지
- 즉 지금 남은 건 **ticagrelor code 자체**보다도 generated full branch structure와의 상호작용 여부

---

## 현재 실행 중인 본 평가

run id:

- `20260318_plato_10k_eval_v3`

### 4. PLATO 10k v3 결과 (old override run)

현재까지 확인된 generated CSV:

- `patients.csv`: `10000`
- `encounters.csv`: `105532`
- `conditions.csv`: `12687`
- `medications.csv`: `1125`
- `procedures.csv`: `113`
- `observations.csv`: `291049`

의미:

> 적어도 PLATO에 대해서는 이제 **생성 데이터 자체가 비어 있어서 0명**인 상황은 아님.

현재 상태:

- native load 성공
- ETL 완료
- OMOP row count:
  - `person=10000`
  - `visit_occurrence=105532`
  - `condition_occurrence=12687`
  - `drug_exposure=1125`
  - `measurement=109`

attrition 결과:

- `L00 EntryOnly`부터 `0명`
- direct SQL도 `0명`

현재 판정:

> 이 시점의 `0명`은 WebAPI execution divergence가 아니라, 생성/매핑된 데이터가 PLATO entry drug semantics를 만족하지 못한 결과로 본다.

따라서 다음 판정 포인트는:

1. `1116635` 기준으로 PLATO 10k rerun
2. rerun 데이터에서 `drug_era`가 ticagrelor ingredient (`40241186`)로 roll up 되는지 확인
3. 그 상태에서 `L00 EntryOnly` 재측정

---

## 현재까지의 잠정 결론

오늘 기준으로는 `0명`의 원인이 하나가 아니었다.

1. **module이 아예 로드되지 않는 실행 문제**
2. **benchmark DB target 불일치**
3. **PLATO primary drug code lowering 문제**

즉 이전의 `0명` 중 일부는 cohort semantics 문제가 아니라, **generator/runtime wiring 문제**였다.

다음 결론은 ETL 완료 후 attrition 결과를 보고 확정한다.

---

## 2026-03-18 late update: fresh rerun으로 data generation 복구 확인

이후 current code 기준으로 PLATO를 다시 돌려서,
이전 v3 산출물이 아니라 **현재 generator + 현재 harness**가 실제로 어떤 결과를 내는지 재검증했다.

### 5. 소규모 sanity rerun

run id:

- `20260318_plato_300_currentcheck`

핵심 결과:

- local module에 더 이상 `1115005`가 아니라 **`1116635`**가 들어감
- generated CSV:
  - `patients.csv = 300`
  - `conditions.csv = 372`
  - `medications.csv = 30`
- ETL 후:
  - `person = 300`
  - `visit_occurrence = 3183`
  - `condition_occurrence = 372`
  - `drug_exposure = 30`
  - `drug_era = 30`
- OMOP mapping:
  - `drug_exposure`는 `40241188 / 1116635 / ticagrelor 90 MG Oral Tablet`
  - `drug_era`는 `40241186 / 1116632 / ticagrelor`
- primary drug direct SQL probe:
  - `EntryOnly persons = 9`

attrition 결과:

- WebAPI `L00 EntryOnly = 0`
- same run의 `translated.sql` direct execute = **9**

즉 이 시점부터는:

> **데이터 생성/ETL은 살아났고, WebAPI execution path와 direct SQL 결과가 갈라진다.**

### 6. PLATO 10k fresh rerun

run id:

- `20260318_plato_10k_currentcheck`

generated CSV:

- `patients.csv = 10000`
- `encounters.csv = 105179`
- `conditions.csv = 12705`
- `medications.csv = 1064`
- `observations.csv = 291810`

ETL 후:

- `person = 10000`
- `visit_occurrence = 105179`
- `condition_occurrence = 12705`
- `drug_exposure = 1064`
- `drug_era = 1064`
- `measurement = 96`

ticagrelor 확인:

- `drug_exposure`:
  - `40241188 / 1116635 / ticagrelor 90 MG Oral Tablet = 1064`
- `drug_era`:
  - `40241186 / 1116632 / ticagrelor / era_days=7 = 1062`
  - `40241186 / 1116632 / ticagrelor / era_days=0 = 2`

primary drug direct SQL probe:

- `EntryOnly rows = 455`
- `EntryOnly persons = 455`

attrition 결과:

- WebAPI `L00 EntryOnly = 0`
- direct execute of saved `translated.sql` = **455**

### 7. 확정 결론

오늘 기준 fresh rerun으로 확정된 것은 다음과 같다.

1. `1116635` lowering은 실제 generated full module에서 medication row를 만든다.
2. 그 medication은 OMOP ETL 후 `ticagrelor` product/exposure와 ingredient/drug_era로 정상 roll-up 된다.
3. 따라서 **PLATO generated data 자체는 이제 cohort entry semantics를 만족하는 환자를 만든다.**
4. 현재 남은 blocker는 generator가 아니라:
   - **WebAPI cohort generation execution path**
   - 또는 WebAPI 내부 translation / execution / splitting 차이

한 줄 결론:

> **“데이터가 제대로 생성되지 않는다” 문제는 fresh rerun 기준으로 해소되었고, 현재의 `0명`은 WebAPI path divergence 문제로 봐야 한다.**

### 8. WebAPI `EntryOnly=0`의 직접 원인 확정

이후 WebAPI / DB 로그를 함께 확인한 결과, direct 원인은 더 좁혀졌다.

증거:

- `ohdsi-webapi` 로그에서 `cohort_definition_id=438/439/440` 모두
  - `GenerationCacheHelper`
  - `Using cached generation results for COHORT`
  - `design = -2126980604`
  가 반복됨
- 즉 WebAPI는 fresh ETL 데이터를 다시 읽은 것이 아니라,
  **과거 `0명`이 나온 design hash 결과를 generation cache에서 재사용**하고 있었다.

추가 검증:

1. `webapi.generation_cache`에서
   - `source_id=5`
   - `design_hash=-2126980604`
   - `result_checksum=0`
   row 확인
2. 해당 row 삭제 후 같은 cohort를 다시 `/generate/{sourceKey}`로 실행
3. 결과:
   - `personCount = 455`
   - `synthea_cdm_benchmark_results.cohort`에 `cohort_definition_id=440` 기준 `455` row 생성
   - WebAPI 로그도
     - `Cache is absent ... Calculating`
     - `Cached results of COHORT`
     로 바뀜

판정:

> **PLATO `EntryOnly=0`의 직접 원인은 WebAPI generation cache stale hit였다.**

즉 “WebAPI translation/execution이 근본적으로 틀렸다”기보다는,
이번 재현에서는 **새 데이터에 대해 fresh generation이 아예 돌지 않고 예전 `0명` cache를 재사용한 것**이 핵심이었다.

### 9. 후속 조치

- `artemis/scripts/evaluate_generated_gold_studies.py`
  - ETL 직후 `webapi.generation_cache`의 해당 source `COHORT` cache를 비우도록 수정
- 관련 테스트:
  - `artemis/tests/test_evaluate_generated_gold_studies.py`
- 소규모 재검증 run:
  - `20260318_plato_300_cachefixcheck_v2`
  - 결과:
    - WebAPI `L00 EntryOnly = 12`
    - final `L05 Rule1to5 = 12`

주의:

- `evaluate_generated_gold_studies.py`의 기존 markdown summary 렌더러는
  `direct_sql is None`인 `webapi_nonzero` 케이스를 처리하지 못해 마지막에 예외가 났다.
- 이 부분도 함께 수정했다.

### 10. 최종 10k 검증 결과

cache clear가 들어간 harness로 다시 PLATO full 10k를 fresh rerun 했다.

run id:

- `20260318_plato_10k_cachefixfinal`

핵심 결과:

- generated CSV:
  - `patients = 10000`
  - `encounters = 104743`
  - `conditions = 12673`
  - `medications = 1066`
- ETL 후:
  - `person = 10000`
  - `visit_occurrence = 104743`
  - `condition_occurrence = 12673`
  - `drug_exposure = 1066`
  - `measurement = 84`
- cache clear:
  - `source_id = 5`
  - `deleted_count = 6`

attrition 결과:

- `L00 EntryOnly = 436`
- `L01 Rule1to1 = 436`
- `L02 Rule1to2 = 436`
- `L03 Rule1to3 = 436`
- `L04 Rule1to4 = 436`
- `L05 Rule1to5 = 436`

판정:

> **PLATO full은 이제 WebAPI 기준으로도 nonzero이며, 현재 generated 10k data에서 final cohort는 436명이다.**

추가 해석:

- 이번 PLATO Gold의 5개 inclusion rule은 fresh 10k generated data에서 추가 attrition을 만들지 않았다.
- 즉 현재 병목은 “full에서 0이 되는가”가 아니라,
  **어떻게 하면 더 trial-like한 attrition shape를 만들 것인가** 쪽으로 넘어갔다.

### 11. 25k scale-up check

`1000+` final cohort 확보 가능성을 보기 위해 PLATO를 `25k`까지 올려서 확인했다.

run root:

- `artemis/output/generated_gold_eval/20260318_plato_25k_cachefix`

주의:

- harness 본 실행은 Postgres recovery 구간에서 끊겼다.
- 하지만 generated CSV는 정상적으로 남아 있었고,
  그 CSV를 재사용해 native load → ETL → cache clear → attrition을 수동 이어달리기로 완료했다.

생성 결과:

- `patients = 25000`
- `encounters = 263705`
- `conditions = 31534`
- `medications = 2785`

ETL 관찰:

- `insert_visit_occurrence`가 약 `51.8분`
- 현재 환경에서 scale-up cost는 거의 전부 이 단계가 먹는다

manual attrition 결과:

- `L00 EntryOnly = 1068`
- `L01 Rule1to1 = 1068`
- `L02 Rule1to2 = 1068`
- `L03 Rule1to3 = 1068`
- `L04 Rule1to4 = 1068`
- `L05 Rule1to5 = 1068`

판정:

> **PLATO는 `25k`에서 final full cohort `1068명`을 확보할 수 있다.**

운영 해석:

- `1000+` final cohort가 필요하면 `25k`는 충분하다.
- 하지만 현재 ETL cost를 감안하면 `50k`는 실익 대비 과도할 수 있다.

2026-03-22 재검증 메모:

- 재확인 대상:
  - `artemis/output/generated_gold_eval/20260318_plato_25k_cachefix/plato/attrition_runs/20260318T_manual_25k_attrition/results.jsonl`
- 확인값:
  - `L00 EntryOnly = 1068`
  - final `L05 Rule1to5 = 1068`
- 따라서 `plato_25k_cachefix`는 nonzero로 완료된 run이다.
- 추가 관찰:
  - 위 run의 저장 경로는 명확히 `plato_25k_cachefix`인데,
    `results.jsonl` 내부 `cohort_name`은 `"[ATTRITION] Gold LEADER ..."`로 기록된다.
  - 현재 해석은 naming-only mismatch이며, PLATO 25k 결과 판정 자체를 뒤집는 근거는 아니다.

### 12. LEADER / ARISTOTLE follow-up

#### LEADER

`LEADER`는 cache fix 이후 PLATO와는 다른 양상을 보였다.

retry run:

- `20260318_leader_10k_cachefix_retry`

핵심:

- entry가 nonzero일 뿐 아니라
  rule이 실제 attrition을 만든다

관측된 값:

- `L00 EntryOnly = 1378`
- `L01 Rule1to1 (Age >= 50) = 1339`

즉:

> **LEADER는 flat cohort가 아니라, rule 적용에 따라 실제로 줄어드는 generated data를 만들고 있다.**

추가 주의:

- 첫 LEADER run은 ETL이 실패했는데도
  당시 wrapper가 nonzero exit를 제대로 올리지 않아 downstream `0명`처럼 보였다.
- 이후 `run_etl_full.sh`가 ETL 실패를 그대로 반환하도록 수정했다.

#### ARISTOTLE

first run:

- `20260318_aristotle_10k_cachefix`
- ETL이 `create_source_to_source_vocab_map.sql` 부근에서 PostgreSQL I/O error

retry run:

- `20260318_aristotle_10k_cachefix_retry`
- ETL은 정상 통과
- cache clear도 정상 수행

새로 드러난 문제:

- `ARISTOTLE` EntryOnly는 15분 기본 timeout 안에 끝나지 않을 수 있다
- manual rerun에서 `--timeout-seconds 3600`으로 timeout을 늘려 재실행

현재까지 관측된 값:

- `L00 EntryOnly = 43`

해석:

> **ARISTOTLE는 현재 generated 10k data에서 entry 자체가 매우 희귀하다.**

즉 이 시점의 병목은 stale cache나 wiring보다,
trial semantics를 만족하는 synthetic patient 생성량 쪽으로 보는 것이 타당하다.
