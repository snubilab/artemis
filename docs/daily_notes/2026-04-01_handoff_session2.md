# 2026-04-01 Handoff — Session 2

## 한 줄 요약

Gold vs AI cohort 비교 파이프라인 구조 확립, concept mapping benchmark v2 스크립트 완성, 멀티모델 LLM 결과 일부 수집. 미해결 에러 3개.

---

## 목표 (이번 세션)

1. **Gold vs AI cohort 비교** — Gold CIRCE JSON → WebAPI 코호트 생성 → AI 코호트와 환자 겹침 + HR/CI 비교
2. **RAG vs LLM vs Agent2 benchmark** — `ohdsi_criteria_benchmark.json` 기준, 도메인 필터 후 재측정
3. **멀티모델 비교** — gpt-4o, gpt-4o-mini, gpt-4.1, gpt-4.1-mini, o4-mini

---

## 완료된 것

### Benchmark Script v2
- `artemis/scripts/quick_concept_benchmark_v2.py` — 신규 작성
- 수정 내용:
  - 도메인 필터: `Condition, Drug, Procedure, Measurement`만 (기존엔 22개 도메인 전부)
  - Agent2 timeout: 30s → 120s
  - `--concept-path`, `--relationship-path` CLI 인수 추가
  - `--mappers rag,llm,agent2` 선택 실행
  - 데이터 소스: `ohdsi_criteria_benchmark.json` (7,945개 임상 항목)

### MI 이벤트 주입 (Ground Truth)
- Treatment arm 20%, Comparator arm 10% 무작위 주입, `+15일` (30일 윈도우 내)
- LEADER: 치료군 83명, 비교군 138명 이벤트
- PLATO: 치료군 15명, 비교군 117명 이벤트
- ARISTOTLE: 치료군 79명, 비교군 204명 이벤트

### AI 코호트 Survival Analysis 결과 (현재)

| Study | Method | HR | 95% CI | p-value |
|-------|--------|----|--------|---------|
| LEADER (431) | IPTW | 15.65 | 11.19–21.88 | <0.001 |
| PLATO (432) | IPTW | 0.94 | 0.89–0.99 | 0.02 |
| ARISTOTLE (424) | IPTW | 1.82 | 1.48–2.24 | <0.001 |

> **주의**: LEADER HR=15.65는 `treatment_vs_rest` 모드에서 치료군(당뇨)이 일반 CDM 인구 대비 이벤트율이 높아서 폭발적으로 나온 것. PLATO는 HR<1로 예상 반대 방향.

### Gold Cohort WebAPI 등록
- LEADER Gold Treatment → cohort_definition_id=**1136**
- PLATO Gold Treatment → cohort_definition_id=**1137**
- ARISTOTLE Gold Treatment → cohort_definition_id=**1138**

---

## 미해결 에러 (다음 세션 P0)

### 에러 1 — Gold cohort generation TIMEOUT
```
status: COMPLETE (but failMessage: statement timeout)
```
- LEADER(1136), ARISTOTLE(1138): WebAPI cohort generation에서 SQL statement timeout
- PLATO(1137)만 436명 생성 성공
- **원인**: Gold CIRCE JSON이 복잡한 concept hierarchy traversal 포함 → `synthea_cdm_leader.CONCEPT` 테이블 조회 타임아웃
- **Fix**: WebAPI statement_timeout 증가 또는 Gold JSON을 단순화

### 에러 2 — Agent2 풀 벤치마크 Neo4j localhost 연결
```
KG expansion failed: bolt://localhost:7687 Connection refused
```
- 컨테이너에서 NEO4J_URI env 미전달 문제
- `-e NEO4J_URI=bolt://artemis-neo4j-v2:7687` 명시해서 재시작 완료
- **현재 상태**: RAG phase 진행 중 — 완료까지 ~1시간 예상 (Agent2 100개 × 45s)

### 에러 3 — gpt-4o-mini 컨테이너에서 CONCEPT.csv not found
```
FileNotFoundError: /omop_vocab/files/CONCEPT.csv
```
- 컨테이너에 vocab 파일 마운트 안 됨
- CONCEPT.csv: 630만 행, CONCEPT_RELATIONSHIP.csv: 3,927만 행 → docker cp 불가
- **Fix 옵션**:
  1. docker-compose에 `omop_vocab/` volume 마운트 추가
  2. vocab 대신 DB (webapi 스키마)에서 직접 조회하도록 `OfflineVocabularyResolver` 수정
  3. 호스트에서 실행 시 virtualenv에 langchain 설치

---

## 멀티모델 LLM 결과 (부분 완료)

### 완료된 결과 파일
| 파일 | 모델 | Recall | F1 | Hit@1 | Latency |
|------|------|--------|----|-------|---------|
| `bench_o4mini.json` | o4-mini | 0.000 | 0.000 | 0.000 | 764ms |
| `bench_gpt41mini.json` | gpt-4.1-mini | 0.067 | 0.015 | 0.120 | 2740ms |
| smoke test (20개) | gpt-4o | 0.064 | 0.046 | 0.300 | 1154ms |

> **o4-mini recall=0.0** 이상함 — vocab resolve 실패가 원인일 가능성 높음. 재검토 필요.

### 아직 안 된 것
- gpt-4.1 100개: host에서 실행 중, vocab 에러 없으면 곧 완료
- RAG + Agent2 + LLM gpt-4o 풀 100개: 컨테이너에서 재시작 (RAG phase)
- gpt-4o-mini: CONCEPT.csv 에러로 미완료

---

## 다음 세션 액션 아이템

### P0
1. **Gold COHORT generation timeout** 해결
   - `docker exec broadsea-atlasdb psql -c "SET statement_timeout='300s'"`로 테스트
   - 또는 `webapi` application.properties에서 `spring.datasource.hikari.connection-timeout` 증가
2. **CONCEPT.csv 접근** 문제 해결 (docker-compose volume 마운트 또는 DB 조회 방식 전환)

### P1
3. **Agent2 풀 벤치마크 완료 대기** — `/tmp/bench_v2_full.log` 모니터링
4. **Gold cohort 생성 후 AI vs Gold HR 비교** — PLATO만 현재 가능 (1137: 436명)
5. **o4-mini recall=0 원인 분석** — per_item 결과에서 pred_ids 확인

### P2
6. `gpt-4.1` host 결과 수집 후 멀티모델 비교 테이블 완성

---

## 인프라 상태

| 컨테이너 | 상태 |
|---------|------|
| artemis-api (`477b3f1664ed`) | Up |
| ohdsi-webapi | Up |
| broadsea-atlasdb | Up |
| artemis-neo4j-v2 | Up (healthy) |
| traefik | Up |

## 주요 파일 경로

| 파일 | 설명 |
|------|------|
| `artemis/scripts/quick_concept_benchmark_v2.py` | 수정된 벤치마크 스크립트 |
| `artemis/data/benchmark_results/` | 벤치마크 결과 JSON |
| `artemis/data/gold/LEADER\|PLATO\|ARISTOTLE/` | Gold CIRCE JSON |
| `/tmp/bench_v2_full.log` | 컨테이너 내 현재 실행 중 벤치마크 로그 |
| `docs/tte_agent/06_backend_atomic_todo_plan.md` | TTE 백엔드 todo |

## Git
- Branch: `fix/agent1-pattern-e-or-logic`
- Push target: `git push fork fix/agent1-pattern-e-or-logic`
