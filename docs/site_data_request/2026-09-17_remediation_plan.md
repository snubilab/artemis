# 해결 계획 — 아주대·동아대 회신 데이터에서 측정된 문제만

근거는 2026-09-12 발송분에 대한 두 병원의 Atlas Inclusion Report 16장
(`data/site_reports/2026-09-12/`)이다. 여기 적힌 숫자는 전부 그 보고서에서 읽은 것이고,
원인은 발송한 `.circe.json`에서 직접 읽어 확인한 것이다. 추정으로 채운 칸은 그렇다고 표시했다.

측정 대상은 10개 코호트다 — 아주대 6개(전부 보고됨), 동아대 4개(CAROLINA 2개는 생성
실패로 보고 없음).

## 문제 요약

| # | 문제 | 데이터가 보여준 것 | 사이트 의존성 |
| --- | --- | --- | --- |
| A | 단위 조건이 사이트 단위 표기와 불일치 | 아주대 6/6 규칙 0명, 동아대 4/4 통과 | **있음** — 아주대만 |
| B | `Endocrine disorder (excluding T2DM)`가 T2DM을 배제하지 않음 | 두 사이트 comparator 모두 0명 | **없음** — 정의 모순 |
| C | `isExcluded` 멤버의 concept 필드 결손 | 동아대 CAROLINA 2개 생성 실패 | **없음** — Atlas 렌더 |
| D | `Stable antidiabetic background medication for 8 weeks` | 네 코호트에서 92~99% 절단 | 양쪽 공통 |

---

## A — 단위 조건

### 데이터

| 규칙 | 아주대 | 동아대 |
| --- | --- | --- |
| CARMELINA #12 HbA1c comparator | 0명 (0.00%) | 14,509명 (15.72%) |
| CARMELINA #12 HbA1c treatment | 0명 (0.00%) | 6,160명 (84.19%) |
| EMPA-REG #4 HbA1c comparator | 0명 (0.00%) | 5,484명 (5.94%) |
| EMPA-REG #4 HbA1c treatment | 0명 (0.00%) | 2,351명 (61.54%) |
| CAROLINA #2 BMI 두 팔 | 0명 (0.00%) | 보고 없음 (문제 C) |
| CAROLINA #7 HbA1c 두 팔 | 0명 (0.00%) | 보고 없음 (문제 C) |

아주대 축차 뷰에서 단일 규칙의 절단 폭이 확인된다: CAROLINA comparator는
`21,199 → 20,058 → 0`, treatment는 `8,837 → 8,611 → 0`으로 **BMI 규칙 하나가** 전부를
없앤다. EMPA-REG comparator는 `38,472 → 0`으로 HbA1c 규칙 하나가 없앤다.

### 원인

발송분은 BMI에 `Unit = 9531 (kg/m2)`, HbA1c에 `Unit = 8554 (%)`를 요구한다. Circe는 이를
`AND unit_concept_id IN (...)`으로 번역하므로, 사이트가 그 concept을 쓰지 않으면 0행이다.
같은 규칙이 동아대에서 5.94~84.19%를 통과하므로 **bound가 틀린 것이 아니라 요구가 좁다.**

### 해결책 — 측정이 먼저다

아주대가 `unit_concept_id`에 무엇을 쓰는지 아직 관측한 적이 없다. 값에 따라 수정이 갈리므로
추측으로 고치면 엉뚱한 것을 고친다. `docs/site_zero_diagnosis_queries.sql`의 Q3(HbA1c)·
Q5(BMI)를 아주대에 요청한다 — 집계값만 반환한다.

| 측정 결과 | 수정 |
| --- | --- |
| 은퇴한 UCUM concept을 씀 | `value_constraint.py:129` `_UNIT_DEPRECATED_FORMS`에 `8554`·`9531` 항목 추가. eGFR(`720870`)에 이미 같은 처리가 있고 아주대 행을 0 → 112로 되살린 선례가 있다 |
| `unit_concept_id`가 NULL | deprecated forms로는 풀리지 않는다. 단위 조건을 떼거나 NULL을 허용하는 별도 결정이 필요하며, 둘 다 정밀도를 낮추므로 사용자 판단 사항이다 |
| 우리가 모르는 다른 concept | 그 concept을 표에 추가할지, 단위를 떼는지 같은 판단 |

`_UNIT_DEPRECATED_FORMS`에 `8554`·`9531`이 없다는 것은 실측으로 확인했다 — 등록된 것은
`[8848, 8961, 9448, 720870]` 넷뿐이다.

### 기대 효과

아주대 6개 코호트 전부의 **필요조건**이다. 다만 충분조건은 아니다 — CARMELINA는 A를
고쳐도 `#2`(3.25%)와 `#10`(0.08%)이 남아 최대 32명(comparator) / 60명(treatment) 수준이다.
CAROLINA와 EMPA-REG treatment는 A만 고치면 0을 벗어난다.

동아대는 A와 무관하다. 이미 통과하고 있다.

---

## B — `Endocrine disorder (excluding T2DM)`

### 데이터

| 팔 | entry event | 아주대 | 동아대 |
| --- | --- | --- | --- |
| comparator | `ConditionOccurrence` T2DM | **0명 (0.00%)** | **0명 (0.00%)** |
| treatment | `DrugEra` empagliflozin | 874명 (14.84%) | 786명 (20.58%) |

동아대 empa-reg_treatment에서 이 규칙의 **To-Gain 27.36%**는 보고서 16장 전체에서 가장 크다.

### 원인

`codeset 29`는 이름이 `'Endocrine disorder'`이고 `isExcluded`가 0개이며
`201820 Diabetes mellitus`를 `includeDescendants: true`로 담는다. entry event가 그 하위인
`201826`이므로 entry 전원이 배제에 걸린다. `Occurrence {Type: 0, Count: 0}`이므로 결과는 0명이다.

**08-31 발송분에는 없던 문제다.** 그 발송분의 어떤 concept set도 `201820`을 담지 않으며
게이트도 PASS다. 09-12 재추출이 새로 만들었다.

추출 단계는 예외를 놓치지 않았다. store의 해당 기준은 `description`에
`Endocrine disorder (excluding T2DM)`, `protocolLine`에 `...except type 2 diabetes`를
보존하고 있고, `sourceText`만 `Endocrine disorder`로 잘려 있다. 파이프라인은 `sourceText`를
파서에 먹인다(`tte_service.py:7945`). 파서 자체는 `(excluding T2DM)`, `excluding`,
`other than`을 전부 파싱한다 — 직접 실행해 확인했다.

### 해결책 — export 시점 repair

재추출 없이 고친다. `_repair_stale_drug_concept_sets`(`tte_service.py:7484`)가 이미 export
시점에 `base`를 수정하는 선례이고, 6월 발송분의 `'linagliptin'` 집합에 sitagliptin이 들어
있던 결함을 그렇게 고쳤다.

같은 자리에 `_repair_entry_excluded_from_absence(base)`를 추가한다. **세 조건이 전부
맞을 때만** entry concept을 그 집합에 `isExcluded`로 표시한다:

1. 규칙 이름 또는 `description`에 예외 절이 있다 — `detect_entity_exception`
2. 그 배제 집합이 entry closure를 100% 덮는다
3. window가 index를 포함하고, 규칙 루트까지의 모든 그룹이 `ALL`이다

조건 1이 안전장치다. **"겹치니까 뺀다"가 아니라 "프로토콜이 빼라고 썼는데 안 빠졌으니
뺀다"**이다. 겹침만으로 고치면 의도된 배제까지 지운다. 부분 겹침(WARN)은 건드리지 않는다.

조건 2·3은 `scripts/verify_entry_exclusion_conflict.py`가 이미 계산한다. 탐지기가 있으므로
수정기는 그 판정을 재사용한다.

### 검증 기준 — 수정 전에 정한다

- `verify_entry_exclusion_conflict.py`가 EMPA-REG comparator에서 FAIL → PASS
- 09-12의 나머지 5개 파일 판정 불변 (WARN 2, PASS 3)
- 06-24·08-31 발송분에 걸었을 때 아무 변화 없음 — 과잉 적용 여부를 가르는 검사다
- re-export한 파일과 현재 파일의 diff가 `codeset 29` 한 곳뿐

### 기대 효과

**동아대 empa-reg_comparator 1개가 0을 벗어난다.** 그 코호트의 유일한 0명 규칙이기 때문이다.
아주대 empa-reg_comparator는 `#4 HbA1c`도 0명이므로 A와 B를 **둘 다** 고쳐야 한다.

---

## C — `isExcluded` 멤버의 concept 필드 결손 (수정 완료)

### 데이터

동아대 결과표의 CAROLINA 칸이 0이 아니라 **비어 있다.** 코호트가 생성되지 않았다. 화면에는
`Requested unknown parameter 'concept.DOMAIN_ID' for row 13, column 2`가 떴다.

### 원인

`carolina_{treatment,comparator}` codeset 80의 row 13~17, 다섯 개 `isExcluded` 멤버가
`CONCEPT_ID`와 `CONCEPT_NAME` 두 필드만 갖는다. Atlas는 그 표에서 `concept.DOMAIN_ID`와
`concept.VOCABULARY_ID`를 역참조한다(`ConceptSetViewer.js`). 정보가 없어서가 아니라
`_included_concepts()`가 매퍼의 열 필드 중 둘만 꺼내 담았다.

**WebAPI는 영향받지 않는다.** 6개 파일 전부 `POST /cohortdefinition/sql`이 HTTP 200이고,
배제도 `LEFT JOIN ... WHERE E.concept_id IS NULL` anti-join으로 정확히 실린다. Circe는
`CONCEPT_ID`만 읽는다. 이 결함은 Atlas 앞에 앉은 사람에게만 보인다.

### 해결책 — 적용됨 (`b3f81ab`)

`ExceptedConcept`가 매퍼의 concept dict 전체를 실어 나르고 append가 그것을 쓴다. DB 조회
없음. 테스트 76개 통과, 수정을 되돌리면 실패하는 것을 직접 확인했다.

재발 방지로 `scripts/verify_atlas_renderable.py`를 만들어 발송 절차에 넣었다. 발송 3건에
적용하면 06-24는 6/6, 08-31은 12/12, 09-12는 4/6이며 문제의 다섯 행을 row 13까지 짚는다.

### 기대 효과

**동아대 CAROLINA 2개가 "생성 가능" 상태가 된다.** 숫자가 살아난다는 뜻은 아니다 — 생성되면
비로소 그 코호트의 규칙별 숫자를 처음 보게 되고, 아주대에서 그 두 팔이 BMI·HbA1c로 0이었으므로
동아대에서도 다른 규칙이 막고 있을 수 있다. **측정을 가능하게 하는 수정이지 숫자를 살리는
수정이 아니다.**

---

## D — 배경약물 8주 규칙 (판정 보류)

### 데이터

| 사이트 / 팔 | entry | `#2` 통과 | 비율 |
| --- | --- | --- | --- |
| 아주대 carmelina_comparator | 38,664 | 1,257 | 3.25% |
| 아주대 carmelina_treatment | 8,837 | 713 | 8.07% |
| 동아대 carmelina_comparator | 92,304 | 798 | **0.86%** |
| 동아대 carmelina_treatment | 7,317 | 449 | 6.14% |

동아대 CARMELINA 두 팔은 **0명인 규칙이 하나도 없는데 결과가 0이다.** 여러 규칙의 교집합이
0이며, 그 중 가장 좁은 항목이 이 `#2`다.

### 왜 보류인가

CARMELINA 프로토콜은 실제로 8주 안정 투약을 요구한다. 92~99%가 떨어지는 것이 구현이 과하게
엄격해서인지 프로토콜에 충실해서인지 **이 데이터로는 판정할 수 없다.** 판정하려면 프로토콜
원문과 이 규칙의 구현을 대조해야 한다.

A·B·C를 고친 뒤에도 동아대 CARMELINA가 0이면 이것이 다음 후보다.

---

## 우선순위

| 순위 | 항목 | 비용 | 살아나는 코호트 | 근거 |
| --- | --- | --- | --- | --- |
| 1 | C (완료) | 적용됨 | 동아대 CAROLINA 2개가 측정 가능해짐 | 재추출 불필요, 이미 검증 |
| 2 | B | export repair, 재추출 불필요 | 동아대 empa-reg_comparator 1개 | 사이트 무관, 게이트로 즉시 검증 |
| 3 | A | 측정 후 결정 | 아주대 최대 6개의 필요조건 | 아주대 단위 값을 모르면 수정 방향이 갈림 |
| 4 | D | 프로토콜 대조 | 미정 | A·B·C 이후 재평가 |

2번이 3번보다 앞선 이유는 효과 크기가 아니라 **확실성**이다. B는 사이트 데이터 없이 원인이
확정됐고 검증 방법도 있다. A는 아직 측정이 없다.

## 이 계획으로도 해결되지 않는 것

- **아주대는 A 없이는 6개 전부 0이다.** B·C를 고쳐도 아주대 숫자는 움직이지 않는다.
- **동아대 CARMELINA 두 팔은 어느 항목으로도 설명되지 않는다.** 0명 규칙이 없고 교집합이
  0이므로, 어느 조합인지 알려면 규칙별 표만으로는 부족하고 교차표가 필요하다.
- **아주대 CARMELINA는 A를 고쳐도 32명/60명 수준이다.** `#2`와 `#10`이 이미 그만큼 좁혔다.
- **동아대 CAROLINA는 숫자 자체가 아직 없다.** C를 고치고 재발송해야 처음 측정된다.

## 다음 행동

1. 아주대에 Q3·Q5 요청 (A의 수정 방향을 가르는 유일한 입력)
2. B의 export repair 구현 + 위 검증 기준 4개 통과
3. 재발송 전 게이트 3개 통과: `verify_delivery_provenance`, `verify_atlas_renderable`,
   `verify_entry_exclusion_conflict`
