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

## 규칙별 실측 — 정확히 0명인 규칙

`% 만족`은 entry event 대비 그 규칙이 단독으로 만족되는 비율이다. `% To-Gain`은 그
규칙만 제거했을 때의 증가분.

| 사이트 | 코호트 | entry | 0명(0.00%)인 규칙 |
| --- | --- | --- | --- |
| 아주대 | carmelina_comparator | 38,664 | #12 `HbA1c at least 6.5% + HbA1c at most 10.0%` |
| 아주대 | carolina_comparator | 21,199 | #2 `Body Mass Index`, #7 `HbA1c in range for treatment-naive patients + …` |
| 아주대 | empa-reg_comparator | 38,664 | #4 `HbA1c for patients on background therapy … + HbA1c for drug naive patients`, #14 `Endocrine disorder (excluding T2DM)` |
| 동아대 | carmelina_comparator | 92,304 | 없음 — 최저는 #2 `Stable antidiabetic background medication for 8 weeks` 798명(0.86%) |
| 동아대 | empa-reg_comparator | 92,304 | #14 `Endocrine disorder (excluding T2DM)` |

**모든 코호트에서 To-Gain이 전부 0.00%다**(동아대 EMPA-REG의 #14만 2.21%). 0인 규칙이
둘 이상이면 하나만 빼도 나머지가 여전히 0이라 To-Gain이 0으로 찍힌다 — To-Gain 0을
"그 규칙은 무관하다"로 읽으면 안 된다.

## 결함 A — 단위 요구가 아주대에서만 코호트를 죽인다

09-12 발송분은 BMI에 `Unit = 9531 (kg/m2)`, HbA1c에 `Unit = 8554 (%)`를 요구한다.
08-31 발송분에는 두 조건이 없었고, 그때 아주대 CAROLINA는 31/46명이었다.

| 규칙 | 아주대 | 동아대 |
| --- | --- | --- |
| CARMELINA HbA1c | **0명 (0.00%)** | 14,509명 (15.72%) |
| CAROLINA HbA1c | **0명 (0.00%)** | (생성 실패) |
| CAROLINA BMI | **0명 (0.00%)** | (생성 실패) |
| EMPA-REG HbA1c | **0명 (0.00%)** | 5,484명 (5.94%) |

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

## 아직 확정되지 않은 것

- treatment arm의 규칙별 표는 확인하지 않았다(스크린샷 16장 중 위에 인용한 5장만 읽음).
  나머지 11장에 treatment arm과 다른 코호트의 표가 있을 수 있다.
- 아주대에서 BMI·HbA1c의 `unit_concept_id`가 실제로 무슨 값인지는 여전히 관측되지
  않았다. 0명이라는 사실만 관측됐고, NULL인지 다른 concept인지는 미확인이다. 이 구분이
  수정 방향을 가른다 — `docs/site_zero_diagnosis_queries.sql`의 Q3·Q5.
- 동아대 CARMELINA는 0명인 규칙이 하나도 없는데 결과가 0이다. 여러 규칙의 교집합이
  0이라는 뜻이고, 어느 조합인지는 이 보고서로 알 수 없다.
