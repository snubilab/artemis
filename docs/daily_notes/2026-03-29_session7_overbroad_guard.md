# Session 7: Overbroad Guard + process_eligibility (2026-03-29)

## Summary

Session 6 핸즈오프 기반으로 roll-up overbroad ancestor 문제 수정 및 process_eligibility 재실행 시도.

## Completed

### 1. python-multipart 추가
- `pyproject.toml`: chromadb ^0.4.0 → ^1.5, python-multipart>=0.0.7 추가
- `requirements.txt`: python-multipart==0.0.22 추가
- 컨테이너 내 pip install로 핫패치 완료

### 2. Roll-up Overbroad Guard 구현
- `expression_builder.py`에 `_filter_overbroad()` 메서드 추가
- `_roll_up()` 첫 단계에서 호출 → overbroad ancestor 먼저 제거 후 정상 roll-up
- Threshold: `AGENT2_ROLLUP_MAX_DESCENDANTS` env var (default: 500)
- Safety: 모든 후보가 overbroad면 원본 유지
- DB 에러 시 graceful fallback

### 3. print() → logger 전환
- expression_builder.py 내 모든 print() → logger.info/warning

### 4. 단위 테스트
- 기존 14개 중 13 pass, 1 fail (기존 mock이 새 _filter_overbroad 호출 미고려 — 수정 필요)
- 새 TestFilterOverbroad 6개 추가: **6/6 pass**

### 5. 실제 DB 시뮬레이션 검증 (synthea23m.concept_ancestor)

| Scenario | Without guard (old) | With guard (new) |
|---|---|---|
| **Stroke** | Clinical finding만 남음 (133K desc) | Cerebral infarction, Cerebral artery occlusion, TIA |
| **MI** | Clinical finding만 남음 | Acute myocardial infarction (벽 하위개념 roll-up됨) |
| **GLP-1 Drug** | INSULINS AND ANALOGUES (10K desc) | liraglutide (247 desc) |

Threshold 500 검증:
- Gold가 사용하는 가장 넓은 ancestor: Ischemic heart disease (206 desc) → 통과
- 제거 대상: Clinical finding (133K), Disorder of body system (68K) → 확실히 제거

### 6. process_eligibility 실행 (partial)
- study 420 매핑 트리거 성공
- 관찰 사항:
  - Overbroad guard: **0회 발동** — Agent2 파이프라인(critic+refiner)이 이미 broad ancestor 걸러냄
  - HbA1c → LOINC 3004410 정상 매핑 (MedCPT 효과)
  - ATC threshold 0.4: insulin 잘못 매칭 차단
  - Roll-up 정상 동작 (27→1, 22→1 등)
- 중단 원인: python-multipart 미설치로 컨테이너 크래시 → 재시작 → 재실행 필요

### 7. 디스크 정리
- Colima 디스크: 100% (288GB) → 80% (226GB), **69GB 회수**
- Stopped 컨테이너 12개 제거, dangling 이미지 23개 제거, orphan 볼륨 제거

## Key Findings

1. **Overbroad guard는 안전망 역할** — Agent2 파이프라인이 이미 대부분 broad ancestor를 걸러내지만, 만약 빠져나올 경우 catch하는 역할
2. **python-multipart는 chromadb 1.5.5의 FastAPI 의존성** — 이미지 리빌드 전까지 pip 핫패치 필요
3. **HADES (R/RStudio)** — TTE 최종 분석 단계(CohortMethod)에서 필요할 수 있으므로 보존

## Pending

- [ ] process_eligibility 완전 재실행 (python-multipart 설치 후 재시작 완료 상태)
- [ ] Gold 비교 — attrition test on LEADER_BENCHMARK (target: Gold 1222)
- [ ] criterion_name 수정 검증 — concept set 이름이 sourceText 사용하는지 확인
- [ ] 기존 test_roll_up_removes_descendants mock 수정
- [ ] 이미지 리빌드 (python-multipart 포함)

## Files Changed

| File | Change |
|---|---|
| `artemis/pyproject.toml` | chromadb ^1.5, python-multipart 추가 |
| `artemis/requirements.txt` | python-multipart==0.0.22 추가 |
| `artemis/src/agents/conceptset/expression_builder.py` | `_filter_overbroad()` 추가, print→logger |
| `artemis/tests/test_expression_builder.py` | TestFilterOverbroad 6개 테스트 추가 |

## Environment

- Branch: `feat/agent2-mapping-accuracy`
- Container: artemis-api (pip hotpatch: python-multipart)
- EMBEDDING_MODEL: medcpt
- AGENT2_ROLLUP_MAX_DESCENDANTS: 500 (default)
