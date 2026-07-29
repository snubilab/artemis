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

- [ ] E1. `parse_value_constraint(phrase) -> ValueConstraint | None`
      임계값 구문 하나 → 조건 하나. 연산자·값·`reference_bound`·단위 추출.
      검증: 코퍼스 POSITIVES 전수의 `reference_bound`/`op`/`value`/단위 단언 통과
- [ ] E2. 부정 케이스 거부 — 신뢰구간 상한·범위·기간·단위환산 재기술 → `None`
      검증: `test_non_constraints_are_rejected` 14건 통과
- [ ] E3. `parse_value_constraints(line) -> list` — 문장을 구문으로 분리 후 E1 매핑
      검증: `TSH >1.2 ULN or <0.8 LLN`이 조건 2개(uln·lln)로 분해
- [ ] E4. 전체 검증 — 코퍼스 268 실패 → 0, 기존 스위트 회귀 0

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
- [ ] F2. 분류 체계 도출 (area / op / 표기) — 코퍼스 114건 근거, 프롬프트에 심을 데이터
- [ ] F3. 대시보드 분류 체계 탭
- [ ] F4. `CONDITION_DURATION` Circe 표현 설계
- [ ] F5. 분류기 구현 (②) — 로컬 vLLM
- [ ] F6. `LLM_MODEL` 전환 + 파이프라인 전체 로컬 검증

## 범위 밖 (3단계)

- 3단계: D9(합성 CDM에 range_high 채우기 → 규칙16 배제 인원 실행 대조)
- D3-b: `process_eligibility` 재실행 — 2단계 완료 후 1회

## 진행 기록

- 시작: 22:22
- 현재 상태: 1단계 완료 (A·B·C·D1·D2). 남은 것은 D3(재생성) — LLM 필요
- 블로커: 없음

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
