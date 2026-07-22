# Lab Meeting: E2E 파이프라인 최우선 개발 요소 파악

**날짜**: 2026-02-20
**참여 모델**: Claude, Gemini (gemini-3-pro-preview), Codex (gpt-5.3-codex-spark)

## 안건
ARTEMIS 3.1의 `DEVELOPMENT_STATUS.md` 기준, E2E 파이프라인 완성을 위한 3개 P0 블로커의 우선순위와 실행 전략을 결정한다.

## 제안 요약

| 모델 | 핵심 제안 | 주요 근거 |
|------|----------|----------|
| Claude | HDPS → InclusionRule→SQL → V4 | HDPS는 기존 코드 연결만으로 1-2일 완료, fallback 데이터에도 분석 품질 개선 |
| Gemini | InclusionRule→SQL → HDPS → V4 | Circe JSON의 90%가 무시되는 현 상태에서 HDPS는 과학적으로 무의미 (GIGO) |
| Codex | InclusionRule→SQL → HDPS → V4 | 모든 하류 블록이 추출 정확성에 의존. 인터페이스 뒤에서 병렬 개발 가능 |

## 교차 검증에서 발견된 문제점

### Claude 제안의 치명적 결함 (Gemini 발견)
- `FeatureExtractor`는 **DB 테이블** 조인용 SQL을 생성하도록 설계됨
- 현재 `CohortExecutor`는 **인메모리 DataFrame**을 반환
- HDPS를 먼저 연결하면 WebAPI 도입 후 전부 버려야 하는 기술 부채 발생
- **결론**: 아키텍처 자체가 Extraction → HDPS 순서를 강제함

### Codex "하이브리드 Fallback" 제안의 문제 (Gemini 발견)
- Python 기반 Circe 트랜스파일러를 "결정론적 fallback"으로 구현하는 것은 **maintenance 지옥**
- Circe 스펙의 전체 구현은 수개월 소요 가능
- **결론**: Fallback은 기존 synthetic data 생성으로 충분

### 공통 누락 사항 (Codex 발견)
- `extract_drugs()` / `extract_procedures()` 헬퍼 메서드가 **존재하지 않음** — Claude의 "기존 코드 연결만" 주장은 부정확
- Target/Comparator 환자 중복 체크 미구현 (`omop_connector.py`)
- SQL 인젝션 위험: `IN (...)` 절의 문자열 직접 빌드 (`omop_connector.py:71, 97, 169`)

### 핵심 자산 확인 (Codex 발견)
- `scripts/cohort_via_webapi.py` 파일이 **이미 존재** — WebAPI 클라이언트 스캐폴드 검증됨
- WebAPI 엔드포인트 (`POST /cohortdefinition/sql`, `GET /generate`, `GET /info`) 연동 코드 보유

## 최종 합의

### ✅ 합의 1: 우선순위 — **InclusionRule→SQL → HDPS → Benchmark V4**

3개 모델 모두 동의 (Claude 수정 후). 근거:
1. **아키텍처 정합성**: WebAPI가 `results_schema.cohort` 테이블을 생성 → `FeatureExtractor`가 해당 테이블에 조인 → 자연스러운 파이프라인
2. **과학적 무결성**: 잘못된 코호트에 대한 고차원 공변량 분석은 GIGO
3. **기존 자산 활용**: `scripts/cohort_via_webapi.py`가 이미 WebAPI 연통 검증

### ✅ 합의 2: SQL 전략 — **WebAPI 위임 (Strict)**

- Circe JSON → `POST /cohortdefinition/sql` → PostgreSQL SQL 수신 → `OMOPConnector`로 실행
- **자체 Python 트랜스파일러 구현 금지** (Circe 스펙 복잡도, 유지보수 비용)
- Fallback: WebAPI 실패 시 기존 synthetic data 생성 (ARTEMIS_FALLBACK_MODE 유지)

### ✅ 합의 3: HDPS 연결 방식

- WebAPI가 생성한 `results_schema.cohort` 테이블을 기반으로 `FeatureExtractor.generate_all_sql()` 호출
- Gemini 제안의 `CohortTableReference` 패턴 채택: DB 테이블 이름을 파이프라인에 전달
- Prevalence filter (`min_prevalence=0.01`) + max_covariates 제한 적용
- `extract_drugs()`, `extract_procedures()` 신규 구현 필요

### ✅ 합의 4: 최소 E2E 데모 기준

| 기준 | 개발 단계 | 릴리즈/PR 게이트 |
|------|---------|---------------|
| Fallback 허용 | `auto` (DB 실패 시 synthetic) | `never` (실 DB 필수) |
| 공변량 수 | age/gender + ≥1 HDPS 그룹 | ≥10 HDPS covariates |
| 리포트 | HTML (4 plots) | HTML + PDF |
| DB | synthea100k | synthea100k |

## 반대 의견 기록

### Claude의 원래 입장 (HDPS-first)
- "HDPS는 1-2일만에 기존 코드 연결로 완료 가능하고, fallback 데이터에서도 분석 품질을 즉시 개선한다"
- **기각 사유**: (1) 기존 코드 연결만으로는 불충분 — 누락 메서드 다수, (2) `FeatureExtractor`가 DB 테이블 의존 — DataFrame 직접 연결 시 기술 부채, (3) GIGO 원칙 위반

### Codex의 하이브리드 Fallback
- "WebAPI 실패 시 결정론적 Python 기반 SQL 변환으로 fallback"
- **기각 사유**: 이중 유지보수, Circe 스펙 전체 구현 비용 과대

## 실행 계획

```
Phase 1: WebAPI 연동 (Day 1-3)
  ├─ scripts/cohort_via_webapi.py 로직을 CohortExecutor에 통합
  ├─ CohortTableReference 패턴 도입 (schema, table_name, cohort_def_id)
  ├─ Circe JSON → POST /cohortdefinition/sql → SQL 수신 → 실행
  └─ synthea100k에서 cohort generation 검증

Phase 2: HDPS 공변량 연결 (Day 4-5)
  ├─ build_analysis_dataset()가 CohortTableReference 수신
  ├─ FeatureExtractor → results_schema.cohort 조인 SQL 실행
  ├─ extract_drugs(), extract_procedures() 신규 구현
  └─ Prevalence filter + sparse matrix 처리

Phase 3: E2E 검증 (Day 6-7)
  ├─ run_artemis() → full pipeline 실행
  ├─ FALLBACK_MODE=never 로 real DB 테스트
  └─ Report 생성 확인 (HTML, 4 plots)

Phase 4: Benchmark V4 (별도 스프린트)
  └─ N:1 parent-level 매칭 구현
```

## 부록: 원본 제안 및 리뷰
> 상세 내용은 `tmp/lab_meeting/20260220_e2e_priority_analysis/` 참조
