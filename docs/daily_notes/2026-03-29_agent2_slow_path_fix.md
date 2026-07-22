# Agent2 Fast Path 비활성화 — 2026-03-29

## 문제
Agent2의 complexity router가 "GLP-1 receptor agonists", "Human NPH insulin",
"Cardiovascular conditions" 등 임상 시험 기준을 "Simple"로 분류 → fast path 진입.

Fast path = LLM reranker 없이 RAG top-1만 반환.
결과: "GLP-1 receptor agonists" → `Adverse reaction to GLP-1`, "Human NPH insulin" → `ultralente insulin` 등 완전히 틀린 매핑.

## 수정
`artemis/src/agents/agent2/workflow.py`에서 fast path 분기 주석처리, 전부 slow path 강제.

```python
# Fast path disabled: all queries go through slow path
route_path = "slow"
```

## 결과 비교
| 기준 | fast path | slow path |
|------|-----------|-----------|
| Cardiovascular conditions | Sequelae only | + Disorder of cardiovascular system ✅ |
| Human NPH insulin | ultralente만 | + insulin isophane (NPH 정확) ✅ |
| GLP-1 receptor agonists | Adverse reaction | Adverse reaction (여전히 개선 필요) |

## 향후 개선
- GLP-1 receptor agonists drug class 매핑 개선 필요
- `drug_class_expander`가 GLP-1 클래스를 liraglutide/exenatide 등으로 확장하도록 수정
