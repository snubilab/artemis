# Lab Meeting: TROY vs SUPP Evaluation

**날짜**: 2026-03-04
**참여 모델**: Claude, Codex (gpt-5.3-codex-spark) — Gemini 2회 실패로 제외 (2-model 검증)

## 안건

Agent2 벤치마크(Exp A)에서 입력 텍스트를 TROY concept set names vs Supplement entity names 중 어느 것을 기본으로 사용할 것인가?

## 제안 요약

| 모델   | 핵심 제안                                                                   | 주요 근거                                                  |
| ------ | --------------------------------------------------------------------------- | ---------------------------------------------------------- |
| Claude | **둘 다 쓰되 의미가 다름** — TROY=Agent2 상한선, SUPP=파이프라인 시뮬레이션 | 3계층 분해(TROY/SUPP/E2E)로 각 Agent 기여도 분리           |
| Codex  | **SUPP을 primary**, TROY를 secondary arm                                    | 실제 task(자연어→OMOP)에 가장 가깝고, 새 trial 확장성 높음 |

## 합의 (✅ 2/2 동의)

### 1. 벤치마크 표준: **SUPP를 primary, TROY를 secondary**

| 실험                       | 입력                        | 측정 대상                        |
| -------------------------- | --------------------------- | -------------------------------- |
| **Exp A (SUPP)** — Primary | Supplement 원문 entity text | Agent2 실전 매핑 역량            |
| Exp A (TROY) — Secondary   | TROY 약칭 concept set name  | Agent2 upper bound (전문가 언어) |
| Exp D — E2E                | Agent1 entity_text          | 전체 파이프라인 성능             |

### 2. 차이 분석으로 bottleneck 정량화

```
Exp A(TROY) - Exp A(SUPP) = 입력 텍스트 스타일 영향
Exp A(SUPP) - Exp D       = Agent1 entity_text 품질 영향
Exp A(TROY) - Exp D       = 전체 파이프라인 gap
```

### 3. 새 trial GOLD standard 스키마 (Codex 제안 채택)

```json
{
  "canonical_entity_text": "Type 1 diabetes mellitus",
  "source_aliases": ["T1DM", "Type 1 Diabetes Mellitus"],
  "gold_concept_ids": [201826, 40484648],
  "trial": "LEADER",
  "entity_id": "exc_01"
}
```

## 실험 결과

### 3-조건 비교표

| 조건                  | 설명                          |  Recall   | Precision |    F1     |  Full  | Partial | Wrong |
| --------------------- | ----------------------------- | :-------: | :-------: | :-------: | :----: | :-----: | :---: |
| **Exp A (TROY)**      | 전문가 약칭, auto routing     | **75.0%** |   56.6%   | **53.5%** | **11** |    3    |   3   |
| **Exp A (SUPP)**      | supplement 원문, auto routing |   60.4%   |   55.3%   |   45.4%   |   7    |    5    |   5   |
| **Exp A (SUPP fast)** | supplement 원문, fast-only    |   55.3%   | **56.0%** |   41.4%   |   6    |    5    |   6   |

### Bottleneck 분해

| 비교             | Delta (Recall) | 의미                                |
| ---------------- | :------------: | ----------------------------------- |
| TROY - SUPP      |  **-14.6pp**   | 입력 텍스트 스타일이 매핑에 큰 영향 |
| SUPP - SUPP fast |   **-5.1pp**   | Slow path(UMLS+reranking) 기여분    |
| TROY - SUPP fast |  **-19.7pp**   | 전체 gap (용어 + 파이프라인)        |

### 핵심 발견

1. **전문가 용어가 Agent2에 유리**: TROY 약칭(`"ACS"`, `"DPP4 inhibitors"`)이 OMOP vocabulary와 더 잘 매칭
2. **Precision은 안정적**: 3조건 모두 55~56% → Agent2가 찾는 건 대체로 맞지만, Recall이 관건
3. **Slow path 기여 제한적**: UMLS+reranking이 5.1pp만 추가 → 용어 표준화가 더 큰 레버

### 논문 Contribution

> "전문가가 선호하는 축약 용어가 OMOP 매핑에서 14.6pp 유리 — 자연어 기반 파이프라인은 terminology normalization 전략이 필요"

## 실행 계획

- [x] `LEADER_GOLD_SUPP.json` concept set name 교체 완료
- [x] `benchmark_a_direct --troy LEADER_GOLD_SUPP.json` SUPP 결과 확보
- [x] `FORCE_FAST_PATH=1` SUPP fast-only 결과 확보
- [x] TROY vs SUPP vs SUPP fast 결과 비교표 생성
- [ ] 논문에 3실험 모두 보고 (주 지표: Exp D, 분해 분석: TROY vs SUPP)

## 코드 변경

- `src/agents/agent2/workflow.py`: `FORCE_FAST_PATH` 환경변수 추가 (fast path 강제 모드)
- `data/gold/LEADER/LEADER_GOLD_SUPP.json`: 56개 concept set name + 18개 rule name을 supplement 원문으로 교체

## 부록: 원본 제안 및 리뷰

> 상세 내용은 `tmp/lab_meeting/20260304_troy_vs_supp_evaluation/` 참조
