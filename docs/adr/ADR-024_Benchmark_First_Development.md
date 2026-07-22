# ADR-024: Benchmark-First Development Policy

**상태**: 승인됨  
**날짜**: 2026-03-12  
**의사결정자**: @kyh

## 컨텍스트

Supervisor의 `MIN_SEED_COUNT=2` + query rewrite retry가 **벤치마크 검증 없이** production(`cohort_pipeline.py`)에 배포됨.
`benchmark_v5.py`에는 supervisor 로직이 전혀 없어 production과 벤치마크가 불일치.

## 결정

**모든 새로운 파이프라인 기능은 반드시 벤치마크에서 먼저 개발하고, 통과 판정 후 production에 도입한다.**

### 프로세스

```
1. 벤치마크 스크립트에 기능 구현
2. GOLD 벤치마크 실행 (LEADER, EMPA-REG, PLATO)
3. 결과를 사용자에게 보고
4. 사용자가 통과 여부 판정
5. 통과 시에만 production (cohort_pipeline.py)에 도입
```

### 위반 금지

- production에만 있고 벤치마크에 없는 로직 ❌
- 벤치마크 없이 production에 새 기능 추가 ❌
- 사용자 승인 없이 production 변경 ❌

## 근거

- 벤치마크 미검증 기능이 production에 들어가 **성능 영향을 측정할 수 없는** 상황 발생
- Supervisor retry가 62% false positive rate로 트리거되고 있었으나, 벤치마크에 없어서 발견이 늦음
- 재현 가능한 평가 → 사용자 판정 → 배포 순서가 품질 보증의 기본

## 영향

### 즉시 조치

- `cohort_pipeline.py`에서 supervisor retry **비활성화** (report-only로 전환)
- `benchmark_v5.py`에 supervisor 로직 추가
- 벤치마크 통과 후 production 재도입
