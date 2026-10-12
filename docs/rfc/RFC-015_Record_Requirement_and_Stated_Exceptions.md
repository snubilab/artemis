# RFC-015: 기록 요구 여부와 명시된 예외를 추출 단계에서 기록한다

**상태**: 설계 합의 대기
**날짜**: 2026-10-12
**관련**: RFC-014(결합 관계·시점), 분석 문서 `docs/site_data_request/2026-10-06_inclusion_report_0923_from_ajou_and_donga.md` 결함 1·2

## 1. 문제

두 수정이 프로토콜 문장의 뜻을 영어 낱말 목록으로 판정한다. 특정 시험·개념 이름은 없지만, 문장 해석을 손으로 쓴 규칙이 대신하므로 "하드룰 없이" 원칙에 어긋난다.

| 수정 | 판정 코드 | 낱말 | 호출 위치 |
| --- | --- | --- | --- |
| 용량 유지 기준 제외 (`26119e9`) | `src/services/dose_stability.py` `_STABILITY`, `_THERAPY` | stable, unchanged, … / background, therapy, dose, … | `tte_service._build_seeded_target_circe`, `scripts/verify_circe_delivery.py` |
| 설명문의 예외 적용 (`c75085c`, `d0ee924`, `686c9cb`, `c588aa7`) | `src/services/entity_exception.py` `_CONNECTIVE` | other than, except, excluding, apart from, but not, exclusive of | `planner/decomposer.py:160,174`, `entry_exclusion_repair.py:398`, `tte_service.py:8595`, `entity_exception.py:205` |

두 경우 모두 원인은 같다. Agent 1 출력에 그 뜻을 담을 자리가 없어서, 뜻이 자유 문장(`description`)에만 남았고, 뒤 단계가 그 문장에서 낱말을 찾아 다시 판정했다.

### 1-1. 기록을 요구하지 않는 기준이 PRESENCE로 나간다

현재 후보 스토어(`output/site_gap/2026-10-12_prompt_f2/store/studies.json`)의 CARMELINA 포함 기준 7:

```
description  "Stable antidiabetic background medication for 8 weeks"
protocolLine "Stable antidiabetic background medication (unchanged daily dose) for at least 8 weeks prior to"
logicType    PRESENCE    domain Drug    window -56..0    sourceText ""    protocolSpan ""
```

원문은 이미 받는 치료가 있으면 그 용량이 일정해야 한다는 조건이고, 같은 프로토콜은 약을 쓴 적 없는 환자도 받는다. Agent 1 스키마의 `logic_type`은 PRESENCE(기록 있음)와 ABSENCE(기록 없음) 둘뿐이라 "기록이 있을 때만 적용되는 조건"을 쓸 수 없다. PRESENCE를 고르면 빌더는 `DrugExposure` 1회 이상을 만들고, 그 규칙은 약 기록이 없는 사람을 모두 떨어뜨린다. 09-23 발송에서 아주대 CARMELINA comparator가 이 규칙 하나로 38,664명에서 1,257명이 됐다. CAROLINA 포함 기준 37·38·41도 같은 형태다.

### 1-2. 명시된 예외가 자유 문장에만 남는다

EMPA-REG 배제 기준 30:

```
description  "Endocrine disorder (excluding T2DM)"
protocolLine "Any uncontrolled endocrine disorder except type 2 diabetes"
sourceText   "Endocrine disorder"    protocolSpan "Endocrine disorder"
```

예외 대상(T2DM)은 `description`의 괄호 안에만 있다. 매퍼가 받는 `entity_text`에는 없으므로 `_CONNECTIVE` 정규식으로 괄호 안의 낱말을 찾아 매퍼에 넘긴다. 09-23 발송에서는 이 경로가 treatment 파일에서 작동하지 않아 EMPA-REG treatment가 두 병원 모두 0명이었다.

## 2. 제안

뜻은 Agent 1이 정하고, 코드는 그 판단의 근거가 원문에 있는지만 확인한다. RFC-014의 `relation_span` 확인과 같은 방식이다.

### 2-1. `record_requirement` 필드

1. Agent 1 스키마의 각 규칙에 필수 필드 `record_requirement`를 더한다.
   - `required`: 기준을 만족하려면 `entity_text`의 기록이 있어야 한다
   - `forbidden`: 그 기록이 없어야 한다
   - `conditional`: 그 기록이 있는 환자에게만 적용되는 조건이고, 기록이 없는 환자는 이 기준으로 걸러지지 않는다
2. `conditional`일 때는 `conditional_span`도 필수다. 조건을 말하는 원문 조각이며, 코드는 그것이 `protocolLine`의 부분 문자열인지만 확인한다.
3. 빌더는 `conditional` 규칙을 occurrence로 내보내지 않는다. `_skippedCriteria`에 사유 `conditional-on-existing-record`와 `conditional_span`을 기록한다.
4. 배송 게이트는 이 사유가 붙은 기록마다 `conditional_span`이 `protocolLine` 안에 있는지 확인한다. 조각이 없거나 원문에 없으면 FAIL이다. 낱말로 다시 판정하지 않는다.
5. `logic_type`은 `required`→PRESENCE, `forbidden`→ABSENCE로 그대로 유지해, 기존 빌더 경로는 바뀌지 않는다.
6. `dose_stability.py`와 게이트의 재판정 경로를 지운다.

필드 설명에는 예시 문장을 넣지 않는다. 세 값의 정의만 적는다.

### 2-2. `excepted_entities` 필드

1. 각 규칙에 선택 필드 `excepted_entities: [{text, span}]`를 더한다. 원문이 기준 대상에서 명시적으로 빼는 것이다.
   - `text`는 매퍼에 넘길 이름이다.
   - `span`은 원문 조각이며, 코드는 `protocolLine`의 부분 문자열인지만 확인한다.
2. 예외 적용은 기존 경로를 그대로 쓴다: 같은 매퍼로 `text`를 매핑하고, 결과를 `isExcluded` 항목으로 더한다(`c588aa7`의 매퍼 쪽 처리, `e0d2221`의 closure 겹침 보정은 구조적 처리이므로 유지).
3. `span`이 원문에 없으면 그 예외는 적용하지 않고, 기준에 사유를 남긴다.
4. `_CONNECTIVE` 정규식과 네 호출 위치의 `detect_entity_exception` 호출을 지운다. planner(`decomposer.py:160,174`)는 정규식 대신 이 필드를 읽는다.

### 2-3. 지우지 않는 것

- 게이트 검사 (t): 같은 테이블에서 presence의 closure가 absence의 closure 안에 있으면 FAIL. 문장이 아니라 내보낸 CIRCE의 concept closure를 비교하므로 유지한다. 2-2가 실패하면 이 검사가 잡는다.
- `e0d2221`의 잔여 겹침 보정의 집합 계산. 다만 이 보정은 "설명문이 예외를 명시했을 때"만 작동하고, 그 판단을 `entry_exclusion_repair.py:398`의 `detect_entity_exception`이 한다. 이 시작 조건만 `excepted_entities`로 바꾼다.

## 3. 실행 전 예측

| 행 | 지금 | 예측 |
| --- | --- | --- |
| CARMELINA 포함 7 (comparator·treatment) | 낱말 판정으로 skip | `conditional`, 같은 skip, 사유만 바뀜 |
| CAROLINA 포함 37·38·41 | 낱말 판정으로 skip | `conditional` |
| EMPA-REG 배제 30 | 정규식으로 T2DM `isExcluded` | `excepted_entities`로 같은 `isExcluded` (201826, 44793113) |
| `entity_exception`이 지금 작동하는 나머지 행 | 정규식 | 같은 결과. 구현 전에 행 목록을 스토어에서 뽑아 고정한다 |
| 그 밖의 모든 포함 기준 | PRESENCE/ABSENCE | `required`/`forbidden`, 변화 없음 |

틀릴 수 있는 방향은 둘이다.

- **모델이 `conditional`을 과하게 붙인다.** 실제로 기록을 요구하는 기준이 빠진다. 기준 손실이고 게이트로는 보이지 않으므로, `conditional` 행 전체를 사람이 원문과 대조한다.
- **모델이 예외를 놓친다.** 그 경우 게이트 검사 (t)가 EMPA-REG treatment처럼 모순이 생긴 파일을 FAIL로 잡는다.

## 4. 측정

1. **실패하는 테스트 먼저.** 모두 실제 스토어 행으로 만든다.
   - 빌더 테스트: `record_requirement="conditional"`인 CARMELINA 7 행은 occurrence로 나가지 않아야 한다. 현재 코드는 필드를 모르므로 PRESENCE로 내보내 FAIL한다.
   - 게이트 테스트: `conditional_span`이 원문에 없는 skip 기록은 FAIL해야 한다. 정상 행은 통과해야 한다.
   - 예외 테스트: `excepted_entities`가 있는 EMPA-REG 30 행에서 `isExcluded`가 나와야 한다. 정규식을 지운 상태에서 확인한다.
2. **행 단위 A/B.** Agent 1 출력은 실행마다 달라지므로, 정보 없는 프롬프트 변경을 한 플라시보 조건을 함께 돌린다. 이전 측정에서 플라시보만으로 기준의 약 3분의 1이 바뀌었다. 판정은 3절 표의 행으로 하고, 시험 합계는 쓰지 않는다.
3. **gold 기준별 대조.** 결과가 지금 후보(`2026-10-12_prompt_f2`)와 ±0.02 안이어야 한다. 이 변경의 목적은 낱말 규칙을 없애는 것이지 점수를 올리는 것이 아니다.

## 5. 비용과 위험

- Agent 1 스키마 변경은 IR 캐시를 무효로 만든다. 6개 시험 재추출이 필요하다(RFC-014 추정 약 132분). RFC-014도 Agent 1 스키마를 바꾸므로, 두 RFC를 같은 재추출에 태우면 한 번으로 끝난다. 설계는 따로 합의하고 실행만 합치는 것을 제안한다.
- 재추출하면 이번 변경과 무관한 기준도 다시 뽑힌다. 그 변동은 플라시보 조건으로 따로 센다.
- 구현 전까지 다음 발송 후보는 두 낱말 규칙을 포함한 채로 둔다. 지우면 EMPA-REG treatment 0명과 배경약 규칙이 후보에 다시 들어간다.

## 6. 범위 밖으로 기록하는 것

- Agent 1 프롬프트 자체에 예시가 들어 있다(`src/agents/agent1/prompts.py:38` "Type 2 Diabetes", "Metformin", `:245`의 이름 예시, Ferritin·Bupivacaine 등). "예시 없음" 원칙에 맞추려면 별도로 정리해야 한다.
- `loinc_specimen.py`의 `CIRCULATING_BLOOD_SYSTEM_WORDS`는 프로토콜 문장이 아니라 LOINC System 값을 읽는다. 하드룰에 해당하는지는 따로 판단한다.

## 7. 결정 요청

- 2-1과 2-2를 이 설계대로 진행할지.
- 재추출을 RFC-014와 합쳐 한 번에 할지.
