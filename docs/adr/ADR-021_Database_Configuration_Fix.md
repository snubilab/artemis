# ADR-021: Database Configuration Fix (DATABASE_URL, CDM_SCHEMA)

**상태**: 승인됨  
**날짜**: 2026-03-05  
**의사결정자**: @kyh

## 컨텍스트

E2E 파이프라인 실행 중 `.env` 파일의 데이터베이스 설정이 잘못되어 있음을 발견했다.

### 문제점 1: `CDM_SCHEMA=omop_vocab`

- `omop_vocab` 스키마에는 **테이블이 0개** (빈 스키마)
- `kg_expander._get_pg_descendant_counts()` → `concept_ancestor` 조회 실패 → `return {}` (graceful fallback)
- `drug_class_expander.expand_drug_class_via_vocab()` → 동일하게 실패
- **결과**: data-driven pruning이 silent하게 비활성화됨

### 문제점 2: `DATABASE_URL=postgresql://...localhost:5432/postgres`

- OMOP CDM 테이블은 `ohdsi` DB에 존재하지만, `postgres` DB를 가리키고 있었음
- Logician (combination drug decomposition) → `synthea23m.concept_ancestor` 조회 실패 → 분해 건너뜀
- **결과**: Logician의 combination drug → ingredient 분해가 비활성화됨

### 벤치마크 영향

모든 이전 벤치마크(A_direct, A+Climb, Exp D 등)에서 위 기능들이 **silent fallback**으로 처리되어 에러 없이 완료됐지만, data-driven 기능이 비활성화된 상태였다. 수정 후 재실행 결과 **동일한 메트릭(R=74.5%, P=52.4%, F1=51.2%)**이 나왔으며, DB 기능 비활성화가 결과에 실질적 영향을 미치지 않았음을 확인했다.

## 결정

`.env` 파일의 데이터베이스 설정을 다음과 같이 수정한다:

```env
# Before (잘못된 설정)
DATABASE_URL=postgresql://postgres:mypass@localhost:5432/postgres
CDM_SCHEMA=omop_vocab

# After (수정된 설정)
DATABASE_URL=postgresql://postgres:mypass@localhost:5432/ohdsi
CDM_SCHEMA=synthea23m
OMOP_DB_HOST=localhost
OMOP_DB_PORT=5432
OMOP_DB_NAME=ohdsi
OMOP_DB_USER=postgres
OMOP_DB_PASS=mypass
```

`settings.py`에 `OMOP_DB_*` 필드를 추가하여 Pydantic `BaseSettings` validation을 통과하도록 했다.

## 근거

- WebAPI source 목록에서 `SYNTHEA23M` (sourceKey) → `synthea23m` (CDM) → `synthea23m_results` (Results)로 등록되어 있음 확인
- `synthea23m.concept_ancestor`에 **75,689,500 rows** 존재 확인
- `omop_vocab` 스키마에는 테이블이 0개임을 확인
- E2E Phase 2에서 WebAPI가 `OMOP_VOCAB` source로 cohort generation 시도 → 500 에러 발생

## 영향

- **수정 파일**: `.env`, `src/settings.py`
- **벤치마크 결과**: 변동 없음 (R=74.5%, P=52.4%, F1=51.2% 동일)
- **E2E 파이프라인**: Phase 2 WebAPI 코호트 생성이 정상 작동하게 됨
- **향후**: data-driven pruning (descendant count 기반)이 실제 환자 데이터를 기반으로 작동하게 되어 정밀도 향상 가능성 있음
