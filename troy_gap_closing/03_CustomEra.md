# Task: CustomEra EndStrategy 구현

## 1. Specification (Strict)
- **Input**: `CohortDefinition.exit_strategy`를 `ExitStrategy` 모델로 확장
- **Output**: Circe JSON에서 `EndStrategy.CustomEra` 블록 생성
- **Logic**:
  1. `ir.py`에 `CustomEraConfig`, `ExitStrategy` 모델 추가
  2. `CohortDefinition.exit_strategy`를 `str | ExitStrategy`로 변경 (하위 호환)
  3. `assembler._build_end_strategy` → ExitStrategy 객체 처리

## 2. TDD Strategy
- [ ] Test A: CustomEra EndStrategy → Circe CustomEra 블록
- [ ] Test B: 기존 str("OBSERVATION_END") → 하위 호환
- [ ] Test C: FIXED_DURATION 하위 호환

## 3. Implementation Log
- 2026-02-18 00:15 코드 확인 결과 이미 구현 완료:
  - `CustomEraConfig`, `ExitStrategy` 모델 (ir.py:102-113)
  - `CohortDefinition.exit_strategy: Union[str, ExitStrategy]` (ir.py:123)
  - `_build_end_strategy` CUSTOM_ERA 분기 (assembler.py:384-390)
- 2026-02-18 00:16 명시적 테스트 8개 작성 → 전체 PASSED
  - `tests/test_troy_gap_03_custom_era.py`

## 4. Final Status
- [DONE]
