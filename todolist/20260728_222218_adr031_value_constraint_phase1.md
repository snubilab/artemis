# ADR-031 값 조건 의미 보존 — 1단계 (차단 해제) - 2026-07-28

## 요구사항 분석

- [x] 결함 규명: `ALT > 3x ULN` → `ValueAsNumber {Value:3, Op:gt}` (tte_service.py:5671)
- [x] 해결 경로 확정: Circe `RangeHighRatio`/`RangeLowRatio`/`Unit` — gold가 32/85 사용, 생성물 0/42
- [x] 테스트 코퍼스 구축: 프로토콜 90개 → 114건, 출처 45곳
- [x] RED 확인: 321 실패 / 6 통과 / 1 skip
- [x] 설계 문서: ADR-031 (결정 D1~D9, 3단계)

## 구현 계획 — 1단계 (D1·D3·D4·D5 + mg 버그)

### 그룹 A — 선행, 서로 독립 (사소)
- [x] A1. `ValueConstraint`에 `reference_bound: Literal["absolute","uln","lln"]` 추가 — `src/models/ir.py:51`
      검증 완료: uln 수용 / 기본값 absolute / 잘못된 값 거부 확인
- [x] A2. `UNIT_MAP["mg"]` 8587(millilitre) → 8576(milligram) 수정 — `src/agents/agent3/mappings.py:73`
      검증 완료: DB 조회 결과 8576 = milligram

### 그룹 B — 공유 모듈 (A 이후, 단일 단위)
- [x] B1. `normalize_unit(unit_text) -> int | None` — NFKC·이스케이프 제거·별칭·UCUM 조회, 실패 시 None
      검증 완료: 코퍼스 단위 37종 전수 일치(불일치 0), `bpm`·`cups per day`는 None. 단위표 27개 DB 정합 확인
- [x] B2. `build_measurement_value_filter(vc) -> dict` — D4 매핑표
      검증 완료: uln→`RangeHighRatio`만(ValueAsNumber 미동반), lln→`RangeLowRatio`만,
      absolute+해소→`ValueAsNumber`+형제 `Unit`, absolute+미해소→`Unit` 미설정
- [x] B3. `unit_text` → `reference_bound` 역호환 복원
      검증 완료: `x ULN`/`xULN`/`X ULN`/`3 x upper limit of normal (ULN)` → uln.
      `reference_bound` 미지정 legacy IR이 `RangeHighRatio`로 출력됨

### 그룹 C — 라우팅 (B 이후, 서로 독립 — 병렬 수행)
- [x] C1. `tte_service.py:5664` 생산 경로를 B 모듈로 라우팅
      검증 완료: `test_production_builder_*` 6건 전부 통과
      추가 발견·수정: `_criterion_dict_from_ir_item:9339`가 model→dict 변환에서
      `reference_bound`·`unit_concept_id`를 누락시키고 있었다. 이걸 안 고쳤으면
      기존 IR(`unit_text="x ULN"`)만 구제되고 신규 추출은 그대로 틀렸다.
- [x] C2. `assembler.py` 라우팅 + `_build_value_constraint` 삭제
      검증 완료: 실물 출력 6분기 확인 — uln→`RangeHighRatio`만, lln→`RangeLowRatio`만,
      절대+`%`→8554, 절대+`kg/m²`(위첨자)→9531, 미해소→`Unit` 없음, legacy→`RangeHighRatio`.
      `Unit`이 `ValueAsNumber` 안에 중첩되지 않음을 단언으로 확인

### 그룹 C-추가 — 실행 중 발견
- [x] C3. `tests/test_agent3.py::test_build_value_constraint` 재작성
      기존 테스트가 **결함을 고정**하고 있었다 — `result["Value"]`와 `"Unit" in result`를
      같은 dict에 단언해, `Unit`이 `ValueAsNumber` 안에 중첩돼야만 통과한다(Circe가 무시하는 구조).
      gold 형제 구조로 재작성 + uln 분기 테스트 추가. 검증 완료: 10 통과

### 그룹 D — 검증 (C 이후, 순차)
- [x] D1. 1단계 범위의 코퍼스 테스트 통과 — 321 실패 → **268 실패 / 69 통과** (+63)
      ※ 최초 목표 "327 통과 / 0 실패"는 잘못 적었다. 남은 268건은 전부 2단계
      (`parse_value_constraint`가 `NotImplementedError`) + 재생성 필요 2건이다.
      1단계가 담당하는 정규화·빌더·라우팅 계층은 전부 통과
- [x] D2. 기존 스위트 회귀 없음
      검증 완료: 변경 전후 실패 ID 집합 대조 — **신규 실패 0건**, 수정 53건.
      (전체 389 실패 / 969 통과 / 19 에러 — 실패·에러는 `langgraph`·`pandas`·
      `python-multipart` 미설치로 인한 기존 상태)
- [x] D3-a. 재생성 시 산출물 확정 (비파괴 측정)
      저장된 6개 스터디의 고유 값 조건 **29건 전수**를 수정된 빌더에 통과시킨 결과:
      `RangeHighRatio` 0 → **2** (EMPA-REG·CARMELINA의 `x ULN` 전부),
      `Unit` 0 → **24**, 무단위 3건은 정당하게 미설정 → **24+2+3 = 29, 100% 정확 처리**.
      RHR+VAN 동반 0. 기존 `UNIT_MAP` 누락분 전부 해소:
      `kg/m²`(위첨자)→9531, `ml/min/1.73 m2`→720870, `years`→9448, `mV`→720843
- [ ] D3-b. `process_eligibility` 재실행으로 `structuredExpression` 갱신 (보류 — 사용자 판단 대기)
      파괴적(스토어 덮어씀) + 개념 매핑이 openrouter gpt-4o 호출을 다수 발생시킴.
      실행 전까지 `data/generated/`와 store의 산출물은 구버전 Circe를 유지한다

### 지표 정정 — "gold 32건과 동등"은 성립하지 않는 비교였다

gold는 `No liver disease` 규칙 하나에 ALT·AST·ALP를 **별도 Measurement 객체 3개**로 쓴다
(EMPA-REG treatment 단독 RHR 3건). 우리는 **개념셋 하나 + Measurement 객체 1개**다.
둘 다 유효한 Circe이고 세는 단위가 달라, 개수 대조는 의미가 없다.
올바른 지표는 **"ULN 조건 중 RangeHighRatio로 나온 비율"** — 현재 2/2 (100%).

PLATO 원문(NCT00391872)에는 ULN 언급이 0건이다. 추출 누락이 아니라 애초에 없는 조건이며,
앞서 다른 시험의 문구를 PLATO 것으로 착각했다.

## 의존성

```
A1 ─┐
A2 ─┴─→ B1 → B2 → B3 ─┬─→ C1 ─┬─→ D1 → D2 → D3
                       └─→ C2 ─┘
```

- A1·A2 병렬 가능 (다른 파일)
- B1~B3 동일 신규 파일 — 단일 단위로 처리
- C1·C2 병렬 가능 (다른 파일, 둘 다 B에 의존)
- D는 순차

## 2단계 — 결정적 파서 (D2·D6·D7·D8)

재생성(D3-b)보다 먼저 한다. 2단계 후 한 번만 재생성하면 LLM 비용이 절반이다.

- [x] E1. `parse_value_constraint(phrase) -> ValueConstraint | None`
      임계값 구문 하나 → 조건 하나. 연산자·값·`reference_bound`·단위 추출.
      검증 완료(2026-07-29 통합 확인, 커밋 114af5a 고정): 코퍼스 파라미터 테스트
      `test_parse_classifies_reference_bound`·`test_parse_extracts_operator_and_value`·
      `test_unit_spelling_normalises_to_concept_id`·`test_unresolvable_unit_returns_none_rather_than_guessing`
      합계 **144건 전수 통과**
- [x] E2. 부정 케이스 거부 — 신뢰구간 상한·범위·기간·단위환산 재기술 → `None`
      검증 완료: `test_non_constraints_are_rejected` **17건** 통과
      (계획 시점 14건 → 코퍼스가 늘어 17건. 숫자를 실측으로 정정)
- [x] E3. `parse_value_constraints(line) -> list` — 문장을 구문으로 분리 후 E1 매핑
      검증 완료: `TSH >1.2 ULN or <0.8 LLN` → `[(gt,1.2,uln), (lt,0.8,lln)]`
      (`python src/services/value_constraint.py` self-check 통과)
      [주의] 이 함수는 **테스트 스위트에 테스트가 없고, 프로덕션 호출자도 없다.**
      검증 근거는 모듈 자체의 `demo()` 뿐이다. 유일한 다른 언급은
      `threshold_classifier.classify_criterion`의 **독스트링 예제**로, 실행되는 코드가 아니다
- [x] E4. 전체 검증 — 코퍼스 **268 실패 → 2**, 기존 스위트 회귀 **0**
      계획서의 "268 → 0"은 달성 불가한 목표였다. 남은 2건은 파서 결함이 아니라
      D3-b(재생성) 미실행 때문이며, 아래 "잔여 2건" 절에 원인을 적었다.
      회귀 0은 워크트리 대조로 확인 (bc33ccc vs d1747e0, 신규 실패 ID 0건)

### 설계 확정 — 단수/복수는 충돌이 아니다

서브에이전트가 "테스트는 단수, ADR D7은 복수"를 모순으로 보고했으나, 입도가 다른 두 함수다.
코퍼스도 `threshold_phrase`(구문)와 `source_text`(문장)를 따로 저장한다.
단수는 구문 하나를 파싱하고, 복수는 문장을 구문으로 쪼개 단수를 매핑한다.
테스트 재작성 불필요.

## 2단계 재설계 (2026-07-29) — 파서를 별도 LLM 기능으로

문헌 조사(TrialGenie·Chia) 결과 판별 기준이 **단위가 아니라 head(수식 대상)** 이고,
head 식별은 구문 규칙으로 안 된다(정규식 시도 실패: 값 조건 97건 중 62%만 해소).
→ **분해·분류는 LLM, 구조화는 코드.** 3단 구조로 재설계한다.

```
① 분해 (LLM)     eligibility 전문 → 원자 criterion 목록
② 분류 (LLM)     criterion → span별 { class, head, threshold_phrase }
③ 구조화 (코드)   span → (op, value, reference_bound, unit) → Circe
```

확정 사항: ②는 **별도 단계로 신설**(Agent 1에 합치지 않음) · 모델은 **로컬 vLLM
(snuh/hari-q3-8b)** · `CONDITION_DURATION`은 **지금 Circe 표현을 설계**.

[HARD] ②의 출력은 criterion당 class 하나가 아니라 **span별 class**여야 한다.
`LVEF \< 40% measured within 6 months`는 값 조건과 시간창이 동시에 필요하고,
코퍼스에 한 문장 두 조건 사례가 12건 있다. enum이 아니라 집합으로 설계할 것.

- [x] F1. 로컬 vLLM 전제 조건 — `<think>` 제거를 `get_llm` vLLM 분기 wrapper로
      검증 완료: 테스트 5건 통과 + 실제 vLLM 호출에서 JSON 파싱 성공. 커밋 a5ae5d2
- [x] F2. 분류 체계 도출 — 9개 class로 코퍼스 114건 전수 배정. `--check` 통과
      초안 정정 2건: `EVENT_QUANTITY` 누락(헌혈량·치료 차수), `CONDITION_DURATION`→`STATE_DURATION`
      (2건 중 1건이 약물 안정성 기간이라 질환에 한정되지 않음)
      프롬프트는 `--prompt`로 JSON에서 렌더 — 둘이 어긋날 수 없음
- [x] F3. 대시보드 분류 체계 탭 — 렌더·딥링크·콘솔에러 0 확인
- [x] F4. `CONDITION_DURATION` Circe 표현 — ADR-031-A
      `ConditionOccurrence` + 과거로 열린 `StartWindow`. gold가 같은 형태를 28회 사용(독립 확인)
      실측: 정답형 17명 vs 방향 반대인 순진한 형태 2명 — 오분류가 자릿수 차이이고 조용함
      `ConditionEra.EraLength`는 실측 기각(synthea HIV era 전원 1일 → 0명, 사이트 3/4에 테이블 부재)
- [x] F5. 분류기 구현 (②) — 로컬 vLLM · 커밋 d1747e0
      검증 완료: `src/agents/agent1/threshold_classifier.py` 454줄,
      `tests/test_threshold_classifier.py` **60건 전수 통과**.
      캐시에 남은 실제 모델 응답으로 G0~G7 게이트 동작 확인 —
      `=> 3 x upper limit of normal (ULN)` → `MEASUREMENT_VALUE` →
      `{"RangeHighRatio": {"Value": 3.0, "Op": "gte"}}`
      [미검증] 아래 3가지는 이번 통합에서 **확인하지 못했다**
      1. **배선 없음.** `classify_criterion`/`classify_criteria`의 호출자는
         테스트와 `scripts/eval_threshold_classifier.py` 뿐이다. 프로덕션 경로 0곳.
         ②→③ 연결은 독스트링에만 있고 실행되지 않는다
      2. **라이브 실행 없음.** `VLLM_BASE_URL`이 connection refused.
         이번 패스의 모든 ② 결과는 `data/cache/threshold_spans/`의 86건 캐시에서 나왔다
      3. **다분석물 head 손실 (신규 실측).** 아래 절 참조
- [ ] F6. `LLM_MODEL` 전환 + 파이프라인 전체 로컬 검증
      커밋 6ed6a8d(`fix(llm): make LLM_MODEL move the whole pipeline`)가 12:34에 올라왔고
      코퍼스·분류기 테스트는 영향 없음(2 실패 / 379 통과, d1747e0과 동일)을 확인했다.
      그러나 "파이프라인 전체 로컬 검증"은 vLLM이 죽어 있어 **수행 불가** → 미완으로 둔다

## 통합 확인 (2026-07-29 12:2x~12:4x) — 실행 기반

측정은 워크트리 대조로 했다. `git stash`는 이미 한 번 사고를 냈고, 총계는
무관한 이유로 움직이므로 **실패 ID 집합**만 비교했다.

| | bc33ccc (전) | d1747e0 (후) |
|---|---|---|
| 실패 ID (FAILED+ERROR) | 458 | 196 |
| 통과 | 899 | 1221 |
| skip / collection error | 28 / 19 | 28 / 19 |

- **신규 실패 0건.** 해소 262건, 전부 `tests/test_value_constraint.py`
- 통과 증가 322 = 해소 262 + 신규 테스트 60(`test_threshold_classifier.py`). 산술 일치
- collection error 19건은 전후 동일 — `langgraph`·`pandas`·`python-multipart` 미설치

### 잔여 2건 — 코퍼스 (319 통과 / 2 실패 / 1 skip)

둘 다 코드가 아니라 **커밋된 산출물**을 읽는 테스트다. D3-b 재생성 전까지 붉다.

- `test_generated_cohorts_use_range_high_ratio_like_gold` — gold 32/81 vs 생성 0/40
- `test_generated_cohorts_set_unit_on_measurement_criteria` — 생성 40건 중 Unit 0건

`data/generated/empa_reg/empa_reg_treatment.circe.json`은 지금도
`RangeHighRatio` 0회 / `ValueAsNumber` 8회이고, 그 중 `{"Value": 3.0, "Op": "gt"}`가
3개다. 즉 **결함은 코드에서 고쳐졌고 데이터에는 그대로 남아 있다.**

저장된 IR의 고유 값 조건 23건을 수정된 빌더에 통과시킨 결과(독립 재측정):
`Unit`+`ValueAsNumber` 18 · `ValueAsNumber` 단독 3(단위 미해소, 정당) ·
`RangeHighRatio` 2. RHR과 VAN이 함께 나온 건 0건.

### 신규 실측 — ②의 다분석물 head 손실 (G7이 구조적으로 못 잡는다)

한 임계값이 여러 분석물을 덮는 문장에서 모델이 head를 하나만 반환한다.
숫자는 살아남은 span이 이미 claim했으므로 **G7 숫자 리콜망에 걸리지 않는다.**

캐시된 실제 응답 중 ALT와 AST를 **둘 다** 명시한 기준선:
기본 프롬프트(`every_numeral=False`) **15건 중 4건이 한쪽을 잃었다.**

```
LOST  heads='ALT'   3. Active liver disease ... ALT (SGPT), AST (SGOT), or alkaline phosphatase (AP) => 3 x ULN
LOST  heads='AST'   Aspartate aminotransferase (AST) or alanine aminotransferase (ALT) in conjunction with GGT
LOST  heads='AST'   Serum aspartate aminotransferase (AST) / alanine aminotransferase (ALT) >5 x ULN
LOST  heads='aspartate aminotransferase (AST) | total bilirubin'   Presence of liver disease (... ALT / AST ...)
```

첫 줄은 CARMELINA의 간 기준선으로, **EMPA-REG 간 기준선과 같은 모양**이다.
모델 원문은 span 하나뿐이었고 게이트는 아무것도 버리지 않았다 — 손실은 모델에서 났다.

대조적으로 ①(Agent 1)은 같은 EMPA-REG 문장을 ALT·AST·ALP **세 개**의
sub_criteria로 정확히 분해한다. 즉 지금 ③을 ②에 배선하면 다분석물 기준선에서는
**현재 ① 경로보다 나빠진다.** 배선 전에 해결해야 한다.

부수 확인: `every_numeral=True`는 `1. ALT or AST > 1.5 × ULN`에서 head를 `ALT`로
줄였다(기본값은 `ALT or AST`로 정상). 플래그가 느리기만 한 게 아니라 해로울 수 있다.

### ③은 되는데 ②를 EMPA-REG 문장으로 직접 확인하지 못했다

해당 문장은 span 캐시에 없고 vLLM은 죽어 있다. 게이트는 설계대로
`REVIEW / "model returned no span list (gate 0)"` 하나로 안전하게 떨어졌지만,
그건 모델이 맞았다는 증거가 아니다. 같은 모양의 캐시된 문장 3건으로 대신 확인했다.

또한 저장된 EMPA-REG IR에는 `source_text`가 **없다**(b536b1e 이전 캐시).
재추출 전까지 저장된 스터디는 ②에 넣을 수 없다.

### 측정 중 트리가 움직였다

다른 에이전트가 작업 중 `threshold_classifier.py`·`utils/llm.py`·`critic.py`를
고치고 12:34에 6ed6a8d를 커밋했다. 그래서 위 수치는 전부 **워크트리에 고정**했다.
라이브 트리(6ed6a8d + 미커밋 `critic.py`)는 124 실패 / 1306 통과이고,
d1747e0 대비 추가 실패 4건은 이 작업과 무관하다:

- `test_criterion_cache.py::TestSingleton` 2건 — `tmp/tte/criterion_cache.sqlite`가
  root 소유 644라 테스트 프로세스가 못 쓴다. 코드는 bc33ccc와 **동일**하고,
  기준선 코드로도 같은 에러가 난다. 환경 문제
- `test_map_002_m3_critic_reflection.py` 2건 — 미커밋 `src/agents/agent2/critic.py`.
  깨끗한 6ed6a8d 워크트리에서는 25건 전부 통과

## 범위 밖 (3단계)

- 3단계: D9(합성 CDM에 range_high 채우기 → 규칙16 배제 인원 실행 대조)
- D3-b: `process_eligibility` 재실행 — 2단계 완료 후 1회

## 진행 기록

- 시작: 22:22
- 현재 상태(2026-07-29 통합 확인 후): 1단계 완료. 2단계는 **③ 완료 / ② 구현됐으나 미배선**.
  E1~E4·F5 실행으로 확인. 남은 것은 ②→③ 배선·F6 라이브 검증·D3-b 재생성
- 블로커 2건
  1. **vLLM 다운** (`VLLM_BASE_URL` connection refused) — ② 라이브 실행과 F6 전체 검증 불가
  2. **② 다분석물 head 손실 4/15** — 배선하면 다분석물 기준선이 현재 ① 경로보다 나빠진다
- 배선 전 미해결: `parse_value_constraints`에 테스트가 없다(E3). ②→③을 붙이는 순간
  이 함수가 프로덕션 경로가 되므로, 배선 커밋과 같은 단위로 테스트를 넣을 것

### 병렬 에이전트 충돌 (2026-07-29)

F2와 F4를 동시에 돌렸더니 **반대 결론**이 나왔다. 분류 체계는 `STATE_DURATION`을
`ConditionEra.EraLength`로 보냈는데, ADR은 같은 시각 그것을 실측으로 기각하고 있었다
(era는 기록 밀도를 재지 지속을 재지 않음 → 0명, 게다가 사이트 3/4에 테이블 부재).
→ 병렬 위임은 스코프가 겹치지 않아도 **결론이 겹칠 수 있다.** 통합·정합성 확인은
위임하지 말 것. 생성기에 실측치를 주석으로 박아 되돌려지지 않게 했다.

### 실행 중 사고

`git stash push -u -- src/ tests/`로 기준선을 재려다 `stash pop`이 인덱스에만 복원되고
작업트리가 HEAD로 되돌아갔다. 인덱스에 443줄이 온전해 `git restore --worktree`로 복구했고,
복원 후 실패 ID 집합이 측정 시점과 동일함을 확인해 델타 측정의 유효성을 검증했다.
→ 회귀 측정에 stash를 쓰지 말 것. 별도 워크트리나 커밋 대조가 안전하다.

### 서브에이전트 보고 중 반박 2건 (검증 결과 둘 다 서브에이전트가 옳음)

1. C2에 배정한 `test_absolute_with_unit_emits_value_and_sibling_unit`은 실제로는
   `parse_value_constraint`(2단계 스텁)를 호출한다 — 내 배정 오류
2. `test_agent3.py::test_build_value_constraint` 회귀는 테스트가 결함을 고정한 것이지
   구현 문제가 아니다 — C3으로 처리
