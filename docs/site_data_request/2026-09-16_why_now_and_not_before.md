# 왜 이번에 에러가 났고, 왜 숫자가 0이 됐나

두 질문 다 "무엇이 바뀌었나"의 문제이고, 둘 다 발송된 세 파일 세트만 비교하면 답이
나온다. 병원 데이터는 필요 없었다.

## 질문 1 — 이전에는 Atlas 에러가 없었는데 이번에 난 이유

**그 코드 경로가 한 번도 실행된 적이 없었기 때문이다.** 에러는 기능이 고장 난 게 아니라
새 기능이 처음 작동한 결과다.

| 발송 | `isExcluded: true` 멤버 수 |
| --- | --- |
| 2026-06-24 | **0개** |
| 2026-08-31 | **0개** |
| 2026-09-12 | **5개** (CAROLINA 두 팔, codeset 80) |

커밋 `c75085c`가 이 기능을 처음 넣었다. 커밋 메시지 자신이 그 사실을 기록한다 —
"No concept set this pipeline has produced has ever carried an excluded member:
0 isExcluded across 514 sets in all 12 delivered files."

결함은 그 기능의 **append 경로**에 있다. `src/services/entity_subtraction.py:130`:

```python
repaired.append({
    "concept": {
        "CONCEPT_ID": concept.concept_id,
        "CONCEPT_NAME": concept.concept_name,
    },
    "isExcluded": True,
    "includeDescendants": True,
    "includeMapped": False,
})
```

concept 객체를 **두 개 키로만** 만든다. Atlas의 concept-set 테이블은 `DOMAIN_ID`를
읽으려 하고, 없으니 DataTables가 그 행에서 멈춘다 — 동아대가 보낸
`Requested unknown parameter 'concept.DOMAIN_ID' for row 13`의 `row 13`이 codeset 80의
첫 append 행이다.

두 경로를 구분해야 한다. base에 이미 있는 멤버를 `isExcluded`로 **뒤집는**
(`excluded_in_place`) 경우는 원래 item을 그대로 쓰므로 키가 온전하다. base에 없어서
**새로 붙이는**(`appended`) 경우만 망가진다. CAROLINA codeset 80은 5개가 전부 append다
— base 13개는 종양 병기 소견이고, 배제해야 할 멜라노마 4개와 비흑색종 피부암 1개는
base에 없었다.

**고칠 지점은 한 곳이다.** `ExceptedConcept`가 `concept_id`와 `concept_name`만 들고
다니므로, 매퍼가 이미 알고 있는 나머지 6개 필드를 여기까지 가져오면 된다.

## 질문 2 — 숫자가 0으로 바뀐 이유

**CAROLINA에만 단위 조건이 새로 붙었기 때문이다.** 나머지 두 시험은 바뀐 게 아니라
08-31부터 이미 같은 이유로 0이었다.

발송별로 값 조건에 `Unit`이 붙은 비율:

| 발송 | 값 조건 criterion | Unit이 붙은 것 |
| --- | --- | --- |
| 2026-06-24 | 40 | **0** |
| 2026-08-31 | 48 | 18 |
| 2026-09-12 | 94 | 64 |

그런데 08-31의 18개가 **어디에 붙었는지**가 핵심이다:

| 발송 | CARMELINA | CAROLINA | EMPA-REG |
| --- | --- | --- | --- |
| 2026-08-31 | 4개 (BMI `kg/m2`, HbA1c `%` x2, eGFR) | **0개** | 5개 (BMI, HbA1c x2, eGFR, Glucose) |
| 2026-09-12 | 6개 (HbA1c `%` x4 …, BMI 없음) | **21개** (BMI `kg/m2`, HbA1c `%` x5 …) | 5개 |

이것을 아주대 실측에 겹치면 전부 설명된다:

| 시험 | 08-31 단위 | 08-31 아주대 | 09-12 단위 | 09-12 아주대 |
| --- | --- | --- | --- | --- |
| CARMELINA | 있음 | **0 / 0** | 있음 | 0 / 0 |
| EMPA-REG | 있음 | **0 / 0** | 있음 | 0 / 0 |
| CAROLINA | **없음** | **31 / 46** | **있음(21개)** | **0 / 0** |

**CAROLINA는 회귀했다기보다 마지막 생존자가 같은 결함에 걸린 것이다.** CARMELINA와
EMPA-REG는 08-31에 이미 단위 조건 때문에 0이었고, CAROLINA만 아직 단위가 안 붙어서
살아 있었다. 09-12에 21개가 붙으면서 셋이 같아졌다.

이 서술은 앞선 기록보다 정확하다. `docs/delivery_index.md`는 이것을 "CAROLINA 회귀"로
적었는데, 맞기는 하지만 **왜 CAROLINA만인지**를 설명하지 못했다. 답은 08-31 시점의
단위 부착이 시험별로 갈렸다는 것이다.

### 단위 텍스트는 처음부터 store에 있었다

바뀐 것은 추출이 아니라 **export의 변환**이다. 두 store 모두 단위 텍스트를 갖고 있었다:

| store | CAROLINA BMI의 valueConstraint |
| --- | --- |
| 08-13 (08-31 발송분의 출처) | `{"op":"lte","value":45.0,"unitText":"kg/m²"}` |
| 09-12 발송분의 출처 | `{"op":"lte","value":45.0,"unitText":"kg/m2","unitConceptId":null}` |

`unitConceptId`는 두 쪽 다 없거나 null이다. UCUM concept `9531`은 **export 시점에
`unitText`를 정규화해서 붙는다**. 08-13 store는 위첨자 `kg/m²`, 09-12 store는 평문
`kg/m2`를 담고 있다는 차이도 있다 — 정규화가 위첨자를 처리하는지가 갈림길이었을 수
있으나, 이 문서는 그것을 측정하지 않았다.

### 06-24가 0이었던 것은 다른 이유다

06-24는 단위가 **0개**인데도 0명이었다. 그 발송의 원인은 치료제 concept 오매핑이다 —
`'linagliptin'`이라는 이름의 concept set이 `1580747 sitagliptin`을, `'BI 10773'`이
`1254065 CHF-6366`을 담고 있었고, 둘 다 `ALL` 규칙이었다.

세 발송을 이어 보면 병목이 옮겨 다닌 것이지 같은 원인이 반복된 게 아니다:

| 발송 | 지배적 원인 |
| --- | --- |
| 06-24 | 치료제 concept 오매핑 (세 시험 전부) |
| 08-31 | 단위 조건 (CARMELINA·EMPA-REG), EMPA-REG는 entry 약물도 오매핑 |
| 09-12 | 단위 조건 (세 시험 전부) + `excluding T2DM` 미배제 + CAROLINA concept 객체 결손 |

## 확정하지 못한 것

- 08-31 시점에 CAROLINA에만 단위가 안 붙은 **코드상 이유**는 특정하지 못했다. store에
  `unitText`가 있었으므로 변환 단계에서 갈렸다는 것까지만 측정됐다. 08-13 store의
  위첨자 `kg/m²`가 당시 정규화를 통과하지 못했을 가능성이 있으나, 그 시점 코드로
  실행해 확인하지는 않았다.
- 아주대의 `unit_concept_id` 실제 값은 여전히 미관측이다. 0명이라는 사실만 관측됐고,
  NULL인지 다른 concept인지에 따라 수정 방향이 갈린다 —
  `docs/site_zero_diagnosis_queries.sql` Q3·Q5.
