# ADR-016: ThreadPoolExecutor에서 as_completed 사용 금지

**상태**: 승인됨  
**날짜**: 2026-03-02  
**의사결정자**: @kyh

## 컨텍스트

Agent 2 배치 최적화에서 UMLS synonym 검색을 `ThreadPoolExecutor`로 병렬화할 때, `as_completed(futures)`를 사용하여 **완료 순서대로** 결과를 수집했다.

### `as_completed`의 역할

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

with ThreadPoolExecutor(max_workers=4) as pool:
    futures = {
        pool.submit(retriever.search, syn, 10, domain_hint): syn
        for syn in ["synonym_A", "synonym_B", "synonym_C"]
    }
    for future in as_completed(futures):  # ← 먼저 끝나는 것부터 반환
        candidates.extend(future.result())
```

`as_completed`는 제출된 future들 중 **가장 먼저 완료된 것부터** 순차적으로 yield하는 iterator이다.  
목적은 **전체 대기 시간을 줄이기 위해** — 느린 작업을 기다리지 않고 빠른 결과부터 처리할 수 있다.

### 문제: LLM 프롬프트에 비결정적 순서 전파

```
Run 1: synonym_B 먼저 완료 → candidates = [B결과, A결과, C결과]
Run 2: synonym_A 먼저 완료 → candidates = [A결과, B결과, C결과]
```

candidates 리스트의 순서가 달라지면 → reranker 프롬프트의 candidates_text가 변경됨:

```
# Run 1 프롬프트:
- ID: 201 | Name: Cardiovascular disorder (from B)
- ID: 101 | Name: Heart disease (from A)
...

# Run 2 프롬프트:
- ID: 101 | Name: Heart disease (from A)
- ID: 201 | Name: Cardiovascular disorder (from B)
...
```

**`temperature=0`이어도 프롬프트 자체가 다르므로 LLM 출력이 달라진다.**  
이로 인해 동일한 입력에 대해 다른 seed concept이 선택되고, `concept_ancestor` 확장 결과가 크게 달라짐.

### 실제 영향

`prior CV disease` rule에서 벤치마크 결과:
- D v2 (변경 전): **R=76%** (overlap=3,528 / troy=4,642)
- D v3 (as_completed 사용): **R=13%** (overlap=601 / troy=4,642)

reranker가 다른 seed concept을 선택 → descendants 확장 범위가 달라짐 → 63pp recall 하락.

## 결정

`as_completed` 대신 **제출 순서를 보존하는 list 기반 futures**를 사용한다.

```python
# ❌ 금지: as_completed (비결정적 순서)
futures = {pool.submit(fn, arg): arg for arg in args}
for future in as_completed(futures):
    results.append(future.result())

# ✅ 권장: 제출 순서 보존 (결정적)
futures = [pool.submit(fn, arg) for arg in args]
for future in futures:
    results.append(future.result())
```

## 근거

1. **재현성**: `temperature=0` LLM 호출의 결정성을 보장하려면 프롬프트가 동일해야 한다
2. **성능 차이 미미**: synonym 검색은 3개 이하의 로컬 ChromaDB 쿼리이므로, 완료 순서 차이는 수 ms에 불과
3. **디버깅 용이성**: 동일 입력 → 동일 출력이 보장되어야 벤치마크 비교가 유의미

## 영향

- 수정 파일: `src/agents/agent2/workflow.py` (4개소 — `_slow_path`, `process_batch`, `_slow_path_batch` 2개소)
- `as_completed` import는 유지하되 사용하지 않음
- 성능 영향: 무시할 수 있음 (로컬 DB 쿼리 3~4개의 완료 순서 차이)
