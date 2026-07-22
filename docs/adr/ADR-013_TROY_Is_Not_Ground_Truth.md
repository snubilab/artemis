# ADR-013: TROY는 정답(Ground Truth)이 아닌 전문가 재해석(Expert Reinterpretation)

**상태**: 승인됨  
**날짜**: 2026-02-17  
**의사결정자**: @kyh

## 컨텍스트

ARTEMIS 파이프라인의 품질을 평가하기 위해 TROY 전문가 cohort definition을 "정답"으로 사용해왔다.
Benchmark V3에서 14건의 Missed match가 발생했고, 이를 분석하는 과정에서 TROY와 Design Paper 간의 구조적 차이를 발견했다.

### 발견 사항

**Design Paper (LEADER trial)의 original criteria:**
- Prior MI, Prior stroke/TIA, Prior revascularization, Arterial stenosis >50%, Symptomatic CHD 등을 **개별 항목**으로 나열

**TROY의 재구성:**
- 위 항목들을 **"prior CV disease"라는 하나의 composite rule**로 묶어서 ATLAS에서 효율적으로 운용
- ESLD에 bilirubin, liver procedure 등 design paper에 없는 sub-criteria를 **추가 보강**
- Renal replacement에 ESRD, kidney transplant condition/procedure 등을 **추가**

**ARTEMIS의 출력:**
- Design paper 원문을 충실히 따라 **개별 criteria로 생성** (32 rules)
- Design paper에 있는 모든 criteria를 빠짐없이 추출

### 핵심 구조 비교

| 항목 | Design Paper | ARTEMIS | TROY |
|---|---|---|---|
| CV disease 조건들 | 개별 나열 (12개) | 개별 rule (12개) | 1개 composite rule |
| ESLD | "end-stage liver disease" | 5 sub-criteria로 분해 | 4 sub-criteria + 추가 보강 |
| Substance abuse | "drug use or dependence" | 9 sub-criteria로 분해 | 1 concept set |
| Rule 수 | ~32개 criteria | 32 rules | 18 rules |

## 결정

1. **TROY를 "정답"이 아닌 "전문가 참조(expert reference)"로 재정의**한다.
2. **Design paper의 criteria가 실제 ground truth**이다.
3. 벤치마크 평가 시 두 가지 축으로 분리한다:
   - **Criteria Coverage**: design paper 기준으로 ARTEMIS가 올바른 criteria를 추출했는가
   - **Concept Mapping Quality**: 개별 concept set 단위로 TROY의 concept 선택과 비교

## 근거

- Benchmark V4 parent-level 비교 결과:
  - Missed=1 (TROY "prior CV disease"만, concept set 없는 wrapper rule)
  - ARTEMIS가 design paper의 모든 criteria를 정확히 추출하고 있음 확인
  - V3에서 Missed=14로 잡힌 것은 **TROY의 재그룹핑 구조** 때문이지, ARTEMIS의 누락이 아님
- TROY의 재구성 패턴:
  - 그룹핑: 개별 criteria → composite rule (운용 효율)
  - 보강: design paper에 없는 sub-criteria 추가 (임상적 완성도)
  - 이는 전문가의 "know-how"이며, 자동화 파이프라인의 결함이 아님

## 영향

- `scripts/benchmark_v3.py`: TROY를 ground truth로 사용하는 매칭 로직에 구조적 한계 존재
- `scripts/benchmark_v4.py`: parent-level 비교로 구조 차이 부분 해소 (Missed 14→1)
- 향후 벤치마크: concept mapping 품질은 **개별 concept set 단위**로 평가해야 정확
- Design paper IR (`verify_leader_design_e2e.py`): 현재 수동 작성, TROY와 granularity 차이 인지 필요
