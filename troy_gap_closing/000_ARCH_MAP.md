# 000 - Architecture Map: TROY-ARTEMIS Gap Closing (Phase 1)

**Project Goal**: ARTEMIS 파이프라인이 생성하는 Circe JSON의 TROY(전문가) 대비 구조적 완전성 확보  
**Target Trial**: LEADER (NCT01179048)  
**Tech Stack**: Python 3.11, Pydantic, pytest  
**Protocol**: Strict-Modular-TDD

---

## Current State Analysis

| Component | File | Issue |
|-----------|------|-------|
| `RegisteredConcept` | `src/registry/models.py:17` | `include_descendants` 기본값 `False` |
| `CohortPipeline` | `src/pipeline/cohort_pipeline.py:182` | pipeline 내부에서 `True` 설정하나, 직접 호출 시 적용 안 됨 |
| `DOMAIN_TO_CRITERIA_TYPE` | `src/agents/agent3/mappings.py:38` | Drug → `DrugExposure`만 지원. `DrugEra` 없음 |
| `_build_primary_criteria` | `src/agents/agent3/assembler.py:125` | domain별 분기 없이 단일 criteria_type 사용 |
| `_build_end_strategy` | `src/agents/agent3/assembler.py:219` | `OBSERVATION_END`, `FIXED_DURATION`만 지원. `CUSTOM_ERA` 없음 |
| `CohortDefinition` | `src/models/ir.py:103` | `exit_strategy` 필드가 단순 str, CustomEra 파라미터 없음 |

## Atomic Sub-tasks

| ID | Subtask | Status | Files Modified |
|----|---------|--------|----------------|
| 01 | `includeDescendants` 기본 `true` + `includeMapped` `true` | **DONE** | `registry/models.py`, `agent3/assembler.py` |
| 02 | Drug 도메인 PrimaryCriteria → `DrugEra` 전환 | **DONE** | `agent3/mappings.py`, `agent3/assembler.py` |
| 03 | `CustomEra` EndStrategy 구현 | **DONE** | `models/ir.py`, `agent3/assembler.py` |

## Dependency Graph

```
01_includeDescendants ──┐
                        ├──→ LEADER 검증
02_DrugEra ─────────────┤
                        │
03_CustomEra ───────────┘
```

> 01, 02, 03은 서로 독립적이므로 병렬 구현 가능하나, 검증은 모두 완료 후 통합 실행.
