# 2026-03-26: Cohort Generation Performance Optimization — Full Log

## Problem Statement

OHDSI CIRCE SQL cohort generation이 PostgreSQL에서 매우 느림.
LEADER Gold (54 ConceptSets, 17 InclusionRules, 10K patients) 기준 **479초 (8분)**.

Root cause: `concept_ancestor` (75M rows) 반복 JOIN + PostgreSQL 쿼리 플래너의 temp table 통계 부재.

---

## Timeline

### Phase 1: Research & Alternative 탐색

1. OHDSI 커뮤니티 조사:
   - circe-be #101: temp Codesets 테이블에 ANALYZE 없어서 PostgreSQL 플래너 오판
   - CohortConstructor: R 패키지, domain별 배치 처리 (Python 통합 어려움)
   - Atlas #2648: 같은 SQL 직접 실행 시 100x 빠름
2. 3가지 최적화 브랜치 결정:
   - Branch 1: ANALYZE Codesets injection (Direct SQL)
   - Branch 2: Pre-resolve descendants (includeDescendants=false)
   - Branch 3: Spark engine (나중에 추가)

### Phase 2: Branch 1 — `optimize/analyze-codesets`

**구현:**
- `_render_sql()`: @placeholder 치환
- `_inject_analyze()`: Codesets INSERT 뒤에 `ANALYZE Codesets;` 주입
- `generate_cohort_direct()`: WebAPI 우회 직접 SQL 실행
- `COHORT_DIRECT_SQL=1` env var opt-in, 실패 시 WebAPI fallback

**실수 1: SqlRender 번역 누락**
- WebAPI `/cohortdefinition/sql`이 반환하는 건 OHDSI SQL (SQL Server dialect)
- DATEADD, DATEDIFF, DATEFROMPARTS, #TempTable이 PostgreSQL에서 에러
- `UPDATE STATISTICS` (SQL Server 전용) 제거 regex만 넣고 나머지 변환 안 함

**실수 2: `generateStats: True`로 인한 추가 placeholder**
- `@results_database_schema` placeholder가 추가로 생겨서 미치환 에러

**실수 3: `drug_era` 테이블 부재**
- SYNTHEA23M 스키마에 drug_era 없음 → 벤치마크 데이터 선택 오류

**Code Review 결과 (6 issues):**
- C1: SqlRender 번역 누락 → `/WebAPI/sqlrender/translate` 추가 (trace_cohort_attrition.py에 이미 패턴 존재)
- C2: SQL injection via schema name → `_validate_schema()` 추가
- I1: `#` regex 너무 공격적 → SqlRender가 처리하므로 제거
- I3: env var import 시점 고정 → 호출 시점 읽기로 변경
- I4: importlib 해킹 → sys.path 방식으로 통일
- I5: integration test mock 과도 → 단순화

**수정 후 결과:**
- SYNTHEA_CDM_BENCHMARK (10K): 3,840ms → 1,832ms (2.1x)
- SYNTHEA23M (2.7M): 479s → 411s (1.16x)

### Phase 3: Branch 2 — `optimize/preresolve-descendants`

**구현:**
- `DescendantResolver`: concept_ancestor에서 batch SQL로 descendants resolve
- Agent 3 assembler에서 expand → `includeDescendants=false`로 CIRCE JSON 생성
- `PRERESOLVE_DESCENDANTS=1` env var opt-in

**결과: 역효과**
- 302 items → 28,151 items 폭증
- Codesets INSERT 비용 증가가 concept_ancestor JOIN 제거 이득을 상쇄
- SYNTHEA23M: 479s → 496s (0.97x, 더 느림)
- BOTH (ANALYZE + PRERESOLVE): 479s → 397s (1.21x)

### Phase 4: 벤치마크 인프라 삽질

**실수 4: 잘못된 데이터로 벤치마크**
- SYNTHEA23M으로 시도 → drug_era 없어서 Direct SQL 에러
- SYNTHEA_CDM_BENCHMARK로 전환 → 0 patients (데이터 안 맞음)
- 유저가 study별 합성 데이터를 사용하라고 지적

**실수 5: ETL 데이터 미스매치**
- `run_etl_full.sh`가 `synthea_cdm_benchmark`만 DROP, `synthea_native_benchmark` 유지
- R ETL이 native schema에 이전 데이터(PLATO) 있으면 CSV 로드 스킵
- 결과: LEADER CSV를 심링크했는데 실제론 PLATO 데이터로 ETL 실행

**실수 6: R ETL Step 2,3 주석 처리**
- R 스크립트에서 CreateSyntheaTables, LoadSyntheaTables가 주석 처리되어 있었음
- 주석 해제 후에도 Step 1 CDM 테이블 이미 존재 에러 → tryCatch로 감싸서 해결

**실수 7: concept VIEW 충돌**
- 이전 실행에서 concept을 VIEW로 만들었는데, 새 실행에서 TABLE로 다시 만들려 해서 에러
- 해결: CDM 스키마도 함께 DROP+CREATE

**실수 8: DROP SCHEMA 블로킹**
- 이전 벤치마크의 cohort generation이 1시간+ 돌면서 테이블 lock 보유
- DROP이 14분+ 대기
- `pg_stat_activity`로 확인 후 `pg_terminate_backend()` 실행

**최종 LEADER 벤치마크 (올바른 데이터):**

| Mode | Patients | Time | Speedup |
|------|----------|------|---------|
| BASELINE (WebAPI) | 1,222 | 479s | 1.0x |
| ANALYZE | 1,222 | 411s | 1.16x |
| PRERESOLVE | 1,222 | 496s | 0.97x |
| BOTH | 1,222 | 397s | 1.21x |

### Phase 5: Spark 결정

- PostgreSQL 최적화 한계 확인 (최대 1.21x)
- OHDSI SqlRender 공식 지원 dialect 조사: PostgreSQL, SQL Server, Spark, Redshift, BigQuery, Snowflake, Oracle, SQLite
- DuckDB 검토 → 비공식 (PostgreSQL dialect 재활용 가능하지만 보장 없음)
- **Spark 채택**: 공식 지원 + 컬럼 엔진 + 무료

### Phase 6: Branch 3 — `optimize/spark-cohort`

**구현:**
- `spark_executor.py`: `SparkCohortExecutor` + `render_spark_sql()`
- `webapi_client.py`: `translate_sql()`, `generate_cohort_spark()`, `COHORT_ENGINE=spark` 라우팅
- SqlRender Spark dialect 사용 (`targetdialect: "spark"`)

**실수 9: concept_ancestor JDBC OOM**
- 75M rows를 Spark JDBC로 전체 읽기 시도 → OOM kill (exit 137)
- Colima 기본 7.7GB 메모리로는 불가능
- 해결: Parquet pre-export + Colima 메모리 18GB로 증설

**실수 10: Parquet export OOM**
- pandas로 75M rows 읽기 시도 → 컨테이너 OOM
- 해결: `psql \COPY` → CSV → 호스트에서 pandas chunked → Parquet
- concept도 mixed types 에러 → `dtype=str` 지정
- concept_relationship (39M rows)도 별도 export 필요

**실수 11: Vocab VIEW를 Spark JDBC가 못 읽음**
- per-study 스키마의 vocab tables가 synthea23m을 참조하는 VIEW
- Spark JDBC는 PostgreSQL VIEW 읽기 불가
- 해결: vocab tables를 synthea23m에서 직접 읽어 Parquet으로 제공

**실수 12: Schema-qualified 참조 미스매치**
- CIRCE SQL이 `synthea_cdm_leader.person`으로 참조
- Spark에서 `createOrReplaceTempView("person")` → unqualified만 접근 가능
- `saveAsTable()` 시도 → 75M rows에서 OOM
- 해결: `render_spark_sql`에서 `@cdm_database_schema.` → "" (빈 문자열)로 치환, unqualified 참조

**실수 13: @target_cohort_table 이중 prefix**
- `@target_database_schema.@target_cohort_table`
- `results_schema.results_schema.cohort`로 이중 치환됨
- 해결: `@target_cohort_table` → `"cohort"` (스키마 없이)

**실수 14: cohort 테이블 미생성**
- CIRCE SQL의 `INSERT INTO results_schema.cohort`가 Spark에서 테이블 없어서 실패
- 해결: 실행 전 `CREATE TABLE results_schema.cohort` 미리 생성

**실수 15: Spark warehouse LOCATION_ALREADY_EXISTS**
- 이전 실행의 `/tmp/spark-warehouse/` 잔여 파일 → CREATE TABLE 충돌
- 해결: `DROP TABLE IF EXISTS` 후 CREATE, spark-warehouse 디렉토리 정리

**실수 16: "36x 속도 향상" 오보**
- 초기 벤치마크에서 13초, 1,222명 보고 → 실제로는 PG fallback이 이전 WebAPI 결과를 읽은 것
- Spark가 실제로 cohort를 생성한 게 아니었음
- PG cohort 테이블을 DELETE하고 재실행하니 0명 → 이중 prefix 버그 발견

**최종 Spark 결과 (실제, 3개 study 모두 WebAPI 교차 검증 완료):**

| Study | CS | Rules | Patients | WebAPI(s) | Spark(s) | Speedup | Match |
|-------|-----|-------|----------|-----------|----------|---------|-------|
| LEADER | 54 | 17 | 1,222 | 479 | 48 | **10x** | ✅ |
| PLATO | 23 | 5 | 436 | 14 | 15 | ~1x* | ✅ |
| ARISTOTLE | 33 | 0 | 1,219 | 2,108 | 19 | **111x** | ✅ |

*PLATO는 소규모 cohort(436명)라 Spark 오버헤드 > 이득. 대규모에서 효과 극대화.
*ARISTOTLE WebAPI 2,108s: 이전 세션 stuck query(35분)가 현 세션 실행과 중복돼 인위적으로 길어짐.

### Phase 7: Study별 영구 스키마 셋업

**구현:**
- `setup_all_benchmark_sources.sh`: LEADER/PLATO/ARISTOTLE 각각 영구 스키마 생성
- `run_etl_per_study.R`: study별 R ETL (env var로 스키마 지정)
- `setup_benchmark_native_tables.R`: native table 생성

**실수 17: bash uppercase `${var^^}` → zsh 비호환**
- 해결: `$(echo $var | tr a-z A-Z)`

**실수 18: WebAPI source 등록 실패**
- INSERT SQL이 WebAPI source 테이블 구조와 안 맞음 → WARNING
- 아직 미해결: WebAPI REST API로 등록하거나 SQL 수정 필요

**실수 19: PLATO 데이터 선택 오류**
- `20260318_plato_10k_currentcheck` 사용 → 0명
- `20260318_plato_10k_cachefixfinal`이 436명 나온 올바른 데이터
- 해결: setup script의 CSV 경로 수정

---

## Lessons Learned (영구 기록)

### Infrastructure
1. **Colima 메모리**: Spark 사용 시 18GB+ 필요 (`colima start --memory 18`)
2. **DROP SCHEMA 시 pg_stat_activity 확인**: long-running query가 lock 보유하면 DROP 무한 대기
3. **ETL 재로드 시 native + CDM 두 스키마 모두 DROP**: R ETL이 native 데이터 있으면 CSV 로드 스킵
4. **Study별 영구 스키마 사용**: DROP/재로드 반복 피하기

### Data
5. **Study별 올바른 합성 데이터 사용**: LEADER→liraglutide, PLATO→ticagrelor
6. **Generated gold eval의 summary.json에서 정확한 cohort_definition_id 확인**: cohort 576 ≠ cohort 452
7. **Vocab tables는 VIEW**: per-study CDM 스키마의 concept/concept_ancestor는 synthea23m VIEW → Spark JDBC 불가 → Parquet 필요

### Spark 실행
8. **concept_ancestor (75M rows) JDBC 불가**: Parquet pre-export 필수
9. **concept Parquet export 시 `dtype=str`**: mixed types 에러 방지
10. **Schema-qualified ref 제거**: `@cdm_database_schema.` → "" (Spark temp view는 unqualified만)
11. **`@target_cohort_table` → `"cohort"`만**: `results_schema.cohort`로 하면 이중 prefix
12. **cohort 테이블 미리 생성**: CIRCE SQL INSERT 대상 테이블이 Spark에 존재해야
13. **spark-warehouse 정리**: 이전 실행 잔여 파일 → LOCATION_ALREADY_EXISTS

### SqlRender
14. **`/WebAPI/sqlrender/translate` 반드시 사용**: templateSql은 OHDSI SQL (SQL Server dialect)
15. **`generateStats: False`**: True면 `@results_database_schema` 추가 placeholder 생성
16. **Spark dialect는 `USING DELTA` 생성**: Delta Lake 없으면 제거 필요
17. **Spark dialect는 temp table에 랜덤 prefix**: `@temp_database_schema.{prefix}TableName`

### 벤치마크
18. **PG fallback 결과를 Spark 결과로 오인 주의**: PG cohort 테이블 DELETE 후 재실행해야 진짜 Spark 결과
19. **WebAPI generation cache 클리어**: 재벤치마크 시 `webapi.generation_cache` DELETE 필수

---

## Final Architecture

```
CIRCE JSON
  → WebAPI /cohortdefinition/sql (OHDSI SQL 생성, 변경 없음)
  → WebAPI /sqlrender/translate (Spark dialect 변환, 변경 없음)
  → render_spark_sql() (placeholder 치환, DELTA 제거)
  → PySpark local[*] (CDM: JDBC, vocab: Parquet, 실행)
  → cohort results → PG writeback
```

변경한 것: **실행 엔진만** (PostgreSQL → Spark)
변경 안 한 것: CIRCE-BE, Agent 3, cohort definition 구조, WebAPI

---

## Files Changed

| Branch | File | Description |
|--------|------|-------------|
| optimize/spark-cohort | `artemis/src/pipeline/spark_executor.py` | SparkCohortExecutor + render_spark_sql |
| optimize/spark-cohort | `artemis/src/pipeline/webapi_client.py` | translate_sql, generate_cohort_spark, COHORT_ENGINE routing |
| optimize/spark-cohort | `artemis/tests/test_spark_executor.py` | 11 unit tests |
| optimize/spark-cohort | `artemis/pyproject.toml` | pyspark optional dependency |
| optimize/spark-cohort | `artemis/scripts/setup_all_benchmark_sources.sh` | Per-study schema setup |
| optimize/spark-cohort | `artemis/scripts/run_etl_per_study.R` | Per-study R ETL |
| optimize/spark-cohort | `artemis/scripts/setup_benchmark_native_tables.R` | Native table creation |
| optimize/analyze-codesets | `artemis/src/pipeline/webapi_client.py` | _render_sql, _inject_analyze, generate_cohort_direct |
| optimize/analyze-codesets | `artemis/tests/test_direct_sql_cohort.py` | 20 tests |
| optimize/preresolve-descendants | `artemis/src/pipeline/descendant_resolver.py` | DescendantResolver |
| optimize/preresolve-descendants | `artemis/src/agents/agent3/assembler.py` | preresolve integration |
| optimize/preresolve-descendants | `artemis/tests/test_descendant_resolver.py` | 21 tests |

---

## Session 2 (2026-03-27): 3-Study Validation Complete

### 실수 20: ARISTOTLE WebAPI stuck query
- 이전 세션 PID 62681이 35분간 `CREATE TEMP TABLE qualified_events` 상태로 block
- 새 세션에서 `pg_terminate_backend`로 kill 후 재실행 → 정상 완료
- 교훈: 새 세션 시작 시 `pg_stat_activity`에서 long-running query 확인 필수

### 실수 21: synthea_cdm_aristotle 구 캐시 (43명)
- `webapi.cohort_generation_info`에 43명 결과 잔류 (이전 스키마 데이터)
- `webapi.generation_cache` DELETE 후 재실행 필요
- SYNTHEA_CDM_BENCHMARK에는 올바른 ARISTOTLE 데이터(apixaban 1,323건) 정상 로드 확인

---

## Next Steps

- [x] PLATO cachefixfinal 데이터로 Spark vs WebAPI 교차 검증 → ✅ 436 match
- [x] ARISTOTLE obs_fix_v3 데이터로 Spark vs WebAPI 교차 검증 → ✅ 1,219 match
- [ ] WebAPI에 study별 source 등록 (LEADER_BENCHMARK, PLATO_BENCHMARK, ARISTOTLE_BENCHMARK)
- [ ] Parquet export 자동화 스크립트
- [ ] Docker 이미지에 JDK + pyspark + JDBC 포함
- [ ] Colima 18GB를 기본 설정으로 문서화
- [ ] `evaluate_generated_gold_studies.py` study별 독립 스키마 + WebAPI cache clear 통합
