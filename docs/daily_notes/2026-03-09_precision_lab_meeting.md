# 2026-03-09 Precision Improvement Lab Meeting & ConceptSetRefiner

## 작업 내용

### 1. ConceptSetRefiner 구현 및 벤치마크 (v4.3)

Lab meeting (2026-03-09, 3-모델 합의) 기반으로 `ConceptSetRefiner` 신규 모듈 구현.

**Module**: `src/agents/agent2/concept_set_refiner.py`
**Toggle**: `ENABLE_REFINER=0/1` (default: 1)

#### 알고리즘

- **Pass 1 (Ancestor Subsumption)**: ancestor/ancestor_climb 관계 concept 중 descendant가 kept set에 있으면 prune
- **Pass 2 (Footprint Guard)**: desc > 3,000인 concept → `includeDescendants=false`
- **Rollback Guard**: pruning 후 kept < seed count면 전체 복원

#### A_direct 벤치마크 결과

| Metric    | OFF (v4.2) | ON (v4.3) |   Delta    |
| --------- | :--------: | :-------: | :--------: |
| Recall    |   90.3%    |   88.9%   |   -1.5pp   |
| Precision |   47.0%    | **52.4%** | **+5.4pp** |
| F1        |   52.3%    | **57.2%** | **+4.8pp** |

### 2. includeDescendants Gating → Assembler 연결 (v4.2)

`MappingResult.overbroad_concept_ids`를 Assembler까지 전달하여 `includeDescendants=false` 적용.

### 3. Precision 60%+ Lab Meeting (2-모델 검증)

**Meeting ID**: `20260309_precision_improvement`
**참여**: Claude + Codex (Gemini CLI 2회 실패)

#### 합의된 3가지 전략

|  #  | Action                       | P 예상 | 기간  |
| :-: | ---------------------------- | ------ | ----- |
|  1  | Critic Skip 정교화           | +3-5pp | 0.5일 |
|  2  | Pass 3: Adaptive Scope Guard | +2-4pp | 1일   |
|  3  | Footprint Threshold Ablation | +1-3pp | 0.5일 |

**합산 예상**: P ~58-64%, R ~87-89%

핵심 인사이트: **Critic skip 정책이 worst precision rules의 공통 원인**. ancestor/ancestor_climb은 항상 Critic 통과 필수.

#### 보류

- Semantic Drift Detection (ChromaDB 인프라 필요)
- RFC-009 Lite (학습 파이프라인 필요)

## 관련 문서

- 회의록: `docs/lab_meetings/2026-03-10_precision_improvement.md`
- ConceptSetRefiner 회의록: `docs/lab_meetings/2026-03-09_precision_new_module.md`
- Ablation Study: `docs/experiments/ABLATION_STUDY.md` (#9, #10)
