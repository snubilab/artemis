# ADR-031-A: Condition Duration (질환 이환 기간의 Circe 표현)

**상태**: 제안됨 (Proposed) — ADR-031 부록
**날짜**: 2026-07-29
**의사결정자**: @kyh
**관련**: ADR-031(값 조건 의미 보존), ADR-030(사이트별 적응 계층), ADR-029(feasibility gating), `tte_related_work.json` 종합 규칙 4

## 컨텍스트

임계값 분류기는 프로토콜 문장의 숫자를 Circe 목적지로 보낸다. 세 갈래는 정해졌다.

| 유형 | Circe 목적지 |
|---|---|
| 측정량 | `ValueAsNumber` / `RangeHighRatio` / `RangeLowRatio` (ADR-031) |
| 환자 나이 | `DemographicCriteria.Age` |
| 진입 이벤트 기준 시간창 | `StartWindow` |

네 번째가 계속 나오는데 셋 중 어디에도 안 맞는다. **환자가 그 질환을 얼마나 오래 앓았는가**이다.

NCT04826341 원문:

> "HIV positive participants with the following exception: Patients with long-standing **(\>5 years)** HIV on antiretroviral therapy **\> 1 month** (undetectable HIV viral load and CD4 count \> 150 cells/microL) may be eligible…"

한 문장에 네 개의 숫자가 있고 서로 다른 것을 가리킨다. `>5 years`는 질환 이환 기간, `> 1 month`는 같은 모양의 약물 노출 기간, 나머지 둘은 진짜 측정값이다.

### 문헌은 이 자리를 비워뒀다

Chia(Sci Data 2020)의 `Temporal`은 `Reference_point`를 필수로 요구한다. 맨몸의 이환 기간에는 기준 사건이 없으므로 해당되지 않고, 부록에 예제도 없다. `tte_related_work.json`의 종합 항목이 이를 규칙 4 "기준 사건 없는 질환 이환 기간 → 제3의 슬롯"으로 적어두고 **"문헌에 미해결"**로 표시했다. 본 ADR은 그 슬롯을 Circe 실물로 채운다.

우리 코퍼스에서도 이 문장은 갈 곳이 없어 값 조건 파서의 **부정 케이스**로 등록돼 있다.

```yaml
# tests/fixtures/value_constraint_corpus.yaml
- id: neg-hiv-duration
  source: NCT04826341
  expect: { kind: "not_a_constraint", note: "Duration of a condition, not a measured value." }
```

ADR-031이 "값 조건이 아니다"까지는 정확히 판정했다. 그 다음 갈 곳을 정하는 것이 본 ADR이다.

### gold는 이미 이 모양을 쓰고 있다

gold 코호트 18개를 전수 조사했다. `StartWindow`가 **시작이 열려 있고 끝이 index보다 N일 앞**인 형태가 **28건**, 서로 다른 (도메인, 개념셋, N) 조합 **12종**으로 나온다.

```json
"StartWindow": {
  "Start": { "Coeff": -1 },
  "End":   { "Days": 90, "Coeff": -1 },
  "UseIndexEnd": false, "UseEventEnd": false
}
```

PLATO의 "index 90일 이전의 뇌졸중", CAROLINA의 "1460일 이전의 CABG"가 이 형태다. 즉 **"index로부터 N일 이상 떨어진 과거에 사건이 있었다"는 Circe 관용구는 이미 존재하고 임상 연구자가 손으로 쓰고 있다.** 새 표현을 설계할 필요가 없다.

### 그런데 gold의 "이환 기간" 표현은 따로 있고, 그쪽은 0명을 낸다

CAROLINA gold는 "T2DM 이환 10년 초과"를 다른 방식으로 썼다.

```json
{
  "Criteria": { "ConditionEra": { "CodesetId": 202, "EraLength": { "Value": 3650, "Op": "gt" } } },
  "StartWindow": { "Start": { "Days": 180, "Coeff": -1 }, "End": { "Days": 0, "Coeff": 1 } }
}
```

`EraLength`가 컴파일되는 SQL은 이렇다 (WebAPI 2.15.1, `POST /cohortdefinition/sql` → `POST /sqlrender/translate`).

```sql
WHERE (CAST(C.end_date AS DATE) - CAST(C.start_date AS DATE)) > 1826
```

**index date가 이 조건에 등장하지 않는다.** `condition_era` 레코드 자체의 길이만 본다. `condition_era`는 질환의 지속이 아니라 **기록의 밀도**를 재는 테이블이다 — `condition_occurrence`를 30일 간격으로 묶은 결과이므로, 만성질환이라도 연 1회만 기록되면 era는 하루짜리로 조각난다.

`synthea_cdm` 실측: HIV 환자 30명의 `condition_era` 길이는 **전원 1일**(min=1, max=1). 최초 진단일은 1994~2022년에 걸쳐 있는데도 그렇다. 따라서 `EraLength > 1826`은 **0명**을 낸다.

## 결정

### D1. `ConditionOccurrence` + 시작이 열린 `StartWindow`를 쓴다

"질환을 index 시점 기준 N일 이상 앓아왔다"는 이렇게 쓴다.

```json
{
  "Criteria": { "ConditionOccurrence": { "CodesetId": 0 } },
  "StartWindow": {
    "Start": { "Coeff": -1 },
    "End":   { "Days": 1826, "Coeff": -1 },
    "UseIndexEnd": false, "UseEventEnd": false
  },
  "RestrictVisit": false,
  "IgnoreObservationPeriod": false,
  "Occurrence": { "Type": 2, "Count": 1 }
}
```

`Days`를 생략한 `Start`는 하한 없음, `End: {Days: N, Coeff: -1}`은 `index - N일`이다. 컴파일 결과:

```sql
) A on A.person_id = P.person_id
   AND A.START_DATE >= P.OP_START_DATE
   AND A.START_DATE <= P.OP_END_DATE
   AND A.START_DATE >= P.OP_START_DATE
   AND A.START_DATE <= (P.START_DATE + -1826*INTERVAL'1 day')
```

새 필드는 없다. gold가 28건 쓰는 관용구에 N만 바꿔 넣은 것이다.

### D2. 앵커는 `condition_start_date` 대 코호트 index 시작일

위 SQL에서 `A.START_DATE`가 criterion 쪽, `P.START_DATE`가 index 쪽이다. `ConditionOccurrence` criterion의 `start_date`는 컴파일 시 `co.condition_start_date`로 바인딩된다.

```sql
select co.person_id, co.condition_occurrence_id, ..., co.condition_start_date as start_date, ...
```

`UseIndexEnd: false`이므로 index 쪽은 `cohort_start_date`다. `UseEventEnd: false`이므로 criterion 쪽은 질환 **종료일이 아니라 시작일**이다. 이 둘을 뒤집으면 에러 없이 다른 환자 집합이 나온다 — `UseEventEnd: true`로 두면 "질환이 index 1826일 전에 **끝났다"**가 되어 완치된 환자만 남는다.

### D3. `First: true`는 이 방향에서 불필요하다 — 반대 방향에서는 필수다

"HIV를 5년 넘게 앓았다"가 *최초* 기록 기준이어야 하는지 검증했다. 논리적으로 `∃ 기록 ≤ index−N` ⟺ `최초 기록 ≤ index−N`이므로 동치여야 한다. 실측으로 확인했다.

`First: true`는 실제로 SQL을 바꾼다(무시되는 필드가 아니다).

```sql
WHERE C.ordinal = 1
```

한 사람당 기록이 여러 건인 개념(Gingivitis, 최대 46건/인)으로 측정한 결과:

| 방향 | 임의 기록 | `First: true` | 차이 |
|---|---|---|---|
| **이환 기간 ≥5년** (`(-inf, ix-1826d]`) | 187 | 187 | **0** |
| **신규 진단 ≤5년** (`[ix-1826d, ix]`) | 4,170 | 4,010 | **160 (3.8%)** |

`≥` 방향에서는 완전 동치다. `First`를 붙이는 것은 무해하지만 의미가 없다.

반대로 **"최근 N년 내 진단"** 방향에서는 `First`가 결정적이다. 없으면 "지난주에 기록이 하나 생긴, 10년 된 환자" 160명이 신규 진단자로 섞여 들어온다. 이 함정은 이환 기간 조건 자체가 아니라 **그 조건의 부정형**에서 발생하므로, HIV 사례처럼 배제 기준의 예외 조항으로 들어올 때 주의해야 한다. 배제 규칙을 창의 극성 반전으로 구현하면(즉 `NOT(≥5년)`을 `≤5년`으로 다시 쓰면) `First`가 필요해진다. 규칙 전체를 부정하면 필요 없다. gold는 criterion 수준 `First`를 **한 번도 쓰지 않는다**(18개 코호트, 0건).

### D4. `ConditionEra` + `EraLength`는 쓰지 않는다

`EraLength`는 이환 기간이 아니라 **기록 밀도**를 잰다. index date와 무관하다(D2의 SQL 참조). 세 가지가 동시에 걸린다.

1. **의미가 다르다.** era는 `condition_occurrence`를 30일 간격으로 묶은 것이다. 같은 환자, 같은 질환이라도 병원이 매년 한 번 코딩하면 era는 하루짜리 조각이 되고, 분기마다 코딩하면 수년짜리가 된다. **동일한 JSON이 사이트의 기록 습관에 따라 다른 답을 낸다.**
2. **테이블이 없을 수 있다.** 워크스페이스의 사이트 CDM 4개 중 3개(`ajou_cdm`, `keimyung_cdm`, `donga_cdm`)에 `condition_era` 테이블이 **아예 없다**. 이 경우는 조용한 0이 아니라 `relation "ajou_cdm.condition_era" does not exist`로 시끄럽게 죽는다 — 그나마 낫다.
3. **있어도 0을 낸다.** `synthea_cdm_benchmark`는 `condition_era`가 있으나 최장 era가 **6일**이다.

`ConditionEra`를 D1의 창과 함께 쓰는 형태(`ConditionEra` + `(-inf, ix-N]`)는 `synthea_cdm`에서 `ConditionOccurrence`와 같은 17명을 낸다. 그래도 D1을 택한다 — era 테이블 의존을 만들 이유가 없고, era start는 "최초 발병"이 아니라 "가장 최근 연속 블록의 시작"이라 조각난 기록에서 의미가 어긋난다.

### D5. 약물 유사형은 같은 창 + `EndWindow` 한 겹

"on antiretroviral therapy > 1 month"는 모양이 같다. 다만 **한 성분이 더 있다** — 조건 질환은 "그때 시작했다"로 충분하지만, 약물은 "지금도 복용 중"이 함께 요구된다. `StartWindow`만으로는 2년 전에 시작해 1년 전에 끊은 환자가 통과한다.

```json
{
  "Criteria": { "DrugEra": { "CodesetId": 2 } },
  "StartWindow": { "Start": { "Coeff": -1 }, "End": { "Days": 30, "Coeff": -1 },
                   "UseIndexEnd": false, "UseEventEnd": false },
  "EndWindow":   { "Start": { "Days": 0, "Coeff": -1 }, "End": { "Coeff": 1 },
                   "UseIndexEnd": false, "UseEventEnd": true },
  "Occurrence": { "Type": 2, "Count": 1 }
}
```

`DrugEra`를 쓰는 것은 여기서 정당하다. `drug_era`는 처방 기록을 묶은 것이 아니라 **`days_supply` 기반 노출 구간**이며, "복용 중"이 실제로 그 테이블의 의미다. `condition_era`와 달리 기록 밀도의 대리물이 아니다. gold도 `DrugEra` + `EraLength`를 31건 쓴다(`EraLength > 7`로 "1회성 처방 제외"를 표현). 같은 조합을 `ConditionEra`에 쓴 것은 2건뿐이고, 그 2건이 D4에서 0명을 내는 CAROLINA 사례다.

**즉 하나의 표현으로 둘을 덮지 않는다.** 창의 모양은 공유하되, 조건은 `ConditionOccurrence` + `StartWindow`, 약물은 `DrugEra` + `StartWindow` + `EndWindow`로 분기한다. 분기 기준은 원문의 head가 질환이냐 약물이냐이며, 이는 `tte_related_work.json` 종합의 "head 우선" 결론과 같은 판정이다.

### D6. observation period 도달 범위를 적응 리포트에 넣는다

D1의 `Start: {Coeff: -1}`은 **−∞가 아니다.** 컴파일된 SQL이 `A.START_DATE >= P.OP_START_DATE`를 항상 붙인다. 즉 조회 범위가 환자의 observation period로 잘린다.

EHR 이력이 3년뿐인 병원에서는 "5년 이상"이 **전원 탈락**한다. 환자가 실제로 10년째 앓고 있어도 그렇다. 에러는 없다.

따라서 ADR-030의 적응 리포트에 지표 하나를 추가한다: **index 코호트 중 observation period가 N일 이상 뒤로 도달하는 환자 비율.** 이 값이 이 조건이 낼 수 있는 상한이다.

```sql
WITH idx AS (SELECT person_id, min(cohort_start_date) ix FROM <cohort> GROUP BY 1)
SELECT count(*) AS index_n,
       sum(CASE WHEN idx.ix - op.observation_period_start_date >= 1826 THEN 1 ELSE 0 END) AS reachable
FROM idx JOIN <cdm>.observation_period op USING (person_id);
```

실측:

| CDM | index_n | ≥5년 도달 | ≥10년 도달 |
|---|---|---|---|
| `synthea_cdm` | 10,486 | 7,545 (72.0%) | 6,724 (64.1%) |
| `synthea_cdm_benchmark` | 10,000 | 1,350 (13.5%) | 1,227 (12.3%) |
| `ajou_cdm` | 4,732 | 4,732 (100.0%) | 3,287 (69.5%) |
| `donga_cdm` | 4,629 | 4,629 (100.0%) | 3,198 (69.1%) |

`synthea_cdm_benchmark`에서는 index 코호트의 **13.5%**만이 5년 조건을 만족할 *가능성*이라도 있다. 나머지 86.5%는 데이터가 없어서 탈락하는 것이지 질환이 없어서가 아니다.

`IgnoreObservationPeriod: true`로 이 제약을 풀 수 있으나 기본값으로 쓰지 않는다 — observation period 밖의 기록은 CDM 계약상 완결성이 보장되지 않는다. 켜고 끄기를 리포트에 노출하고 사이트 담당자가 판단하게 한다.

## 실측 — HIV 사례 전체

NCT04826341의 문장 전체를 Circe로 옮긴 것이다. 배제 기준 + 예외 조항이므로 "HIV 없음 **OR** (장기 이환 AND ART 1개월 초과 AND 바이러스 미검출 AND CD4 > 150)" 구조가 된다.

```json
{
  "name": "HIV exclusion with long-standing-HIV carve-out",
  "expression": {
    "Type": "ANY",
    "CriteriaList": [],
    "DemographicCriteriaList": [],
    "Groups": [
      {
        "Type": "ALL",
        "CriteriaList": [
          {
            "Criteria": { "ConditionOccurrence": { "CodesetId": 0 } },
            "StartWindow": { "Start": { "Coeff": -1 }, "End": { "Days": 0, "Coeff": 1 },
                             "UseIndexEnd": false, "UseEventEnd": false },
            "RestrictVisit": false, "IgnoreObservationPeriod": false,
            "Occurrence": { "Type": 0, "Count": 0 }
          }
        ],
        "DemographicCriteriaList": [], "Groups": []
      },
      {
        "Type": "ALL",
        "CriteriaList": [
          {
            "Criteria": { "ConditionOccurrence": { "CodesetId": 0 } },
            "StartWindow": { "Start": { "Coeff": -1 }, "End": { "Days": 1826, "Coeff": -1 },
                             "UseIndexEnd": false, "UseEventEnd": false },
            "RestrictVisit": false, "IgnoreObservationPeriod": false,
            "Occurrence": { "Type": 2, "Count": 1 }
          },
          {
            "Criteria": { "DrugEra": { "CodesetId": 2 } },
            "StartWindow": { "Start": { "Coeff": -1 }, "End": { "Days": 30, "Coeff": -1 },
                             "UseIndexEnd": false, "UseEventEnd": false },
            "EndWindow":   { "Start": { "Days": 0, "Coeff": -1 }, "End": { "Coeff": 1 },
                             "UseIndexEnd": false, "UseEventEnd": true },
            "RestrictVisit": false, "IgnoreObservationPeriod": false,
            "Occurrence": { "Type": 2, "Count": 1 }
          },
          {
            "Criteria": { "Measurement": { "CodesetId": 4, "ValueAsNumber": { "Value": 50, "Op": "lt" } } },
            "StartWindow": { "Start": { "Days": 180, "Coeff": -1 }, "End": { "Days": 0, "Coeff": 1 },
                             "UseIndexEnd": false, "UseEventEnd": false },
            "RestrictVisit": false, "IgnoreObservationPeriod": false,
            "Occurrence": { "Type": 2, "Count": 1 }
          },
          {
            "Criteria": { "Measurement": { "CodesetId": 3,
              "ValueAsNumber": { "Value": 150, "Op": "gt" },
              "Unit": [ { "CONCEPT_ID": 8647, "CONCEPT_NAME": "per microliter",
                          "CONCEPT_CODE": "/uL", "DOMAIN_ID": "Unit", "VOCABULARY_ID": "UCUM" } ] } },
            "StartWindow": { "Start": { "Days": 180, "Coeff": -1 }, "End": { "Days": 0, "Coeff": 1 },
                             "UseIndexEnd": false, "UseEventEnd": false },
            "RestrictVisit": false, "IgnoreObservationPeriod": false,
            "Occurrence": { "Type": 2, "Count": 1 }
          }
        ],
        "DemographicCriteriaList": [], "Groups": []
      }
    ]
  }
}
```

개념셋: `0` = HIV (SNOMED 439727), `2` = ART 성분 5종, `3` = CD4 (LOINC 3028167), `4` = HIV viral load (LOINC 3010747). `Unit`은 ADR-031 D4대로 `Measurement`의 형제로 둔다.

### 표현별 환자 수 (`synthea_cdm`, index = 2018-01-01 이후 최초 외래 방문)

| 표현 | n |
|---|---|
| index 코호트 | 10,486 |
| HIV 기록 있음 (기간 무관) | 19 |
| **D1 — `ConditionOccurrence`, `(-inf, ix-1826d]`** | **17** |
| D1 + `First: true` | 17 |
| D1 + `IgnoreObservationPeriod: true` | 17 |
| **B — 시간창으로 오분류, `[ix-1826d, ix]`** | **2** |
| **C — `ConditionEra` `EraLength > 1826d` (CAROLINA gold 관용구)** | **0** |
| C′ — `ConditionEra` + `(-inf, ix-1826d]` | 17 |

예외 조항 전체(네 조건 AND)로 좁히면:

| 예외 조항의 이환 기간 표현 | 통과 환자 |
|---|---|
| **D1 (본 ADR)** | **4** |
| B (시간창 오분류) | 1 |
| C (`EraLength`) | 0 |

배제 기준의 예외 조항이므로 이 차이는 그대로 **잘못된 배제**가 된다. B를 쓰면 3명, C를 쓰면 4명이 자격이 있는데도 조용히 빠진다. 규칙 전체로는 10,471명(= 10,467 + 4)이 통과한다.

### 사이트를 바꾸면 같은 JSON이 다른 답을 낸다

| CDM | HIV 기록 있음 | D1 (≥5년) | D1 (≥10년) | C (`EraLength`) |
|---|---|---|---|---|
| `synthea_cdm` | 19 | **17** | 13 | 0 |
| `ajou_cdm` | 4 | **0** | 0 | 테이블 없음 (SQL 오류) |
| `donga_cdm` | 1 | **0** | 0 | 테이블 없음 (SQL 오류) |
| `synthea_cdm_benchmark` | 0 | 0 | 0 | 0 |

`ajou_cdm`은 observation period가 100% 5년을 도달하는데도 D1이 0이다 — 도달 범위 문제가 아니라 HIV 기록이 전부 최근이라 그렇다. **원인이 둘인데 증상은 같은 숫자 0이다.** D6의 도달 범위 지표가 둘을 가른다.

## 근거

- **Circe 표현력을 새로 설계하지 않는다.** 시작이 열린 `StartWindow`는 gold가 28건 쓰는 기존 관용구다. N만 바꿔 끼운다. ADR-031과 같은 입장이다.
- **era를 피하는 이유는 취향이 아니라 이식성이다.** `condition_era`는 사이트 CDM 4개 중 3개에 없고, 있어도 기록 밀도에 따라 값이 달라진다. 같은 코호트를 여러 병원에 보내는 것이 ADR-030의 전제이므로, 사이트 ETL 습관에 의존하는 구조는 쓸 수 없다.
- **`First`를 기본으로 켜지 않는 이유는 검증했기 때문이다.** 187 대 187. 켜도 되지만 의미 없는 절이 붙으면 다음 사람이 그것이 필요하다고 오해한다. 정말 필요한 자리(신규 진단 방향, 4,170 대 4,010)를 D3에 명시해 뒀다.
- **조용한 0의 원인을 둘로 분리한다.** "데이터가 그 시점까지 안 간다"와 "그 시점에 질환이 없다"는 다른 문제이고 대응도 다르다. 전자는 사이트에 물어볼 것이고, 후자는 실제 결과다. 지표가 없으면 구분할 수 없다.

## 스코프 (의도적 단순화)

- **`>=` 방향만 정한다.** "N년 이내 진단"(신규 진단)은 창의 극성이 반대이고 `First`가 필요하다. D3에 근거를 남겼으나 정식 결정은 하지 않는다.
- **이환 기간의 종료를 다루지 않는다.** "5년간 앓다가 완치"는 `UseEventEnd: true`로 표현 가능하지만 코퍼스에 사례가 없다.
- **"undetectable"을 정의하지 않는다.** 위 fragment의 `< 50 copies/mL`은 관례값이며 검사실 검출한계는 사이트마다 다르다. ADR-030의 `verificationRequests`로 물어야 할 항목이다.
- **개념셋 폭을 검증하지 않는다.** `includeDescendants: true`인 HIV 개념셋에 "HIV 선별검사"나 "HIV 노출"이 섞여 있으면 오래된 무관한 기록이 이환 기간을 부풀린다. 이는 이 ADR의 창 모양이 아니라 개념셋 문제이고 ADR-030 단계 ①②의 소관이다.
- **역년 대 일수 변환은 고정값을 쓴다.** 5년 = 1826일(365×5+1). Circe는 `Days`만 받는다.

## 미해결 리스크

- **`First` 검증이 대리 개념으로 이뤄졌다.** `synthea_cdm`의 HIV 환자 30명은 전원 기록이 정확히 1건이라 `First`를 구분할 수 없다. Gingivitis(최대 46건/인)로 대신 측정했다. 기전은 같지만 임상적으로 다른 개념이며, 진짜 병원 데이터에서 재확인해야 한다.
- **약물 유사형의 네 표현이 `synthea_cdm`에서 전부 19명으로 같다.** ART를 시작한 19명이 전원 index 시점에 복용 중이고 era가 30일을 넘는다. 즉 **이 CDM은 D5의 `EndWindow` 유무를 구분하지 못한다.** "2년 전 시작, 1년 전 중단" 환자가 0명이라 그렇다. D5는 논증과 SQL 의미로만 뒷받침되며 실행 대조가 없다.
- **`keimyung_cdm`은 비교에서 빠졌다.** `visit_occurrence`가 비어 있어 index 코호트가 0이다. 사이트 CDM 전수 대조가 아니다.
- **`synthea_cdm_benchmark`에 HIV 환자가 0명이다.** 벤치마크 파이프라인에서는 이 규칙의 회귀를 잡을 수 없다. 다른 만성질환으로 대체 케이스를 세워야 한다.
- **`Coeff` 부호를 잘못 쓰면 에러 없이 정반대가 된다.** `End: {Days: 1826, Coeff: -1}`(이환 기간)과 `Start: {Days: 1826, Coeff: -1}`(시간창)은 한 글자 차이이고 둘 다 유효한 Circe다. 실측 17 대 2. 빌더 단위 테스트가 유일한 방어선이다.
- **index 이후 기록을 배제하지 않는다.** D1의 창은 index 이전만 보므로 미래 누출은 없다. 다만 `UseIndexEnd: true`로 잘못 켜면 index **종료일** 기준이 되어 코호트 지속기간만큼 창이 밀린다.

## 관련

- ADR-031 — 값 조건 의미 보존. 본 ADR은 그 분류기의 네 번째 목적지를 정의한다. `Unit` 배치 규칙(D4)을 그대로 따른다.
- ADR-030 — 사이트별 적응 계층. D6의 도달 범위 지표는 적응 리포트의 항목이 된다.
- `docs/daily_notes/tte_related_work.json` — `synthesis` 항목, 규칙 4("기준 사건 없는 질환 이환 기간 → 제3의 슬롯, 문헌에 미해결").
- `tests/fixtures/value_constraint_corpus.yaml` — `neg-hiv-duration`. 값 조건 파서의 부정 케이스로 남되, 본 ADR의 목적지가 생기면 양성 케이스가 추가되어야 한다.
- gold 실물: `data/gold/CAROLINA/[TROY v1.1] Linagliptin (CAROLINA).json` 의 `High risk of CV events` 규칙(`ConditionEra` + `EraLength`), `data/gold/PLATO/*` 의 시작이 열린 `StartWindow`.
- 재현 스크립트: `scripts/probe_condition_duration.py`. 본 문서의 모든 숫자를 한 번에 낸다. WebAPI 코호트 정의를 만들거나 지우지 않으며, 결과는 세션 임시 테이블에 쓰고 롤백한다.
