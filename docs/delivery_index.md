# 발송 이력 — 발송일 기준 코드 버전과 추출 숫자

병원에 **실제로 보낸** 배포만 기록한다. 발송 3건: 2026-06-24, 2026-08-31, 2026-09-12
(사용자 확인, 2026-09-14). 준비만 하고 보내지 않은 export는 넣지 않는다 —
`output/circe_be/`에 파일이 있다는 것은 발송의 증거가 아니다.

코드 버전은 **발송일 기준**으로 적는다. 런 디렉터리 라벨이나 store mtime이 아니라,
그 산출물이 병원으로 나간 시각의 artemis HEAD다.

## 표 1 — 발송일별 코드 버전

| 발송일 | 보낸 것 | 시험 수 | 발송 시각 artemis HEAD | 내용을 만든 코드 버전 |
| --- | --- | --- | --- | --- |
| 2026-06-24 | `output/circe_be/2026-06-24/test_study_circe_json/` + `test_study_circe_json_20260624.zip` | 3 (6파일) | **없음** | **없음** |
| 2026-08-31 | `output/circe_be/2026-08-31/` + `tte_circe_6studies_arms_20260831.zip` | 6 (12파일) | `745ea83` (08-27 01:33) | **불명 — 08-13 이전** |
| 2026-09-12 | `output/circe_be/2026-09-12/` + `tte_circe_3studies_arms_20260912.zip` | 3 (6파일) | `c6adb4a` (09-12 21:25) | `d50bf8c` (09-12 18:33) |

세 칸의 "없음 / 불명"은 추정을 포기한 것이 아니라 측정된 사실이다.

- **2026-06-24 — 버전 관리 이전이다.** artemis 최초 커밋은 `6ffd07c` (2026-07-22)로,
  06-24 시점에는 리포지터리가 존재하지 않았다. 커밋으로 지정할 수 없다. 파일 mtime은
  06-22 18:54(생성), 디렉터리 mtime은 06-24 17:12(패키징)이므로 **내용은 06-22에
  만들어졌고 06-24에 보냈다.** 아카이브는 원본 레이아웃(`test_study_circe_json/<study>/`,
  `empa_reg_*` 표기)을 그대로 두었다 — 다른 두 발송의 평면 `empa-reg_*` 구조와 다르다.
- **2026-08-31 — HEAD와 내용의 코드 버전이 다르다.** 발송 시각 HEAD는 `745ea83`이지만,
  이 export는 컨테이너의 live store에서 뽑혔고 그 store는 **08-13에 마지막으로 기록된**
  상태였다. 산출물이 반영한 코드는 08-13 이전 어느 시점이며 `745ea83`이 아니다.
  (note-018 Row 1, `TTE_STORE_PATH` 결함)
- **2026-09-12 — 유일하게 확정된 건이다.** 반영 커밋 8개가 `PROVENANCE.md`에 있다:
  `623e663`, `a2ecba6`, `141ecb7`, `a2fb858`, `c75085c`, `d0ee924`, `c0df6db`, `e8daa37`.
  런 디렉터리는 `output/site_gap/2026-09-15/`(라벨이 발송일과 다름)이고, 그 `DELIVERY/`
  6파일과 발송 zip의 md5가 파일별로 일치함을 확인했다.

## 표 2 — 발송분의 추출 숫자

`InclusionRules / ConceptSets`, 그리고 `_generationCensus`가 있는 경우 `총 기준수 / 매핑 / 미매핑 / 스킵`.

| 발송일 | EMPA-REG | CARMELINA | CAROLINA |
| --- | --- | --- | --- |
| 2026-06-24 | 21/56 · census 없음 | 21/53 · census 없음 | 28/72 · census 없음 |
| 2026-08-31 | 25/58 · census 없음 | 21/31 · census 없음 | 27/74 · census 없음 |
| 2026-09-12 | 20/41 · 65/40/3/21 | 22/36 · 63/35/4/22 | 26/85 · 115/84/4/25 |

`_generationCensus`는 09-12 산출물에만 있다(회계 필드가 나중에 추가됨). **세 행의 총
기준수를 직접 비교하면 안 된다** — 두 행은 측정값 자체가 없다.

ARISTOTLE·PLATO·LEADER는 08-31에만 포함됐다. 06-24와 09-12의 기본 배포는 3개 시험이다.

## 표 3 — 발송분의 병원 실측 결과 (아주대, treatment / comparator)

| 발송일 | CARMELINA | CAROLINA | EMPA-REG | 출처 |
| --- | --- | --- | --- | --- |
| 2026-06-24 | — | — | — | "대부분 환자 0명" (정성 서술만, 스터디별 수치 없음) |
| 2026-08-31 | 0 / 0 | **31 / 46** | 0 / 0 | note-010 (2026-09-05 보고) |
| 2026-09-12 | 0 / 0 | **0 / 0** | 0 / 0 | 사용자 보고 (2026-09-14) |

## 표 4 — 발송별 지배적 차단 요인 (정의에서 직접 읽은 값)

세 발송의 차단 요인이 서로 다르다. 아래는 전부 `.circe.json`에서 직접 읽은 값이며
병원 데이터를 관측한 값이 아니다.

| 항목 | 2026-06-24 | 2026-08-31 | 2026-09-12 |
| --- | --- | --- | --- |
| entry event | 3개 시험 전부 `ConditionOccurrence` T2DM | CAROLINA `DrugEra`, CARMELINA·EMPA-REG `ConditionOccurrence` T2DM | `DrugEra` 4개, `ConditionOccurrence` T2DM 2개 |
| 치료제 지정 방식 | `ALL` inclusion rule (`DrugExposure`) | CAROLINA는 entry, CARMELINA는 `ALL` rule | entry (`DrugEra`) |
| CARMELINA 치료제 concept | **`1580747` sitagliptin — 오매핑** | `40239216` linagliptin (정상) | `40239216` linagliptin (정상) |
| CAROLINA 치료제 concept | **`1580747` sitagliptin — 오매핑** | `40239216` linagliptin (정상) | `40239216` linagliptin (정상) |
| EMPA-REG 치료제 concept | **`1254065` CHF-6366 — 오매핑** | **5개 무관 약물** `859730`, `1254065`, `1201518`, `1201447`, `702171` | `45774751` empagliflozin (정상) |
| BMI / HbA1c 단위 조건 | **없음** | **없음** | **`9531 (kg/m2)` / `8554 (%)` 요구** |

`1580747 sitagliptin`은 `'linagliptin'`이라는 이름의 concept set 안에 들어 있었다 —
이름과 내용이 어긋난 채로 발송됐다. EMPA-REG의 5개 무관 약물 세트는 entry-drug-exact-match
결함으로, 개발 코드명 "BI 10773"에 매칭되는 RxNorm Ingredient가 없어 exact-name 매핑이
무관한 concept으로 떨어진 결과다(note-010에 기록됨).

## CAROLINA 회귀

**CAROLINA는 아주대에서 31/46명이었고, 09-12 발송에서 0/0명이 됐다.** 나머지 두 시험은
세 발송 모두 0이므로, 09-12에서 새로 나빠진 것은 CAROLINA 하나다.

두 발송의 CAROLINA에서 presence를 요구하는 `ALL` 규칙만 비교하면 변수는 하나다:

| 규칙 | 2026-08-31 (31/46명) | 2026-09-12 (0/0명) |
| --- | --- | --- |
| entry event | `DrugEra` linagliptin / glimepiride | **동일** |
| Body Mass Index | `<= 45`, **단위 조건 없음** | `<= 45`, **`Unit = 9531 (kg/m2)` 요구** |
| HbA1c | `>= 6.5`, `> 7.5`, **단위 조건 없음** | `6.5~8.5`, `> 7.5`, **`Unit = 8554 (%)` 요구** |

두 규칙 모두 `ALL`이므로 AND로 묶이고, 하나만 0을 반환해도 코호트 전체가 0이 된다.
entry event가 두 발송에서 동일하고 08-31에 31/46명을 냈으므로 **아주대의 `drug_era`는
비어 있지 않다** — 추정이 아니라 08-31 실측이 배제해 주는 가설이다. 남는 변수는 단위다.

단위 요구를 넣은 커밋: `141ecb7`("carry the UCUM units the table lacked"),
`956d8e8`("a threshold whose unit was dropped is refused"). 같은 방향 lint:
`5d4dc1d`, `606c686`.

같은 함정이 이미 기록돼 있다: note-021은 아주대·동아대·계명대 delivery CDM의 eGFR
13,845행 **전부**가 은퇴한 `9117`을 쓰고 현행 `720870`을 쓰지 않는다고 적었고,
`_UNIT_DEPRECATED_FORMS`로 eGFR만 복구했다(아주대 0 → 112행). BMI의 `9531`과
HbA1c의 `8554`에 같은 처리가 들어갔는지는 이 문서에서 확인하지 않았다.

**단위 가설로 설명되지 않는 것: CARMELINA.** 08-31 CARMELINA는 entry가 T2DM,
치료제 concept이 정상(`40239216`), 단위 조건도 없었는데 양쪽 팔 모두 0이었다.
comparator 팔에는 치료제 `ALL` 규칙조차 없었다. CARMELINA의 0은 단위와 무관한 별개
차단 요인이며, 이 문서는 그것을 특정하지 못한다.

## 게이트가 이걸 잡지 못한 이유

배포 게이트는 **단위가 없는** bound를 결함으로 잡는다(`unitless value bound`).
**단위가 있고 사이트가 그 concept을 쓰지 않는** 경우는 검사 항목에 없다. 게이트
관점에서 09-12 정의는 08-31 정의보다 개선이고, 병원 실행에서는 31/46명이 0명이 됐다.
게이트가 한 방향으로만 조여져 있다.

## 규칙별 attrition을 받으면 무엇이 끝나는가

세 번의 발송 내내 미확정으로 남은 것은 "어느 규칙이 0을 만들었는가" 하나다. 아주대는
People/Records 헤드라인만 제공했다.

이 요청의 가치는 이미 증명돼 있다. 동아대가 한 번 규칙별 보고서를 제공했을 때,
EMPA-REG comparator의 원인이 한 줄로 확정됐다 — `rule 11 "Dietary regimen + Exercise
regimen"이 entry event 94,164건 중 0건 충족` (note-010). 같은 것을 아주대에서 받으면
위의 단위 가설과 CARMELINA의 미특정 차단 요인이 한 번에 판정된다.

요청할 것 (Atlas / WebAPI 양쪽 다 있는 표준 산출물):

1. **Inclusion Rule Statistics** — 코호트 정의 → Generation → 해당 CDM source 탭.
   규칙별로 `id`, `name`, `personCount`(그 규칙까지 통과한 인원), `gainCount`,
   `personTotal`. CSV export 또는 화면 캡처.
2. **Entry event 인원수** — 규칙 적용 전 초기 인원. 이것과 규칙 1의 `personCount`를
   비교하면 첫 규칙에서 떨어졌는지 판별된다.
3. 위 둘을 **6개 파일 각각**(3개 시험 × 2개 팔)에 대해.

집계값만 있으면 되고 환자 단위 행은 필요 없다. 규칙별 표가 어려우면 대안으로
`docs/site_zero_diagnosis_queries.sql`의 Q3(HbA1c 단위 분포)·Q5(BMI 단위 분포)
두 쿼리로도 단위 가설은 판정된다 — 다만 CARMELINA의 별개 차단 요인은 규칙별 표가
있어야 잡힌다.

## 확정하지 못한 것

- 아주대에서 BMI·HbA1c의 `unit_concept_id` 실제 값을 관측한 적이 없다. CAROLINA 회귀의
  결론은 "단위 요구가 추가됐다"(정의 측 사실)와 "31/46 → 0"(실측)의 결합이며, 어느 단위
  값 때문인지는 미확인이다.
- CARMELINA가 세 발송 모두 0인 원인은 특정하지 못했다. 단위 가설로는 설명되지 않는다.
- 2026-06-24의 스터디별 수치는 없다. 기록은 "대부분 환자 0명"이라는 정성 서술뿐이고,
  어느 시험이 0이었는지 특정되지 않는다. 06-24 정의의 치료제 오매핑(sitagliptin,
  CHF-6366)은 정의에서 읽은 사실이지만, 그것이 그 발송의 0을 만들었다는 것은
  측정되지 않았다.
- 아주대는 규칙별 attrition을 제공한 적이 한 번도 없다.
