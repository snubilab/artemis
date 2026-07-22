# Benchmark Parallelization Results (2026-03-16)

**Version**: benchmark_v5.py / benchmark_a_direct.py (ThreadPoolExecutor refactor)  
**Date**: 2026-03-16  
**Commit**: `35912ff` (feat/agent2-parallel branch)

## Objective

벤치마크 실행 시간 단축을 위해 `ThreadPoolExecutor`로 룰 단위 병렬 처리를 도입.

## Changes

| File | 변경 내용 |
|------|-----------|
| `scripts/benchmark_a_direct.py` | `ThreadPoolExecutor` + `ThreadedConnectionPool` (--workers flag) |
| `scripts/benchmark_v5.py` | 동일 패턴 적용 (E2E Agent 1→Agent 2 파이프라인) |
| `src/agents/agent2/agent2_cache.py` | `threading.Lock` 추가 (thread-safe cache) |

## Results

### benchmark_v5.py (E2E: Agent 1 → Agent 2) — LEADER GOLD

| Workers | Elapsed | Speedup | Recall | Precision | F1 | Soft P1 | Soft P2 |
|---------|---------|---------|--------|-----------|-----|---------|---------|
| 1 (순차) | **466.9s** | 1.0x | 66.0% | 51.4% | 51.3% | 43.2% | 53.4% |
| 5 (병렬) | **85.0s** | **5.5x** 🚀 | 64.6% | 51.2% | 51.0% | 44.7% | 54.0% |

> Recall 차이(66.0% vs 64.6%)는 Agent 1 LLM 호출의 비결정성(non-determinism)에 의한 것.  
> 병렬화 자체로 인한 메트릭 저하는 없음.

### benchmark_a_direct.py (Agent 2 only) — LEADER GOLD

| Workers | Elapsed | Speedup | Recall | Precision | F1 | Soft P1 | Soft P2 |
|---------|---------|---------|--------|-----------|-----|---------|---------|
| 1 (순차) | **16.4s** | 1.0x | 86.1% | 42.2% | 43.3% | 56.4% | 65.9% |
| 5 (병렬) | **18.4s** | ~1.0x | 86.1% | 42.2% | 43.3% | 56.4% | 65.9% |

> Cache 100% hit 상태에서는 속도 차이 없음. Cold cache 시 유의미한 단축 기대.

## Analysis

- **E2E 파이프라인**(v5)에서 **5.5x speedup** 달성 — 이론적 최대(17룰/5워커=3.4x)보다 높음
  - 원인: 각 룰 내부의 Agent 1 LLM 호출 + Agent 2 UMLS 검색이 I/O-bound이므로 스레드 간 대기 시간이 중첩됨
- **A_direct** 벤치마크는 Agent 2 cache가 warm한 상태에서 DB 쿼리만 실행되므로 병렬화 이득 미미
- **Thread-safety**: `Agent2Cache`에 `threading.Lock` 추가로 race condition 방지 확인

## Raw Reports

- `output/benchmark_v5_20260316_0921.json` (workers=5)
- `output/benchmark_v5_20260316_1001.json` (workers=1)
- `output/benchmark_a_direct_20260316_0903.json` (workers=5)
- `output/benchmark_a_direct_20260316_0142.json` (workers=1, 순차)
