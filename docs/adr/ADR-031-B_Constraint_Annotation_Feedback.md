# ADR-031-B: 파서 결과를 프롬프트로 되먹여 성분 분해를 LLM에 맡긴다

**상태**: 승인됨
**날짜**: 2026-08-03
**의사결정자**: @kyh
**연관**: ADR-031 D2 (발견은 LLM이, 구조화는 결정적 파서가)

## 컨텍스트

ADR-031 D2는 역할을 이렇게 나눴다.

> Agent 1은 어떤 기준에 임계값이 있는지 찾고 원문 구문을 그대로 넘긴다.
> 구문 → 구조 변환은 결정적 코드가 한다.

이 분담은 **한 방향**이다. LLM → 파서. 파서의 결과가 LLM으로 돌아가는 경로는 없었다.

2026-07-31 ARISTOTLE 재수집에서 그 한계가 드러났다. 프로토콜 제외기준 20번이
Agent 1을 통과하면서 값을 통째로 잃었다.

```
입력   ALT or AST > 2X ULN or a Total Bilirubin ≥ 1.5X ULN
        (unless an alternative causative factor [e.g., Gilbert's syndrome] is identified)

출력   {"description": "Liver Enzyme Elevation", "valueConstraint": null}
```

같은 실행에서 `LVEF ≤ 40%`, `Hemoglobin < 9`, `Platelet ≤ 100,000`, `Creatinine > 2.5`는
정확히 뽑혔다. 실패한 것만 **분석물 3개 × 임계값 2개가 한 문장**이었다. 난이도가 아니라
문장 모양이 갈랐다.

D2 원칙대로라면 파서가 구조화해야 하는데, **파서에게 도달할 구문 자체가 넘어오지
않았다.** LLM이 "발견" 단계에서 라벨로 요약해버리면 그 뒤 결정적 코드는 할 일이 없다.

## 결정

**파서를 LLM 호출 앞에 배치하고, 그 결과를 프롬프트에 주석으로 실어 보낸다.**

```
기준 원문 ──▶ parse_value_constraints ──▶ 주석
                                            │
기준 원문 + 주석 ──────────────────────────▶ Agent 1 ──▶ IR
```

프롬프트에 실리는 형태:

```
  20. ALT or AST > 2X ULN or a Total Bilirubin ≥ 1.5X ULN (unless …)
      [value_constraint] {"op": "gt",  "value": 2.0, "referenceBound": "uln"}
      [value_constraint] {"op": "gte", "value": 1.5, "referenceBound": "uln"}
```

지시는 두 가지다.

1. 주석의 숫자는 **그대로 복사**하고 재유도하지 않는다.
2. 주석은 **임계값**을 준다. 기준 텍스트가 **성분**을 준다.
   **성분 하나당 규칙 하나**이며, 두 성분이 공유하는 임계값은 양쪽에 쓴다.

## 역할 분담 (명시)

| 단계 | 담당 | 근거 |
|---|---|---|
| 어떤 기준이 측정값 조건인가 | LLM | 문맥 판단. 파서는 통계 표현과 임계값을 구분 못 함 |
| **숫자·연산자·기준선(ULN/LLN/절대)** | **결정적 파서** | 코퍼스 114건 회귀 검증. 표기 변형 31종 대응 |
| 문장 → 성분별 규칙 분해 | LLM | 개체 인식. `ALT or AST or ALP`를 세 검사로 나누는 일 |
| 도메인·논리형·시간창 분류 | LLM | 기존 역할 |
| 개념집합 매핑 | Agent 2 | 기존 역할 |

## 근거

**되먹임이 없으면 D2가 성립하지 않는다.** 파서가 아무리 정확해도 LLM이 구문을 요약해
버리면 입력이 없다. 주석은 파서의 답을 LLM 앞에 놓아, 요약하더라도 숫자는 남게 한다.

**성분 분해는 파서가 못 한다.** `parse_value_constraints`는 위 문장에서 제약 2개를
정확히 낸다. 그러나 분석물이 ALT·AST·빌리루빈 셋이라는 것은 개체 인식이고, gold는
셋을 별도 행으로 요구한다. 이 분해는 LLM의 일이다.

**측정된 효과** (gemma-4-E4B, 격리 스토어):

| | 주석 전 | 주석 후 |
|---|---|---|
| ARISTOTLE | 0 | **3** (ALT, AST, Total Bilirubin, ANY 그룹) |
| PLATO | 0 | **3** (Troponin I, Troponin T, CK-MB, ANY 그룹) |

## 반려된 대안

**A. 원래대로 프롬프트만 강화** — Pattern E에 Measurement 예시를 넣는 것만으로는
ARISTOTLE의 문장을 다시 놓칠 수 있다. 프롬프트 준수는 실행마다 보장되지 않는다.

**C. 주석을 검증용으로만 사용** — Agent 1이 뽑게 하고 파서 결과와 대조해 경고만 낸다.
추출 주체가 LLM으로 유지되어 D2 취지에 가깝지만, 경고가 떠도 값은 여전히 비어 있다.
불일치를 드러낼 뿐 고치지 못한다.

## 영향과 주의

**주장 범위.** "LLM이 문헌에서 값 제약을 추출한다"고 말할 수 없다. 정확히는
**"결정적 파서가 값을 뽑고, LLM이 그것을 성분별 규칙으로 배치한다"**이다. 보고서·논문에
쓸 때 이 구분을 지켜야 한다.

**주석이 없는 줄에는 주석을 달지 않는다.** 모든 줄에 달면 모델이 "항상 있어야 하는 것"
으로 학습해 지어낸다. `annotate_value_constraints`는 파싱 결과가 없으면 빈 문자열을
반환한다.

**규칙 수 = 주석 수가 아니다.** 초판 문구가 "제약이 여러 개면 규칙도 여러 개"였고,
ARISTOTLE에서 주석 2개 → 규칙 2개가 나오며 AST가 사라졌다. 임계값과 성분은 다른 축이다.

## 구현

| 대상 | 위치 |
|---|---|
| 주석 생성 | `src/services/value_constraint.py::annotate_value_constraints` |
| 프롬프트 주입 | `src/agents/agent1/parser.py::_format_criteria` |
| 지시문 | `src/agents/agent1/prompts.py` — `NCT_DECOMPOSITION_PROMPT` 규칙 0 |
| 성분 분해 예시 | 같은 파일 `NCT_SYSTEM_PROMPT` Pattern E |
| 테스트 | `tests/test_criterion_constraint_annotation.py` |

커밋: `baa2629` (주석 도입), `fe08096`·`3fd4b8e` (성분당 규칙 하나로 정정)
