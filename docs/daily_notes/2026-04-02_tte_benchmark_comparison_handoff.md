# 2026-04-02 Handoff — TTE Benchmark Comparison (Latest)

## 2026-04-02 late addendum — fresh 450/451 execution + benchmark-vs-fresh framing

- this note is stale below; use this addendum as the latest controller summary

### 1. LEADER

- no material change from the earlier conclusion:
  - recovered under current fresh family
  - benchmark semantics still align reasonably well

### 2. ARISTOTLE

- benchmark frame and fresh frame must be kept separate
- benchmark AI-side reference:
  - old AI treatment family `1127`
  - AI `N=930`
  - gold treatment `1138`
  - gold `N=1113`
- fresh runtime family:
  - old fresh `442`: target `1142`, treatment `1145`, outcome `1147`
  - counts `146 / 27 / 119 / 1834`
  - fresh explicit-comparator `450`: target `1155`, treatment `1156`, comparator `1157`, outcome `1158`
- latest `450` execution outcome:
  - study status `completed`
  - version `8`
  - cohort IDs attached:
    - target `1155`
    - treatment `1156`
    - comparator `1157`
    - outcome `1158`
  - execution artifacts applied:
    - `art_868`, `art_870`
  - analysis artifacts applied:
    - `art_869`, `art_871`
  - canonical persisted analysis result:
    - `treatmentN=27`
    - `comparatorN=270`
    - HR fields `null`
    - `generatedBy=artemis-agent5-error`
- interpretation:
  - fresh ARISTOTLE is executable again
  - but it is not the old benchmark AI family
  - current remaining issue is phenotype drift plus Cox convergence failure

### 3. PLATO

- benchmark AI-side reference:
  - old AI treatment family `941`
  - AI `N=74~75`
  - gold treatment `1137`
  - gold `N=436`
- fresh runtime family before latest rerun:
  - `443`: target `1143`, treatment `1144`, outcome `1146`
  - execution `0 / 0 / 0 / 1174`
- latest fresh explicit-comparator family:
  - `451`: target `1159`, treatment `1160`, comparator `1161`, outcome `1162`
- latest `451` execution outcome:
  - study status `completed`
  - version `6`
  - cohort IDs attached:
    - target `1159`
    - treatment `1160`
    - comparator `1161`
    - outcome `1162`
  - validation first raced and then passed on retry:
    - stale blocker artifact `art_873`
    - passing validation `art_874`
  - execution artifact applied:
    - `art_876`
  - analysis artifact applied:
    - `art_877`
  - execution counts:
    - target `0`
    - treatment `0`
    - comparator `0`
    - primary outcome `1174`
  - persisted analysis result:
    - all cohort counts remain `0`
    - `generatedBy=artemis-agent5-error`
    - runtime error because generated cohort dataset was empty / unusable
- interpretation:
  - fresh PLATO pipeline is no longer blocked by runtime plumbing
  - the blocker is phenotype family mismatch with `PLATO_BENCHMARK`
  - fresh `451` is closer to the zero-producing `443` family than to the old benchmark AI `941` family

### 4. Infra lessons from this session

- `submission-artemis-api` was unsafe for TTE mutations:
  - it shared the same TTE store path
  - but all provider env vars were blank
  - it has been stopped
- Docker disk exhaustion caused secondary failures:
  - `broadsea-atlasdb` entered PostgreSQL recovery mode
  - `ohdsi-webapi` returned `500`
  - reclaimed about `44.9GB` with:
    - `docker image prune -af`
    - `docker container prune -f`
  - atlasdb recovered afterwards

### 5. What the next session should do

- do not confuse fresh `450/451` with the benchmark AI families
- benchmark-facing question to answer:
  - how were old AI benchmark families actually produced?
  - ARISTOTLE benchmark AI family to use as reference: `1127`
  - PLATO benchmark AI family to use as reference: `941`
- fresh-facing question to answer:
  - why did auto parsing / processing drift from those benchmark families?
- recommended next task:
  - compare `gold vs benchmark-AI vs fresh` for:
    - PLATO
    - ARISTOTLE
  - use old benchmark AI family as the target reproduction standard, not fresh `450/451`

## 한 줄 요약

`LEADER`는 fresh compatibility rerun으로 all-zero를 깨고 기존 benchmark semantics에서 gold와 꽤 가깝게 복구됐다. `PLATO`는 여전히 AI treatment cohort가 0이라 최종 blocker고, `ARISTOTLE`는 비교는 되지만 current AI treatment가 너무 작다.

---

## 이번 세션에서 유지/확인된 코드 변화

### 이미 반영된 핵심 커밋

- root repo:
  - `1c516be` `fix(tte): make structured targets canonical in backend`
  - `6a11401` `fix(tte): derive target population from trial criteria`
- `atlas-dev` repo:
  - `e19e3b0` `fix: align structured eligibility adapter and zero-count banner`

### 이번 세션에서 확인한 drift 의미

- `1c516be` 이후:
  - target truth가 `targetCohortName`에서 `structuredExpression/PrimaryCriteria` 쪽으로 이동
- `6a11401` 이후:
  - draft target label이 drug-entry 이름에서 condition/population 쪽으로 이동

이 두 변화 때문에 LEADER가 예전 drug-entry 계열(`839/840/1141`)에서 새 condition-entry 계열(`1148/1149/1150`)로 drift했다.

---

## 스터디별 최신 상태

### 1. LEADER

#### stale/corrupted old run

- study `437`
- target label: `liraglutide`
- result:
  - `targetN=0`
  - `treatmentN=0`
  - `comparatorN=0`
  - `primaryOutcomeN=1105`

의미:
- old stale shell
- target/treatment가 둘 다 `liraglutide`
- 더 이상 기준으로 쓰면 안 됨

#### failed fresh run before restore

- study `445`
- target cohort `1148`
- treatment cohort `1149`
- outcome cohort `1150`
- result:
  - `0 / 0 / 0 / 0`

subagent diff 결론:
- `1148`: strict stenosis-centered condition-entry family
- `1149`: `1148` clone + liraglutide rule
- `1150`: prior nonzero outcome family와 다른 root concepts

#### current recovered fresh run

- study `449`
- comparison mode: `explicit_comparator`
- generated cohorts:
  - target `1151`
  - treatment `1152`
  - comparator `1153` (`placebo`)
  - outcome `1154`
- WebAPI execution result:
  - `targetN=1308`
  - `treatmentN=1194`
  - `comparatorN=0`
  - `primaryOutcomeN=1239`

중요 해석:
- all-zero collapse는 깨짐
- placebo explicit comparator는 여전히 0
- 하지만 historical benchmark semantics(`whole CDM rest comparator`)로 비교하면 LEADER는 복구된 것으로 보는 게 맞음

#### LEADER benchmark rerun using historical comparator semantics

기존 `run_gold_vs_ai_comparison.py` 의미로 재실행:
- comparator = `whole CDM rest`
- fresh AI treatment = `1152`
- gold treatment = `1136`
- outcome = `1154`

결과:
- AI:
  - `treatment_n=1194`
  - `comparator_n=8654`
  - `HR=2.0816 [1.8498, 2.3424]`
- Gold:
  - `treatment_n=1228`
  - `comparator_n=8654`
  - `HR=2.0241 [1.7994, 2.2770]`
- overlap:
  - `1076`
  - recall `0.876`
  - precision `0.901`

결론:
- LEADER는 historical benchmark framing에서 gold와 꽤 가깝게 붙음
- 현재 세 스터디 중 가장 크게 회복된 쪽

---

### 2. PLATO

#### old fresh baseline still on file

- study `443`
- draft `art_835`
- processed `art_840`
- seeded `art_841`
- execute `art_845`
- final:
  - `targetN=0`
  - `treatmentN=0`
  - `comparatorN=0`
  - `primaryOutcomeN=1174`

해석:
- target/treatment label corruption 문제는 해결됨
- 남은 문제는 phenotype assembly
- target concept set이 benchmark data에 맞지 않음

#### benchmark rerun under historical semantics

- gold treatment = `1137`
- AI treatment = `1144`
- outcome = `1146`

결과:
- `1144`는 cohort definition은 존재하지만 `synthea_cdm_plato_results.cohort`에 materialize되지 않음
- 따라서 AI-side HR 계산 불가
- gold-side만 계산됨:
  - `treatment_n=436`
  - `comparator_n=4360`
  - `HR=5.3339 [3.7334, 7.6206]`

결론:
- 현재 전체 benchmark 종료를 막는 최종 blocker는 PLATO
- 다음 작업이 필요:
  - current PLATO target/treatment family가 nonzero가 되도록 data injection 또는 phenotype remap

#### fresh rerun in progress

- study `451`
- draft generation/apply 완료:
  - `art_861`
- current study state:
  - version `2`
  - `comparisonMode = explicit_comparator`
  - target = `Hospitalized for chest pain and potential ACS`
  - treatment = `ticagrelor`
- live pipeline state:
  - `job_892` `process_eligibility` running
  - 아직 `eligibility_processing` artifact는 없음

결론:
- `451`이 현재 PLATO의 active fresh baseline
- 다음 실질 체크포인트는 `process-eligibility` artifact 생성 여부

---

### 3. ARISTOTLE

#### old fresh baseline still on file

- study `442`
- target = `Atrial fibrillation or atrial flutter`
- treatment = `apixaban`
- final:
  - `targetN=146`
  - `treatmentN=27`
  - `comparatorN=119`
  - `primaryOutcomeN=1834`

해석:
- 구조 수정 이후 실제 nonzero 복구
- 다만 old AI family(`~395/400`)보다는 훨씬 작은 treatment

#### benchmark rerun under historical semantics

- gold treatment = `1138`
- AI treatment = `1145`
- outcome = `1147`

결과:
- AI:
  - `treatment_n=27`
  - `comparator_n=270`
  - `HR=1.4944 [0.6457, 3.4584]`
- Gold:
  - `treatment_n=1113`
  - `comparator_n=11130`
  - `HR=1.3270 [1.1901, 1.4795]`
- overlap:
  - `25`
  - recall `0.022`
  - precision `0.926`

결론:
- 비교는 가능
- 하지만 current AI treatment cohort가 너무 작아 overlap/recall이 매우 낮음

#### fresh rerun in progress

- study `450`
- draft generation/apply 완료:
  - `art_862`
- current study state:
  - version `2`
  - `comparisonMode = explicit_comparator`
  - target = `Atrial fibrillation or atrial flutter`
  - treatment = `apixaban`
- live pipeline state:
  - `job_891` `process_eligibility` completed
  - artifact `art_863` persisted
  - 아직 apply / seeded / validate / execute는 안 감

결론:
- `450`은 fresh baseline으로 의미 있는 progress를 냈고
- 다음 단계는 `art_863` apply 후 seeded/validate/execute

---

## benchmark 기준 treatment 크기

현재 비교에 실제 사용한 기준값:

- LEADER
  - Gold: `1228`
  - AI current: `1194` (`1152`)
- PLATO
  - Gold: `436`
  - AI current: `0` (`1144` materialization 실패)
- ARISTOTLE
  - Gold: `1113`
  - AI current: `27` (`1145`)

---

## comparator semantics 주의

기존 AI-vs-gold benchmark는:
- `target - treatment`가 아니라
- `whole CDM rest comparator`

즉 `run_gold_vs_ai_comparison.py` 기준 comparator는:
- `all CDM persons - treatment cohort`

현재 TTE runtime의 `target minus treatment`와는 기준이 다르다.

---

## 현재 운영 판단

- `449`:
  - recovered LEADER baseline
- `450`, `451`:
  - user 지시로 다시 active execution baseline으로 사용 중
- 실질적인 현재 결론:
  - LEADER: recovered
  - ARISTOTLE: fresh rerun 계속 진행 가능
  - PLATO: 여전히 final blocker이지만 fresh `451` 결과를 먼저 확인해야 함

---

## 다음 액션

우선순위:
1. `PLATO` target/treatment를 nonzero로 만드는 최소 intervention 결정
2. 필요 시 target-expansion / support-data injection으로 `1144` materialization 복구
3. 기존 benchmark semantics(`whole CDM rest`)로 final compare 재실행
4. `450` apply 후 seeded/validate/execute 완료
5. `451` process-eligibility 완료 후 full pipeline 진행

---

## 참고 파일

- current store:
  - `artemis/tmp/tte/studies.json`
- comparison scripts:
  - `artemis/scripts/run_gold_vs_ai_comparison.py`
- main notes:
  - `artemis/docs/daily_notes/2026-04-01_gold_vs_ai_hr_benchmark_final.md`
  - `artemis/docs/daily_notes/2026-04-01_handoff_1630.md`
  - `artemis/docs/daily_notes/2026-04-02_tte_target_population_handoff.md`
