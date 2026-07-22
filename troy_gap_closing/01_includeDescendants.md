# Task: includeDescendants & includeMapped Defaults

## 1. Specification (Strict)
- **Input**: `RegisteredConcept` 생성 시 기본값, `CohortAssembler._build_concept_sets` 출력
- **Output**: 
  - `RegisteredConcept.include_descendants` 기본값: `True`
  - Circe JSON `ConceptSet.expression.items[].includeMapped`: `True`
- **Logic**:
  1. `RegisteredConcept.include_descendants` 기본값을 `False` → `True`로 변경
  2. `CohortAssembler._build_concept_sets`에서 `includeMapped` 항상 `True`로 출력

## 2. TDD Strategy
- [x] Test A: RegisteredConcept 기본 생성 → include_descendants == True
- [x] Test B: CohortAssembler._build_concept_sets → includeMapped == True
- [x] Test C: Circe JSON 내 includeDescendants == True 확인

## 3. Implementation Log
- 10:24 Test Created (Fail expected)
- 2026-02-18 00:11 코드 확인 결과 이미 구현 완료:
  - `RegisteredConcept.include_descendants = True` (models.py:17)
  - `includeMapped: True` (assembler.py:95)
- 2026-02-18 00:12 명시적 테스트 5개 작성 → 전체 PASSED
  - `tests/test_troy_gap_01_include_descendants.py`

## 4. Final Status
- [DONE]
