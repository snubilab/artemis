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

### 아주대 단위를 관측할 방법이 없다

병원에 추가 쿼리를 보낼 수 없다는 제약이 확인됐다. 우리가 가진 것으로는 알 수 없다:

- `data/site_snapshots/ajou.zip`은 `analysis_id, stratum_1, count_value` 세 컬럼뿐이고
  **단위 정보가 없다**. 받은 ACHILLES 분석은 `{200, 400, 600, 700, 800, 1800}`이며 단위
  분포를 담는 분석은 포함되지 않았다.
- `ajou_cdm`의 단위는 사이트 사실이 아니다. `scripts/synthesize_site_cdm.py:93-95`가
  HbA1c에 `8554`, BMI에 `9531`, eGFR에 `9117`을 **하드코딩**한다. 우리가 쓴 값이다.

그래서 **로컬에서는 이 결함이 구조적으로 잡히지 않는다** — synthesizer가 넣는 단위와
우리 정의가 요구하는 단위가 같은 값이기 때문이다. note-021이 "세 병원 CDM의 eGFR 13,845행이
은퇴한 `9117`을 쓴다"고 적은 것도 사이트 사실이 아니라 이 하드코딩을 측정한 것이다.

### 단위 실패의 방향은 규칙 종류에 따라 정반대다

09-12 발송분에서 `Unit`이 붙은 criterion 64개를 분류하면:

| 규칙 종류 | 개수 | 단위가 안 맞을 때 |
| --- | --- | --- |
| 배제 (`Occurrence {Type:0, Count:0}`) | 40 | 0행이 되어 **조용히 통과** — 코호트가 커진다 |
| 포함 | **24** | 0행이 되어 **코호트가 0명** |

**시급한 것은 포함 규칙 24개뿐이다.** 배제 40개는 잘못된 방향으로 관대해질 뿐 0을 만들지
않는다(별개 문제이므로 여기서 다루지 않는다).

### 포함 규칙의 analyte는 6종뿐이고, 값 범위가 단위를 함의한다

| analyte | 우리가 요구하는 단위 | bound | 대안 단위의 같은 범위 | 값이 단위를 결정하나 |
| --- | --- | --- | --- | --- |
| HbA1c | `%` (8554) | 6.5~10.0 | IFCC `mmol/mol` 48~86 | **예** — 겹치지 않음 |
| BMI | `kg/m2` (9531) | ≤45 | 없음 | **예** |
| eGFR | `mL/min/1.73m2` (720870) | ≥30 | 없음 | **예** |
| UACR | `ug/mg` (8838) | ≥30 | `mg/g` 동일 수치 | **예** — 이미 둘 다 허용 |
| SBP | `mm[Hg]` (8876) | >140 | `kPa` 약 18.7 | **예** |
| LDL | `mg/dL` (8840) | ≥135 | `mmol/L` 3.5 | **예** |

여섯 개 모두 bound 자체가 단위를 특정한다. 즉 **포함 규칙에서 단위 조건은 정보를 더하지
않고 실패 위험만 더한다.**

### 해결책 — 포함 규칙의 단위 조건을 뗀다

단위가 NULL인 사이트까지 커버하려면 동등 단위를 나열하는 것으로는 부족하다. NULL은 어떤
`IN (...)` 목록에도 걸리지 않기 때문이다. 아주대가 NULL인지 다른 concept인지 모르는 이상
**조건 제거가 유일하게 둘 다 커버하는 방법이다.**

- 적용 범위: **포함 규칙에 한한다.** 배제 규칙은 그대로 둔다.
- 적용 근거: 위 표처럼 **analyte별로 "bound가 단위를 특정한다"를 명시**하고, 표에 없는
  analyte는 단위를 유지한다. 일반 규칙이 아니라 검증된 목록이다.
- `unitless value bound` lint가 이를 결함으로 잡으므로, 같은 표를 lint의 허용 목록으로
  등록한다 — 그래야 게이트와 산출물이 한 곳에서만 정의된다.

### 트레이드오프 — 사용자 결정 사항

| | 단위 유지 (현재) | 포함 규칙에서 제거 |
| --- | --- | --- |
| 아주대 | 6개 코호트 전부 0명 | 0을 벗어날 가능성 |
| 동아대 | 이미 통과 | 변화 없음 |
| 위험 | 없음 | 잘못된 단위로 기록된 값이 매칭될 수 있음 |
| 위험의 실제 크기 | — | 위 6종은 bound가 단위를 특정하므로 낮음 |

측정으로 확인할 수 없는 부분이 남는다: 아주대에 실제로 잘못된 단위의 값이 있는지는
관측할 수 없다. 이 결정은 **재발송 후 숫자로만 검증된다.**

### 기대 효과

아주대 6개 코호트 전부의 필요조건이다. 충분조건은 아니다 — CARMELINA는 `#2`(3.25%)와
`#10`(0.08%)이 남아 최대 32명(comparator) / 60명(treatment) 수준이고, EMPA-REG comparator는
B도 함께 고쳐야 한다. CAROLINA와 EMPA-REG treatment는 A만으로 0을 벗어난다.

동아대는 A와 무관하다.

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
| 3 | A | 포함 규칙 24개에서 단위 제거 | 아주대 최대 6개의 필요조건 | 사용자 결정 필요 — 정밀도와 도달률의 교환 |
| 4 | D | 프로토콜 대조 | 미정 | A·B·C 이후 재평가 |

2번이 3번보다 앞선 이유는 효과 크기가 아니라 **확실성**이다. B는 사이트 데이터 없이 원인이
확정됐고 게이트로 즉시 검증된다. A는 아주대 단위를 끝내 관측할 수 없으므로 **재발송 후
숫자로만 검증된다.**

## 이 계획으로도 해결되지 않는 것

- **아주대는 A 없이는 6개 전부 0이다.** B·C를 고쳐도 아주대 숫자는 움직이지 않는다.
- **동아대 CARMELINA 두 팔은 어느 항목으로도 설명되지 않는다.** 0명 규칙이 없고 교집합이
  0이므로, 어느 조합인지 알려면 규칙별 표만으로는 부족하고 교차표가 필요하다.
- **아주대 CARMELINA는 A를 고쳐도 32명/60명 수준이다.** `#2`와 `#10`이 이미 그만큼 좁혔다.
- **동아대 CAROLINA는 숫자 자체가 아직 없다.** C를 고치고 재발송해야 처음 측정된다.

## 다음 행동

1. B의 export repair 구현 + 위 검증 기준 4개 통과
2. A의 단위 제거 범위를 사용자가 승인 (포함 규칙 24개, analyte 6종)
3. 재발송 전 게이트 3개 통과: `verify_delivery_provenance`, `verify_atlas_renderable`,
   `verify_entry_exclusion_conflict`
