# 2026-03-17: V6 Cohort 0-Patient Attrition 디버깅 및 DB 환경 일치화

## 오늘 완료

- [x] P3: Target Dataset Update (Synthea T2DM Generation)
  - `generate_synthea_from_gold.py` 수정하여 `AdditionalCriteria` 파싱 버그 해결
  - 10,000명의 환자를 T2DM 포함되도록 정확하게 재생성하여 ETL 적재 완료 ([관련 일지](../debugging/2026-03-17_v6_cohort_zero_patient_attrition_plan.md) 참고)
- [x] P4: Fix DB Mismatch
  - ETL 스크립트 3종의 타겟 DB 문자열을 `ohdsi`에서 `postgres`로 일괄 수정 (실제 WebAPI가 바라보는 위치와 동기화)
  - WebAPI의 `generation_cache` 내부 캐시 테이블까지 강제 삭제 처리하여 이전의 잘못된 0명 결과 캐싱 방지

## 진행중

- [/] P5: Attrition Debugging & Prompt Tuning
  - `prompts.py` One-shot Example 완전 삭제 (사용자 요청 사항) 
  - 순수 `requests`/`urllib` 기반 WebAPI Attrition 추적 스크립트 작성 완료 (`/tmp/trace_cohort_attrition.py`)

## 발견/변경사항

- **Docker URL 불일치 이슈**: `ohdsi-webapi` 도커 컨테이너는 포트 8080을 직접 외부에 바인딩하지 않고 `traefik` 리버스 프록시를 통해 `http://127.0.0.1/WebAPI` (80 포트)로 서빙되고 있음을 확인함.
- **Python 환경 충돌**: `conda run -n artemis` 수행 시 의존성 꼬임으로 모듈을 찾지 못하는 이슈 발생. 차후 스크립트 실행 환경 점검 및 ZSHRC 프로파일 리로드 필요성 대두됨 (사용자 피드백). WebAPI 내부 Generate 실패(500 에러) 현상까지 포착하였음.

## 내일의 최우선 작업 (Blockers & Next Steps)

- WebAPI Generate EndPoint(500 에러)의 Java 백엔드 로그 확인 및 해결.
- Entry Criteria 검증 및 Attrition 단계별 환자 누적 그래프/로그 기록 마무리.
