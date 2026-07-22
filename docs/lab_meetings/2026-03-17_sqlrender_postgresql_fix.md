# Lab Meeting (Round 2): WebAPI Cohort Generation 0명 — 진짜 원인 추적

**날짜**: 2026-03-17  
**참여 모델**: Claude, Codex (gpt-5.4)  
**Gemini 참여 실패**: gemini-3.1-pro-preview CLI exit code 1 (2-모델 검증)

## 안건

SqlRender 1.19.1이 정상 번역됨을 확인한 후, WebAPI cohort generation이 여전히 0명을 반환하는 근본 원인 재조사.

## Round 1 결론 기각 사유

| 가설 | 검증 결과 | 판정 |
|:---|:---|:---|
| SqlRender 버전 오래됨 | **1.19.1** (최신) 번들 확인 | ❌ 기각 |
| SqlRender 번역 불가 | 동일 JAR로 3개 함수 모두 정상 번역 | ❌ 기각 |
| source_dialect 설정 오류 | `postgresql` 올바르게 설정 | ❌ 기각 |

## 제안 요약

| 모델 | 핵심 제안 | 주요 근거 |
|:---|:---|:---|
| Claude | TEMP_EMULATION_SCHEMA가 비어있어 temp table 실패 | SqlRender temp table emulation에 스키마 필요 |
| Codex | TEMP_EMULATION_SCHEMA는 비원인. Source metadata 정리 후 WebAPI 실행 경로 버그 추적 | Achilles only env var. PostgreSQL has native temp tables. |

## 교차 검증에서 발견된 문제점

### Codex의 Claude 제안 반박 (채택)

1. **TEMP_EMULATION_SCHEMA는 WebAPI에 전달되지 않음**
   - `.env`의 `TEMP_EMULATION_SCHEMA`는 Achilles runner에만 주입 ([docker-compose.yml L300](file:///Users/kyh/Workspace/Broadsea/docker-compose.yml#L300))
   - WebAPI의 환경변수 목록에 없음 ([ohdsi-webapi.yml](file:///Users/kyh/Workspace/Broadsea/compose/ohdsi-webapi.yml))
   - PostgreSQL은 **native temp table 지원** → temp emulation 불필요

2. **`/cohortdefinition/sql` endpoint의 미번역은 정상 동작**
   - 이 endpoint는 **template SQL** (SQL Server dialect, `@placeholders` 포함)을 반환
   - 실행 가능한 PostgreSQL SQL이 아님 → 여기서 `DATEADD`가 보이는 건 당연
   - 결정적 증거: `/generate/{sourceKey}` 실행 시 **PostgreSQL 로그**에 raw `DATEADD`가 남는 것

3. **Vocabulary daimon mismatch는 정리 대상** (원인은 아님)
   - `SYNTHEA_CDM_BENCHMARK` vocabulary daimon → `synthea23m` (다른 스키마)
   - `synthea_cdm_benchmark`로 통일 권장

## 최종 합의: 2-Step 접근

### ✅ Step 1 — Source Metadata 정리 (즉시)

```sql
-- Vocabulary daimon을 synthea_cdm_benchmark로 통일
UPDATE webapi.source_daimon 
SET table_qualifier = 'synthea_cdm_benchmark'
WHERE source_daimon_id = 15;  -- source_id=5, daimon_type=1 (Vocabulary)

-- Temp daimon 추가 (optional, OHDSI best practice)
INSERT INTO webapi.source_daimon (source_daimon_id, source_id, daimon_type, table_qualifier, priority)
VALUES (18, 5, 5, 'synthea_cdm_benchmark_results', 0);
```

→ WebAPI 재시작 후 cohort generation 재시도.

### ✅ Step 2 — 결과 확인 후 분기

**만약 Step 1 후에도 raw DATEADD가 PostgreSQL 로그에 남으면:**
→ WebAPI 2.15.1 cohort generation 실행 경로 버그로 확정
→ `webapi-from-git`으로 코드 디버깅 or upstream issue 보고

**만약 Step 1로 해결되면:**
→ Vocabulary daimon mismatch가 SqlRender translate() 호출 경로에 영향을 준 것
→ ADR로 기록

### ⚠️ 다른 source에서 먼저 검증

EUNOMIA나 SYNTHEA23M source에서 cohort generation이 정상 동작하는지 확인.
→ 정상이면 SYNTHEA_CDM_BENCHMARK 설정만의 문제.
→ 그것도 0명이면 WebAPI 자체 버그.

## 반대 의견 기록

- **Claude**: TEMP_EMULATION_SCHEMA 가설 제시 → Codex에 의해 반박됨 (WebAPI에 전달 안 됨, PostgreSQL native temp table)

## 실행 계획

- [ ] EUNOMIA source에서 간단한 cohort generate 테스트 (기존 source 검증)
- [ ] Source daimon vocabulary → `synthea_cdm_benchmark`로 수정
- [ ] WebAPI restart 후 Gold cohort generation 재시도
- [ ] PostgreSQL 로그에서 raw DATEADD 유무 확인
- [ ] 결과에 따라 WebAPI upstream issue 보고 또는 ADR 작성

## 부록

> 원본 제안: `tmp/lab_meeting/20260317_sqlrender_root_cause_r2/`
> Round 1 회의록: `docs/lab_meetings/2026-03-17_sqlrender_postgresql_fix.md`
