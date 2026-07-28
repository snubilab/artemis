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
- [ ] D3. 6개 코호트 재생성 후 계수 — RangeHighRatio 0/42 → gold 동등(32/85 = 38%)
      ※ LLM 재추출 필요. 1단계 코드 변경만으로는 기존 산출물이 갱신되지 않는다

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

## 범위 밖 (2·3단계)

- 2단계: D2(결정적 파서)·D6(암묵적 배수 1)·D7(한 줄 두 조건)·D8(부정 케이스)
- 3단계: D9(합성 CDM에 range_high 채우기 → 규칙16 배제 인원 실행 대조)

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
