# TTE 자격기준 코호트 정의 (OHDSI Circe) — 6개 임상시험

생성일 2026-08-03, CARMELINA만 2026-08-04 갱신. 임상시험 프로토콜 원문에서
자격기준을 추출해 OMOP CDM용 코호트 정의로 변환한 것입니다.

## 파일

| 파일 | 시험 | NCT | ConceptSets | InclusionRules | 생성 |
| --- | --- | --- | --- | --- | --- |
| `ARISTOTLE_NCT00412984_study3_circe.json` | ARISTOTLE | NCT00412984 | 43 | 35 | 08-03 |
| `PLATO_NCT00391872_study2_circe.json` | PLATO | NCT00391872 | 90 | 33 | 08-03 |
| `CAROLINA_NCT01243424_study10_circe.json` | CAROLINA | NCT01243424 | 77 | 42 | 08-03 |
| `EMPA-REG_NCT01131676_study8_circe.json` | EMPA-REG OUTCOME | NCT01131676 | 76 | 33 | 08-03 |
| `CARMELINA_NCT01897532_study9_circe.json` | CARMELINA | NCT01897532 | 30 | 25 | **08-04** |
| `LEADER_NCT01179048_study1_circe.json` | LEADER | NCT01179048 | 58 | 27 | 08-03 |

체크섬은 `manifest.json`에 있습니다.

**CARMELINA는 다른 다섯 개보다 한 판 뒤의 코드로 만들어졌습니다.**
원문 PDF가 `... serum levels of either ALT` 뒤에서 줄바꿈되는데, 추출기가 그
이어지는 줄(`(SGPT), AST (SGOT), or alkaline phosphatase (AP) ≥3 x ULN`)을
별개 기준으로 잘라내고 있었습니다. `ALT`가 빠진 파편만 남아 세 검사 항목을
구분하지 못했고, 결과적으로 `Liver enzyme elevation` 하나로 뭉쳐 있었습니다.
지금은 ALT / AST / 알칼리성 인산분해효소 세 기준으로 분리됩니다.

같은 수정이 나머지 다섯 개의 기준 목록에도 영향을 주지만(줄바꿈으로 갈라진
파편이 합쳐집니다), ULN 조건 개수는 달라지지 않아 재생성하지 않았습니다.
전부 같은 코드로 통일한 판이 필요하시면 말씀해 주세요.

## 사용 방법

각 파일은 ATLAS/WebAPI에 그대로 등록 가능한 Circe 표현식입니다.

- ATLAS: Cohort Definitions → New → Export/Import 탭에 JSON 붙여넣기
- WebAPI: `POST /WebAPI/cohortdefinition` 의 `expression` 필드에 그대로 전달

등록 후 소스를 선택해 Generate 하면 환자 수와 규칙별 감쇠표(attrition)가 나옵니다.

## 알아두실 점

**자격기준의 제외조건은 `InclusionRules` 안에 발생 0회 조건으로 표현돼 있습니다.**
Circe에는 `ExclusionRules`가 없어서, "X가 있으면 제외"는
`Occurrence: {Type: 0, Count: 0}`(발생 0회여야 함)인 InclusionRule이 됩니다.
ARISTOTLE 기준 35개 규칙 중 28개가 이 형태입니다.

**모든 규칙이 AND로 묶입니다.** 하나라도 0명이면 코호트 전체가 0명이 됩니다.
결과가 0명이면 감쇠표에서 어느 규칙이 0인지 먼저 확인하시는 것을 권합니다.

**검사 결과 기준 중 일부는 정상 상한 배수(ULN) 조건을 담고 있습니다.**
`RangeHighRatio`로 표현되며 스터디별 개수는 ARISTOTLE 3, PLATO 3, CAROLINA 3,
EMPA-REG 6, CARMELINA 3, LEADER 0 입니다. 해당 검사의 기관별 정상범위에 따라
값을 조정하셔야 할 수 있습니다.

PLATO는 원 프로토콜 기준으로는 4건이어야 하나 3건입니다. 네 번째는 고감도
트로포닌 I 검사인데, 근거로 삼은 2009년 설계 논문에 그 검사법이 없습니다.

**투여 경로 구분이 적용돼 있습니다.**
"전신 스테로이드" 같이 경로를 한정하는 제외기준은, 성분 전체를 잡은 뒤
비전신 제형을 `isExcluded`로 되빼는 방식으로 표현했습니다. 안약·연고·샴푸
사용자가 "전신 스테로이드 사용자"로 잘못 걸리지 않습니다.

| 시험 | isExcluded 항목 | 대상 기준 |
| --- | --- | --- |
| CAROLINA | 139 | 전신 코르티코스테로이드 2건 |
| EMPA-REG | 9 | 전신 스테로이드 1건 |
| 나머지 4개 | 0 | 해당 기준 없음 |

PLATO의 경구 항응고제 기준은 대상이지만 제외 항목이 0입니다 — 리바록사반·
다비가트란·아픽사반은 경구 제형만 존재해 되뺄 것이 없습니다.

판정이 불가능한 제형(예: `Prefilled Applicator` — 질용·직장용·안과용 구분 불가)은
**빼지 않고 남겼습니다.** 추측으로 빼면 새로운 오제외가 생기기 때문입니다.

**EMPA-REG의 ULN 조건 6건은 원문 중복입니다.** 부록에 같은 간효소 기준이 12번,
13번 두 항목으로 실려 있고(표기도 다릅니다), 각각이 ALT/AST/ALP 세 검사로
정상 분해되어 2 x 3 = 6이 되었습니다. 논리상 문제는 없으나 중복 제거된 버전이
필요하시면 말씀해 주세요.

## 문의

각 기준이 프로토콜 원문 어느 문장에서 왔는지, 어떤 OMOP 개념으로 매핑됐는지
추적 가능합니다. 필요하시면 기준별 근거 문장과 개념 목록을 함께 드리겠습니다.
