# Session 3: csId Offset Bug Fix & Retest (2026-03-29)

## Summary

process-eligibility 자동 생성 → 0명 결과 → 원인 추적 → csId 오프셋 버그 발견/수정

## Timeline

1. Background agent 2개 실행 → 둘 다 **final=0** 보고
2. WebAPI cohort 756 확인 → ConceptSet 이름이 criteria와 불일치
3. criteria 메타데이터 확인 → HbA1c가 "Cerebrovascular accident"로, MI가 "glimepiride"로 표시
4. `_apply_draft_concept_set_metadata` 함수에서 **Demographics offset 버그** 발견
5. 수정 + 컨테이너 재생성 (env 변수 문제도 동시 해결)
6. 재실행 진행 중

## Bug: csId Offset in `_apply_draft_concept_set_metadata`

### Location
- `artemis/src/services/tte_service.py:2084-2105`

### Problem
```python
# BEFORE (buggy)
for offset, criterion in enumerate(criteria):  # ALL criteria including Demographics
    concept_set_index = start_index + offset    # offset counts Demographics too
```

Demographics criteria (3개)는 ConceptSet이 없는데 offset에 포함 → 이후 모든 csId가 3칸 밀림:
```
criteria[0] T2DM       → CS[1] ✓
criteria[1] Demographics → CS[2] ✗ (Demographics에 CS 없음)
criteria[2] Demographics → CS[3] ✗
criteria[3] Demographics → CS[4] ✗
criteria[4] HbA1c      → CS[5] ✗ (3칸 밀림!)
```

### Fix
```python
# AFTER (fixed)
mappable_offset = 0
for criterion in criteria:
    if domain in DEMOGRAPHIC_DOMAINS:
        continue  # skip offset increment
    concept_set_index = start_index + mappable_offset
    mappable_offset += 1
```

Caller도 수정 — exclusion start_index: `len(inclusion_criteria)` → `mappable_inclusion_count`

### Why Not Caught Before
- 이전 253명 결과는 **수동 CIRCE 수정** → 이 코드 경로 미사용
- INFRA-002 수정 시 `_build_seeded_target_circe`만 검토, 같은 파일의 다른 함수 미검토
- **교훈**: 도메인 버그 수정 시 파일 전체 grep 필수

## Additional Issue: Container Env Vars Not Applied

- `docker restart` 후 `AGENT2_CRITIC_MODEL_TIER=gpt-4o` 미반영
- Critic → gpt-4o-mini → 404 DeploymentNotFound
- **해결**: `docker rm -f` + `docker run -d` with explicit `-e` flags
- **교훈**: env 변경 시 반드시 컨테이너 재생성 + `docker exec env | grep` 검증

## Current Status

- [x] csId offset 버그 수정
- [x] 컨테이너 재생성 (AGENT2_CRITIC_MODEL_TIER=gpt-4o 확인)
- [x] 실수노트 저장 (feedback_container_env.md, feedback_grep_all_paths.md)
- [ ] process-eligibility 재실행 중 (5/17 criteria mapped)
- [ ] artifact apply
- [ ] cohort generation on LEADER_BENCHMARK
- [ ] attrition 결과 확인 (목표: Gold 1222에 근접)

## Related Files & Links

| Item | Path |
|------|------|
| Bug fix | `artemis/src/services/tte_service.py:2084-2115` |
| INFRA-002 fix (관련) | commit `c29ae6e` — `_build_seeded_target_circe` demographics groupId |
| INFRA-002 refactor | commit `1e900f9` — dead code removal, group builder helper |
| Ablation results | `artemis/docs/daily_notes/2026-03-29_ablation_study_results.md` |
| Gold comparison | `artemis/docs/daily_notes/2026-03-29_gold_vs_agent_full_comparison.md` |
| Session 2 summary | `artemis/docs/daily_notes/2026-03-29_agent_circe_vs_gold_session2_summary.md` |
| Plan | `docs/superpowers/plans/2026-03-29-agent2-retriever-seed-quality.md` |
| Feedback: container env | `~/.claude/projects/.../memory/feedback_container_env.md` |
| Feedback: grep all paths | `~/.claude/projects/.../memory/feedback_grep_all_paths.md` |
| Known issues | `~/.claude/projects/.../memory/known-issues.md` |
| Branch | `feat/agent2-mapping-accuracy` |

## Commits on Branch (latest first)

```
740b544 feat(agent2): add UMLS-backed query pre-expansion for abbreviations
989fc33 fix(agent2): preserve KG-validated concepts in self-reflection filter
8766bc3 fix(agent2): tighten ATC distance threshold
a8ce33a fix(agent2): SPEC-MAP-002 review fixes
86dfe40 feat(agent2): SPEC-MAP-002 M3 — critic self-reflection
144e6da feat(agent2): SPEC-MAP-002 M2 — UMLS strict, reranker, critic inclusive
1e900f9 refactor(tte): SPEC-INFRA-002 — cleanup
8d77412 feat(agent2): SPEC-MAP-002 M1 — includeDescendants
c29ae6e feat(tte): SPEC-INFRA-002 — demographics groupId
+ SPEC-PERF-001 (5 commits), SPEC-MAP-001 (1 commit) on main
+ csId offset fix (uncommitted)
```
