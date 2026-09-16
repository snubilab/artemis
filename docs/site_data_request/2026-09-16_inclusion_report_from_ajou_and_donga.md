# 2026-09-12 발송분에 대한 병원 회신 (아주대·동아대)

사용자가 2026-09-16에 전달한 두 docx. **세 번의 발송 만에 처음으로 규칙별 attrition이
들어왔다** — 그전까지 아주대는 People/Records 헤드라인만 줬다.

| 파일 | 사이트 | CDM source | 스크린샷 |
| --- | --- | --- | --- |
| `아주대_ajou_v20260912.docx` | 아주대 | `CDMPv538` | `ajou_screenshots/` 12장 |
| `동아대_3studies_20260912.docx` | 동아대 | `DAMC_5.3.1_01` | `donga_screenshots/` 4장 |

각 스크린샷은 Atlas의 **Inclusion Report**(포함 조건 레포트) 화면이며, 규칙별
`N` / `% 만족` / `% 증가(To-Gain)`를 담고 있다.

## 헤드라인

| 사이트 | CARMELINA t/c | CAROLINA t/c | EMPA-REG t/c |
| --- | --- | --- | --- |
| 아주대 | 0 / 0 | 0 / 0 | 0 / 0 |
| 동아대 | 0 / 0 | **표가 비어 있음** | 0 / 0 |

동아대 CAROLINA 칸은 0이 아니라 **값이 없다.** 아래 결함 C 참조.

## 스크린샷 16장의 구성

전부 읽었다. 아주대 12장은 6개 코호트 x 2뷰, 동아대 4장은 4개 코호트 x 1뷰다.

| 사이트 | 장수 | 구성 |
| --- | --- | --- |
| 아주대 | 12 | 코호트당 2장 — 홀수: **독립 뷰**(`% 만족` + `% 증가(To-Gain)`), 짝수: **축차 뷰**(`% 잔류` + `% 차이`). 순서는 carmelina c/t, carolina c/t, empa-reg c/t |
| 동아대 | 4 | carmelina c/t, empa-reg c/t의 Generation 화면 + Inclusion Report(독립 뷰). **CAROLINA는 없다** |

두 뷰는 다른 질문에 답한다. **독립 뷰**는 "그 규칙 하나만 놓고 보면 entry 중 몇 명이
만족하나", **축차 뷰**는 "위에서부터 순서대로 적용하면 어디서 떨어지나"다. 독립 뷰에서
0명인 규칙은 순서와 무관하게 단독으로 코호트를 0으로 만든다.

## 아주대 (CDMPv538) — 6개 코호트 전부

| 코호트 | entry | 독립 뷰에서 0명인 규칙 | 축차 뷰 경로 |
| --- | --- | --- | --- |
| carmelina_comparator | 38,664 | #12 HbA1c | #2 → 1,257 (-96.75%) → #10 → 32 → **#12 → 0** |
| carmelina_treatment | 8,837 | #12 HbA1c (**To-Gain 0.12% — 유일한 비-제로**) | #1 → 7,178 → #2 → 630 (-74.10%) → #10 → 60 → **#12 → 0** |
| carolina_comparator | 21,199 | #2 BMI, #7 HbA1c | #1 → 20,058 → **#2 BMI → 0 (-94.62%)** |
| carolina_treatment | 8,837 | #2 BMI, #7 HbA1c | #1 → 8,611 → **#2 BMI → 0 (-97.44%)** |
| empa-reg_comparator | 38,664 | #4 HbA1c, #14 Endocrine disorder | #1 → 38,472 → **#4 HbA1c → 0 (-99.50%)** |
| empa-reg_treatment | 5,891 | #4 HbA1c | #2 T2DM → 4,370 (-25.80%) → **#4 HbA1c → 0 (-74.18%)** |

## 동아대 (DAMC_5.3.1_01) — 4개 코호트, CAROLINA는 생성 실패

| 코호트 | entry | 0명인 규칙 | 최저 통과 규칙 / 최대 To-Gain |
| --- | --- | --- | --- |
| carmelina_comparator | 92,304 | **없음** | #2 798명(0.86%) / To-Gain 전부 0.00% |
| carmelina_treatment | 7,317 | **없음** | #2 449명(6.14%) / #13 To-Gain 0.29% |
| empa-reg_comparator | 92,304 | **#14 Endocrine disorder** | #14 / To-Gain 2.21% |
| empa-reg_treatment | 3,820 | **없음** | #14 786명(20.58%) / **#14 To-Gain 27.36%** |

**To-Gain 0.00%를 "그 규칙은 무관하다"로 읽으면 안 된다.** 0명인 규칙이 둘 이상이면
하나만 빼도 나머지가 여전히 0이라 전부 0.00%로 찍힌다. 아주대 CAROLINA는 #2와 #7이
동시에 0이므로 **둘 다** 빼야 늘어난다.

## 결함 A — 단위 요구가 아주대에서만 코호트를 죽인다

09-12 발송분은 BMI에 `Unit = 9531 (kg/m2)`, HbA1c에 `Unit = 8554 (%)`를 요구한다.
08-31 발송분에는 두 조건이 없었고, 그때 아주대 CAROLINA는 31/46명이었다.

| 시험 / 팔 | 규칙 | 아주대 | 동아대 |
| --- | --- | --- | --- |
| CARMELINA comparator | #12 HbA1c 6.5~10.0 | **0명 (0.00%)** | 14,509명 (15.72%) |
| CARMELINA treatment | #12 HbA1c 6.5~10.0 | **0명 (0.00%)** | 6,160명 (84.19%) |
| EMPA-REG comparator | #4 HbA1c 7.0~10.0/9.0 | **0명 (0.00%)** | 5,484명 (5.94%) |
| EMPA-REG treatment | #4 HbA1c 7.0~10.0/9.0 | **0명 (0.00%)** | 2,351명 (61.54%) |
| CAROLINA comparator | #2 BMI <= 45 | **0명 (0.00%)** | (생성 실패) |
| CAROLINA treatment | #2 BMI <= 45 | **0명 (0.00%)** | (생성 실패) |
| CAROLINA c/t | #7 HbA1c in range | **0명 (0.00%)** | (생성 실패) |

**아주대는 단위 조건이 붙은 규칙 전부(6/6)가 정확히 0명이고, 동아대는 전부(4/4) 통과한다.**
사이트별로 완전히 갈린다.

**같은 규칙이 아주대에서는 0, 동아대에서는 통과한다.** 단위 concept을 사이트 ETL이
무엇으로 쓰느냐의 차이이며, 정의의 문제가 아니라 정의가 사이트에 요구하는 것이 너무
좁다는 문제다. 이전 세션이 세운 단위 가설은 **아주대에서는 맞고 동아대에서는 틀리다.**

## 결함 B — "excluding T2DM"이 배제되지 않는다

EMPA-REG의 `#14 Endocrine disorder (excluding T2DM)`가 **두 사이트 모두 0명**이다.
정의에서 직접 확인된다 — `empa-reg_comparator.circe.json`의 `codeset 29`는 이름이
`'Endocrine disorder'`이고, 23개 멤버 중 `isExcluded`가 **0개**이며,
`201820 Diabetes mellitus`를 **descendants 포함**으로 담고 있다.

entry event가 T2DM(`201826`, `201820`의 descendant)이므로 **entry 전원이 이 배제에
걸린다.** 규칙은 `Exactly 0`을 요구하므로 결과는 0명이다. 이것은 어떤 CDM에서도
0명이며, 사이트 데이터와 무관한 정의 자체의 결함이다.

**entry event가 무엇이냐로 갈린다는 것이 네 코호트에서 확인된다:**

| 팔 | entry event | 아주대 #14 | 동아대 #14 |
| --- | --- | --- | --- |
| comparator | `ConditionOccurrence` T2DM | **0명 (0.00%)** | **0명 (0.00%)** |
| treatment | `DrugEra` empagliflozin | 874명 (14.84%) | 786명 (20.58%) |

comparator는 entry 자체가 T2DM이라 전원이 걸리고, treatment는 약물로 진입하므로 T2DM
진단 기록이 없는 사람이 살아남는다. 사이트가 달라도 결과가 같다는 점이 이것을 데이터
문제가 아니라 정의 문제로 확정한다.

동아대 empa-reg_treatment에서 이 규칙의 **To-Gain이 27.36%로, 전체 스크린샷 통틀어 가장
크다.** 아주대 empa-reg_comparator에서는 #4 HbA1c가 먼저 전부 죽이므로 축차 뷰에서는
#14의 기여가 보이지 않는다 — 독립 뷰에서만 드러난다. **둘 다 고쳐야 코호트가 0에서
벗어난다.**

## 결함 C — CAROLINA의 concept 객체가 불완전해 Atlas가 렌더에 실패한다

동아대에서 아래 에러가 떴고, 그래서 CAROLINA 칸이 비어 있다:

```
DataTables warning: table id=DataTables_Table_421 - Requested unknown parameter
'concept.DOMAIN_ID' for row 13, column 2
```

`deliveries/2026-09-12/carolina_{treatment,comparator}.circe.json`의 `codeset 80`
(`'cancer other than non-melanoma skin cancer'`, 멤버 18개)에서 **row 13~17의 5개
멤버가 `CONCEPT_ID`와 `CONCEPT_NAME`만 갖고 있고** `DOMAIN_ID`·`VOCABULARY_ID`·
`CONCEPT_CODE`·`STANDARD_CONCEPT`·`INVALID_REASON`·`CONCEPT_CLASS_ID` 6개 키가 없다.
에러 메시지의 `row 13`이 정확히 첫 결손 행이다.

그 5개는 이 파이프라인이 처음으로 방출한 `isExcluded: true` 멤버들이며, 커밋
`c75085c`(`"X other than Y"를 excluded 멤버로 방출`)가 만들었다. 06-24·08-31 발송분
전체와 09-12의 나머지 4개 파일은 이 결손이 없다 — 09-12 CAROLINA 두 팔에만 있다.

결함 B와 C는 같은 계열이다: 이름이 "X other than Y"인 집합에서 Y를 실제로 배제하는 일.
CAROLINA에서는 배제를 구현했으나 concept 객체를 불완전하게 만들었고, EMPA-REG에서는
배제가 아예 구현되지 않았다.

## 결함 D(후보) — CARMELINA의 배경약물 8주 규칙이 두 사이트에서 96~99%를 떨어뜨린다

`#2 Stable antidiabetic background medication for 8 weeks`는 어느 사이트에서도 0명은
아니지만, 단일 규칙으로는 가장 큰 감소를 만든다.

| 사이트 / 팔 | entry | #2 통과 | 비율 |
| --- | --- | --- | --- |
| 아주대 carmelina_comparator | 38,664 | 1,257 | 3.25% |
| 아주대 carmelina_treatment | 8,837 | 713 | 8.07% |
| 동아대 carmelina_comparator | 92,304 | 798 | **0.86%** |
| 동아대 carmelina_treatment | 7,317 | 449 | 6.14% |

동아대 CARMELINA 두 팔은 **0명인 규칙이 하나도 없는데 결과가 0**이다. 여러 규칙의
교집합이 0이라는 뜻이고, 그 중 가장 좁은 것이 이 #2다.

CARMELINA 프로토콜이 실제로 8주 안정 투약을 요구하므로 **이것이 결함인지 충실한 번역인지
이 보고서로는 알 수 없다.** 다만 네 코호트 모두에서 99~92%를 떨어뜨린다는 사실은
기록해 둔다. 판정하려면 프로토콜 원문과 대조해야 한다.

## 아직 확정되지 않은 것

- **스크린샷 16장은 전부 읽었다.** 다만 동아대는 CAROLINA 두 팔의 보고서가 아예 없고
  (결함 C로 생성 실패), 아주대와 달리 축차 뷰도 제공되지 않았다.
- 아주대에서 BMI·HbA1c의 `unit_concept_id`가 실제로 무슨 값인지는 여전히 관측되지
  않았다. 0명이라는 사실만 관측됐고, NULL인지 다른 concept인지는 미확인이다. 이 구분이
  수정 방향을 가른다 — `docs/site_zero_diagnosis_queries.sql`의 Q3·Q5.
- 동아대 CARMELINA는 0명인 규칙이 하나도 없는데 결과가 0이다. 여러 규칙의 교집합이
  0이라는 뜻이고, 어느 조합인지는 이 보고서로 알 수 없다.
