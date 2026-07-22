# 2026-03-15: Supervisor Selective Retry 구현

## 오늘 완료

- [x] P1: Selective Retry Phase 0 — Loop 1 `domain_hint`/`rule_context` 누락 수정 (`supervisor.py`)
- [x] P1: Selective Retry Phase 1 — `entity_key` 도입 (`supervisor.py`, `map_entity.py`, `assembler.py`)
- [x] P1: Selective Retry Phase 2 — `raw_mapped_sets` 보존 (`supervisor_agent.py`)
- [x] P1: Selective Retry Phase 3 — `mapping_retry.py` + 2 LangGraph 노드 + `SELECTIVE_RETRY` 라우팅
- [x] P1: `map_single_entity()` 호출 통일 (`map_entity.py`)
- [x] P1: Domain Mismatch → SELECTIVE_RETRY 전환 (기존 report-only → 자동 교정)

## 진행중

- [/] P1: Selective Retry Phase 4 — Legacy Loop 1 → shared `mapping_retry.py` 교체 (deferred)
- [/] P1: Retry 전략 데이터 검증 (GOLD에서 retry가 recall을 높이는 case 분석)

## 발견/변경사항

- Loop 1의 `get_agent2().process(text)` 호출이 `domain_hint`와 `rule_context`를 완전히 누락 → `map_single_entity()` 교체로 해결
- `entity_key` 형식: `{source}:{section}:{rule_idx}:{sub_idx}` (예: `target:inclusion:2:0`)
- 원본 룰 텍스트의 sub_idx는 `-1` (sentinel)로 표현 (hierarchical expansion 시)
- `concept_domains`는 audit에서 dict가 아닌 list로 반환 → `Counter`로 majority vote 구현
- `force_slow_path`는 환경변수 `AGENT2_FORCE_ROUTE=slow`로 구현 (clean restore via finally)
- Rollback gate: 새 매핑이 기존보다 concept 수가 적으면 커밋하지 않음 (domain_mismatch 제외)

## 테스트 결과

| Suite | Count | Status |
|-------|-------|--------|
| test_supervisor.py | 15 | ✅ (4 new entity_key tests) |
| test_supervisor_agent.py | 27 | ✅ (graph node set + domain mismatch→SELECTIVE_RETRY) |
| test_map_entity.py | 14 | ✅ (2 new entity_key tests) |
| test_mapping_retry.py | 9 | ✅ (NEW: all retry policy signals) |
| **Total** | **65** | **0 failed** |
