# ACHILLES 스냅샷 feasibility 예측 vs 실제 ATLAS 코호트 생성 — 격차 분석

**작성일** 2026-09-05
**대상** CARMELINA / CAROLINA / EMPA-REG × treatment·comparator (CIRCE 6종, `artemis/output/circe_be/2026-08-31/`)
**사이트** 아주대·동아대·계명대 ACHILLES 스냅샷 (`artemis/data/site_snapshots/`, run date 2026-07-28)
**실측** 동아대 ATLAS `DAMC_5.3.1_01` 생성분(2026-09-04, cohort #19–#24, rule별 리포트 포함), 아주대 생성 총계
**데이터·재현** `artemis/output/site_gap/2026-09-05/` (README.md에 전 명령 수록)

---

## 결론 먼저

**Entry 모집단 예측은 잘 맞고, rule 단위 예측은 크게 빗나가며, 빗나간 이유의 대부분은 ACHILLES의 한계가 아니라 병원에 넘어간 코호트 정의 파일 자체의 결함이다.** 동아대에서 entry 모집단은 관측치의 1.19–2.36배 안에 들어왔고(EMPA-REG treatment는 0을 정확히 맞혔다), rule 단위로는 리포트가 있는 117개 중 50개가 "ACHILLES는 있다는데 ATLAS는 0" 이었다. 그런데 그 50개 중 48개는 예측이 틀린 게 아니다. 다중 개념 제외 rule이 전부 `Type: ANY`로 작성되어 `ANY(NOT A, NOT B, …) = NOT(A AND B AND …)`가 되었고, 나열된 개념을 **전부 동시에** 가진 사람만 제외한다. 실제로 그런 rule 53개 중 52개가 정확히 100.00%에서 멈췄고, 나머지 하나(`carolina_treatment` #22)는 99.99% — 5개 개념을 모두 가진 단 1명만 걸러졌다. 전체 137개 rule 중 62개(45%)가 이 상태로, 사실상 아무도 거르지 못한다.

**단, 이 62개는 현재 파이프라인의 결함이 아니다 — 반면 `BI 10773` entry 결함은 현재 것이다(§6).** 납품 파일 6개는 컨테이너 scratch 산출물과 md5가 일치하고, 그 생성 스크립트 3종은 `TTE_STORE_PATH` 환경변수에 밀려 **의도한 `tte_six_post007_full` store 대신 서비스의 live 기본 store를 읽었다.** live store의 rule 구조(20/20/27개, no-op 9/9/13개)가 납품본에 그대로 옮겨와 있고, 정작 쓰려던 store에는 no-op이 사실상 없으며(0/0/1) EMPA-REG entry도 empagliflozin(45774751)으로 이미 고쳐져 있다. 관련 수정은 전부 납품일 이전에 머지되었다. 실제로 store를 명시해 재-export해 보면 no-op은 62개 → 2개로 사라진다 — **다만 수정 store 자체가 EMPA-REG·CAROLINA에서 rule↔개념집합 연결이 어긋나 있어(§6-2), 재-export 원본으로 바로 쓸 수 있는 것은 CARMELINA뿐이다.** **그러나 `BI 10773` 쓰레기 entry 집합은 재-export해도 그대로 재생산된다** — export 경로가 store의 개념집합을 쓰지 않고 arm 이름 `"BI 10773"`을 그때그때 다시 해석하기 때문이며, 이쪽은 낡은 artifact가 아니라 **현행 코드의 결함**이다(§6-1). 다만 수정된 store는 rule 집합이 더 크고 다르므로(EMPA-REG 20→29, CAROLINA 27→37) **재-export 후 인원은 이 분석으로 예측할 수 없고 사이트 재실행이 필요하다.** 아래 예측 품질 결론(entry 적중, rule 오차의 no-op 지배, 거짓음성 0건)은 실제로 병원에서 돌아간 정의를 대상으로 한 것이므로 그대로 유효하다.

반대 방향 오류, 즉 "ACHILLES가 0이라 했는데 실제로는 있었다"는 **117개 중 0건**이다. 예측이 0을 말할 때는 믿어도 된다는 뜻이고, EMPA-REG treatment가 그 사례다 — entry 개념집합 `BI 10773`(codeset 57)에 empagliflozin(45774751)이 아예 없어 세 병원 모두 0개 매칭이며 ATLAS Total Events도 0이었다.

세 코호트가 죽은 지점은 각각 다르다. CARMELINA는 rule #10(0.30% 통과)과 #3 BMI(3.91%), EMPA-REG comparator는 rule #11 `Dietary regimen + Exercise regimen` 하나가 단독으로 94,164 → 0을 만들었으며, CAROLINA는 rule #3 BMI(5.99% / 10.21%)가 최대 절단자다. 값 제약이 걸린 Measurement rule이 반복해서 상위에 오는 것이 공통 패턴이고, 이는 ACHILLES가 원리적으로 볼 수 없는 축이다.

마지막으로 **아주대 스냅샷은 동아대와 같은 척도가 아니다.** 아주대 파일의 Outpatient Visit이 28,656,713인데 같은 파일의 Birth date는 8,055,390이다. 사람 수라면 방문 보유 인원이 전체 인원을 넘을 수 없으므로 모순이며, 아주대 수치는 record 척도로 보아야 한다. 따라서 아주대–동아대 절대값 비교는 성립하지 않고, 개념 보유 여부와 coverage만 비교 가능하다.

---

## 1. Entry 모집단 — 예측 vs 실제

PrimaryCriteria는 세 코호트 모두 `ObservationWindow.PriorDays = 365`, `PrimaryCriteriaLimit = First`다. 즉 ATLAS Total Events는 "선행 관찰기간 365일을 만족하는 사람 1인당 첫 사건"이며, ACHILLES의 "해당 개념을 언젠가 보유한 사람 수"보다 구조적으로 작아야 한다.

| 사이트 | cohort | entry domain | 개념집합 | closure | 사이트 매칭 | 사이트 보유 상한(합) | 하한(최대) | ATLAS Total Events | 상한/실측 | 하한/실측 |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| 동아대 | carmelina_{tx,cp} | ConditionOccurrence | Type 2 Diabetes Mellitus | 84 | 5 | 111,843 | 109,292 | 94,164 | 1.19 | 1.16 |
| 동아대 | empa-reg_comparator | ConditionOccurrence | Type 2 Diabetes Mellitus | 84 | 5 | 111,843 | 109,292 | 94,164 | 1.19 | 1.16 |
| 동아대 | carolina_treatment | DrugEra | linagliptin | 301 | 4 | 12,304 | 8,590 | 7,317 | 1.68 | 1.17 |
| 동아대 | carolina_comparator | DrugEra | glimepiride | 3,422 | 11 | 33,023 | 20,970 | 14,000 | 2.36 | 1.50 |
| 동아대 | empa-reg_treatment | DrugEra | BI 10773 | 8 | **0** | **0** | 0 | **0** | 정확 | 정확 |
| 아주대 | carmelina_{tx,cp} | ConditionOccurrence | Type 2 Diabetes Mellitus | 84 | 6 | 803,569 | 800,323 | (미보고) | — | — |
| 아주대 | carolina_treatment | DrugEra | linagliptin | 301 | 6 | 199,387 | 177,891 | (미보고) | — | — |
| 아주대 | carolina_comparator | DrugEra | glimepiride | 3,422 | 9 | 691,260 | 465,499 | (미보고) | — | — |
| 아주대 | empa-reg_treatment | DrugEra | BI 10773 | 8 | **0** | **0** | 0 | (미보고) | — | — |
| 계명대 | carmelina_{tx,cp} | ConditionOccurrence | Type 2 Diabetes Mellitus | 84 | 4 | 12,874 | 12,802 | (ATLAS 없음) | — | — |
| 계명대 | carolina_treatment | DrugEra | linagliptin | 301 | 6 | 13,940 | 10,001 | (ATLAS 없음) | — | — |
| 계명대 | carolina_comparator | DrugEra | glimepiride | 3,422 | 8 | 6,503 | 3,627 | (ATLAS 없음) | — | — |

**해석**

- **T2DM entry (1.19배).** 111,843 → 94,164의 차이 15.8%는 `PriorDays 365` + `First` 두 제약으로 설명된다. 최근 유입 환자와 관찰기간이 짧은 환자가 빠지는 몫이다. 추가 설명이 필요 없는 수준의 일치다.
- **DrugEra entry (1.17–2.36배).** ACHILLES에 drug_era(analysis 900)가 없어 analysis 700(drug_exposure)의 **제품 수준** 개념을 `concept_ancestor`로 성분에 롤업해 예측했다. 동아대 linagliptin은 상한 12,304 / 하한 8,590 대 실측 7,317로, 하한 기준 1.17배다. 성분 개념(40239216)은 세 병원 어디에도 없고 제품 개념(21115577 등)만 있으므로, 롤업 없이 성분 ID로 예측했다면 세 병원 모두 0이 나왔을 것이다. **롤업이 이 예측을 성립시킨 유일한 이유다.**
- **BI 10773 = 0, 정확히 적중.** codeset 57의 5개 항목은 859730 bictegravir/emtricitabine/tenofovir, 1254065 CHF-6366 대사체, 1201518 elexacaftor/ivacaftor/tezacaftor 팩, 1201447 vilobelimab, 702171 bictegravir 조합으로 **empagliflozin이 하나도 없다**. closure 8개 중 세 병원 매칭 0개, ATLAS Total Events 0. 데이터 문제가 아니라 개념집합 명명 결함이며, ACHILLES 스냅샷만으로 생성 전에 잡을 수 있었던 사례다. **이 결함은 수정된 store에서 재-export해도 그대로 재생산된다 — §6-1.**
- **아주대.** entry 개념은 T2DM·linagliptin·glimepiride 모두 존재한다(매칭 6/6/9개). 따라서 아주대의 CARMELINA 0/0과 EMPA-REG comparator 0은 entry가 비어서가 아니라 inclusion rule 단계에서 죽은 것이다. EMPA-REG treatment 0은 동아대와 같은 이유(BI 10773)로 entry 단계에서 죽었다. 절대값(803,569 등)은 record 척도이므로 인원으로 읽지 말 것(§한계).

---

## 2. 동아대 rule별 격차

`site_persons_upper/lower`는 **한 가지 양**의 상·하한이다: 그 개념집합 중 하나 이상을 CDM 어디에서든 보유한 distinct person 수. ATLAS `N satisfied`의 경계가 아니다 — ATLAS는 이미 선택된 entry 코호트 안에서, index 기준 window 안에서, 값 필터를 통과한 event만 센다. 모집단이 다르므로 하한이 실측을 넘는 일은 48/48건 모두에서 발생하며 이는 정상이다. **두 값의 거리가 이 절의 주제다.**

분류: **(a)** 예측 없음·실측 없음 / **(b)** 예측 있음·실측 ~0 / **(c)** 개념 부재로 absence rule 100% 충족 / **(d)** 양쪽 다 존재 / **(e)** 예측 0인데 실측 존재(=위험한 거짓음성)
`실측 보유` = presence rule이면 `N`, absence rule이면 `Total − N`. `배율` = 사이트 보유 상한 ÷ 실측 보유.

#### cohort #19 `carmelina_comparator` — Total Events 94,164 / People 5

| # | rule | 극성 | domain | 값제약 | window(일) | 사이트 보유 상한 | 하한 | ATLAS N | % | to-gain | 실측 보유 | 배율 | 분류 | 식결함 |
|---:|---|---|---|:-:|---|---:|---:|---:|---:|---:|---:|---:|:-:|---|
| 1 | Age criteria | — | Demo |  | — | — | — | 92,070 | 97.78 | — | 92,070 | — | — |  |
| 2 | Type 2 Diabetes Mellitus | present | Cond |  | 전기간 | 111,843 | 109,292 | 94,164 | 100.0 | — | 94,164 | 1.19 | (d) |  |
| 3 | Body Mass Index | present | Meas | Y | [-180,0] | 87,807 | 87,807 | 3,681 | 3.91 | 0.01 | 3,681 | 23.85 | (d) |  |
| 4 | Hemoglobin A1c/Hemoglobin.total in Blood | present | Meas | Y | [-180,0] | 211,233 | 211,233 | 9,023 | 9.58 | — | 9,023 | 23.41 | (d) |  |
| 5 | Hemoglobin A1c/Hemoglobin.total in Blood | absence | Meas | Y | [-180,0] | 211,233 | 211,233 | 93,128 | 98.9 | — | 1,036 | 203.89 | (d) |  |
| 6 | Estimated Glomerular Filtration Rate | absence | Meas | Y | [-180,0] | 0 | 0 | 94,164 | 100.0 | — | 0 | — | (c) |  |
| 7 | Participation in another trial | absence | Obs |  | [-60,0] | 0 | 0 | 94,164 | 100.0 | — | 0 | — | (c) |  |
| 8 | Type 1 Diabetes Mellitus | absence | Cond |  | 전기간 | 6,179 | 6,163 | 91,902 | 97.6 | — | 2,262 | 2.73 | (d) |  |
| 9 | Albuminuria and previous macrovascular disease + Impaire | present | Cond|Meas |  | [-365,0] | 41,428 | 28,303 | 5,030 | 5.34 | 0.01 | 5,030 | 8.24 | (d) | ANY union |
| 10 | Drug-naïve + Pre-treated with antidiabetic medication | present | Drug|Obs |  | [-365,0] | 6,283 | 3,201 | 287 | 0.3 | 0.07 | 287 | 21.89 | (d) | ANY union |
| 11 | Metformin + Sulfonylureas + DPP-4 Inhibitors + GLP-1 Rec | present | Drug |  | [-56,0] | 156,141 | 20,010 | 5,478 | 5.82 | — | 5,478 | 28.5 | (d) | ANY union |
| 12 | ALT >= 3 x ULN + AST >= 3 x ULN + AP >= 3 x ULN | absence | Meas | Y | [-365,0] | 1,334,353 | 667,227 | 94,164 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 13 | Myocardial Infarction + Unstable Angina | absence | Cond |  | [-60,0] | 31,905 | 12,651 | 94,164 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 14 | Gastric Bypass Surgery + Sleeve Gastrectomy + Adjustable | absence | Proc |  | [-9999,365] | 409 | 353 | 94,164 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 15 | Alcohol Abuse + Opioid Abuse + Cannabis Abuse + Cocaine  | absence | Cond |  | 전기간 | 22,634 | 6,161 | 94,164 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 16 | Drug Allergy + Food Allergy + Environmental Allergy + Co | absence | Cond|Obs |  | 전기간 | 2,604 | 1,238 | 94,164 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 17 | Life expectancy < 5 years due to advanced cancer + Life  | absence | Cond |  | 전기간 | 30,612 | 11,546 | 94,164 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 18 | Coronary artery bypass grafting + Percutaneous coronary  | absence | Proc |  | [-60,365] | 0 | 0 | 94,164 | 100.0 | — | 0 | — | (c) | **ANY/absence 무력** |
| 19 | Stroke + Transient Ischemic Attack | absence | Cond |  | [-90,0] | 8,629 | 7,924 | 94,164 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 20 | GLP-1 receptor agonists + DPP-4 inhibitors + SGLT-2 inhi | absence | Drug |  | [-365,0] | 84,592 | 20,010 | 94,164 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 21 | No linagliptin | absence | Drug |  | [-180,365] | 12,304 | 8,590 | 91,852 | 97.54 | 0.0 | 2,312 | 5.32 | (d) |  |

#### cohort #21 `carolina_comparator` — Total Events 14,000 / People 44

| # | rule | 극성 | domain | 값제약 | window(일) | 사이트 보유 상한 | 하한 | ATLAS N | % | to-gain | 실측 보유 | 배율 | 분류 | 식결함 |
|---:|---|---|---|:-:|---|---:|---:|---:|---:|---:|---:|---:|:-:|---|
| 1 | Age between 40 and 85 years | — | Demo |  | — | — | — | 13,641 | 97.44 | — | 13,641 | — | — |  |
| 2 | Type 2 Diabetes Mellitus | present | Cond |  | 전기간 | 109,326 | 109,292 | 4,029 | 28.78 | 0.06 | 4,029 | 27.13 | (d) |  |
| 3 | Body Mass Index | present | Meas | Y | [-180,0] | 87,807 | 87,807 | 839 | 5.99 | 1.64 | 839 | 104.66 | (d) |  |
| 4 | Hemoglobin A1c/Hemoglobin.total in Blood | present | Meas | Y | [-180,0] | 211,233 | 211,233 | 8,366 | 59.76 | — | 8,366 | 25.25 | (d) |  |
| 5 | Hemoglobin A1c/Hemoglobin.total in Blood | absence | Meas | Y | [-180,0] | 211,233 | 211,233 | 10,384 | 74.17 | — | 3,616 | 58.42 | (d) |  |
| 6 | Hemoglobin A1c/Hemoglobin.total in Blood | present | Meas | Y | [-180,0] | 211,233 | 211,233 | 8,366 | 59.76 | — | 8,366 | 25.25 | (d) |  |
| 7 | Hemoglobin A1c/Hemoglobin.total in Blood | absence | Meas | Y | [-180,0] | 211,233 | 211,233 | 8,229 | 58.78 | 0.38 | 5,771 | 36.6 | (d) |  |
| 8 | Type 1 Diabetes Mellitus | absence | Cond |  | 전기간 | 6,179 | 6,163 | 13,772 | 98.37 | 0.01 | 228 | 27.1 | (d) |  |
| 9 | Metabolic Acidosis | absence | Cond |  | 전기간 | 1,820 | 521 | 13,910 | 99.36 | 0.01 | 90 | 20.22 | (d) |  |
| 10 | Congestive Heart Failure | absence | Cond |  | 전기간 | 12,140 | 10,391 | 13,508 | 96.49 | 0.01 | 492 | 24.67 | (d) |  |
| 11 | Systemic Corticoids | absence | Drug |  | 전기간 | 53,848 | 14,310 | 12,793 | 91.38 | 0.06 | 1,207 | 44.61 | (d) |  |
| 12 | Clinical Trial Participation | absence | Proc |  | [-60,0] | 0 | 0 | 14,000 | 100.0 | — | 0 | — | (c) |  |
| 13 | Pre-existing cardiovascular disease + Specified diabetes | present | Cond |  | [-365,0] | 266,081 | 35,575 | 6,569 | 46.92 | 0.09 | 6,569 | 40.51 | (d) | ANY union |
| 14 | Biguanides + Sulfonylureas + Thiazolidinediones + DPP-4  | present | Drug |  | [-56,0] | 99,915 | 20,010 | 6,397 | 45.69 | 0.34 | 6,397 | 15.62 | (d) | ANY union |
| 15 | Chronic Kidney Disease + Acute Kidney Injury + Nephropat | absence | Cond |  | 전기간 | 41,133 | 14,087 | 14,000 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 16 | rosiglitazone + pioglitazone + GLP-1 analogue/agonists + | absence | Drug |  | [-365,0] | 17,627 | 4,941 | 14,000 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 17 | Myocardial Infarction + Unstable Angina | absence | Cond |  | [-42,0] | 31,905 | 12,651 | 14,000 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 18 | Acute Hepatitis + Acute Liver Failure + Drug-Induced Liv | absence | Cond |  | 전기간 | 36,643 | 6,392 | 14,000 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 19 | Alcohol Abuse + Opioid Abuse + Cannabis Abuse + Cocaine  | absence | Cond |  | 전기간 | 1,708 | 1,257 | 14,000 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 20 | Levothyroxine + Liothyronine + Liotrix + Thyroid Desicca | absence | Drug |  | 전기간 | 30,805 | 8,825 | 14,000 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 21 | Galactosemia + Galactokinase deficiency + Galactose epim | absence | Cond |  | 전기간 | 22 | 22 | 14,000 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 22 | Allergic Rhinitis + Asthma + Anaphylaxis + Urticaria + C | absence | Cond |  | 전기간 | 141,662 | 49,473 | 14,000 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 23 | Coronary Artery Bypass Grafting + Percutaneous Coronary  | absence | Proc |  | [-180,0] | 1,268 | 574 | 14,000 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 24 | Gastric Bypass Surgery + Sleeve Gastrectomy + Adjustable | absence | Proc |  | 전기간 | 409 | 353 | 14,000 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 25 | Stroke + Transient Ischemic Attack | absence | Cond |  | [-90,0] | 3,021 | 2,182 | 14,000 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 26 | Treatment with Orlistat + Treatment with Phentermine + T | absence | Drug |  | [-90,0] | 14,745 | 3,840 | 14,000 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 27 | Diabetes Mellitus with Hyperglycemia + Hyperglycemia due | absence | Cond |  | 전기간 | 0 | 0 | 14,000 | 100.0 | — | 0 | — | (c) | **ANY/absence 무력** |

#### cohort #22 `carolina_treatment` — Total Events 7,317 / People 60

| # | rule | 극성 | domain | 값제약 | window(일) | 사이트 보유 상한 | 하한 | ATLAS N | % | to-gain | 실측 보유 | 배율 | 분류 | 식결함 |
|---:|---|---|---|:-:|---|---:|---:|---:|---:|---:|---:|---:|:-:|---|
| 1 | Age between 40 and 85 years | — | Demo |  | — | — | — | 7,219 | 98.66 | — | 7,219 | — | — |  |
| 2 | Type 2 Diabetes Mellitus | present | Cond |  | 전기간 | 109,326 | 109,292 | 4,998 | 68.31 | 0.1 | 4,998 | 21.87 | (d) |  |
| 3 | Body Mass Index | present | Meas | Y | [-180,0] | 87,807 | 87,807 | 747 | 10.21 | 5.25 | 747 | 117.55 | (d) |  |
| 4 | Hemoglobin A1c/Hemoglobin.total in Blood | present | Meas | Y | [-180,0] | 211,233 | 211,233 | 5,128 | 70.08 | — | 5,128 | 41.19 | (d) |  |
| 5 | Hemoglobin A1c/Hemoglobin.total in Blood | absence | Meas | Y | [-180,0] | 211,233 | 211,233 | 5,591 | 76.41 | — | 1,726 | 122.38 | (d) |  |
| 6 | Hemoglobin A1c/Hemoglobin.total in Blood | present | Meas | Y | [-180,0] | 211,233 | 211,233 | 5,128 | 70.08 | — | 5,128 | 41.19 | (d) |  |
| 7 | Hemoglobin A1c/Hemoglobin.total in Blood | absence | Meas | Y | [-180,0] | 211,233 | 211,233 | 4,284 | 58.55 | 0.48 | 3,033 | 69.64 | (d) |  |
| 8 | Type 1 Diabetes Mellitus | absence | Cond |  | 전기간 | 6,179 | 6,163 | 6,877 | 93.99 | 0.07 | 440 | 14.04 | (d) |  |
| 9 | Metabolic Acidosis | absence | Cond |  | 전기간 | 1,820 | 521 | 7,200 | 98.4 | 0.01 | 117 | 15.56 | (d) |  |
| 10 | Congestive Heart Failure | absence | Cond |  | 전기간 | 12,140 | 10,391 | 6,512 | 89.0 | 0.1 | 805 | 15.08 | (d) |  |
| 11 | Systemic Corticoids | absence | Drug |  | 전기간 | 53,848 | 14,310 | 6,445 | 88.08 | 0.08 | 872 | 61.75 | (d) |  |
| 12 | Clinical Trial Participation | absence | Proc |  | [-60,0] | 0 | 0 | 7,317 | 100.0 | — | 0 | — | (c) |  |
| 13 | Pre-existing cardiovascular disease + Specified diabetes | present | Cond |  | [-365,0] | 266,081 | 35,575 | 5,713 | 78.08 | 0.16 | 5,713 | 46.57 | (d) | ANY union |
| 14 | Biguanides + Sulfonylureas + Thiazolidinediones + DPP-4  | present | Drug |  | [-56,0] | 99,915 | 20,010 | 4,129 | 56.43 | 0.64 | 4,129 | 24.2 | (d) | ANY union |
| 15 | Chronic Kidney Disease + Acute Kidney Injury + Nephropat | absence | Cond |  | 전기간 | 41,133 | 14,087 | 7,317 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 16 | rosiglitazone + pioglitazone + GLP-1 analogue/agonists + | absence | Drug |  | [-365,0] | 17,627 | 4,941 | 7,317 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 17 | Myocardial Infarction + Unstable Angina | absence | Cond |  | [-42,0] | 31,905 | 12,651 | 7,317 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 18 | Acute Hepatitis + Acute Liver Failure + Drug-Induced Liv | absence | Cond |  | 전기간 | 36,643 | 6,392 | 7,317 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 19 | Alcohol Abuse + Opioid Abuse + Cannabis Abuse + Cocaine  | absence | Cond |  | 전기간 | 1,708 | 1,257 | 7,317 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 20 | Levothyroxine + Liothyronine + Liotrix + Thyroid Desicca | absence | Drug |  | 전기간 | 30,805 | 8,825 | 7,317 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 21 | Galactosemia + Galactokinase deficiency + Galactose epim | absence | Cond |  | 전기간 | 22 | 22 | 7,317 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 22 | Allergic Rhinitis + Asthma + Anaphylaxis + Urticaria + C | absence | Cond |  | 전기간 | 141,662 | 49,473 | 7,316 | 99.99 | — | 1 | 141662.0 | (b) | **ANY/absence 무력** |
| 23 | Coronary Artery Bypass Grafting + Percutaneous Coronary  | absence | Proc |  | [-180,0] | 1,268 | 574 | 7,317 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 24 | Gastric Bypass Surgery + Sleeve Gastrectomy + Adjustable | absence | Proc |  | 전기간 | 409 | 353 | 7,317 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 25 | Stroke + Transient Ischemic Attack | absence | Cond |  | [-90,0] | 3,021 | 2,182 | 7,317 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 26 | Treatment with Orlistat + Treatment with Phentermine + T | absence | Drug |  | [-90,0] | 14,745 | 3,840 | 7,317 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 27 | Diabetes Mellitus with Hyperglycemia + Hyperglycemia due | absence | Cond |  | 전기간 | 0 | 0 | 7,317 | 100.0 | — | 0 | — | (c) | **ANY/absence 무력** |

#### cohort #23 `empa-reg_comparator` — Total Events 94,164 / People 0

| # | rule | 극성 | domain | 값제약 | window(일) | 사이트 보유 상한 | 하한 | ATLAS N | % | to-gain | 실측 보유 | 배율 | 분류 | 식결함 |
|---:|---|---|---|:-:|---|---:|---:|---:|---:|---:|---:|---:|:-:|---|
| 1 | Age >= 18 years | — | Demo |  | — | — | — | 92,070 | 97.78 | — | 92,070 | — | — |  |
| 2 | Type 2 Diabetes Mellitus | present | Cond |  | 전기간 | 111,843 | 109,292 | 94,164 | 100.0 | — | 94,164 | 1.19 | (d) |  |
| 3 | Body Mass Index | present | Meas | Y | [-180,0] | 87,807 | 87,807 | 3,681 | 3.91 | — | 3,681 | 23.85 | (d) |  |
| 4 | Hemoglobin A1c/Hemoglobin.total in Blood | present | Meas | Y | [-180,0] | 211,233 | 211,233 | 6,294 | 6.68 | — | 6,294 | 33.56 | (d) |  |
| 5 | Hemoglobin A1c/Hemoglobin.total in Blood | absence | Meas | Y | [-180,0] | 211,233 | 211,233 | 93,128 | 98.9 | — | 1,036 | 203.89 | (d) |  |
| 6 | Glomerular Filtration Rate | absence | Meas | Y | [-180,0] | 0 | 0 | 94,164 | 100.0 | — | 0 | — | (c) |  |
| 7 | Participation in another trial | absence | Obs |  | [-30,0] | 0 | 0 | 94,164 | 100.0 | — | 0 | — | (c) |  |
| 8 | Systemic steroids | absence | Drug |  | [-365,0] | 53,848 | 14,310 | 92,920 | 98.68 | — | 1,244 | 43.29 | (d) |  |
| 9 | Glucose | absence | Meas | Y | [-180,0] | 135 | 135 | 94,164 | 100.0 | — | 0 | — | (b) |  |
| 10 | Hypertension + Type 2 Diabetes Mellitus + Hyperlipidemia | present | Cond|Obs |  | 전기간 | 356,834 | 137,247 | 94,164 | 100.0 | — | 94,164 | 3.79 | (d) | ANY union |
| 11 | Dietary regimen + Exercise regimen | present | Obs |  | [-365,0] | 2 | 2 | 0 | 0.0 | 0.88 | 0 | — | (b) | ANY union |
| 12 | Acute coronary syndrome + Stroke + Transient ischemic at | absence | Cond |  | [-60,0] | 27,054 | 9,274 | 94,164 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 13 | Alcohol abuse + Drug abuse | absence | Obs |  | [-90,0] | 0 | 0 | 94,164 | 100.0 | — | 0 | — | (c) | **ANY/absence 무력** |
| 14 | Uncontrolled Hyperthyroidism + Uncontrolled Hypothyroidi | absence | Cond |  | 전기간 | 6,982 | 1,337 | 94,164 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 15 | Gastric Bypass Surgery + Sleeve Gastrectomy + Adjustable | absence | Proc |  | [-730,0] | 409 | 353 | 94,164 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 16 | Anemia + Leukopenia + Thrombocytopenia + Hemolytic anemi | absence | Cond |  | 전기간 | 15,574 | 2,938 | 94,164 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 17 | ALT > 3x ULN + AST > 3x ULN + Alkaline phosphatase > 3x  | absence | Meas | Y | [-180,0] | 667,126 | 667,126 | 94,164 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 18 | Medical history of breast cancer within the last 5 years | absence | Cond |  | [-1825,0] | 81,081 | 9,063 | 94,164 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 19 | Cardiac surgery + Angioplasty | absence | Proc |  | [-90,0] | 4,887 | 3,142 | 94,164 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 20 | Treatment with Orlistat + Treatment with Phentermine + T | absence | Drug |  | [-90,0] | 9,114 | 2,084 | 94,164 | 100.0 | — | 0 | — | (b) | **ANY/absence 무력** |
| 21 | No BI 10773 | absence | Drug |  | [-180,365] | 0 | 0 | 94,164 | 100.0 | — | 0 | — | (c) |  |

`carmelina_treatment`(#20)는 rule 1–20이 comparator와 N·% 모두 동일하고, rule 21만 `linagliptin` presence로 바뀌어 N=2,312(2.46%, to-gain 0.01) — 즉 사이트 보유 상한 12,304 대비 배율 5.32, 분류 (d)다. `empa-reg_treatment`(#24)는 Total Events 0이라 rule별 리포트가 성립하지 않는다(전 rule 0/0.00%).

### 2-1. 코호트를 실제로 자른 rule (ATLAS N·to-gain 기준)

| cohort | Total → People | 1위 | 2위 | 3위 |
|---|---|---|---|---|
| #19 carmelina_comparator | 94,164 → 5 | #10 Drug-naïve+Pre-treated **287 (0.30%)** | #3 Body Mass Index 3,681 (3.91%) | #9 Albuminuria+Impaired renal 5,030 (5.34%) |
| #20 carmelina_treatment | 94,164 → 1 | #10 동일 **287 (0.30%)** | #21 linagliptin 2,312 (2.46%) | #3 Body Mass Index 3,681 (3.91%) |
| #21 carolina_comparator | 14,000 → 44 | #3 Body Mass Index **839 (5.99%)** | #2 Type 2 Diabetes Mellitus 4,029 (28.78%) | #14 항당뇨 7종 6,397 (45.69%) |
| #22 carolina_treatment | 7,317 → 60 | #3 Body Mass Index **747 (10.21%)** | #14 항당뇨 7종 4,129 (56.43%) | #7 HbA1c 4,284 (58.55%) |
| #23 empa-reg_comparator | 94,164 → 0 | #11 Dietary+Exercise regimen **0 (0.00%)** | #3 Body Mass Index 3,681 (3.91%) | #4 HbA1c 6,294 (6.68%) |

`to-gain`(그 rule만 제거했을 때 얻는 인원 비율)이 가장 큰 곳이 곧 단일 최대 병목이다.

- **EMPA-REG comparator #11 = 단독 사망 원인.** to-gain 0.88% × 94,164 ≈ **829명**. 이 rule 하나만 완화하면 0 → 약 829명이 된다. codeset 12(Dietary regimen 4개) + 13(Exercise regimen 31개), 총 35항목의 descendant closure 532개를 세 병원 **전 analysis(400/600/700/800/1800)** 에 대조한 결과 매칭은 단 하나 — 42872393 `Inappropriate diet and eating habits`(analysis 800)로 아주대 14, 동아대 2, 계명대 0. 생활습관 사실을 이 병원들은 구조화 개념으로 기록하지 않는다.
- **CAROLINA #3 BMI.** to-gain 1.64%(comparator) / **5.25%**(treatment). treatment 기준 7,317 × 5.25% ≈ 384명. BMI closure 9개 중 세 병원 모두 3038553 하나만 존재하고, rule은 `ValueAsNumber ≤ 45 kg/m²` + Unit 9531 + window [-180, 0]을 요구한다. 값·단위·창 셋 다 ACHILLES가 못 보는 축이다.
- **CARMELINA #10 (0.30%).** `Drug-naïve`(Observation codeset 8) ANY `Pre-treated with antidiabetic medication`(DrugExposure codeset 9), window [-365, 0]. 사이트 보유 상한 6,283에 매칭 개념 8개인데 실측 287. 두 갈래 모두 window 안에서 거의 기록되지 않는다.

### 2-2. 독립 가정과의 대조

각 rule의 통과율이 서로 독립이라면 최종 인원은 `Total × Π(Nᵢ/Total)`이 된다.

| cohort | 독립 가정 기대 | 실제 People | 배수 |
|---|---:|---:|---:|
| #19 carmelina_comparator | 0.0031 | 5 | ×1,600 |
| #20 carmelina_treatment | 0.000077 | 1 | ×12,900 |
| #21 carolina_comparator | 6.77 | 44 | ×6.5 |
| #22 carolina_treatment | 35.3 | 60 | ×1.7 |
| #23 empa-reg_comparator | 0 | 0 | — |

실제가 독립 기대보다 항상 크다 — 기준들이 강하게 양의 상관을 갖는다는 뜻이다. BMI가 기록된 환자는 HbA1c도, 항당뇨제 처방도, 동반질환도 함께 기록되어 있다. **ACHILLES는 개념별 주변 분포만 주고 이 상관을 전혀 담지 못하므로, rule별 통과율을 곱해 최종 인원을 추정하는 방식은 CARMELINA에서 3자릿수 이상 과소 추정한다.**

---

## 3. 병원 간 비교

먼저 **아주대와 동아대의 절대값은 비교할 수 없다**(§한계 1). 아래는 척도에 무관한 두 축 — 개념 보유 여부와 closure 대비 coverage — 만 본 것이다.

| cohort | rule | closure | 아주대 매칭 / 상한 | 동아대 매칭 / 상한 | 계명대 매칭 / 상한 |
|---|---|---:|---|---|---|
| carmelina | entry T2DM | 84 | 6 / 803,569 | 5 / 111,843 | 4 / 12,874 |
| carolina_tx | entry linagliptin | 301 | 6 / 199,387 | 4 / 12,304 | 6 / 13,940 |
| carolina_cp | entry glimepiride | 3,422 | 9 / 691,260 | 11 / 33,023 | 8 / 6,503 |
| empa-reg_tx | entry BI 10773 | 8 | **0 / 0** | **0 / 0** | **0 / 0** |
| carmelina | #3 Body Mass Index | 3 | 1 / 1,676,956 | 1 / 87,807 | 1 / 218,605 |
| carmelina | #4 HbA1c | 5 | 1 / 1,334,949 | 1 / 211,233 | 1 / 104,569 |
| carmelina | #9 Albuminuria + 신기능 | 134 | 22 / 306,701 | 22 / 41,428 | 11 / 3,613 |
| carmelina | #10 Drug-naïve + Pre-treated | 396 | 8 / 80,496 | 8 / 6,283 | 10 / 9,184 |
| carmelina | #11 항당뇨 7종 | 19,494 | 113 / 3,112,725 | 119 / 156,141 | 107 / 102,821 |
| carolina | #13 CV질환 + 말기장기손상 | 2,240 | 252 / 2,385,049 | 246 / 266,081 | 102 / 92,889 |
| carolina | #14 항당뇨 7종 | 12,574 | 70 / 1,928,496 | 78 / 99,915 | 72 / 72,473 |
| empa-reg_cp | #11 Dietary + Exercise | 532 | **1 / 14** | **1 / 2** | **0 / 0** |

**핵심: 아주대와 동아대의 개념 coverage는 사실상 같다.** linagliptin 6 vs 4, glimepiride 9 vs 11, T2DM 6 vs 5, 항당뇨 7종 113 vs 119, CV질환 252 vs 246, BMI 1 vs 1, HbA1c 1 vs 1. 어느 쪽도 상대가 못 쓰는 개념을 갖고 있지 않다.

따라서 **ACHILLES만으로는 CARMELINA 동아대 5/1 대 아주대 0/0을 설명할 수 없고, 설명할 필요도 없다.** 94,164건 규모의 entry에서 5명과 0명은 같은 결과다(match rate 0.01% vs 0.00%). CAROLINA도 마찬가지로 동아대 44/60 대 아주대 46/31 — 같은 자릿수이며, ACHILLES가 두 병원 모두 linagliptin·glimepiride 제품 개념을 보유한다고 말한 것과 일치한다. 예측이 맞은 부분은 "두 병원 다 소수 인원이 나온다"이지 "어느 쪽이 더 많다"가 아니다.

ACHILLES가 **끝내 해결하지 못하는 것**은 다음 셋이며, 위 5 vs 0 · 44 vs 46 · 60 vs 31의 차이는 전부 여기에 들어간다.

1. **값 분포** — BMI ≤ 45, HbA1c 구간, eGFR, ALT/AST/ALP 3×ULN. analysis 1815(값 분포)가 계약에 없다.
2. **시간창** — [-180,0], [-365,0], [-56,0], [-180,+365]. ACHILLES는 시간축 없는 전기간 누적치만 준다.
3. **인원 교집합** — §2-2에서 본 상관. 개념별 주변 분포로는 복원 불가.

계명대는 ATLAS 결과가 없어 검증 대상이 아니지만 참고점으로: #9(11 vs 22)와 #13(102 vs 246)에서 coverage가 다른 두 병원의 절반 이하다. 계명대에서 이 두 rule은 다른 병원보다 더 세게 자를 가능성이 있다.

---

## 4. 예측 품질

### 4-1. 분류 요약 (동아대, rule별 리포트가 있는 117개)

| 분류 | 건수 | 이 중 `ANY/absence` 결함 | 읽는 법 |
|---|---:|---:|---|
| (d) 양쪽 다 존재 | 48 | 0 | 정상 예측. 배율은 아래 |
| (b) 예측 있음 · 실측 ~0 | 50 | **48** | 48건은 예측 실패가 아니라 rule이 무력 |
| (c) 개념 부재 → absence 100% 충족 | 14 | 5 | 정확한 0 예측 |
| — 인구학 전용 (ACHILLES 범위 밖) | 5 | 0 | 예측 대상 아님 |
| **(e) 예측 0인데 실측 존재** | **0** | — | **거짓음성 없음** |

(b) 50건 중 결함으로 설명되지 않는 2건: `empa-reg_comparator` #9 `Glucose`(값 제약 absence, 상한 135 = entry의 0.14%, 실측 0 — 사실상 맞음)와 #11 `Dietary+Exercise`(상한 2, 실측 0 — 사실상 맞음). 즉 **ACHILLES의 진짜 rule 단위 오예측은 117건 중 0~2건**이고, 나머지 48건은 정의 결함이다.

### 4-2. 크기 배율 (분류 (d) 48건)

| 지표 | 원값 배율 (상한 ÷ 실측 보유) | 유병률 정규화 배율 |
|---|---|---|
| 중앙값 | **24.4** | **0.42** |
| 사분위 | 15.2 – 42.8 | 0.24 – 1.81 |
| 범위 | 1.19 – 203.9 | 0.09 – 16.05 |
| 값제약 있음 (n=19) | 41.2 | 1.22 |
| 값제약 없음 (n=29) | 20.2 | 0.30 |
| 3배 이내 | — | 23 / 48 |
| 10배 이내 | — | 40 / 48 |

유병률 정규화 = `(상한 ÷ 사이트 인원 하한 1,196,549) ÷ (실측 보유 ÷ Total Events)`.

- **원값 배율 24배는 대부분 분모가 다른 데서 온다.** ACHILLES는 병원 전체 인원 기준, ATLAS는 entry 코호트 기준이다. 정규화하면 중앙값 0.42로 뒤집힌다 — entry 코호트(T2DM 환자)가 병원 전체보다 동반질환·검사 기록이 훨씬 많기 때문이며, 이 방향은 예상대로다.
- **값 제약이 정확히 예상대로 작동한다.** 값제약 rule의 정규화 배율 중앙값 1.22, 값제약 없는 rule은 0.30. ACHILLES가 값 필터를 못 보므로 값제약 rule에서만 과대 예측 쪽으로 4배 밀린다. **이 신호는 ACHILLES 한계의 직접 측정치다.**

### 4-3. 어느 격차가 구조적 한계로 설명되고, 어느 것이 아닌가

**설명됨**

- 분류 (d)의 24배 원값 격차 — 모집단(전체 vs entry) + 시간창 + 값 필터 + 상한의 concept 간 중복 계수.
- 값제약 rule이 비값제약 rule보다 4배 더 과대 — 값 필터 부재의 정량치.
- entry의 1.19–2.36배 — `PriorDays 365` + `First`.
- §2-2의 독립 기대 대비 3자릿수 차이 — 주변 분포만으로는 인원 교집합 복원 불가.

**설명 안 됨 (= ACHILLES 탓이 아님)**

- (b) 48건. 예측도 관측도 각각 옳다. `ANY(NOT A, NOT B, …)`가 나열 개념을 전부 동시에 가진 사람만 제외하므로 rule이 아무도 안 거른다. `carolina_treatment` #22가 이 해석의 반증 시험 — 5개 개념(Allergic Rhinitis / Asthma / Anaphylaxis / Urticaria / Contact Dermatitis) 전부 보유자가 정확히 1명이었고 7,317 → 7,316이 되었다. 다른 52개는 예외 없이 정확히 100.00%.
- EMPA-REG treatment entry 0. 개념집합에 empagliflozin이 없다.

**한 줄 요약: ACHILLES 스냅샷은 "가능/불가능"과 "entry 규모"의 예측기로는 쓸 만하고(거짓음성 0건, entry 1.2–2.4배), "최종 인원"의 예측기로는 쓸 수 없다.** 값·창·교집합 세 축이 빠져 있고, 그 셋이 최종 인원을 결정하기 때문이다.

---

## 5. 이상징후 (지적만 하고 원인 단정은 하지 않음)

1. **`carolina_comparator` Total Events가 정확히 14,000.**
   전역 상한이라는 설명은 **성립하지 않는다** — 같은 배치의 `carmelina_*`가 94,164로 14,000을 넘고 `carolina_treatment`는 7,317로 아래이므로, 14,000에 걸리는 고정 cap이라면 94,164도 잘렸어야 한다. glimepiride DrugEra 첫 사건 인원이 우연히 정확한 라운드 수일 확률은 코호트당 대략 1/10⁴다. 원인은 확인하지 못했다. 동아대에 `SELECT count(DISTINCT person_id) FROM drug_era WHERE drug_concept_id = 1597756`(및 하위 제품 롤업분) 재확인을 요청할 것을 권한다.

2. **`4032243`을 "Dietary regimen"이라 적은 기록이 틀렸다.**
   `artemis/docs/site_data_request/수령데이터_정규화.md` §5-3은 `Dietary regimen(4032243)`이 세 병원에 존재한다며 아주대 2,574 / 계명대 199 / 동아대 234를 든다. 실제로 `omop_vocab.concept`에서 4032243은 **`Dialysis procedure`(Procedure, SNOMED)** 이고, 세 스냅샷 모두 그 행은 **analysis 600(procedure)** 에만 있다 — 라벨과 도메인이 일치하지 않는다. 더욱이 4032243은 **EMPA-REG의 Dietary/Exercise closure 532개에 포함되지도 않는다**. 따라서 그 항목은 rule #11과 무관하며, "생활습관 개념이 세 병원에 존재한다"는 §5-3의 결론은 근거를 잃는다. (해당 파일은 이번 작업 범위 밖이라 수정하지 않았다.)

3. **codeset 12/13이 다른 도메인에 숨어 있지 않은지 확인함 — 없다.**
   closure 532개를 analysis 400·600·700·800·1800 **전부**에 대조했다. 아주대·동아대는 analysis 800의 42872393 한 건뿐이고 계명대는 0건이다. `4222559 Dietary finding` 등 직접 항목은 어느 도메인에서도 매칭되지 않는다. 이 병원들이 생활습관 사실을 procedure나 다른 도메인에 다르게 저장하고 있어서 놓친 것이 아니다.

4. **계명대 스냅샷에 analysis 200(visit)이 통째로 없다.** 10,319행 중 visit 0행. `수령데이터_정규화.md`의 행수 표에도 visit 칸이 `—`로 남아 있다. 현재 6개 CIRCE가 visit 기준을 쓰지 않아 이번 분석엔 영향이 없지만, visit 기준이 들어오는 순간 계명대는 예측 불가가 된다.

5. **`smallCellCount = 0`은 확인된 값이 아니다.** 세 스냅샷 모두 0으로 채워져 있고, 이는 "억제 없음"을 뜻한다. 실제로 억제가 걸려 있었다면 이 분석의 모든 "0" 판정이 "0 또는 억제 임계 미만"으로 바뀐다. 다만 분류 (e)가 0건이므로, 적어도 동아대에서는 0 판정이 실측과 어긋난 사례가 없었다.

6. **`ANY` 다중 개념 제외 rule 62개(전체 137개 중 45%).** 제외 조건은 `Type: ALL` + 각 하위에 absence, 또는 단일 group에 여러 codeset을 OR로 묶는 형태여야 한다. 현재 형태는 개념 수가 많을수록 더 무력해진다. **다만 이는 납품 시점에 이미 수정되어 있던 결함이며, 낡은 store에서 export된 탓에 파일에 남았다 — §6 참조.**

---

## 6. 납품 파일의 출처

§2·§4의 no-op rule 62개와 §1의 `BI 10773` entry 집합은 **현재 파이프라인의 성질이 아니라 이미 수정된 결함이 담긴 낡은 export의 성질**이다. 근거는 다음 네 단계다. md5·컨테이너 환경변수·두 store의 rule 구조와 entry 집합은 디스크에서 직접 재확인했고, 인용한 커밋 4건과 ledger HEAD는 확인하지 않았다(git 명령 금지, §한계 10).

**① 납품 파일 = 컨테이너 scratch 산출물, byte 동일.** `output/circe_be/2026-08-31/`의 6개 파일은 아래 scratch 디렉터리의 동명 파일과 md5가 일치한다.

| 납품 파일 | scratch 원본 | 생성 스크립트 | md5 |
|---|---|---|---|
| `carmelina_treatment` | `artemis/tmp/carmelina_seeded_cohorts/` | `gen_carmelina_seeded.py` | `6752139f…` |
| `carmelina_comparator` | `artemis/tmp/carmelina_seeded_cohorts/` | `gen_carmelina_seeded.py` | `d19dce6b…` |
| `carolina_treatment` | `artemis/tmp/seeded_cohorts_all_v2/` | `gen_all_seeded_v2.py` | `938476e9…` |
| `carolina_comparator` | `artemis/tmp/seeded_cohorts_all_v2/` | `gen_all_seeded_v2.py` | `ca22d425…` |
| `empa-reg_treatment` | `artemis/tmp/seeded_cohorts_all_v2/` | `gen_all_seeded_v2.py` | `e3b36017…` |
| `empa-reg_comparator` | `artemis/tmp/seeded_cohorts_flag0/` | `gen_flag0_only.py` | `68027f2b…` |

**② 세 스크립트 모두 의도한 store를 읽지 않았다.** 세 스크립트는 동일하게
`STORE_PATH = os.environ.get("TTE_STORE_PATH", "/app/tmp/tte_six_post007_full/studies.json")`
로 쓰여 있는데, `artemis-api` 컨테이너에는 `TTE_STORE_PATH=/app/tmp/tte/studies.json`이 설정되어 있다(`docker exec artemis-api printenv TTE_STORE_PATH`로 확인). 환경변수가 이기므로 스크립트는 **이름으로 적어둔 `tte_six_post007_full` store를 한 번도 읽지 않고** 서비스의 live 기본 store를 읽었다. `docs/tte_agent/07_current_status.md`의 2026-08-31 ledger 항목은 export가 `tte_six_post007_full/studies.json` 기준으로 돌았다고 적고 있으나(HEAD 745ea83), 산출물이 그 진술을 반박한다.

**③ live store가 실제 출처라는 증거 — rule 구조가 그대로 옮겨왔다.** `artemis/tmp/tte/studies.json`(mtime 2026-08-13)과 납품 파일 대조:

| study | live store rules / no-op | modifiedDate | 납품 파일 | rule 이름 순서 일치 | 덧붙은 rule |
|---|---|---|---|---|---|
| 8 (EMPA-REG) | 20 / **9** | 2026-07-30 | `empa-reg_comparator` 21 | 앞 20개 완전 일치 | `No BI 10773` |
| 9 (CARMELINA) | 20 / **9** | 2026-07-30 | `carmelina_comparator` 21 | 앞 20개 완전 일치 | `No linagliptin` |
| 10 (CAROLINA) | 27 / **13** | 2026-06-22 | `carolina_comparator` 27 | 27개 완전 일치 | 없음 |

no-op 개수도 그대로다: live store 9+9+13 = 31이 arm 두 벌로 펼쳐져 납품 6파일의 62개가 된다(§2의 62/137을 독립 계수 함수로 재검산해 일치 확인).

entry 개념집합만 export 시점에 다시 매핑되어 live store와 다르다. live store의 `linagliptin` 집합은 `[1580747]` = **sitagliptin**(AGENTS.md가 이미 기록한 결함)인데 납품본은 40239216 linagliptin으로 정상화되었고(exact-ingredient 경로), live store의 `BI 10773`은 `[964008 bictegravir, 1254065 CHF-6366 대사체, 35605546 tenofovir alafenamide]` 3항목인데 납품본은 MeSH-alias 경로를 타면서 §1에서 본 5항목 쓰레기 집합이 되었다. **즉 rule 구조는 낡은 store에서 그대로 왔고, entry 집합만 export 시점에 갈아끼워졌다.**

**④ 의도했던 store에는 두 결함이 이미 없다.** `artemis/tmp/tte_six_post007_full/studies.json`(studies modified 2026-08-27):

| study | rules | ANY-over-absence | entry 개념집합 |
|---|---:|---:|---|
| 8 (EMPA-REG) | 29 | **0** | `BI 10773` = `[45774751 empagliflozin]` |
| 9 (CARMELINA) | 20 | **0** | `Linagliptin` = `[40239216 linagliptin]` |
| 10 (CAROLINA) | 37 | **1** | `linagliptin` = `[40239216 linagliptin]` |

관련 수정은 모두 납품일(2026-08-31) 이전이다 — planner De Morgan 유도 `23570e6`(2026-07-28), emission 시점 가드 `_effective_group_type` `01eee1e`(2026-08-23, SPEC-INFRA-003 M5), MeSH 기반 약물 seed `7837274`(2026-08-10)·`8692a55`(2026-08-13).

> **조율자 보고와 다른 점 하나.** study 10의 잔여 ANY-over-absence는 0이 아니라 **1**이다 — `Presence of Diabetes Diagnosis + Use of Anti-diabetic Medication`(leaf 2개). 이름은 "Presence of"인데 두 leaf 모두 `Occurrence {Type: 0, Count: 0}`(absence)로 인코딩되어 있다. study 8·9는 0이 맞다.

### 6-1. 재-export 실측 — 결함 두 개 중 하나만 사라진다

위 ④는 store의 내용 대조일 뿐이므로, 실제로 `tte_six_post007_full`에서 다시 export해 확인했다. 산출물은 `artemis/output/site_gap/2026-09-05/reexport_probe_flag1/`(신규 `artemis/scripts/export_seeded_cohorts.py`, 컨테이너 안, `TTE_DRUG_ANCHORED_ENTRY=1`).

| 파일 | rules | no-op | entry domain | entry 개념집합 |
|---|---:|---:|---|---|
| `carmelina_comparator` | 21 | **0** | DrugEra | `[40239216 linagliptin]` |
| `carmelina_treatment` | 20 | **0** | DrugEra | `[40239216 linagliptin]` |
| `carolina_comparator` | 37 | 1 | DrugEra | `[1597756 glimepiride]` |
| `carolina_treatment` | 37 | 1 | DrugEra | `[40239216 linagliptin]` |
| `empa-reg_comparator` | 30 | **0** | DrugEra | `[45774751 empagliflozin]` |
| `empa-reg_treatment` | 29 | **0** | DrugEra | **`[702171, 859730, 1201447, 1201518, 1254065]`** |

**no-op은 사라진다.** 62개 → 2개(CAROLINA 두 arm의 `Presence of Diabetes Diagnosis + Use of Anti-diabetic Medication` 잔여 1건씩). ④에서 예상한 대로다. **다만 이 잔여 1건은 극성 결함이 아니라 연결 결함이다 — 그 rule은 간효소 집합 두 개를 물고 있다(§6-2).**

**`BI 10773` entry 집합은 사라지지 않는다.** `empa-reg_treatment`의 재-export 결과는 2026-08-31 납품본과 **개념집합이 완전히 동일하다**(정렬 후 `[702171, 859730, 1201447, 1201518, 1254065]` 대 동일). 수정된 store의 PrimaryCriteria에는 `[45774751 empagliflozin]`이 들어 있는데도 그렇다 — `_build_seeded_target_circe`(`artemis/src/services/tte_service.py:4499`)가 store의 PrimaryCriteria 집합을 재사용하지 않고 arm 이름 문자열 `"BI 10773"`에서 약물을 **export 시점에 다시 해석**하기 때문이다. 해석 순서는 `_exact_ingredient_mapping`(6252행) → `_alias_ingredient_mapping`(6284행) → embedding fallback이고, `"BI 10773"`은 앞의 두 단계를 통과하지 못해 embedding까지 내려간다. 소스 주석(6292행)이 바로 이 사례를 적어 두었다 — embedding search가 `1254065 CHF-6366 .beta.-2 metabolite`를 답으로 냈다는 기록이다.

`empa-reg_comparator`가 `[45774751]`로 나오는 것은 대조 arm이 이 이름 해석 경로를 타지 않기 때문이며, 같은 study에서 arm에 따라 entry 집합이 갈리는 것이 이 결함의 서명이다.

> **참고: 플래그를 끄면 entry 자체가 달라진다.** `TTE_DRUG_ANCHORED_ENTRY`를 설정하지 않고 export하면(`reexport_probe/`) 여섯 arm 전부가 disease-anchored(`ConditionOccurrence`)로 나온다 — treatment arm 포함. 즉 약물 기점 entry는 플래그로만 켜진다.

### 6-2. 수정된 store의 rule↔개념셋 연결 검사

§6-1은 수정 store를 재-export 원본으로 쓰자는 결론을 향하지만, 그 전에 store 자체가 **rule 이름이 약속한 개념집합을 실제로 물고 있는지**를 확인해야 한다. 검사 방법: leaf가 2개 이상인 grouped rule마다 이름을 `" + "`로 쪼개고, 각 criterion이 참조하는 개념집합 이름이 그 조각들 중 하나와 토큰을 공유하는지 본다. 공유하지 않으면 flag. 스크립트는 `artemis/output/site_gap/2026-09-05/rule_wiring_check.py`.

criterion 단위 `conceptSetName` 메타데이터는 이 검사에 쓰지 않았다 — live store에서 이미 낡아 있고(실제 emit된 rule은 옳은데 메타데이터만 어긋난 사례가 다수), **실제로 emit된 `CodesetId` → `ConceptSets[].name` 연결만이 유효한 측정**이다.

**병원이 돌린 파일은 연결이 옳다.** 납품 comparator 6종:

| trial | flagged / grouped | flag의 성격 |
|---|---:|---|
| aristotle | 1 / 5 | `AF` ↔ `Postoperative atrial fibrillation` — 약어 |
| carmelina | 2 / 12 | `UACR` ↔ `Urine Albumin Creatinine Ratio`, `ALT/AST/AP` ↔ 정식 효소명 — 약어 |
| carolina | 1 / 15 | `Biguanides` ↔ `Metformin`, `Sulfonylureas` ↔ `Glipizide` 등 — 계열 ↔ 대표약 |
| empa-reg | 3 / 11 | `Smoking` ↔ `Tobacco use`, `ALT/AST` ↔ 정식명, 암종 ↔ `Melanoma/Leukemia/Lymphoma` — 동의어 |
| plato | 0 / 6 | — |
| leader | 0 / 0 | grouped rule 없음 |

flag 8건을 전부 눈으로 확인했고 **모두 동의어·약어·계열명이다. 오연결은 없다.** 즉 §2·§6에서 지적한 두 결함(no-op, `BI 10773` entry) 외에 납품 파일에 추가 결함은 없다.

**수정 store(2026-08-27)는 study 8·10에서 연결이 어긋나 있다.**

| study | flagged / grouped | 판정 |
|---|---:|---|
| 8 EMPA-REG | **6 / 9** | 오연결 |
| 9 CARMELINA | 1 / 5 | 동의어뿐 — 정상 |
| 10 CAROLINA | **14 / 18** | 오연결 |
| 1–7 | 각 최대 1건 | 동의어뿐 — 정상 |

실제 사례:

- `"High risk of CV events (Stroke) + Myocardial infarction > 6 months"` → `[Percutaneous Coronary Intervention, Estimated glomerular filtration rate]`
- `"Malignant neoplasm of breast + lung + …"` → `[Investigational drug trial, Cardiac surgery, Angioplasty]`
- `"Presence of Diabetes Diagnosis + Use of Anti-diabetic Medication"` → `[Alanine aminotransferase, Aspartate aminotransferase]`, 두 leaf 모두 `Occurrence {Type: 0, Count: 0}`

마지막 것이 §6-1의 "잔여 no-op 1건"이다. **그 rule은 극성 결함이 아니라 연결 결함이었다** — 이름은 당뇨 진단·약물의 presence를 약속하는데 간효소 집합 두 개가 absence로 물려 있다. §6-1에서 "잔여 no-op"이라 부른 것을 여기서 정정한다.

**어긋남의 모양: 일정한 index shift가 아니라 광범위한 오연결.** criterion이 자기 조각(offset 0)이 아니라 어느 조각과 맞는지 세어 보면 —

- study 8: 39개 중 offset 0이 19개, +1이 1개, **어느 조각과도 안 맞음 19개**
- study 10: 63개 중 offset 0이 9개, offset −2·−1·+1·+2·+3에 흩어진 것이 17개, **어느 조각과도 안 맞음 37개**
- study 9(CARMELINA): 11개 중 offset 0이 9개, 안 맞음 2개 — 정상

균일한 +1 이동이었다면 offset 분포가 한 값에 몰렸을 텐데 그렇지 않고, study 10에서는 63개 중 37개가 **자기 rule의 어느 조각과도 무관한 집합**을 참조한다. 즉 이웃 rule의 집합을 끌어다 쓴 것에 가깝다.

**후보 원인 (재현으로 확정하지 않음).** `_apply_draft_concept_set_metadata`(`artemis/src/services/tte_service.py:3702-3707`)가 id로 개념집합을 찾지 못하면 `concept_sets[start_index + mappable_offset]` 위치 기반 fallback을 탄다. 이 코드는 2026-07-22 baseline부터 있었으나 어긋남은 criteria 삭제·병합 변경(`bdd7da2`, `1ccfbba`, 2026-08-25/26) 이후인 **2026-08-27 재생성분의 study 8·10에서만** 나타난다. 인과는 확인하지 못했다.

**결론: 수정 store는 CARMELINA에 한해서만 재-export 원본으로 쓸 수 있다.** EMPA-REG과 CAROLINA는 파이프라인에서 이 연결 결함을 고치고 **재생성한 뒤에야** 재납품 대상이 된다. §6-1의 재-export 산출물(`reexport_probe_flag1/`)도 이 store에서 나온 것이므로, EMPA-REG·CAROLINA 쪽 rule 내용은 그대로 신뢰하면 안 된다 — no-op이 사라졌다는 사실만 유효하다.

### 이 절이 바꾸는 것과 바꾸지 않는 것

**no-op 62개 — 귀속이 바뀐다.** "코호트 정의 생성기의 현재 결함"이 아니라 "이미 고쳐진 결함이 남아 있는 낡은 artifact"다. `TTE_STORE_PATH`를 명시해서(또는 스크립트가 환경변수가 다른 store를 가리키면 큰 소리로 실패하도록 고쳐서) 다시 export하면 실제로 62개 → 2개가 된다(§6-1에서 실측).

**`BI 10773` entry 집합 — 귀속이 바뀌지 않는다.** 이쪽은 낡은 store 탓이 아니라 **현행 export 경로의 결함**이다. store를 고쳐도, 명시해서 재-export해도 같은 쓰레기 5항목이 다시 만들어진다. 수정 지점은 store가 아니라 `_build_seeded_target_circe`이며, 이름 문자열을 다시 해석하는 대신 store의 PrimaryCriteria 개념집합을 그대로 쓰거나, 이름 해석이 embedding fallback까지 내려가면 조용히 답을 내지 말고 실패해야 한다. **§1의 "EMPA-REG treatment entry 0"은 재-export만으로는 고쳐지지 않는다.**

**바뀌지 않는 것 — 예측 품질 결론 전부.** entry 예측이 1.19–2.36배로 맞은 것, rule 단위 오차가 no-op rule에 지배된 것, 거짓음성 0건인 것은 그대로다. 이 분석은 "실제로 병원에서 돌아간 정의"를 대상으로 했고, 그 정의가 무엇이었는지는 md5로 확정되어 있다.

**재-export 후의 인원은 이 분석으로 예측할 수 없다.** 재-export한 rule 집합은 개수부터 다르다(EMPA-REG treatment 20→29, CAROLINA 27→37). §2의 절단 순위는 지금 rule 번호에 묶여 있으므로 그대로 옮겨 쓸 수 없고, **사이트 재실행이 필요하다.** 방향만 말하면: no-op이 제거되어 지금 100.00%에 서 있던 rule 53개가 실제로 사람을 거르기 시작하므로 최종 인원은 지금보다 **줄어들 가능성이 크다**. 그리고 `empa-reg_comparator`는 entry가 `[45774751 empagliflozin]`로 바뀌어 세 병원 모두 analysis 700에 제품 개념이 있으므로 entry가 0을 벗어나지만, `empa-reg_treatment`는 위 결함 때문에 **재-export해도 여전히 0**이다.

---

## 한계 (검증하지 못한 것)

1. **아주대 스냅샷의 척도를 신뢰할 수 없다.** 아주대 파일에서 `9202 Outpatient Visit`(analysis 200) = 28,656,713인데 같은 파일 `3022007 Birth date`(analysis 800) = 8,055,390이다. Birth date는 대부분의 ETL에서 1인 1행이므로 인원 수의 근사치인데, 방문 개념 보유 인원이 그보다 클 수 없다. analysis 600(15,231,974)·1800(16,812,986)·700(8,702,682)도 모두 8,055,390을 넘는다. 동아대는 전 domain 최댓값이 1,196,549(analysis 200)로 내적 모순이 없다. `수령데이터_정규화.md` §1은 세 병원 모두 `distinct person count`라고 적었지만 아주대 원본 헤더는 `domain, concept_id, count`로 person 표기가 없다. **아주대의 절대값은 이 문서 어디에서도 인원으로 해석하지 않았고, 병원 간 절대값 비교도 하지 않았다.** 원본 재확인이 필요하다.
2. **아주대 rule별 inclusion 리포트가 없다.** 생성 총계(People/Records)만 있어 §2에 해당하는 아주대 분석은 불가능하다. 아주대 CARMELINA 0/0이 어느 rule에서 죽었는지는 확인하지 못했다.
3. **계명대는 ATLAS 결과 자체가 없다.** 세 번째 참고점으로만 썼고 예측 품질 계산에서는 제외했다.
4. **ATLAS 실측치는 UI 스크린샷 전사분이다.** People/Total Events = 보고된 match rate가 4개 코호트 모두 산술 일치함을 확인했으나(5/94,164 = 0.01%, 1/94,164 = 0.00%, 44/14,000 = 0.31%, 60/7,317 = 0.82%), 원본 DB에서 재조회하지는 않았다.
5. **`to-gain` 열의 정의를 독립 검증하지 못했다.** ATLAS 표준 해석("이 rule만 제거 시 얻는 Total Events 대비 비율")을 따랐고, EMPA-REG #11의 829명 추정치는 이 해석에 의존한다.
6. **`site_persons_lower`는 ATLAS 관측치의 하한이 아니다.** 사이트 전체 인원 합집합의 하한일 뿐이며, 48/48건에서 실측을 상회한다. 이는 모집단이 달라서이지 오류가 아니다(§2 서두).
7. **유병률 정규화의 분모가 근사치다.** 동아대 인원을 1,196,549(analysis 200 최댓값)로 잡았는데, 이는 실제 인원의 하한이다. 실제 인원이 더 크면 §4-2의 정규화 배율은 전부 지금보다 작아진다.
8. **`ValueAsNumber`·`RangeHighRatio` 제약의 실제 통과율을 산출하지 않았다.** ACHILLES analysis 1815(측정값 분포)가 계약에 없어 계산할 방법이 없다. §4-2의 "값제약 4배"는 두 rule 집단의 배율 차이에서 얻은 간접 추정이다.
9. **동아대 5명·1명·44명·60명의 개인 단위 검증은 하지 않았다.** 어떤 환자가 왜 통과했는지는 확인 범위 밖이다.
10. **§6의 커밋 4건(`23570e6`, `01eee1e`, `7837274`, `8692a55`)과 ledger HEAD `745ea83`은 직접 확인하지 않았다.** 이번 작업은 git 명령이 금지되어 조율자가 확인한 내용을 그대로 인용했다. §6의 나머지 — md5 6건, 컨테이너 환경변수, 두 store의 rule·no-op·entry 집합, rule 이름 순서 일치 — 는 전부 디스크에서 직접 재확인했고, 그 과정에서 조율자 보고의 `0/0/0`을 `0/0/1`로 정정했다.
11. **재-export는 이제 실측으로 확인되었고, 이전 판의 추론 절반이 틀렸다.** 앞선 판은 "재-export하면 두 결함이 모두 사라진다"고 적었으나, `reexport_probe_flag1/` 산출물이 이를 반증했다 — no-op은 62개 → 2개로 사라지지만 `BI 10773` entry 집합은 납품본과 동일하게 재생산된다(§6-1). 남은 미검증 사항은 이것이다: **재-export 정의로 사이트에서 다시 돌린 결과는 없다.** §6-1의 인원 방향("줄어들 가능성이 크다")은 rule 구조에서 나온 추론이며 실측이 아니다.
12. **§6-2의 원인 후보(`_apply_draft_concept_set_metadata`의 위치 기반 fallback)는 재현으로 확정하지 않았다.** 연결이 어긋났다는 사실과 그 범위는 측정했지만, 그 코드 경로가 실제로 이 어긋남을 만들었는지는 확인하지 못했다. 인용한 커밋 `bdd7da2`·`1ccfbba`도 §한계 10과 같은 이유로 미확인이다. 또한 flag 건수는 토큰화 방식에 민감하다 — study 10은 "조각 중 아무거나 일치" 기준으로 14/18, "자기 조각과 일치" 기준으로 17/18이며 조율자 보고는 16/18이었다. **어긋남의 존재와 규모는 세 기준 모두에서 같은 결론이지만, 특정 건수를 인용할 때는 기준을 함께 밝혀야 한다.**

---

## 재현

전 명령과 파일 목록은 `artemis/output/site_gap/2026-09-05/README.md`. 요약:

```bash
cd artemis

# 1) 6개 CIRCE의 concept id 합집합(489개) → concept_ancestor descendant 맵
docker exec broadsea-atlasdb psql -U postgres -d postgres -Atc \
  "SELECT c.concept_id, coalesce(ca.descendant_concept_id,-1)
   FROM omop_vocab.concept c
   LEFT JOIN omop_vocab.concept_ancestor ca ON ca.ancestor_concept_id = c.concept_id
   WHERE c.concept_id IN (<489 ids>)"     # -> vocabulary_map.json (60,678행)

# 2) 프로덕션 엔진 18회 (3 site × 6 cohort, 실패 0건)
for site in ajou donga keimyung; do
  for c in carmelina_treatment carmelina_comparator carolina_treatment \
           carolina_comparator empa-reg_treatment empa-reg_comparator; do
    .venv/bin/python scripts/adapt_site_cdm.py \
      --snapshot data/site_snapshots/$site.zip \
      --circe output/circe_be/2026-08-31/$c.circe.json \
      --vocabulary-map output/site_gap/2026-09-05/vocabulary_map.json \
      --output output/site_gap/2026-09-05/reports/${site}__${c}.json
  done
done

# 3) rule 단위 대조 + 병원 간 비교 + 요약
.venv/bin/python output/site_gap/2026-09-05/analyze_gap.py
cd output/site_gap/2026-09-05 && \
  /home/bilab/work/projects/Broadsea/artemis/.venv/bin/python cross_site_and_summaries.py
```

§6-1의 재-export 프로브:

```bash
# 수정 store에서 다시 export (컨테이너 안, 약물 기점 entry 플래그 ON)
#   -> artemis/output/site_gap/2026-09-05/reexport_probe_flag1/
TTE_STORE_PATH=/app/tmp/tte_six_post007_full/studies.json \
TTE_DRUG_ANCHORED_ENTRY=1 \
  python scripts/export_seeded_cohorts.py
# 플래그 미설정 비교군 -> reexport_probe/ (여섯 arm 전부 disease-anchored)

# 산출물의 rule 수 / no-op 수 / entry 개념집합 대조
.venv/bin/python - <<'EOF'
import json, pathlib, sys
sys.path.insert(0, "output/site_gap/2026-09-05")
from provenance_check import noop_count
for d in ("reexport_probe_flag1", "reexport_probe"):
    for f in sorted((pathlib.Path("output/site_gap/2026-09-05") / d).glob("*.circe.json")):
        c = json.loads(f.read_text())
        pc = c["PrimaryCriteria"]["CriteriaList"][0]
        dom = next(k for k in pc if isinstance(pc[k], dict))
        cs = next(x for x in c["ConceptSets"] if x.get("id") == pc[dom].get("CodesetId"))
        ids = sorted(i["concept"]["CONCEPT_ID"] for i in cs["expression"]["items"])
        print(d, f.stem, len(c["InclusionRules"]), noop_count(c["InclusionRules"]), dom, ids)
EOF
```

**엔진 산출과 자체 산출의 구분.** `reports/*.json`(concept 단위 `ConceptEvidence`, `proposedChanges`, `verificationRequests`)은 `src/services/site_cdm_adaptation.py`를 **무수정**으로 쓴 결과다. rule 단위 집계·closure 재계산(`isExcluded` anti-join 포함)·ALL→min·ANY→sum 경계 전파·polarity 판정·ATLAS 대조·분류·유병률 정규화는 엔진에 없는 층이라 `analyze_gap.py`로 새로 작성했다(`artemis/src/**`, `artemis/scripts/**` 미변경).
