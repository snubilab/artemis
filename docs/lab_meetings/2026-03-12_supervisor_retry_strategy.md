# Lab Meeting: Supervisor Retry Strategy

**날짜**: 2026-03-12  
**참여 모델**: Claude (Gemini 2x empty → excluded, Codex output missing → excluded)

## 안건

Supervisor의 Post-Agent2 query rewrite retry 전략이 유효한가?

## Claude 제안 요약

| 결정 사항                     | Claude 입장                                                                                   |
| ----------------------------- | --------------------------------------------------------------------------------------------- |
| MIN_SEED_COUNT=2              | → **1로 변경** (empty gate만). 1개라도 concept이 있으면 Agent 2 파이프라인의 정당한 결과      |
| Query rewrite (domain prefix) | **유효하지 않음**. `domain_hint`는 이미 파라미터로 전달, text에 prefix 추가는 embedding noise |
| Query rewrite (types of)      | **유효하지 않음**. UMLS/OMOP에 "types of X" 패턴 없음, Agent 2 내부에 이미 synonym expansion  |
| Retry vs Report-only          | **Report-only 전환**. retry는 RFC-005 Loop 1-3에 위임                                         |

## 핵심 문제 (교차 검증 없이 Claude 자체 분석)

### 문제 1: Query Rewrite는 Agent 2의 설계와 충돌

Agent 2는 이미 다층 파이프라인을 갖고 있다:

```
ChromaDB Retrieval → UMLS Synonym Expansion → KG Expansion → Critic → Ancestor Climbing
```

query text를 `"Drug: X"`로 바꿔서 다시 호출하면:

- ChromaDB retrieval 결과가 바뀔 수 있지만 **더 좋아진다는 보장이 없음**
- UMLS/KG/Critic은 동일 → 최종 결과 차이 미미할 가능성 높음
- **검증 데이터 없음**: retry 전후 concept 비교를 단 한 번도 안 함

### 문제 2: MIN_SEED_COUNT=2의 False Positive Rate

Drug ingredient는 대부분 1개 concept이 정답:

- Liraglutide → 1개
- Empagliflozin → 1개
- Clopidogrel → 1개

MIN_SEED_COUNT=2는 **모든 Drug entity를 weak로 판정**한다. 이건 gate가 아니라 noise.

### 문제 3: Supervisor Retry ≠ Loop 1 Retry

|            | Supervisor Retry | Loop 1 (RFC-005)        |
| ---------- | ---------------- | ----------------------- |
| **시점**   | Agent 2 직후     | Agent 4 validation 후   |
| **트리거** | seed count < 2   | CodesetId=0             |
| **전략**   | query rewrite    | 동일 query 재호출       |
| **근거**   | 없음 (추정)      | 실제 assembly 실패 확인 |

Loop 1은 **실제 실패를 확인한 후 retry** → 합리적. Supervisor retry는 **추정에 기반** → 위험.

## 최종 합의 (단독 결론)

> ⚠️ Gemini/Codex 검증 없는 단독 결론이므로, 다음 세션에서 데이터로 검증 필요.

### 즉시 변경

1. `MIN_SEED_COUNT=1` (0개만 retry, 사실상 empty gate)
2. `retry_weak_entities()` 호출 → **report-only mode** (retry 비활성화)
3. `SupervisorReport`에 weak entity 로깅은 유지 (관찰용)

### 다음 세션 TODO

- [ ] GOLD 벤치마크에서 retry가 실제로 recall을 높이는 case가 있는지 분석
- [ ] 있다면, 해당 case에 맞는 **검증된** retry 전략 설계
- [ ] ADR-023 Phase 2 (supervisor orchestrator 승격) 시 통합

## 부록: 원본 제안 및 리뷰

> 상세 내용은 `tmp/lab_meeting/20260312_supervisor_retry_strategy/` 참조
