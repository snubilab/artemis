# ADR-010: Broadsea Docker DB 연결 설정

**상태**: 승인됨  
**날짜**: 2026-02-02  
**의사결정자**: @kyh

## 컨텍스트

ARTEMIS ConceptSet Recommendation System을 Broadsea Docker 환경의 OMOP CDM에 연결해야 한다.
로컬 Mac에 별도 PostgreSQL이 설치되어 있어 포트 충돌 문제가 발생했다.

## 결정

### DB 연결 정보

| 항목 | 값 |
|:-----|:---|
| Host | `localhost` (Docker port forwarding) |
| Port | `5432` |
| Database | `postgres` |
| Username | `postgres` |
| Password | `mypass` |
| CDM Schema | `omop_vocab` |
| PHOEBE Schema | `omop_vocab` |

### 연결 문자열

```
DATABASE_URL=postgresql://postgres:mypass@localhost:5432/postgres
```

### OMOP Vocabulary 로드 완료

| 테이블 | Rows |
|:-------|-----:|
| CONCEPT | 6,328,777 |
| CONCEPT (Standard) | 2,750,364 |
| CONCEPT_ANCESTOR | 75,689,500 |
| CONCEPT_RELATIONSHIP | 39,273,730 |
| CONCEPT_SYNONYM | 2,703,046 |
| DRUG_STRENGTH | 3,020,774 |

## 근거

1. **Broadsea 표준 설정 사용**: `/Users/kyh/Workspace/Broadsea/.env` 및 `secrets/` 폴더 참조
2. **Demo 데이터**: Eunomia Demo DB (439 Standard Concepts)
3. **프로덕션 준비**: 추후 omop_vocab 스키마로 전환 필요

## 영향

### 수정된 파일

- `artemis/.env`: DATABASE_URL, CDM_SCHEMA, PHOEBE_SCHEMA 설정
- `src/agents/conceptset/ontology_search.py`: `{self.schema}` 접두사 추가

### 포트 충돌 해결

로컬 PostgreSQL과 Docker PostgreSQL이 충돌할 경우:

```bash
# 로컬 postgres 중지
brew services stop postgresql@16

# Docker postgres 확인
docker exec broadsea-atlasdb psql -U postgres -c "SELECT 1"
```

## 관련 파일

- Broadsea 환경: `/Users/kyh/Workspace/Broadsea/.env`
- ARTEMIS 환경: `/Users/kyh/Workspace/Broadsea/artemis/.env`
- 비밀번호 파일: `/Users/kyh/Workspace/Broadsea/secrets/webapi/WEBAPI_DATASOURCE_PASSWORD`

## 알려진 이슈 및 제한사항

### ✅ 해결됨

1. **로컬 PostgreSQL 포트 충돌** - `brew services stop postgresql@16`으로 해결
2. **스키마 하드코딩 문제** - `ontology_search.py`, `expression_builder.py`에서 settings 연동

### ⚠️ 경미한 이슈 (운영에 영향 없음)

1. **CLUSTER 인덱스 생성 실패** - 디스크 공간 부족으로 `CLUSTER concept USING idx_concept_concept_id` 실패
   - 영향: 일부 쿼리 성능 저하 가능, 기능 동작에는 문제 없음
2. **structlog 미설치** - 기본 logging으로 대체 작동
3. **Redis 미설치** - 캐시 비활성화, 기능에는 문제 없음
4. **sentence-transformers 미설치** - LLM fallback reranker로 대체 작동

### 🔧 다음 단계 권장

1. Docker 디스크 공간 확보 후 CLUSTER 인덱스 재생성
2. ChromaDB에 Concept 임베딩 로드 (RAG 검색 활성화)
3. Analysis 관련 의존성 설치: `pip install pandas matplotlib lifelines`

## 테스트 현황 (2026-02-03)

```
conda run -n artemis python -m pytest tests/
================= 129 passed, 6 skipped, 7 warnings in 11.90s ==================
```

| 모듈 | 결과 |
|:-----|:-----|
| Agent 3-4 (Assembler/Validator) | ✅ 14/14 |
| Agent 5-6 (Analysis/Reporting) | ✅ All Passed |
| Registry | ✅ 5/5 |
| Expression Builder | ✅ 14/14 |
| NLU Router | ✅ 13/13 |
| Stage 1 Pipeline | ✅ 15/15 |
| 기타 | ✅ 68개 |
| **총계** | **129 passed** |
