# 2026-09-23 발송분에 대한 병원 회신 (아주대·동아대)

사용자가 2026-10-06에 전달한 docx 두 건을 분석한 결과다. 원본은 `data/site_reports/2026-09-23/`에 있다.
동아대 생성 시각은 2026-09-28이고, 아주대 문서에는 생성 시각이 없다.

| 파일 | 사이트 | CDM source | 내용 |
| --- | --- | --- | --- |
| `ajou_v20260923.docx` | 아주대 | `CDMPv538` | 코호트 6개마다 `intersect view`와 `attrition view` 1장씩, 모두 12장. 규칙별 `% Satisfied` 15% 이하 항목에 대한 사이트의 원인 의견 |
| `donga_20260923.docx` | 동아대 | `DAMC_5.3.1_01` | 코호트 6개의 Generation 화면과 `intersect view` 1장씩, 모두 6장 |

`intersect view`는 규칙 하나만 적용했을 때 entry 중 몇 명이 만족하는지(`N`, `% Satisfied`)와,
그 규칙 하나 때문에만 탈락한 사람의 비율(`% To-Gain`)을 보여 준다. `attrition view`는 규칙을
위에서부터 차례로 적용했을 때 남는 인원(`N`, `% Remain`, `% Diff`)을 보여 준다.

## 결론

- **12개 코호트 중 9개가 0명이 아니다.** 09-12 발송분은 아주대 6개가 모두 0명이었고, 동아대는
  4개가 0명이었으며 CAROLINA 2개는 결과가 없었다.
- **09-12의 0명 원인 7건 중 6건은 예상한 규칙의 통과 인원이 늘었다.** 나머지 1건인 EMPA-REG
  Endocrine 배제는 comparator에서만 풀렸다. treatment에서는 통과 인원이 두 사이트 모두 09-12와
  같았다. T2DM 제외 멤버가 comparator 파일에만 들어갔다. 그래서 treatment 파일에서는 `#2`(T2DM
  기록 1회 이상)와 `#15`(당뇨 기록 0회)가 같은 window에서 동시에 만족될 수 없고, 어떤 CDM에서도
  0명이다(결함 1).
- 0명이 아닌 코호트에서도 인원을 가장 많이 줄인 규칙은 추출 결함과 겹친다. 하나는 배경약
  concept set에 프로토콜이 배제한 약물 계열이 들어간 것이다(결함 2). 다른 하나는 값 범위
  기준(BMI, HbA1c)을 gold와 달리 "범위 안 측정 1회 이상"으로 만든 것이다(결함 3).
- 두 사이트 모두에서 아무도 배제하지 않은 배제 규칙이 있다. 혈당 배제는 concept set에 사이트가
  쓰는 혈당 개념이 없어서 배제하지 못했다(결함 4). 단위 필터가 걸린 배제 규칙 중 CAROLINA HbA1c
  상한은 아주대에서 아무도 배제하지 않았고 동아대에서는 comparator 41.22%, treatment 41.45%를 배제했다. eGFR 배제는
  아주대에서 0명, 동아대에서 코호트당 0~5명을 배제했다(결함 5).

## 헤드라인 — treatment / comparator

| 사이트 | 발송 | CARMELINA | CAROLINA | EMPA-REG |
| --- | --- | --- | --- | --- |
| 아주대 | 09-12 | 0 / 0 | 0 / 0 | 0 / 0 |
| 아주대 | **09-23** | **4 / 0** | **1 / 6** | **0 / 2,301** |
| 동아대 | 09-12 | 0 / 0 | 결과 없음 | 0 / 0 |
| 동아대 | **09-23** | **9 / 7** | **1 / 2** | **0 / 1,655** |

09-12 보고서가 있는 10개 코호트의 entry 인원은 09-12와 같다(아주대 CARMELINA comparator 38,664,
treatment 8,837, 동아대 CARMELINA comparator 92,304 등). 이 10개 코호트에서 두 발송 사이에 바뀐 것은
entry 뒤의 규칙뿐이다. 동아대 CAROLINA의 entry는 comparator 14,000, treatment 7,317이다.

## 09-12 0명 원인별 — 예상한 규칙의 통과 인원이 늘었는가

note-031이 이번 발송 전에 적은 수정 대상 7건을 기준으로 맞춰 봤다. 값은 `intersect view`의
`% Satisfied`다.

| 09-12 원인 | 이번 수정 | 09-23 결과 | 판정 |
| --- | --- | --- | --- |
| 아주대 CARMELINA HbA1c 0명 (단위 조건) | 단위 조건 제거, `bt 6.5..10` | comparator 31.34%, treatment 57.88% | 늘었음 |
| 동아대 CARMELINA 0명 (#12·#13 논리적 여집합) | 한 규칙으로 합침 | 동아대 treatment 9명, comparator 7명 | 늘었음 |
| 아주대 CAROLINA BMI 0명 (단위 조건) | 단위 조건 제거 | comparator 4.51%, treatment 3.95% | 늘었음. 그래도 인원 감소가 가장 큰 규칙(결함 3) |
| 아주대 CAROLINA HbA1c 0명 (단위 조건) | 단위 조건 제거 | comparator 41.96%, treatment 48.58% | 늘었음 |
| 아주대 EMPA-REG HbA1c 0명 (단위 조건) | 단위 조건 제거 | comparator 21.28%, treatment 54.22% | 늘었음 |
| 두 사이트 EMPA-REG Endocrine 0명 (T2DM 미배제) | T2DM 두 concept 제외 | comparator 아주대 0% → 83.96%, 동아대 0% → 86.20%. **treatment 아주대 874명(14.84%), 동아대 786명(20.58%) — 09-12와 같은 값** | **comparator에서만 늘었음** |
| 동아대 CAROLINA 결과 없음 (Atlas 렌더 실패) | concept 객체 보완 | 동아대 treatment 1명, comparator 2명, 보고서 생성됨 | 결과가 생김 |

동아대 CARMELINA HbA1c의 `% Satisfied`는 comparator 15.72% → 8.91%, treatment 84.19% → 63.69%로
줄었다. 09-12 `#12`는 "≥6.5(%)"와 "≤10(%)"를 `ANY`로 묶었으므로, 단위가 %인 HbA1c 측정이
하나라도 있으면 값과 관계없이 만족했다. 09-23 `#3`은 `bt 6.5..10` 하나다. 09-23 규칙의 조건이
09-12보다 좁으므로 줄어드는 방향이 맞고, 회귀로 볼 근거는 없다. 동아대 EMPA-REG HbA1c는 comparator 5.94%, treatment 61.54%로
09-12와 같다. 동아대는 09-12에도 단위가 맞았으므로, 단위 조건을 빼도 달라지지 않는 것이 맞다.

## 코호트별 `attrition view` (아주대)

| 코호트 | entry | 차례로 적용했을 때의 경로 | 최종 |
| --- | --- | --- | --- |
| carmelina_comparator | 38,664 | #2 배경약 → 1,257 (−96.75%) → #3 → 694 → #8 → 667 → **#11 → 23** → #13 → 2 → #20 → 1 → #23 → 0 | 0 |
| carmelina_treatment | 8,837 | #1 T2DM → 7,178 → #2 배경약 → 630 (−74.10%) → #3 → 529 → #8 → 502 → **#11 → 37** → #13 → 4 | 4 |
| carolina_comparator | 21,199 | #1 → 20,058 → **#2 BMI → 922 (−90.27%)** → #3 항당뇨약 → 39 → #7 → 22 → #9 → 15 → #11 → 11 → #19 → 6 | 6 |
| carolina_treatment | 8,837 | #1 → 8,611 → **#2 BMI → 343 (−93.56%)** → #3 항당뇨약 → 20 → #7 → 15 → #9 → 11 → #11 → 6 → #19 → 1 | 1 |
| empa-reg_comparator | 38,664 | #1 → 38,472 → **#6 HbA1c → 8,192 (−78.32%)** → #7 → 4,896 → … → #14 → 3,381 → #15 → 2,617 → #20 → 2,421 → #21 → 2,301 | 2,301 |
| empa-reg_treatment | 5,891 | #2 T2DM → 4,370 (−25.80%) → #6 HbA1c → 2,842 (−25.94%) → … → #14 → 1,912 → **#15 Endocrine → 0** | 0 |

동아대는 `attrition view`를 보내지 않았다. 동아대 EMPA-REG treatment에서 0이 아닌 `% To-Gain`은
`#2 T2DM` 4.82%와 `#15 Endocrine` 30.42% 둘이다.

## 결함 1 — EMPA-REG treatment 파일에 T2DM 제외가 들어가지 않았다

`#15 'Endocrine disorder (excluding T2DM)'`는 두 파일 모두 `cs29 'Endocrine disorder'`를
`exactly 0`, window `-9999..0`으로 쓴다. 두 파일의 `cs29`가 다르다.

| 파일 | `cs29` 멤버 | `isExcluded` 멤버 |
| --- | --- | --- |
| `empa-reg_comparator.circe.json` | 25 | `201826 Type 2 diabetes mellitus`, `44793113 Diabetes mellitus with multiple complications` |
| `empa-reg_treatment.circe.json` | 23 | **없음** |

두 파일 모두 `201820 Diabetes mellitus`를 descendants 포함으로 담고 있다. treatment의 `#2 Type 2
Diabetes Mellitus`는 `cs2`(`201826`, `44793113`, 둘 다 descendants 포함)를 `at least 1`, window
`-9999..0`으로 요구한다. `synthea_cdm.concept_ancestor`에서 `201826`과 `44793113`은 둘 다 `201820`의
하위 개념(`min_levels_of_separation` 1)이다. 따라서 treatment에서 `#2`를 만족시키는 기록은 언제나
`#15`가 금지하는 기록이고, 두 규칙을 함께 만족하는 사람은 어떤 CDM에도 없다. 아주대
`attrition view`에서 `#2`를 통과해 `#14`까지 남은 1,912명이 `#15`에서 0명이 된 것과 맞는다.

note-031의 스토어 독립 lint는 `unsatisfiable_presence_rules`를 0으로 보고했다. 두 규칙의 concept
set이 같은 멤버가 아니라 하위 개념 관계로 겹치는 경우를 이 lint가 검사하는지는 확인하지 않았다.

`#15`의 `% To-Gain`은 아주대 29.79%, 동아대 30.42%다. entry에 곱하면 약 1,755명, 약 1,162명이다
(표시된 비율이 반올림돼 있어 근사값이다). 이 값은 규칙을 **뺐을 때** 늘어나는 인원이지 고쳤을 때
늘어나는 인원이 아니다.

수정이 comparator에만 들어간 경로는 `output/site_gap/2026-09-22_verify5/fix_reflection.txt`에
있다.

```
PASS            B entry-absence
                  control: baseline detector exit 1, repair would change ['empa-reg_comparator.circe.json']
                  applicable: repair fired 1 time(s) during export
```

수정 B는 "배제 규칙의 concept set이 entry 사건의 concept을 덮는 경우"를 찾는 검출기였다.
comparator는 T2DM 진단으로 진입하므로 검출됐고, treatment는 empagliflozin으로 진입하므로 검출
대상이 아니었다. treatment에서 같은 규칙이 진입 이전의 T2DM 기록으로 사람을 배제하는 것은 이
검출기의 범위 밖이다. note-031의 발송 확인("`isExcluded` 멤버 12개")은 파일 전체의 멤버 수를
센 것이라서 파일 하나가 빠진 것을 구별하지 못한다.

09-16 분석(`2026-09-16_inclusion_report_from_ajou_and_donga.md`)의 결함 B도 `codeset 29`를
comparator 파일에서만 확인했다.

아주대 의견("컨셉셋에 T2DM을 exclude하는 항목 없음")은 treatment 파일에 대해 맞다.

**고쳐도 남는 것.** 원문은 `"Any uncontrolled endocrine disorder except type 2 diabetes"`인데,
규칙에는 "uncontrolled"가 없고 window는 평생(`-9999..0`)이다. T2DM을 제외해도 `cs29`에는
`201820 Diabetes mellitus`의 다른 하위 개념, `24609 Hypoglycemia`, `35622016 Insulin resistance`,
`192963 Disorder of pancreas`가 남는다. 이것들이 treatment에서 몇 명을 배제할지는 측정하지
않았다.

## 결함 2 — 배경약 concept set에 프로토콜이 배제한 약물 계열이 들어 있다 (09-16 결함 D 확정)

| 시험 | 규칙 | concept set 멤버 | 프로토콜 원문 |
| --- | --- | --- | --- |
| CARMELINA | `#2 Stable antidiabetic background medication for 8 weeks` (`DrugExposure` at least 1, `-56..0`) | `cs6`: saxagliptin, dapagliflozin, empagliflozin | "Male or female patients who are drug-naïve or pre-treated with any antidiabetic background therapy, excluding treatment with GLP-1 receptor agonists, DPP-4 inhibitors or SGLT-2 inhibitors if ≥ 7 consecutive days" |
| CAROLINA | `#3`, `#10 Anti-diabetic medication` (`DrugExposure` at least 1, `-56..0`) | `cs33`, `cs32`: dapagliflozin, empagliflozin | "Stable anti-diabetic background medication (unchanged daily dose) for at least 8 weeks prior V1a and without short term use of insulin" |

- CARMELINA `cs6`의 세 약물은 모두 `#11`의 배제 집합(`cs4 DPP-4 inhibitors`, `cs5 SGLT-2
  inhibitors`) 안에 있다. `#2`는 이 약물을 `-56..0`에 요구하고 `#11`은 같은 약물을 `-7..0`에
  금지한다(treatment의 DPP-4 그룹만 `-7..-1`). `#11`의 `% Satisfied`는 comparator 88.48%, treatment 91.63%다. 반면 `#2`를 통과한
  사람 중에서는 comparator 667명 중 23명, treatment 502명 중 37명만 `#11`을 통과했다.
- 원문은 drug-naïve 환자를 허용하는데, 두 규칙 모두 약물 기록이 있어야 통과한다.
- CAROLINA gold(`[TROY v1.1] Linagliptin (CAROLINA).json`)에는 배경약 기록을 요구하는 규칙이
  없다. gold의 관련 규칙은 `#6 'No other antidiabetic druts'`(rosiglitazone, pioglitazone,
  GLP-1 receptor agonists, linagliptin 외 DPP-4 inhibitors, insulin 배제)다. gold에는
  `[TROY drug] Metformin`(`cs194`)과 `[TROY drug] alpha-glucosidase inhibitor`(`cs195`, acarbose)
  concept set이 있다.

아주대 의견과의 대조:

- CARMELINA treatment "리나글립틴 신규 사용자의 87%가 배경약 기록이 전혀 없음(인덱스 이전 1,141명)"
  — 이 수는 세 약물만 담은 `cs6`로 계산된 값이다. 실제 배경약 처방 비율을 나타내는지는 이 보고서로
  판정할 수 없다.
- CAROLINA "기간을 전체로 늘려도 1,414명(comparator) / 867명(treatment), 윈도우 문제는 아님"
  — concept set이 dapagliflozin·empagliflozin 두 약물이라는 사실과 맞는다.
- "3차 의료기관이라 지역 병원 처방이 잡히지 않을 수 있음" — 사이트 데이터 사정이며 이 보고서로는
  판정할 수 없다.

## 결함 3 — 값 범위 기준을 "범위 안 측정 1회 이상"으로 만들었다 (gold와 다름)

| 규칙 | 이번 발송 | gold |
| --- | --- | --- |
| CAROLINA `#2 Body Mass Index` | `Measurement` BMI `lte 45` **at least 1**, `-180..0` | `#3 'BMI <=45 kg/m2'`: BMI `gt 45` **exactly 0**, `-180..0` |
| CAROLINA `#7` HbA1c | HbA1c `bt 6.5..8.5` **at least 1**, `-180..0` | `#1 'Insufficient glycaemic control'`: HbA1c `!bt 6.5..8.5` **exactly 0**, `-180..0` |

이번 발송의 정의에서는 window 안에 측정이 없는 사람이 탈락하고, gold의 정의에서는 통과한다.
EMPA-REG gold도 BMI를 `gte 45` exactly 0으로 정의하고, HbA1c 조건도 exactly 0 형태로 쓴다. 이 차이를 정한 결정
기록은 `docs/adr/`과 위키에서 찾지 못했다.

아주대 CAROLINA에서 `#2 BMI` 하나로 comparator −90.27%, treatment −93.56%가 탈락했다. 아주대
의견은 "BMI가 기록된 환자 자체가 적음, 키·몸무게로 계산하면 +152명, window를 2년으로 늘리면
+1,078명"이다. gold의 정의에서는 BMI 기록이 없는 사람이 통과하므로, 이 규칙에서는 window를
늘릴 필요가 없다. HbA1c 규칙(CARMELINA `#3`, EMPA-REG `#6`)도 같은 형태다. EMPA-REG comparator에서
`#6`이 −78.32%로 감소 폭이 가장 크다.

## 결함 4 — 혈당 concept set에 사이트가 쓰는 혈당 개념이 없다

EMPA-REG `#3 glucose`(`cs10`)와 CAROLINA `#13`(`cs41`, `cs42`)은 혈당 >240 mg/dL(또는 >13.3 mmol/L)인
측정이 `exactly 0`이어야 통과한다. EMPA-REG 원문은 "Uncontrolled hyperglycemia with glucose >240 mg/dL
after an overnight fast during placebo run-in and confirmed by a second measurement (not on the same
day)"다.

| concept | 이름 | 아주대 | 동아대 |
| --- | --- | --- | --- |
| `3000483` (set 멤버) | Glucose [Mass/volume] in Blood | 0 | 0 |
| `3004378` (set 멤버) | Glucose in CSF/Glucose plas | 0 | 0 |
| `3004676` (set 멤버) | Glucose [Mass/volume] in Vitreous fluid | 0 | 0 |
| `44816672` (set 멤버) | Glucose [Mass/volume] in Serum, Plasma or Blood | 0 | 0 |
| `3037110` (set 밖) | Fasting glucose [Mass/volume] in Serum or Plasma | 9,137,097 | 41,515 |
| `3004501` (set 밖) | Glucose [Mass/volume] in Serum or Plasma | 0 | 638,261 |

값은 사이트가 2026-07-28에 준 ACHILLES analysis 1800의 `count_value`다
(`data/site_snapshots/{ajou,donga}.zip`). 혈당 배제 규칙은 4개 파일 모두, 두 사이트 모두
`% Satisfied` 100.00%다. 이 규칙은 아무도 배제하지 않았고, 코호트는 원문보다 넓다.

## 결함 5 — 단위 필터가 걸린 배제 규칙이 아주대에서 아무도 배제하지 않았다

note-026은 배제 규칙의 단위 필터를 유지하기로 했다. 단위가 맞지 않으면 배제가 작동하지 않아
코호트가 넓어질 뿐 0명이 되지는 않는다는 판단이었다. 이번 회신에서 아주대는 아래 세 규칙에서
아무도 배제되지 않았다.

| 규칙 | 단위 | 아주대 `% Satisfied` | 동아대 `% Satisfied` |
| --- | --- | --- | --- |
| CAROLINA `#8` HbA1c > 7.5 배제 (comparator / treatment) | `8554 %` | 100.00% / 100.00% | 58.78% / 58.55% |
| EMPA-REG `#4` eGFR < 30 배제 (comparator / treatment) | `720870` | 100.00% / 100.00% | 99.99% (5명 배제) / 100.00% (0명) |
| CARMELINA `#18` eGFR < 15 배제 (comparator / treatment) | `720870` | 100.00% / 100.00% | 100.00% (92,300/92,304, 4명 배제) / 99.96% (3명) |

아주대 스냅샷에는 eGFR concept `40764999`, `46236952`에 기록이 있다. 따라서 개념이 없어서
배제하지 못한 것은 아니다. 남는 후보는 단위인데, 아주대의 실제 `unit_concept_id`는 관측하지
않았다. 동아대의 eGFR 배제 인원(0~5명)이 실제 eGFR 분포를 반영하는지도 이 보고서로는 판정할 수
없다.

그 결과 같은 파일의 CAROLINA HbA1c 조건이 사이트마다 다르게 적용됐다. 동아대에서는 `#7`(6.5~8.5
측정 1회 이상)과 `#8`(7.5 초과 0회)이 함께 적용되어 사실상 6.5~7.5이고, 아주대에서는 `#8`이 아무도
배제하지 않았으므로 6.5~8.5다. `#8`의 그룹 10개는 모두 `gt 7.5`(%)로 같다. 규칙 이름에 있는
배경 치료별 구분("for treatment naïve patients", "for metformin monotherapy patients" 등)은 조건에는
없다.

## 결함 6 — 중복 규칙

같은 조건을 다른 codeset id로 두 번 만든 규칙이 있다. 두 사이트 모두에서 `N`이 정확히 같다.
인원에는 영향이 없다.

| 시험 | 규칙 | 아주대 `N` (comparator) |
| --- | --- | --- |
| CARMELINA | `#11`과 `#14`(GLP-1·DPP-4·SGLT-2, `-7..0`). `#15 DPP-4 inhibitors`는 그 일부 | 34,211 / 34,211 |
| CAROLINA | `#3`과 `#10 Anti-diabetic medication` | 1,174 / 1,174 |
| EMPA-REG | `#8`과 `#18`(ALT·AST·ALP > 3×ULN) | 36,272 / 36,272 |

## 사이트 의견과 판정

| 아주대 의견 | 판정 | 분류 |
| --- | --- | --- |
| CARMELINA comparator `#2`: 인덱스가 당뇨 첫 진단일이라 구조적으로 거의 존재하지 않음, entry 확인 필요 | 맞다. comparator를 첫 T2DM 진단으로 진입시키는 설계는 note-031이 남은 항목으로 적었다(ADR-027 phase 2 미구현, 사람의 승인이 필요하다). 이 규칙에는 결함 2도 걸려 있다 | 설계(미결) + 추출 결함 |
| CARMELINA comparator `#13` UACR: 진단 이후 선별검사로 시행, entry 확인 필요 | 위와 같은 설계 문제다. `#13`은 `ANY`로, 해당 진단 기록 1회 이상 또는 UACR 측정 1회 이상(`-180..0`, 값 조건 없음)이면 통과한다. 이름에 있는 "Impaired renal function"의 기준값은 조건에 없다(note-031 남은 항목) | 설계(미결) |
| CARMELINA treatment `#2`: 87%가 배경약 기록 없음, 배경약 리스트 확인 필요 | 맞다. 리스트가 saxagliptin·dapagliflozin·empagliflozin이다 | 추출 결함(결함 2) |
| CAROLINA `#2` BMI: 기록이 적다, window를 늘려야 한다 | 기록이 적다는 것은 사이트 사정이다. 다만 gold 정의에서는 기록이 없어도 통과한다 | gold와 다름(결함 3) |
| CAROLINA `#3` 항당뇨약: 전체 기간으로 늘려도 1,414명, window 문제 아님 | 맞다. concept set이 두 약물이다 | 추출 결함(결함 2) |
| EMPA-REG treatment `#15`: 컨셉셋에 T2DM exclude 항목 없음 | 맞다. treatment 파일에만 없고, 그 때문에 `#2`와 `#15`를 함께 만족하는 사람이 없다 | 추출 결함(결함 1) |

## 확정하지 못한 것

- 결함 1을 고친 뒤 EMPA-REG treatment에서 `#15`를 통과할 인원. `% To-Gain`은 규칙을 뺐을 때의
  값이고, 고친 `cs29`에도 비(非)T2DM 당뇨 개념과 Hypoglycemia가 남는다.
- 아주대의 HbA1c·eGFR `unit_concept_id`. 결함 5는 개념이 있는데도 배제가 없었다는 결과에서 단위를
  후보로 남긴 것이다.
- ACHILLES 스냅샷은 2026-07-28 실행분이고, 이번 코호트를 돌린 CDM(`CDMPv538`, `DAMC_5.3.1_01`)과
  같은 시점인지 알 수 없다.
- 동아대 화면의 Atlas `Messages` 건수(CARMELINA 29/27, CAROLINA 53/53, EMPA-REG 19/18)는 보였지만
  내용은 받지 않았다.
- 결함 3의 gold 대조는 CAROLINA와 EMPA-REG의 BMI·HbA1c에 대해서만 했다. CARMELINA의 HbA1c 규칙은
  gold와 대조하지 않았다.

## 수정 내역 (2026-09-23 ~ 10-08, 브랜치 fix/0923-reply)

이번 발신 전 커밋 8개를 묶었다. "측정 결과"는 각 커밋 본문이 적은 수치를 그대로 옮긴
것이다. 스토어는 이미 빌드된 CIRCE 표현식을 캐시하므로, 이 여덜 커밋 중 어느 것도
재빌드(재export) 전에는 발송 대상 파일에 반영되지 않는다. 재빌드는 아직 하지
않았다. `b306088`은 이 분석 문서 자체를 쓴 커밋이라 표에서 뺐다.

| 커밋 | 고친 결함 | 바뀐 것 | 측정 결과 |
| --- | --- | --- | --- |
| `c588aa7` | 결함 1 | `entity_exception.description_stated_exception`이 설명문에 적힌 예외를 매퍼까지 전달; `circe_lint` 검사 (t) 추가(같은 테이블에서 ALL 경로로만 도달한 presence의 closure가 absence의 closure 안에 있으면 FAIL) | 검사 (t)는 `deliveries/2026-09-23`에서 `empa-reg_treatment`(#2 대 #15)만 FAIL, 나머지는 통과; `entity_exception`은 verify5 스토어에서 EMPA-REG 제외 #29/#30에서만 발동(3회 동일), "T2DM"은 201826으로 귀결 |
| `e0d2221` | 결함 1 (후속) | `entry_exclusion_repair`에 residual-after-exception 경로 추가 — description이 예외를 명시하고, 배제 집합에 이미 `isExcluded` 항목이 있고 그 closure가 entry closure와 겹치고, 잔여 겹침이 남을 때만 entry 항목을 미러링 | `deliveries/2026-09-23`·`2026-09-12`·gold 18개 파일 전체에서 새 경로를 타는 파일 없음; `2026-09-12`의 `empa-reg_comparator`는 기존 full-coverage 경로로 여전히 발동; 대조군(closure 밖 배제 항목, 배제 항목 없는 부분 겹침) 모두 declined |
| `26119e9` | 결함 2(배경약 규칙을 스킵) | `dose_stability.py`의 단일 술어(안정성 용어 + Drug 도메인 + 치료·복약·용량 용어)로 CARMELINA #7, CAROLINA #37·38·41을 식별; `_build_seeded_target_circe`가 `dose-stability-not-representable` 사유로 스킵; `verify_circe_delivery`가 그 사유를 스토어 행에서 술어로 재검사 | stub 빌드: CARMELINA 24 → 23 규칙, CAROLINA 26 → 24 규칙, 나머지 규칙·concept set 동일 |
| `d97397e` | 결함 4, 결함 5(eGFR) | `loinc_specimen.py`로 검사 concept set을 LOINC specimen·property·challenge 기준으로 재구성; 다수 LOINC 성분으로 analyte 결정, 시스템·property·challenge가 안 맞는 멤버 제거, 숫자 조건이 있으면 순환혈액 Qn 검사 추가; 게이트 (u) 추가 | 실제 매퍼 51개 Measurement seed x 2모드 x 3회, 독립 재서술 대비 불일치 0; EMPA-REG·CAROLINA mg/dL 혈당 집합이 세 사이트 모두 0 → 0 아님; EMPA-REG eGFR recall 0.2 → 1.0; CARMELINA UACR precision 1.000 유지; `deliveries/2026-09-23`에서 게이트(u)는 발송된 glucose·ALT/AST·LDL 집합 FAIL, CARMELINA ALP·EMPA-REG GFR(mL/min) WARN |
| `b1e18e6` | 결함 3 | `_convert_value_range_inclusions`가 숫자 조건을 가진 ALL 경로의 Measurement presence 규칙을 complement의 exactly 0으로 변환(Circe `bt`는 inclusive); LOINC property family로 단위를 확인 못 하면 변환 안 함; 검사 (v)(옛 presence 형식 FAIL), (q)(변환된 absence에서만 단위 없는 조건 예외) | stub 빌드에서 예측한 4개 규칙의 6개 항목만 정확히 변환, 나머지 동일. 알려진 한계: LEADER HbA1c(단위 미기재)는 변환 안 됨; BMI percentile 제거로 BMI recall 1.0 → 0.5 |
| `5d9bf6c` | 결함 6 | `restated_rules.py`의 단일 술어로, 역할별로 모은 ALL-only 규칙 중 CodesetId를 집합 내용으로 바꾼 뒤 동일한 것(identical)과 다른 규칙 결합의 한 성분인 것(implied)을 빌드 마지막 단계에서 합침; 합침마다 `_restatedRuleCollapse`에 기록, 게이트가 발송 파일에서 재도출 | stub 빌드: EMPA-REG 20 → 19 규칙(ALT/AST/ALP 재서술), CARMELINA 21 → 19 규칙, CAROLINA 변화 없음; 게이트(w)는 `2026-09-23`·`2026-09-12`의 CARMELINA comparator·treatment 모두 FAIL, gold 18개 파일은 0건 FAIL; 기준별 gold 평가 변화 없음 |
| `03717a8` | 결함 2(concept set 내용) | `drug_class_expander`가 ATC 상위 1건만 조회하던 것을 상위 5건까지 읽고 `AGENT2_ATC_DISTANCE_THRESHOLD` 안에서 성분 3개 이상인 첫 후보를 선택; `ExpressionBuilder._filter_overbroad`가 RxNorm·RxNorm Extension Ingredient를 500개 초과 하위개념 필터에서 제외 | verify5 스토어의 Drug class seed 37개(실제 매퍼, 3회씩, comparator·treatment 모두 결정적)에서 4개 seed가 A10으로 이동, 엉뚱한 계열로 가는 pick 없음, GLP-1 6/6과 SGLT-2 7/7 변화 없음; gold 대비 closure: DPP4 inhibitors recall 0.621 → 0.984(precision 1.000), CAROLINA any insulin 0.203 → 1.000, systemic glucocorticoid 0.010 → 0.998 |
| `907ab84` | 결함 2 관련(경로 배제) — 이 문서의 결함 2(CARMELINA·CAROLINA 배경약)와 다른 사례(CAROLINA systemic glucocorticoid, LEADER oral anti-diabetic drugs)에서 측정 | `_recommend_seeded_concept_set`이 표현식 항목을 복사한 뒤 `_apply_route_subtraction`이 그 복사본에만 `isExcluded` 형태를 추가하고 원본 표현식을 반환하던 결함을 수정 — 복사본을 표현식 자신의 항목 리스트로 바꿔 반환 표현식·캐시 항목·domain 해석이 모두 배제를 보게 함 | 실제 매퍼 3회(prefetch·direct)에서 경로 배제 카운트가 로그 수치와 일치(systemic corticosteroid 779, oral anti-diabetic drugs 191, inhaled insulin 16), 포함 항목 변화 없음; gold 대비 closure: CAROLINA systemic glucocorticoid precision 0.273 → 0.561(recall 0.998), LEADER oral anti-diabetic drugs precision 0.665 → 0.947, recall 0.995 → 0.937(recall 하락은 한계로 기록, gold는 그대로 둠) |

## 한계와 미해결

- LEADER 경구 항당뇨약(oral anti-diabetic drugs): gold의 "OADs and GLP-1 only" 집합에
  주사형 GLP-1 RA 제형이 들어 있어 프로토콜의 "oral"과 어긋난다. precision 0.665 →
  0.947, recall 0.995 → 0.937. gold는 결정에 따라 그대로 둔다(커밋 `907ab84`).
- BMI percentile 코드를 제거한 BMI absence 변환: gold 대비 BMI recall 1.0 → 0.5(커밋
  `b1e18e6`).
- LEADER HbA1c `gte 7`은 단위가 적혀 있지 않아 변환되지 않는다(커밋 `b1e18e6`).
- CAROLINA mmol/L 혈당 기준은 세 사이트 모두 계속 0이다. 사이트에 Substance
  Concentration 단위의 혈당 측정 행이 없다.
- CAROLINA fasting glucose(cs41)는 recall 0.000 → 1.000, precision 0.000 → 0.021이다. gold
  `'[TROY lab] Fasting glucose'`는 코드 하나를 보유한다. 출처: d97397e 검증 실행의 gold 대조
  (`scripts/conceptset_overlap_eval.py` closure, 실제 매퍼 direct#1).
- LEADER HbA1c는 `conceptset_overlap_eval`에서 짝짓기 오류가 있다(gold 코드는 집합에
  그대로 있다).
- 기준 캐시(criterion cache)에는 코드 버전이 없다. `907ab84` 이전에 쓰인 항목은 TTL이
  끝날 때까지 예전 표현식을 그대로 돌려준다. TTL 기본값(`CRITERION_CACHE_TTL_HOURS`
  24시간)은 `src/agents/agent2/criterion_cache.py`의 현재 코드에서 확인한 것이고,
  커밋 본문이나 계획 문서에는 적혀 있지 않다.
- 여러 검증 실행이 재사용한 stub 매퍼가 스토어에서 매핑되지 않은 기준에 임의 개념을
  만들어 넣고 있었다. 수정 전후 비교는 같은 stub을 썼으므로 유효하지만, 매핑되지 않은
  기준(EMPA-REG 제외 #22·#33, CARMELINA 포함 #3·제외 #35·#44, CAROLINA 제외 #33·#69)에
  대한 결론은 실제 매퍼 재빌드로 다시 확인한다.
- 계획 문서에 남은 미결 항목: 7번 약물 계열 매핑 정밀도 중 D(ATC 문서 텍스트를 다른
  vocabulary의 같은 분류 이름으로 보강해 0.75 기준을 다시 맞추는 것)와 B+C(상위
  분류를 포함하는 더 구체적인 하위 분류 선택 규칙 + 복합제 성분만으로 닿는 성분
  제외)는 합의만 됐고 구현 전이다. 8번 UMLS MRREL 관계 데이터 부재(M4, 첫 단계가
  서버에 없어 디버그 로그만 남기고 조용히 넘어감)는 데이터를 배포할지 없으면 실패로
  드러낼지 결정이 필요하다. 범위 밖에서 CARMELINA `ALT (SGPT)` concept set에 AST 코드
  `3013721`이 섞여 있는 것을 발견했다. 추출 단계에서 PLATO 항혈소판제 기준이 새로
  생겼다. 내보내기 단계의 range_disjunction 수정이 값 범위 변환 뒤 다시 presence로
  되돌리지 않는지는 재빌드 때 확인해야 한다.
