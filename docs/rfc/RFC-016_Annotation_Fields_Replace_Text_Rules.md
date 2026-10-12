# RFC-016: 텍스트 규칙을 주석 필드로 바꾼다

**상태**: 설계 합의 대기
**날짜**: 2026-10-12
**포함**: RFC-014(결합 관계·시점), RFC-015(기록 요구·예외). 이 문서가 두 RFC의 실행 범위를 합친다.
**근거**: `docs/inventory/2026-10-12_text_rules.{md,json}`, 가드 `tests/test_no_text_rules.py`(pending 298건), 계획 `todolist/20261012_095201_remove_examples_and_text_rules.md` P3·P4
**알려진 한계(6절 2단계, 2026-10-12 후보 저장소에서 확인)**: `relation`은 한 줄의 하위 항목 전체에 관계 하나를 적고, `timing`은 규칙 하나에 값 하나를 적는다. 그래서 세 경우는 이 필드로 표현할 수 없다. (1) "X 그리고 (A 또는 B)" 꼴의 줄: CAROLINA 배제 [17](NYHA class III 또는 IV인 울혈성 심부전)과 [20](폐경 전 여성의 수유·임신·피임, 하위 항목 16개). `all`로 적으면 모든 하위 항목 기록이 있는 환자만 배제하고, `any`로 적으면 지금처럼 하나만 있어도 배제한다. (2) 예정된 사건과 과거 사건을 한 줄에 적은 CAROLINA [14]와 PLATO [6]. `prospective`로 적으면 과거 부분까지 빠지고, `prior`로 적으면 지금처럼 과거 기간 규칙으로 나가며 `_windowDisagreement`가 기록된다. (3) PLATO "≥2 of the following": Agent 1 IR과 저장소에 하위 항목이 1개만 있어 `at_least` 2를 적용할 수 없다. (1)·(2)는 추출 단계가 중첩 묶음을 내거나 줄을 나눠야, (3)은 추출 단계가 하위 항목을 모두 내야 고칠 수 있다.

## 1. 원칙

- 문장의 뜻은 LLM이 정한다. 코드는 LLM이 낸 근거 조각이 `protocolLine`의 부분 문자열인지만 확인한다(`decomposer.py` gate 1과 같은 방식).
- 근거 조각이 원문에 없으면 그 필드는 없는 것으로 보고 기본 동작을 쓴다. 거절한 이유는 기준에 남겨 게이트가 센다.
- vocabulary 이름을 문자열로 읽지 않는다. 필요한 것은 `concept_relationship`, `concept_ancestor`, LOINC parts, ATC 코드로 얻는다. 그것으로 얻을 수 없는 판단은 LLM(critic)이 후보를 보고 정한다.
- 프롬프트에는 예시를 넣지 않는다. 필드마다 정의만 쓴다.

## 2. 주석 단계

Agent 1 스키마에 필드를 계속 더하지 않는다. 규칙(rule)마다 별도의 LLM 호출 한 번을 둔다.

- 입력: `protocolLine`, 그리고 이미 추출된 `entity_text`, `domain`, `logic_type`, `window`, `value_constraint`, 하위 항목 목록.
- 출력: 아래 필드와 각 필드의 근거 조각.
- 위치: planner 다음, Agent 2 앞. 저장소에 `annotation`으로 기록한다.
- 캐시 키: `protocolLine` + 추출된 필드 + 주석 프롬프트 버전.

Agent 1에 넣지 않는 이유는 세 가지다.
- gemma-4-E4B는 스키마가 커지면 다른 필드까지 흔들린다. P1에서 바꾼 Agent 1을 다시 흔들지 않는다.
- 행 단위로 A/B를 비교하기 쉽다. 주석만 다시 돌리면 되므로 재추출(약 132분)이 필요 없다.
- 실패해도 그 기준만 기본 동작으로 돌아간다.

## 3. 필드와 대체하는 규칙

| 필드 | 값 | 근거 조각 | 대체하는 규칙 |
| --- | --- | --- | --- |
| `record_requirement` | required / forbidden / conditional | `conditional_span` (conditional일 때 필수) | A19 `dose_stability`. 기존 `conditional: bool`을 흡수하고, `_criteria_from_ir`의 무기록 삭제를 skip 기록으로 바꾼다 |
| `excepted_entities` | `[{text, span}]` | 항목마다 `span` | A8, A11 `entity_exception`, A25 |
| `relation` | all / any / at_least | `relation_span`, at_least면 `cardinality` | A2 Pattern E 낱말 묶음, A6 `[OR-GROUP]` 접기, A18 ALL→ANY·AT_LEAST, A14 " or " 분할 |
| `timing` | prior / at_index / prospective | `window_span` | A4 `temporal_grounding`(단위→일 환산은 기계 형식이라 유지), A10 seed의 기간 잘라내기(대신 `entity_text`가 비면 거절하고 기록), E3 |
| `quantity_kind` | lab_value / dose / duration / count / statistical / other | `threshold_span` | A1 `<=` 판정, A5a 영어 비교어 해석과 Step 6·8 재부착, A5b 수치 거절, A29 게이트 (j) |
| `reference_bound` | uln / lln / none (기존 필드) | `threshold_span` | A21. 저장소의 `unitText`에만 ULN이 있는 12행은 주석으로 다시 채운다 |
| `route` | oral / parenteral / topical / inhaled / any (값 목록은 OMOP dose form group에서 확정) | `route_span` | A12 `route_qualifier`, C2 `dose_form_route` |
| `specimen` | blood / urine / other / any | `specimen_span` | A17 `loinc_specimen`의 낱말 판정, C3 |
| `no_entity` | none / refers_elsewhere / investigator_judgement | `no_entity_span` | A16 placeholder 낱말 목록 |

`relation`과 `excepted_entities`는 planner가 하위 항목을 나누는 결정에 쓰인다. 그래서 이 둘만 planner 출력에도 같은 이름으로 둔다. 주석 단계는 planner가 비운 경우에만 채운다.

추가(구현 중 합의): `excepted_entities`에는 형제 필드 `base_span`(예외를 빼는 대상 집합을 가리키는 `protocolLine` 조각, 부분 문자열일 때만 채택)을 둔다. 채택되면 그 기준의 매퍼 시드를 대신하고, 없거나 거절되면 시드는 그대로 두고 거절을 기록한다. 시드에 예외 절까지 들어 있는 행(CAROLINA 배제 68, LEADER 배제 39–41)에서 옛 정규식이 하던 기준 분리를 대신한다.

## 4. 구조적 데이터로 바꾸는 것

| 규칙 | 대체 |
| --- | --- |
| A20 분석물→단위 표 | 하위 항목 개념의 LOINC Property(`loinc_specimen`의 기계 형식 부분) |
| A22 placebo 팔 이름 | ClinicalTrials.gov `armGroups[].type`. 저장소에 없으면 가져와 저장 |
| A26 두 경계 합치기 | 같은 store 묶음·같은 `protocolLine` + 기존 closure 검사 |
| A27 여집합 배제 제거 | 두 기준의 구조화된 op 비교(이미 있음) |
| A28 혼동 분석물 | 집합 구성원의 LOINC `Has component` |
| C1 RxNorm 제품명 → 성분 | `Has ingredient` / `concept_ancestor` |
| C5 ATC 이름 비교 | ATC 코드 계층 |
| C2 dose form 이름 → 경로 | dose form group 관계(있는지 먼저 측정). 없으면 `route` 필드와 후보 dose form을 critic이 대조 |
| C3, A17 혈액 검체 낱말 | 판정을 critic에 넘긴다. 후보 LOINC 개념과 `specimen` 필드를 보고 고른다 |
| C4 개념 이름 겹침 가산점 | 삭제. 임베딩·reranker 점수만 쓴다 |
| C7 집합 이름 = 개념 이름 | 삭제. 과대 배제 집합은 critic이 다룬다 |
| C8 질환 entry 토큰 Jaccard | registry condition을 Agent 2 매퍼로 매핑 |

## 5. 교체 없이 지우는 것

- A3, A13(약어 확장표 4개), A15, A23, A24: 현재 후보에 영향이 없거나, 이미 있는 필드로 충분하다.
- A7(중복 판정 낱말): 경로 밖에 LLM 판정기(`criteria_dedup_judge.py`)가 있다. 연결할지 판정 자체를 없앨지는 측정 후 정한다.
- A9 gate 2(`FUNCTION_WORDS`): gate 1(부분 문자열)만 남긴다.
- E6(`restated_clusters._TRAILING_PARENTHETICAL`): 설명문 대신 구조화된 필드(도메인, 개념 집합, 기간, 값 조건)로 중복을 판정한다.
- 문서 구간 나누기 S1–S5, S7, S8: LLM 구간 경계 단계 하나로 바꾼다. 출력은 포함·배제 구간의 시작과 끝 조각이고, 코드는 부분 문자열인지만 확인한다. S3의 제약사 이름 목록도 여기서 사라진다.
- S6(지수 숫자 재결합): 삭제. LLM이 원문을 읽는다.
- S9(파일 이름의 appendix/supp): 우리 저장소의 파일 이름 규약이라 B로 옮긴다. "Downloaded from"/"Copyright" 줄 제거는 삭제한다.
- 경로 밖·죽은 코드 11묶음: P5에서 삭제.

## 6. 실행 순서

1. **주석 단계 + `record_requirement` + `excepted_entities`.** RFC-015 범위다. 가장 큰 결함(EMPA-REG treatment 0명, 배경약 규칙)을 다루므로 먼저 한다. A19, A8, A11, A25를 지운다.
2. `relation`, `timing`. RFC-014 범위다. A2, A4, A6, A10, A14, A18을 지운다.
3. `quantity_kind`, `reference_bound`, `threshold_span`. A1, A5a, A5b, A21, A29를 지운다.
4. `route`, `specimen`, `no_entity`, 그리고 4절의 구조적 대체. A12, A16, A17, A20, A22, A26–A28, C1–C8을 지운다.
5. 5절의 삭제와 구간 나누기 단계.

각 단계는 실패하는 테스트를 먼저 쓰고, 지운 규칙의 장부 항목을 함께 지운다(`test_no_text_rules.py`가 강제한다). 단계마다 커밋한다.

## 7. 측정

- **실행 전 예측.** 장부의 "지웠을 때 영향" 열(`docs/inventory/2026-10-12_text_rules.json`의 `candidate_effect_if_deleted`)에서 행을 고른다. 각 행이 주석 필드로 같은 결과를 내는지 본다.
- **주석 단계만의 A/B.** 주석은 재추출 없이 다시 돌릴 수 있다. 같은 IR에 주석 프롬프트 두 벌(본 프롬프트 / 정보 없는 변경)을 돌려 행 단위로 비교한다.
- **P6.** 재추출 + 재빌드 + gold 기준별 대조(±0.02) + 게이트. P2와 같은 두 갈래(본 실행 / 플라시보).
- **근거 조각 확인 실패 건수.** 필드마다 센다. 0건이면 확인 경로가 실제로 돌지 않았는지 먼저 의심한다.

## 8. 위험

- **주석 호출 수.** 6개 시험에서 기준 수백 개가 늘어난다. 기준 하나당 1회이고 캐시된다. P2 실행에서 Agent 1 한 시험이 약 22분 걸린 것과 비교해 측정한다.
- **모델이 필드를 과하게 채움.** 특히 `conditional`, `excepted_entities`, `no_entity`가 그렇다. 기준 손실이 생기는데 게이트로는 보이지 않으므로, 이 세 필드가 채워진 행은 전부 원문과 대조한다.
- **critic으로 넘긴 판단(검체, dose form).** critic 출력이 깨지면 seed로 돌아가는 기존 결함이 이 판단에도 영향을 준다. 그 경우 몇 건이 seed로 돌아갔는지 센다.

## 9. 결정 요청

- 주석 단계를 Agent 1과 분리된 호출로 둘지(권장), 아니면 RFC-014·015처럼 Agent 1/planner 스키마에 넣을지.
- 6절의 순서.
- A7(중복 판정)은 LLM 판정기를 연결할지, 판정 자체를 없앨지.
