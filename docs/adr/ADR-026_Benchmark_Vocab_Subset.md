# ADR-026: Benchmark 전용 Vocabulary Subset 생성

**상태**: 승인됨  
**날짜**: 2026-03-17  
**의사결정자**: @kyh

## 컨텍스트

`synthea_cdm_benchmark` (10K 환자)는 자체 vocabulary 테이블이 없어서 `synthea23m` 스키마의 vocabulary를 공유하고 있었다.

- `synthea23m.concept_ancestor`는 **3.2 GB**, `concept_relationship`은 수 GB 규모
- WebAPI 코호트 생성 시 이 거대한 테이블을 매번 JOIN → 단일 코호트 생성에 **9~25분** 소요
- Postgres 기본 설정(`shared_buffers=128MB`)에서는 JOIN이 전부 디스크 temp file로 spillover → 공간 부족 에러 발생

## 결정

**`synthea_cdm_benchmark` CDM에서 실제 사용되는 concept만 추출**하여 동일 스키마 내에 subset vocabulary 테이블을 생성한다.

### 추출 전략

1. CDM 테이블(`drug_era`, `condition_occurrence`, `measurement`, `observation`, `procedure_occurrence`, `drug_exposure`, `visit_occurrence`, `person`)에서 사용된 모든 `concept_id` 추출 → **15개**
2. `concept_ancestor`를 통해 해당 concept들의 **모든 ancestor + descendant** 확장 → **752개**
3. 확장된 concept set으로 `concept`, `concept_ancestor`, `concept_relationship`, `concept_synonym` 서브셋 생성
4. `vocabulary`, `domain`, `concept_class`, `relationship`은 전체 복사 (작은 테이블)

### 결과 크기 비교

| 테이블 | synthea23m (원본) | synthea_cdm_benchmark (서브셋) |
|--------|:-:|:-:|
| `concept_ancestor` | 3.2 GB | **1.3 MB** |
| `concept` | ~500 MB | **200 KB** |
| `concept_relationship` | ~2 GB | **384 KB** |

## 근거

- 코호트 생성 속도: **9~25분 → 수 초**로 단축 예상
- WebAPI Daimon을 `synthea_cdm_benchmark` 자체 vocab으로 전환하면 대형 테이블 JOIN 완전 제거
- 디스크 공간 절약: 코호트 생성 시 temp file spillover 문제 원천 해결

### 고려한 대안

1. **Postgres 메모리 튜닝만** — `shared_buffers=2GB`, `work_mem=256MB`로 올려도 3.2GB 테이블 JOIN은 여전히 수 분 소요
2. **인덱스만 추가** — 인덱스 적용 완료 후에도 9분 이상 걸림
3. **다른 작은 vocab 소스 사용** — EUNOMIA 등은 vocabulary가 불완전하여 Liraglutide 같은 concept이 누락될 수 있음

## 영향

- 수정 파일: `webapi.source_daimon` (Vocab daimon을 `synthea23m` → `synthea_cdm_benchmark`로 변경)
- **데이터 재생성 시 필수 재실행**: ETL 후 반드시 `/tmp/create_benchmark_vocab.sql` 재실행 필요
- SQL 스크립트: `/tmp/create_benchmark_vocab.sql` → 향후 `scripts/create_benchmark_vocab.sql`로 이동 권장
