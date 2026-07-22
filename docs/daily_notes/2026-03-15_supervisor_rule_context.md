# 2026-03-15: Supervisor Quality Gates + rule_context AB 벤치마크

## 오늘 완료

- [x] Domain Mismatch Gate 구현 (`supervisor_agent.py` `_check_domain_mismatches`)
  - entity domain_hint vs mapped concept domain_id 비교, report-only
  - 28개 + 7개 = 35/35 테스트 통과
- [x] rule_context 전달 구현 (`supervisor.py` `_step2_map()`)
  - `parent_rule` → humanize → Agent 2 `context` 파라미터
  - Codex 리뷰 반영: fallback=None, slug humanize
- [x] benchmark_v5.py `--no-rule-context` CLI 플래그 추가
- [x] AB 벤치마크 실행 (PLATO E2E_TROY, Clopidogrel v3.4)
- [x] ABLATION_STUDY.md §2.15 문서화

## 발견/변경사항

- **rule_context는 PLATO에서 성능 차이 없음** (B=A: R=56.4%, P=20.2%, F1=22.2%)
  - Rule 1-3: fast path → reranker 미사용, context 무관
  - Rule 4-5 (R=0%): Agent 1이 domain=Condition으로 오분류 → **domain_hint가 근본 bottleneck**
- **domain_hint 오분류 문제 확인**: "oral anticoagulation therapy" → Agent 1이 Condition으로 분류 (Drug이어야 함)
  - 이건 Agent 1 파서의 domain 분류 정확도 문제 → rule_context와 무관
- **인프라**: `artemis-neo4j`(7687), `artemis-redis`(6379, 신규 생성), `broadsea-atlasdb` 기동 체크리스트 필요
- Codex 리뷰: `entity.get("parent_rule") or entity.get("text")` 중복 context → fallback=None으로 수정

## 벤치마크 결과

| 조건                   | Avg Recall | Avg Precision | Avg F1 | Full | Wrong |
| ---------------------- | :--------: | :-----------: | :----: | :--: | :---: |
| [B] WITH rule_context  |   56.4%    |     20.2%     | 22.2%  |  3   |   2   |
| [A] WITHOUT rule_context|  56.4%    |     20.2%     | 22.2%  |  3   |   2   |

## 다음 TODO

- [x] ~~LEADER trial에서 rule_context AB 재검증~~ → domain pre-check 실험으로 대체
- [ ] Agent 1 domain 분류 정확도 개선 (oral anticoagulation → Drug)
- [ ] Agent 2 MappingResult에 path metadata 추가 (fast/slow/ATC/critic_skip)

---

## Domain Pre-Check 실험 (폐기)

- [x] `workflow.py` `process_with_details()` 초입에 ChromaDB top-3 (domain_hint=None) 검색 → domain vote → override 삽입
- [x] PLATO E2E_TROY 벤치마크: 변화 없음 (R=56.4%, P=20.2%, F1=22.2%)
- [x] **LEADER E2E_TROY 벤치마크: R=83.9%, P=61.7%, F1=61.4%**
- [x] **Harmful override 6건** 발생 → **기본 비활성화** (`DOMAIN_PRECHECK=0`)

### Harmful Override 목록

| Entity | Agent 1 domain | Pre-check override | 올바른 domain | 판정 |
|--------|:---:|:---:|:---:|:---:|
| Insulin | Drug | Procedure | Drug | ❌ harmful |
| Microalbuminuria | Measurement | Condition | Measurement | ❌ harmful |
| Proteinuria | Measurement | Condition | Measurement | ❌ harmful |
| Acute stroke | Condition | Procedure | Condition | ❌ harmful |
| Kidney Transplant | Procedure | Device | Procedure | ❌ harmful |
| Organ transplant | Procedure | Observation | Procedure | ❌ harmful |

### 근본 원인
ChromaDB semantic embedding은 **의미적 유사성** 기반이라 "Insulin" → "Administration of insulin" (Procedure)처럼 같은 임상 용어가 다른 도메인에 존재. Domain 분류에는 부적합.

### 결론
- 코드는 실험용으로 유지 (`DOMAIN_PRECHECK=1`로 활성화 가능)
- **Agent 1 domain 분류 정확도** 개선이 근본 해법
