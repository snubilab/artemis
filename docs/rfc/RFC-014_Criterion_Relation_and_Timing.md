# RFC-014: 기준의 결합 관계와 시점을 추출 단계에서 기록한다

**상태**: 설계 합의 대기
**날짜**: 2026-10-11
**근거**: 진단 산출물 `scratchpad/diag_structure/`(세션 13f2e2ed), 분석 문서 `docs/site_data_request/2026-10-06_inclusion_report_0923_from_ajou_and_donga.md`

## 1. 문제

두 결함 모두 09-12 발송본부터 있었고 현재 발송 후보(`output/site_gap/2026-10-11_final_t1dfix2/`)에도 남아 있다. 둘 다 gold 기준별 대조(concept-set closure)로는 드러나지 않는다. 대조는 묶음 방식과 기간을 계산에 넣지 않기 때문이다.

### 1-1. 여러 조건을 '모두' 요구하는 문장이 ANY로 만들어진다

- CAROLINA 포함 규칙의 protocolLine은 "Documented diagnosis of T2DM **and concurrently** insufficient glycaemic control **and** a high risk of CV events prior to informed consent:"이다. 저장된 기준은 PRESENCE/ANY이고, 발송 파일에서 세 조건 중 하나만 있어도 규칙이 만족된다.
- 출처는 planner다. Agent 1 IR(`data/cache/agent1_ir/NCT01243424_…_cfd9dbd5a98266e1.json`)은 이 기준을 나누지 않았고, planner가 세 개로 나누면서 `src/agents/planner/decomposer.py:469`가 `group_type`을 `logic_type`만으로 정했다(PRESENCE→ANY, ABSENCE→ALL). planner 출력 스키마(`src/agents/planner/prompts.py:117-130`)에는 원문에서 조건들이 어떻게 이어지는지 담을 필드가 없다.
- 빌더(`src/services/tte_service.py:545-569`)는 PRESENCE/ANY 묶음을 바꾸지 않는다. 재빌드는 planner를 다시 돌리지 않으므로 저장된 ANY가 그대로 남는다.
- 같은 원인으로 배제 쪽이 넓어진다. ABSENCE 묶음은 늘 ALL("하나라도 있으면 배제")이 되어, CAROLINA "Congestive heart failure of NYHA class III or IV"와 LEADER "Chronic heart failure (NYHA class IV)"가 심부전 전체를 배제하고, CAROLINA 임신·피임 기준은 16개 항목이 각각 배제 규칙이 된다.
- ALL로만 바꾸는 것도 답이 아니다. CAROLINA의 두 번째·세 번째 항목은 뒤 문장들(HbA1c 규칙, 심혈관 위험 OR 묶음)이 정의하는 용어를 되풀이한 것이라, ALL로 묶으면 나이·위험 인자만으로 자격이 되는 환자가 빠진다. gold에는 이 머리 규칙이 없다.

### 1-2. 앞으로 예정된 사건이 과거 기간으로 만들어진다

- CAROLINA "Pre-planned coronary artery re-vascularisation (PCI, CABG) within next 6 months after V1a or any previous PCI and/or CABG ≤ 6 weeks prior informed consent"는 ABSENCE, 기간 `[-9999, 0]`인 규칙 하나로 저장됐다. 예정된 절반은 과거 기록으로 찾고, 과거 절반의 6주(`[-42, 0]`, gold 규칙 10과 같다)는 사라졌다. 배송 게이트 검사 (x)가 이 규칙을 FAIL한다.
- Agent 1 스키마(`src/agents/agent1/prompts.py:40-42`, `249-251`)는 index 기준의 과거 기간만 표현한다. `[-9999, 0]`은 Procedure 도메인 기본값(`src/utils/circe_lint.py:559`)이고, 같은 문장의 이전 IR은 `[-42, 0]`이었다.
- 창 보정 `_repair_protocol_windows`(`parser.py:1682`)는 `temporal_grounding.stated_interval`이 `(None, None)`을 돌려줘 아무것도 하지 않는다. `temporal_grounding._direction`(`:136-158`)은 가장 가까운 방향 낱말을 골라, EMPA-REG "Planned cardiac surgery or angioplasty within 3 months"를 90일 과거 기간으로 확인해 준다.
- 6개 시험에서 같은 모양이 9건이다: CAROLINA `[14]`, CARMELINA `[4]`, EMPA-REG `[8]`, LEADER `[19]`·`[22]`, PLATO `[10]` 항목·`[6]`, ARISTOTLE `[11]`·`[12]`.

## 2. 제안

### 2-1. 결합 관계 필드

1. planner 출력 스키마에 `relation`("all" 또는 "any")과 `relation_span`(그 관계가 드러나는 원문 조각)을 더한다. `relation_span`은 `_grounded_span`이 `source_span`을 확인하는 방식 그대로, protocolLine의 부분 문자열인지 확인한다. 모델이 문장에 없는 하위 항목을 보탠 경우(근거 조각 없음)는 'any'로 본다.
2. `decomposer.py:469`는 두 필드로 묶음 방식을 정한다.

   | logic | relation | group_type |
   | --- | --- | --- |
   | PRESENCE | all | ALL |
   | PRESENCE | any | ANY |
   | ABSENCE | any | ALL |
   | ABSENCE | all | ANY |

   문장에서 나온 항목이 둘 이상인데 `relation`이 없거나 `relation_span`이 원문에 없으면 나누기를 거절한다(`_torn_range_declined`와 같은 처리). CAROLINA 머리 규칙은 나누기가 거절되어 "T2DM" 하나로 남고, 뒤 규칙들과 함께 프로토콜과 같은 의미가 된다.
3. 기준에 `relation`을 저장하고, 근거 조각이 확인된 관계는 `tte_service.py:556-562`의 묶음 방식 재작성이 덮어쓰지 않게 한다.
4. Agent 1이 직접 만드는 묶음에도 같은 필드를 쓴다(CARMELINA 묶음 85eaf366).

### 2-2. 시점 필드

1. Agent 1 스키마에 규칙별 필수 필드 `timing`을 더한다: 과거 이력(prior), index 시점 상태(at_index), 예정·index 이후(prospective). 한 문장에 둘이 섞이면 규칙 두 개로 나눈다. 프롬프트는 이미 나눈 규칙마다 원문을 되풀이하도록 요구한다.
2. prospective 규칙은 occurrence 기간으로 내보내지 않는다. 허용된 skip 사유("index 시점에 관찰할 수 없음", 원문 포함)로 기록해 게이트가 누락으로 세지 않게 한다. planner는 기간·logic과 같이 이 필드를 하위 항목에 넘긴다.
3. `circe_lint.py`에 검사를 더한다: prospective 기준이 CIRCE occurrence로 나가면 FAIL.
4. `_direction`이 한 기간 앞에 두 방향 낱말을 모두 보면 고르지 않고 거절하게 한다(기존 낱말 목록을 건드리므로 선택 사항).

두 제안 모두 특정 시험·개념·표현을 코드에 넣지 않고, 프롬프트에 예시를 넣지 않는다.

## 3. 실행 전 예측

- CAROLINA T2DM 머리 규칙이 ALL이 되거나 "T2DM" 하나로 남는다(treatment·comparator 둘 다).
- CAROLINA `[17]`·`[20]`, LEADER `[18]`이 더는 심부전 전체·가임기 여성 전체를 배제하지 않는다. LEADER 심부전 짝의 검사 (x) FAIL이 사라진다.
- 원문에서 '또는'으로 이어진 묶음은 그대로 남는다: CAROLINA a3e8f106, ARISTOTLE 0a570408, PLATO 31523358·951d934e, EMPA-REG f0cf6a7d, 모든 "X or Y" 배제.
- 1-2의 9건이 과거 기간으로 나가지 않는다. CAROLINA PCI/CABG의 과거 절반은 `[-42, 0]`, CARMELINA는 `[-60, 0]`이 된다. 검사 (x)는 CAROLINA·PLATO에서 0건이 된다.

## 4. 측정

- LLM 없이 먼저: planner 분해 테스트(LLM 스텁, 현재 코드에서 relation과 무관하게 ANY가 나오는 것을 실패로 먼저 보인다), 근거가 확인된 ABSENCE/all 묶음이 빌드 뒤에도 ANY로 남는 빌더 테스트, 실제 CAROLINA 기준으로 만든 저장 행에서 FAIL하는 lint 테스트. 현재 저장소에는 timing 필드가 없어 lint가 현재 데이터에서는 아무것도 시험하지 않으므로, 실제 행으로 만든 음성 사례가 필요하다.
- 행 단위 판정: 위 예측 목록의 묶음 방식과 기간을 행마다 확인한다. planner와 Agent 1은 실행마다 결과가 달라지므로 플라시보 조건(정보 없는 프롬프트 변경)을 함께 돌린다. 이전 측정에서 플라시보 변경만으로 기준의 약 3분의 1이 바뀌었다.
- concept-set closure 대조는 이 변경을 0으로 채점한다. 판정에는 검사 (x) 건수와 gold 규칙 10의 기간을 쓴다.

## 5. 비용과 위험

- Agent 1 스키마 변경은 IR 캐시를 무효로 만든다. 6개 시험 재추출에 약 132분이 든다. 먼저 DECLARE(NCT01730534)에 `prompt_ab.py`로 시험한다.
- planner 변경은 IR 캐시 키(`parser.py:397`)를 바꾸지 않지만, 재빌드 경로가 planner를 다시 돌리지 않으므로 재수집(reingest)이 필요하다.
- 재추출하면 이번 수정과 관계없는 기준도 다시 뽑힌다. 그 변동은 플라시보 조건으로 따로 센다.

## 6. 확인하지 못한 것

- planner의 temperature와 seed.
- LEADER·PLATO·ARISTOTLE 저장 행을 만든 IR은 이름 겹침으로 짝지었다. 이 세 시험의 "planner가 만들었다"는 표시는 추정이다.
- PLATO fibrinolytic 행이 `-24`일을 유지하는 이유.
- LEADER 재관류술 짝을 검사 (x)가 놓치는 이유(concept closure를 비교하지 않았다).

## 7. 결정 요청

2-1과 2-2를 이 설계대로 진행할지, 순서(2-1만 먼저, 2-2는 DECLARE 시험 뒤)를 바꿀지 결정이 필요하다.
