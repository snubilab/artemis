# RFC-013: SqlRender SQL Server→PostgreSQL 변환 실패 우회

> Historical note:
> This RFC captured an earlier working hypothesis and bypass strategy.
> Later verification showed that Atlas UI uses a two-step path:
> `cohortdefinition/sql -> sqlrender/translate`.
> The current generated-gold mismatch is therefore better understood as a path divergence
> between Atlas/UI and the repo-local `python_fallback`, not simply as "WebAPI cannot translate".
> For the consolidated current interpretation, see:
> `artemis/docs/debugging/2026-03-22_generated_gold_sql_translation_current_state.md`

**상태**: 검토 중  
**날짜**: 2026-03-17  
**제안자**: @kyh

## 1. 가설 및 목표

### 문제
WebAPI 2.15.1의 내부 SqlRender가 Circe SQL template의 SQL Server 함수 3종을 PostgreSQL로 변환하지 않음.

| 함수 | Circe 출력 (SQL Server) | PostgreSQL 기대 변환 | 실제 |
|:---|:---|:---|:---|
| `DATEADD(day, n, d)` | `(d + n * INTERVAL '1 day')` | ❌ 변환 안 됨 |
| `DATEDIFF(d, s, e)` | `(CAST(e AS DATE) - CAST(s AS DATE))` | ❌ `DATEDIFF('day', s, e)`로 부분 변환 |
| `DATEFROMPARTS(y,m,d)` | `make_date(y,m,d)` | ❌ 변환 안 됨 |

- `DATEDIFF`, `DATEFROMPARTS` → DB에 사용자 함수 생성으로 우회 가능
- **`DATEADD(day, ...)`** → unquoted `day`가 column name으로 해석 → 함수 우회 **불가**
- WebAPI는 에러 시 ROLLBACK → **0명 반환** (silent failure)

### 목표
V6 Cohort Benchmark에서 Gold/Agent cohort를 PostgreSQL에서 정상 실행하여 환자 수 > 0 달성

### 성공 기준
- Gold cohort: 수동 SQL과 동일한 ~1,093명
- Agent cohort: > 0명 (E2E 파이프라인 검증)

## 2. 제안 설계 (3개 옵션)

### Option A: Python 직접 SQL 번역 + psql 실행 (⭐ 추천)

**개요**: WebAPI의 cohort generation을 우회. Circe SQL template을 받아서 Python regex로 PostgreSQL 변환 후 `psql`로 직접 실행.

**장점**:
- WebAPI 의존성 완전 제거
- 변환 로직을 직접 통제 가능
- 디버깅 용이 (실행 SQL을 파일로 저장)
- 구현 시간: ~2시간

**변환 규칙** (5개):
```python
# 1. DATEADD(day, n, d) → (d + n * INTERVAL '1 day')
re.sub(r'DATEADD\(day,\s*(-?\d+),\s*(.+?)\)', r'(\2 + \1 * INTERVAL \'1 day\')', sql)

# 2. DATEDIFF(d, s, e) → (CAST(e AS DATE) - CAST(s AS DATE))
re.sub(r'DATEDIFF\(d,\s*(.+?),\s*(.+?)\)', r'(CAST(\2 AS DATE) - CAST(\1 AS DATE))', sql)

# 3. DATEFROMPARTS(y, m, d) → make_date(y, m, d)
re.sub(r'DATEFROMPARTS\((.+?),\s*(.+?),\s*(.+?)\)', r'make_date(\1, \2, \3)', sql)

# 4. #TempTable → temp table
sql.replace('#Codesets', 'codesets_temp')

# 5. schema substitution
sql.replace('@cdm_database_schema', cdm_schema)
```

**구현 위치**: `benchmark_v6_cohort.py` 에 `generate_cohort_direct()` 함수 추가

**Flow**:
```
Gold JSON ──→ WebAPI /sql endpoint (template) ──→ Python translate ──→ psql 직접 실행
                                                                         ↓
                                                              synthea_cdm_benchmark_results.cohort
```

---

### Option B: R SqlRender 직접 호출

**개요**: R의 `SqlRender::translate()` 함수를 subprocess로 호출하여 정확한 PostgreSQL SQL 생성

**장점**:
- OHDSI 공식 변환 엔진 사용 (가장 정확)
- 모든 edge case 처리됨

**단점**:
- R 런타임 의존성 추가
- 복잡한 파이프라인 (Python → R → psql)
- Circe template을 먼저 R에서 처리 필요

**구현**:
```r
library(SqlRender)
sql <- readLines("/tmp/circe_template.sql")
translated <- SqlRender::translate(sql, targetDialect = "postgresql")
writeLines(translated, "/tmp/circe_pg.sql")
```

---

### Option C: WebAPI SqlRender 설정 수정

**개요**: WebAPI가 SqlRender를 올바르게 호출하도록 설정/코드 수정

**장점**:
- 근본 해결
- 다른 cohort에도 적용됨

**단점**:
- WebAPI Java 소스 수정 필요 (시간 소요 큼)
- Docker 이미지 재빌드 필요
- 원인이 SqlRender 라이브러리 버그일 경우 upstream fix 대기

---

## 3. 추천: Option A

| 기준 | Option A (Python) | Option B (R) | Option C (WebAPI) |
|:---|:---|:---|:---|
| 구현 시간 | ~2시간 | ~3시간 | ~1일+ |
| 정확성 | 높음 (5개 규칙) | 최고 | 최고 |
| 유지보수 | 중간 | 낮음 (R 의존성) | 높음 |
| WebAPI 의존성 | 제거 | 제거 | 유지 |
| **리스크** | 미처리 edge case | R 호출 복잡성 | WebAPI 재빌드 |

**추천 이유**: 
- V6 벤치마크 전용이므로 완벽한 OHDSI 호환보다 **동작하는 결과**가 우선
- 수동 SQL로 이미 1,093명 확인 → 변환 규칙 5개만으로 충분
- WebAPI dependency 제거로 디버깅이 훨씬 쉬움

## 4. 예상되는 리스크

1. **Python regex 변환의 한계**: 중첩된 `DATEADD(day, n, DATEADD(day, m, d))` 같은 패턴에서 regex가 실패할 수 있음
   - 완화: Circe가 생성하는 패턴을 분석하여 테스트 케이스 작성
2. **Inclusion Rules SQL의 복잡성**: Gold JSON에 18개 inclusion rules가 있어 SQL이 114K chars
   - 완화: 전체 SQL을 한 번에 변환하면 됨 (단순 문자열 치환)
3. **Results 스키마 호환**: WebAPI는 `cohort_inclusion_stats` 등을 자동 생성하지만 직접 실행 시 없음
   - 완화: 벤치마크는 `cohort` 테이블의 `subject_id` 비교만 필요

## 5. 해결되지 않은 질문

1. WebAPI SqlRender가 왜 변환하지 않는지 근본 원인 (OHDSI 커뮤니티 이슈 확인 필요)
2. Agent cohort도 같은 문제를 가지는지 (거의 확실히 동일)
3. 다른 trial (PLATO, ARISTOTLE)에서도 동일한 문제인지

## 6. 타임라인

- **Day 1**: Option A 구현 + Gold cohort 검증
- **Day 2**: Agent cohort 검증 + PLATO/ARISTOTLE 확장
- **향후**: Option C (WebAPI fix)를 OHDSI 커뮤니티에 이슈 보고
