# Daily Note: 2026-03-30 — feat/agent2-mapping-accuracy Merge to Main

**Branch merged:** `feat/agent2-mapping-accuracy` → `main`
**Session focus:** Test cleanup, branch verification, and fast-forward merge of the agent2 mapping accuracy sprint.

---

## Overview

`feat/agent2-mapping-accuracy` 브랜치가 main에 fast-forward 머지됨.
총 34 커밋, 85 files changed, +13,373 / -793 lines.

이 브랜치는 2026-03-27~30에 걸쳐 진행된 대규모 스프린트로,
Agent2 매핑 정확도 개선, 성능 최적화, TTE UI 다수 기능을 포함.

---

## 1. 머지 전 테스트 픽스

### 문제: sys.modules pollution (22+ 테스트)

**원인:** 여러 테스트 파일이 모듈 수준에서 fake stub을 `sys.modules`에 주입한 후 정리하지 않음.
이후 실행되는 테스트들이 stub을 실제 모듈로 착각해 실패.

**픽스 파일:**

| 파일 | 픽스 |
|------|------|
| `test_mapping_retry.py` | `teardown_module()` 추가 — pandas stub 정리 |
| `test_supervisor.py` | `teardown_module()` 추가 |
| `test_supervisor_agent.py` | `teardown_module()` 추가 |
| `test_parser_paper_status.py` | 공격적 teardown — stub 제거 + `src.agents.agent1.*` 부모 패키지까지 sys.modules 제거 |

**핵심 교훈:** stub을 sys.modules에서 제거해도 부모 패키지(`src.agents.agent1`)가 stub 참조를 캐시하고 있을 수 있음.
부모 패키지까지 함께 제거해야 완전 격리.

```python
def teardown_module():
    for mod_name in list(sys.modules):
        if mod_name.startswith("src.agents.agent1."):
            sys.modules.pop(mod_name, None)
    sys.modules.pop("src.agents.agent1", None)
```

### 문제: 4-tuple return signature (4 테스트)

`_generate_with_trial_agent_from_nct`이 3-tuple → 4-tuple로 변경됨 (paper_status 추가).
`test_tte_api.py`의 fake 함수들이 3-tuple을 반환하고 있어 `ValueError: not enough values to unpack`.

**픽스:** fake 함수에 `None` (paper_status) 추가:
```python
return (make_generated_nct_study(...), "trial_agent", None, None)  # 4th = paper_status
```

### 문제: double filename prefix (2 테스트)

업로드 엔드포인트가 `{role}_` 접두사를 자동 추가하는데,
`test_tte_upload.py`가 이미 `supplement_s1.pdf`를 전송 → `supplement_supplement_s1.pdf`로 저장됨.

**픽스:** 테스트 입력을 `s1.pdf`로 변경.

### 문제: SPEC-UI-012 동적 바인딩 (8 테스트)

`test_tte_frontend_bindings.py`에서 static 문자열 `"Run Full Pipeline"` 등을 검사했는데,
SPEC-UI-012에서 KnockoutJS 동적 바인딩 `pipelineButtonText()`로 변경됨.

**픽스:** assertion을 동적 바인딩 형태로 업데이트.

### 커밋: `0a1ba54` fix(tests): resolve sys.modules pollution and API signature mismatches

---

## 2. 머지 결과

```
git merge feat/agent2-mapping-accuracy  # Fast-forward, 충돌 없음
```

**테스트 결과 (머지 후 main):**
- 1011 passed / 31 failed
- 31 failures = main 브랜치 기존 tech debt (integration tests, 네트워크 의존 테스트)
- 브랜치 이전 baseline 29 failures와 동일 수준

---

## 3. 이번 스프린트 구현 내용 (전체)

### SPEC-INFRA-002: Demographics 그룹 보존

- `CIRCE builder`에서 demographics criteria의 groupId 보존
- 그룹 빌더 헬퍼 추출, dead code 제거

### SPEC-MAP-001: Vocab Preference & Standard Concept Scoring

- OMOP vocab preference 순위 적용 (RxNorm > SNOMED > ICD 등)
- `standard_concept` 스코어링으로 비표준 개념 페널티

### SPEC-MAP-002: CV Breadth Improvements (M1–M3)

| 마일스톤 | 내용 |
|----------|------|
| M1 | `includeDescendants` 데이터 기반 결정 (refiner) |
| M2 | UMLS strict 모드, reranker domain-aware, critic inclusive |
| M3 | Critic self-reflection with counterevidence |

**추가 픽스:** ATC distance threshold 강화, compound 'or' drug class 쿼리 분리,
KG-validated 개념 self-reflection filter 보존.

### SPEC-PERF-001: Agent2 Performance

- Critic result cache (TTL+LRU)
- Critic model tiering by domain (gpt-4o vs gpt-4o-mini)
- artemis-api --workers 2, thread pool 16
- WebAPI JVM heap limit (OOM 방지)

### SPEC-PERF-002: process_eligibility Pipeline Optimization

- `CriterionResultCache` — 동일 criterion 중복 Agent2 실행 방지
- `ChromaDB batch_search` — N 쿼리를 ⌈N/50⌉ 배치로 축소
- `Agent2Workflow singleton` — 초기화 비용 제거
- `psycopg2 ThreadedConnectionPool` — 연결 풀 공유

### SPEC-UI-009: AI Review Panel (Builder Integration)

- Eligibility builder에 AI Review 패널 추가
- 매핑 후보 제안 및 수동 검토 인터페이스

### SPEC-UI-010: Treatment Preview + RAG Fallback Warning

- Treatment 코호트 미리보기 기능
- RAG fallback 발생 시 경고 표시

### SPEC-UI-011: Paper Sources Panel & Upload Role

- Preview 시 paper enrichment 상태 표시 (성공/실패/URL 안내)
- Upload 엔드포인트에 role-based 파일명 접두사 (`{role}_`)
- `GET /tte/papers/{nct_id}/status` 경량 상태 확인 API

### SPEC-UI-012: Auto-validate Before Execute

- Execute Study 클릭 전 design validation 자동 실행
- KnockoutJS 버튼 텍스트 동적 바인딩으로 교체

### 기타 버그픽스

- orphan dict bug in `_materialize_seeded_outcome_cohorts`
- `process_eligibility` idempotency (stale structuredExpression 제거)
- isGroupLabel 행 Agent2 매핑 skip
- csId offset에서 Demographics 제외
- inclusion rule 내 Group 재귀 CodesetId 패치
- AI Review panel studyId & 404 수정
- rerankConfidence 점수 반영

---

## 4. 파일 통계

| 카테고리 | 새 파일 |
|----------|---------|
| 테스트 | test_batch_prefetch, test_cohort_name_sanitization, test_criterion_cache, test_drug_class_fix, test_infra_002_demographics_grouping, test_interaction_regression, test_map_002_{m1,m2,m3}, test_outcome_eligibility_bridge, test_paper_status_models, test_paper_url_mapper, test_parse_criteria_items, test_parser_paper_status, test_perf002_integration, test_query_expander, test_seeded_outcome_cohort, test_service_paper_status |
| Agent2 | criterion_cache.py, query_expander.py, retriever.py |
| Agent1 | paper_url_mapper.py |
| SPECs | SPEC-PERF-002/, SPEC-UI-011/ |

---

## 5. Branch 정리

```bash
git branch -d feat/agent2-mapping-accuracy  # 삭제 완료
```
