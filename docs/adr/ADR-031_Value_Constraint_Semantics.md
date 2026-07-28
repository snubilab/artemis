# ADR-031: Value Constraint Semantics (값 조건의 의미 보존)

**상태**: 제안됨 (Proposed) — 수정 설계
**날짜**: 2026-07-28
**의사결정자**: @kyh
**관련**: ADR-029(feasibility gating), ADR-030(사이트별 적응 계층), 이슈노트 #10·#11·#12

## 컨텍스트

"ALT > 정상상한의 3배"라는 프로토콜 문장이 Circe에서 `ValueAsNumber {Value: 3.0, Op: "gt"}`가 됐다. 실제 ALT는 10~40 U/L이므로 이 조건은 간기능 검사를 받은 환자 **전원**에 매칭된다. 배제 조건이므로 코호트는 0명이 된다.

Synthea 실측: 검사 이력 2,841명 중 2,841명(100%) 배제. 올바른 3×ULN(ALT 165 / AST 144 / ALP 441 U/L)이라면 24명(0.84%)이다. **118배 과다 배제**이며, 세 병원 모두 ALT/AST/ALP를 대량 보유하므로 현장에서도 0명이 확정된다.

### 이것은 추출 실패가 아니다

Agent 1은 `unit_text: "x ULN"`을 정확히 추출했고 저장된 IR에 6건 남아 있다. 프롬프트도 이미 `op`/`value`/`unit_text`를 필수로 요구한다.

손실은 빌더 한 줄에서 일어난다.

```python
# src/services/tte_service.py:5671  — 생산 경로
criteria_attrs["ValueAsNumber"] = {"Value": val, "Op": circe_op}
```

같은 `valueConstraint` 객체 안에 `unitText`가 들어 있는데 읽지 않는다. `"x ULN"`이 여기서 사라지고 `3`만 남는다. **모델을 바꾸거나 프롬프트를 고쳐도 해결되지 않는다.**

### Circe에는 이미 올바른 표현이 있다

gold 코호트(임상 연구자가 직접 작성)는 같은 기준을 이렇게 쓴다.

```json
{"CodesetId": 194, "RangeHighRatio": {"Value": 3, "Op": "gt"}}
```

`RangeHighRatio`는 `value_as_number / range_high`를 계산한다. OMOP `measurement` 테이블은 행마다 `range_high`(그 검사실이 그 결과에 적용한 정상 상한)를 갖는다. **따라서 검사실별 ULN을 우리가 알 필요가 없다** — 각 결과가 자기 검사실 기준으로 평가된다.

전수 비교: gold는 Measurement 조건 중 `RangeHighRatio` **32건**, 생성물은 **0건**. 단위를 고정하는 `Unit` 필터도 gold 2건 / 생성물 0건이다. 파이프라인이 두 필드의 존재를 모른다.

### 코퍼스가 드러낸 것 (설계를 바꾼 사실)

ClinicalTrials.gov 90개 프로토콜 + NEJM 논문에서 임계값 표현 114건을 원문 그대로 수집했다(`tests/fixtures/value_constraint_corpus.yaml`). 표기 변형 31종이 나왔고, 그중 셋은 초기 설계로 처리 불가였다.

1. **암묵적 배수 1** — `≤ institutional ULN`, `<lower limit of normal (LLN)`, `at or below the upper limit of normal`. 숫자가 적히지 않는다. 실제 의미는 `≤ 1 × ULN`이다. 숫자부터 찾는 파서는 여기서 아무것도 얻지 못한다.
2. **`x`의 이중 의미** — `3x ULN`은 비율, 같은 문서의 `3x10⁹/L`은 절대값(3×10⁹). 같은 토큰, 정반대 의미.
3. **한 줄에 조건 둘** — `TSH >1.2 ULN or <0.8 LLN`. `ValueConstraint | None` 반환형으로는 **구조적으로 표현할 수 없다**.

또한 LLN이 6건 실재하므로 `RangeLowRatio`도 필요하다.

### 부수적으로 확인된 사실

- `UNIT_MAP["mg"] = 8587`인데 **8587은 millilitre**다(milligram은 8576). 용량 조건에 부피 단위 필터가 붙는다.
- `UNIT_MAP`은 9개 키 문자열 완전일치라 추출된 41건 중 14건(34%)만 적중한다. `years`(맵은 `year`), `kg/m²`(위첨자), `mL/min`, `ml/min/1.73 m2`, `mV`, `ng/L`이 모두 누락된다.
- UCUM concept_code는 직관과 다르다 — `year`는 코드 `a`, `U/L`은 `[U]/L`, eGFR 단위는 `mL/min/(173.10*-2.m2)`. 코드를 짐작해 조회하면 "개념 없음"으로 오판한다(실제로 그렇게 오판했다).

## 결정

### D1. `reference_bound`를 IR의 1급 필드로

`ValueConstraint`에 추가한다.

```
reference_bound: Literal["absolute", "uln", "lln"] = "absolute"
```

`unit_text`는 순수 단위만 담는다. `"x ULN"`은 더 이상 여기에 들어가지 않는다.

근거: 지금 `"x ULN"`이 단위 칸에 있는 이유는 갈 곳이 없어서다. 그 상태로는 빌더가 `"x ULN"`과 `mg/dL`을 구분할 방법이 없다. 자리를 만들지 않으면 어떤 빌더 패치도 문자열 추측에 의존하게 된다.

### D2. 발견은 LLM이, 구조화는 결정적 파서가

Agent 1은 **어떤 기준에 임계값이 있는지 찾고 원문 구문을 그대로** 넘긴다. 구문 → 구조 변환은 결정적 코드가 한다.

근거: LLM은 발견을 잘한다 — `"x ULN"`을 이미 정확히 뽑았다. 그러나 표기 변형 31종에 대해 매 실행 동일한 구조를 낼 보장이 없고, 검증할 방법도 없다. 파서는 코퍼스 114건으로 회귀 검증된다. 부정 케이스(신뢰구간 상한 등)를 결정적으로 걸러내는 것도 파서만 가능하다.

역호환: 기존 IR이 `op`/`value`/`unit_text`만 갖는 경우에도 `unit_text`를 정규화해 `reference_bound`를 복원한다. 저장된 스터디를 재추출 없이 고칠 수 있다.

### D3. 단일 공유 모듈 — 호출자별 중복 금지

`src/services/value_constraint.py`

```
parse_value_constraints(text: str) -> list[ValueConstraint]
normalize_unit(unit_text: str) -> int | None
build_measurement_value_filter(vc: ValueConstraint) -> dict
```

`tte_service.py`와 `agent3/assembler.py` **둘 다** 여기로 라우팅한다.

근거: 지금 빌더가 둘이고 결함이 각각 다르다 — 하나는 `Unit`을 아예 안 내보내고, 다른 하나는 잘못된 위치에 넣는다. 한쪽만 고치면 나머지가 다음번에 같은 방식으로 틀린다. 반환형이 **리스트**인 것은 D7(한 줄 두 조건) 때문이다.

### D4. Circe 출력 매핑

| `reference_bound` | 단위 해소 | 출력 |
|---|---|---|
| `absolute` | 성공 | `ValueAsNumber` + **형제** `Unit: [개념]` |
| `absolute` | 실패 | `ValueAsNumber` 만 |
| `uln` | — | `RangeHighRatio` (`ValueAsNumber` 금지) |
| `lln` | — | `RangeLowRatio` (`ValueAsNumber` 금지) |

`Unit`은 `ValueAsNumber` 딕셔너리 **안**이 아니라 `Measurement`의 형제로 둔다. gold 실물 구조가 그렇고, 안쪽에 넣으면 Circe가 무시한다.

`uln`/`lln`에서 `ValueAsNumber`를 함께 내보내면 안 된다. `RangeHighRatio > 3`과 `ValueAsNumber > 3`이 AND로 결합돼 원래 결함이 그대로 살아난다.

### D5. 단위 해소 — 완전일치 금지, 실패 시 추측 금지

1. CT.gov 이스케이프 제거 (`\>`, `\<`, `=\>`, `=\<`)
2. NFKC 정규화 — `µ`(U+00B5)와 `μ`(U+03BC), 위첨자 `²`, `×`
3. 복수형·공백·대소문자 흡수 (`years`→`year`, `ml/min`→`mL/min`)
4. UCUM `concept_code`로 조회. **코드를 짐작하지 말고 별칭 표를 둔다** — `year`→`a`, `U/L`→`[U]/L`, `mL/min/1.73 m2`→`mL/min/(173.10*-2.m2)`
5. 해소 실패 시 `Unit` 미설정

가장 가까운 개념으로 대체하지 않는다. 틀린 `Unit` 필터는 0행에 매칭되며, 이는 #10과 정확히 같은 조용한 실패다 — 에러 없이 코호트가 비고, 원인은 훨씬 찾기 어렵다.

### D6. 암묵적 배수 1은 파서가 합성한다

`≤ institutional ULN` → `{op: "lte", value: 1.0, reference_bound: "uln"}`

`value`가 존재한다는 사실이 더 이상 "원문에 숫자가 적혔다"를 뜻하지 않는다. 이 구분이 필요한 소비자를 위해 파서는 원문 구문을 함께 보존한다.

### D7. 한 기준이 여러 조건을 낼 수 있다

`parse_value_constraints`는 리스트를 반환한다. `TSH >1.2 ULN or <0.8 LLN`은 조건 두 개다.

빌더는 이를 Circe 그룹으로 결합한다. 결합 타입은 원문의 접속사를 따른다 — `or`면 `ANY`, `and`면 `ALL`. 이슈 #5(드모르간)와 같은 함정이 여기서도 성립하므로, 배제 조건 안에서는 극성을 반전해야 한다.

### D8. 부정 케이스는 코퍼스가 방어한다

신뢰구간 상한, 유의수준, 기간, 범위 표현은 임계값이 아니다.

```
"upper boundary of the two-sided 95.02% confidence interval was less than 1.3"
"6.5 - 8.5%, inclusive"                     (범위이지 임계값이 아님)
">240 mg/dl (>13.3 mmol/L)"                 (같은 임계값의 단위 환산 재기술)
```

첫 문장이 가장 위험하다 — `upper ... of` + 숫자 + 비교연산자로, `upper limit of normal`과 한 단어 차이다. 세 번째는 두 조건으로 내보내면 상호배타적 필터가 AND로 묶여 0명이 된다.

코퍼스 14건이 회귀 방어선이다. `x` 중의성(`3x ULN` vs `3x10⁹/L`)은 뒤따르는 토큰으로 판별한다.

### D9. `range_high` 의존성을 명시하고 검증 가능하게 만든다

`RangeHighRatio`는 `measurement.range_high`가 채워져야 동작한다. Synthea는 간수치·HbA1c 전부 0건이므로 **현재 인프라로는 이 수정을 실행 검증할 수 없다.**

- 합성 사이트 CDM(`scripts/synthesize_site_cdm.py`)이 `range_high`/`range_low`를 채우도록 확장한다. 그래야 수정 전후를 같은 조건에서 실행 대조할 수 있다.
- 실제 병원에는 물어야 한다: "귀원 CDM의 `measurement.range_high`가 채워져 있습니까?" ADR-030의 `verificationRequests` 기구를 그대로 쓴다.
- 채워져 있지 않은 사이트에서는 `RangeHighRatio`가 0행에 매칭된다. 이는 `ValueAsNumber` 오용과 **반대 방향의 조용한 실패**이므로(과다 배제 → 과소 배제), 적응 리포트가 이 조건을 명시적으로 표시해야 한다.

## 단계

| 단계 | 범위 | 해결 | 산출 |
|---|---|---|---|
| 1 — 차단 해제 | D1·D3·D4·D5 + `mg` 버그 | #10·#11 | 병원 발송 가능한 Circe |
| 2 — 강건화 | D2·D6·D7·D8 | 표기 변형 31종·부정 케이스 | 코퍼스 114건 통과 |
| 3 — 검증 | D9 | 실행 대조 | 수정 전후 환자 수 |

1단계만으로 현재 차단 요인(#16)은 해소된다. 2단계는 다음 프로토콜에서 같은 유형이 재발하지 않게 한다.

## 성능 확인 기준 (수정 후 측정할 것)

| 지표 | 현재 | 목표 | 측정 방법 |
|---|---|---|---|
| 코퍼스 통과 | 6 통과 / 321 실패 / 1 skip | 327 통과 / 0 실패 (skip 1건은 LLM 필요) | `pytest tests/test_value_constraint.py` |
| `RangeHighRatio` 사용 | 0 / 42 (0%) | gold와 동등 — 32 / 85 (38%) | 6개 코호트 재생성 후 계수 |
| `Unit` 설정 | 0 / 42 | gold 이상 — 2 / 85 | 동일 |
| 규칙16 배제 인원 | 2,841 / 2,841 | ~24 (0.84%) | 합성 CDM 실행 |
| 부정 케이스 오탐 | 미측정 | 0/14 | 코퍼스 |
| 기존 스위트 | 909 통과 | 회귀 없음 | `pytest tests/ -q` |

규칙16 지표는 D9(합성 CDM에 `range_high` 채우기)가 선행되어야 측정 가능하다.

## 근거

- **Circe 표현력을 새로 설계하지 않는다.** `RangeHighRatio`·`RangeLowRatio`·`Unit`이 이미 있고 gold가 쓴다. 우리 쪽 배관만 고치면 된다.
- **ULN을 병원에 묻지 않는다.** CDM이 행마다 갖고 있다. 물어야 할 것은 "그 칸이 채워져 있는가" 하나뿐이며, 이는 훨씬 답하기 쉬운 질문이다.
- **파서를 두는 이유는 정확도가 아니라 검증 가능성이다.** LLM 추출은 실행마다 같다는 보장이 없고 회귀를 잡을 수 없다. 코퍼스 114건은 매 커밋마다 돌아간다.

## 스코프 (의도적 단순화)

- **값 조건에만 적용한다.** 시간창·발생 횟수 등 다른 수치는 범위 밖이다.
- **참조 범위의 출처를 검증하지 않는다.** `range_high`가 채워져 있으면 신뢰한다. 사이트가 잘못된 참조 범위를 넣었는지는 우리가 판단할 수 없다.
- **성별·연령별 참조 범위를 따로 다루지 않는다.** CDM의 `range_high`가 이미 해당 결과에 적용된 값이므로 자동으로 반영된다.
- **`Abnormal` 플래그는 쓰지 않는다.** gold도 생성물도 0건이고, 정도(3배인지 1.5배인지)를 잃는다.

## 미해결 리스크

- **`range_high` 미충전 사이트.** 과소 배제 방향의 조용한 실패가 된다. D9의 표시가 유일한 방어선이며, 사이트 회신 전까지는 해당 조건의 결과를 확정으로 읽으면 안 된다.
- **`3x10⁹/L` 판별.** 뒤따르는 토큰 기반 판별은 휴리스틱이다. 코퍼스에 없는 새 표기가 나오면 오분류할 수 있다.
- **접속사 극성.** D7의 그룹 결합은 이슈 #5와 같은 함정을 갖는다. 배제 조건 안의 `or`는 드모르간에 따라 `ALL`이 되어야 한다.
- **역호환 경로.** D2의 `unit_text` 복원은 기존 IR을 구제하지만, `"x ULN"` 외의 관용 표기가 저장돼 있으면 놓친다.

## 관련

- 이슈노트: `docs/daily_notes/tte_issue_log.json` — #10·#11·#12, 손실 지점 추적 섹션
- 코퍼스: `tests/fixtures/value_constraint_corpus.yaml` (114건, 출처 45곳)
- 테스트: `tests/test_value_constraint.py` (현재 321건 실패 = RED)
- 수집기: `scripts/fetch_threshold_protocols.py`, `scripts/build_value_constraint_corpus.py`
