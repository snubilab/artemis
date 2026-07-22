# ISSUE: Concept Mapping에 대한 Ground Truth 부재

**Date**: 2026-02-27  
**Severity**: Structural  
**Affects**: Mapping Agent (Agent 2) 평가 체계 전체

---

## 문제

Agent 2가 생성한 OMOP Concept ID가 "맞는지" 자동으로 검증할 수 있는 ground truth가 존재하지 않음.

| 비교 대상 | 왜 GT로 부적합한가 |
|----------|-------------------|
| **TROY concepts** | 88건 데이터 품질 이슈 (ADR-013), non-standard concept 다수 |
| **Design Paper** | 자연어 텍스트만 있고 OMOP concept ID 없음 |
| **LLM 생성 정답** | ARTEMIS(LLM)와 동일 편향 → 순환 논리 |

## V5 벤치마크의 실제 측정 범위

| 수준 | 자동 측정? | 설명 |
|------|:---:|------|
| **Criteria completeness** | ✅ | DP의 모든 criteria를 Agent 2가 커버했는가 |
| **Concept correctness** | ⚠️ 참조만 | TROY(불완전) 대비 concept overlap |
| **Concept ground truth** | ❌ | 도메인 전문가 직접 검수만 가능 |

## 현실적 대안

1. **TROY를 불완전 참조로 활용**: standard 치환 후 diagnostic score만 보고, 공식 recall 분모로는 사용하지 않음
2. **인간 검수 병행**: Agent 2 출력의 concept set을 교수님이 review → 소규모 golden set 확보
3. **다중 전문가 의견 수렴**: TROY + ARTEMIS 출력을 함께 보고, 어느 쪽이 더 적절한지 전문가 판정

## 관련 문서

- `docs/adr/ADR-013_TROY_Is_Not_Ground_Truth.md`
- `docs/lab_meetings/2026-02-27_mapping_v5_benchmark.md`
- `docs/lab_meetings/2026-02-20_troy_benchmark_redesign.md`
