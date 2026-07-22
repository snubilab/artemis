# V6 Cohort 0-Patient Attrition Log

## 1단계 (A) 사실 고정 및 문서 정리

- **TODO-A01**: Gold JSON의 실제 구조 수치 고정
  - 확인 결과: `rules=18 cs=54 add=True`
- **TODO-A02**: Entry 첫 기준과 `AdditionalCriteria` 텍스트 고정
  - *Entry drug 기준*: `DrugEra` CodesetId 32 (length >= 7 days starting from 2010-10-06)
  - *추가 correlated criteria*: Any `ConditionOccurrence` in CodesetId 91 occurring within 180 days before the `DrugEra` start.
- **TODO-A03**: `AdditionalCriteria` 파싱 수정 확인
  - 코드 위치: `artemis/scripts/generate_synthea_from_gold.py:501` (`ac = gold.get("AdditionalCriteria")`)
- **TODO-A04**: ETL 경로 고정
  - `postgres` DB 타겟팅 확인 (`run_synthea_parallel_and_etl.py`, `run_etl_full.sh`, `run_etl_benchmark.R`)
- **TODO-A05**: 문서 충돌 요약 및 분리
  - 기존 가설(캐시 꼬임 vs 데이터 부재 vs SqlRender 문법 이슈) 충돌: 이후 디버깅은 반드시 tracer를 사용한 fresh rerun 결과를 기준으로 판단.
- **TODO-A06**: 프롬프트 튜닝 분리
  - Agent 1 prompt 정리 작업은 병렬 작업으로, 이번 RCA의 blocker 아님.

## 2단계 (B) 런타임 전제조건 검증

- **TODO-B01**: 고정 Source
  - ID 5, `SYNTHEA_CDM_BENCHMARK`, connection은 `ohdsi` DB로 복구 (`jdbc:postgresql://broadsea-atlasdb:5432/ohdsi?user=postgres&password=mypass`)
- **TODO-B02**: Source Daimons
  - CDM: `synthea_cdm_benchmark`, Vocab: `synthea23m`. 모두 `ohdsi` DB 내 스키마 확인.
- **TODO-B03**: Cache 회피 전략
  - 고유한 cohort 이름 사용(예: `[ATT] 00_Entry_Only_Bash`)
- **TODO-B04**: OMOP CDM 기본 row count
  - `ohdsi` DB 기준: person=10000, drug_era=1496, condition_occurrence=3644, measurement=5940
- **TODO-B05**: liraglutide + T2DM 존재 여부
  - **CRITICAL FINDING**: Liraglutide (40170911) 1496명, Type 2 Diabetes (201826) 3644명이 발생했으며, 이 두 조건을 시간 순서(Entry 기준)로 모두 만족하는 환자는 **1496명**으로 확인됨 (`ohdsi` 데이터베이스 직접 SQL 쿼리 검증).
  - 즉, 데이터 자체는 **충분히 존재하며, Entry-Only는 정상적으로 >0명이어야 함을 입증!**

## 3단계 (C/D/E/F) Tracer 스크립트 실행 및 RCA 최종 결론

- **RCA 핵심 원인 1: 셸 스크립트 렉시컬 버그**
  - 기존 작성된 `run_attrition.sh`의 payload 생성 파트(`cat << 'JSON_EOF'`)에서 따옴표가 평가를 막아 `$(jq ...)`가 문자열로 WebAPI에 보내짐. 이로 인해 Payload 생성이 묵살되고 Cohort ID가 빈 문자열을 리턴해 에러/0명 결과를 초래함.

- **RCA 핵심 원인 2: Database Index 부재로 인한 Temp File 용량 한계 (No space left on device)**
  - WebAPI가 Cohort를 돌리려면 Vocabulary 테이블들(특히 3.2GB 크기의 `synthea23m.concept_ancestor`)을 join해야 함.
  - OHDSI 기본 Index(`ancestor_concept_id`, `descendant_concept_id`)가 전부 누락되어 WebAPI가 Full Table Scan과 Hash Join을 시도함.
  - 이로 인해 PostgreSQL이 Temp 파일을 생성하다가 **broadsea-atlasdb 컨테이너의 잔여 디스크(1.1GB 불과)를 전면 소진**해버림.
  - *결론*: WebAPI 쿼리는 환자 데이터 자체가 좁혀서가 아니라, 내부 쿼리 실행이 폭발하여 무한 Polling (타임아웃) 이나 0명이라는 에러 상태(generation_cache 오염)로 귀결된 것임.

### 권고사항 (Mitigation)
1. Broadsea 컨테이너 내부 스토리지 용량을 확보하거나 불필요한 스키마(`synthea_cdm` 등) 백업본을 정리한다.
2. `synthea23m.concept_ancestor` 등 어휘 테이블들에 표준 OHDSI Index 생성을 반드시 수행한다. (용량이 확보되어야 가능)

## 추가 발견 및 인프라 수정 (2026-03-17 21:00~22:45)

### 4-1. JDBC Connection 복구

- source 5 (`SYNTHEA_CDM_BENCHMARK`)의 `source_connection`이 `jdbc:ohdsiql://...` (잘못된 드라이버)로 설정되어 있어 WebAPI가 `No suitable driver found` 에러 반환.
- known-good 값으로 복구: `jdbc:postgresql://broadsea-atlasdb:5432/ohdsi?user=postgres&password=mypass`
- WebAPI 컨테이너 restart 후 반영 확인.

### 4-2. Colima VM 디스크 확장

- Colima VM 디스크: 200GB → **300GB** 확장
- `synthea23m.concept_ancestor`(3.2GB) 인덱스 생성 시 디스크 부족으로 실패하던 문제 해결.

### 4-3. Postgres 메모리 튜닝

기존 기본 설정으로는 3.2GB vocab 테이블 JOIN 시 전부 디스크 temp file로 spillover.

| 파라미터 | Before | After |
|----------|--------|-------|
| `shared_buffers` | 128 MB | **2 GB** |
| `work_mem` | 4 MB | **256 MB** |
| `effective_cache_size` | 4 GB | **6 GB** |
| `maintenance_work_mem` | 64 MB | **512 MB** |

- `ALTER SYSTEM SET` 으로 영구 적용, Postgres 재시작으로 반영.

### 4-4. Vocabulary 인덱스 생성

`synthea23m` 어휘 테이블에 표준 OHDSI 인덱스 추가 (디스크 확장 후 가능해짐):

```
idx_ca_ancestor     → synthea23m.concept_ancestor (ancestor_concept_id)
idx_ca_descendant   → synthea23m.concept_ancestor (descendant_concept_id)
idx_concept_id_23m  → synthea23m.concept (concept_id)
idx_cr_1_23m        → synthea23m.concept_relationship (concept_id_1)
```

`synthea_cdm_benchmark` CDM 테이블들에도 인덱스 추가:
- `condition_occurrence`, `drug_era`, `measurement`, `person`, `observation_period`

모든 테이블 `ANALYZE` 수행으로 Postgres query planner 통계 갱신.

### 4-5. Benchmark 전용 Vocabulary Subset 생성 (ADR-026)

**핵심 결정**: `synthea23m`의 거대한 vocab을 공유하는 대신, `synthea_cdm_benchmark` CDM에서 **실제 사용되는 concept만 추출**하여 로컬 vocab 테이블 생성.

**추출 전략**: CDM 테이블에서 사용된 concept_id (15개) → `concept_ancestor`로 ancestor/descendant 확장 (752개) → 서브셋 생성.

| 테이블 | `synthea23m` (Before) | `synthea_cdm_benchmark` (After) |
|--------|:---------------------:|:-------------------------------:|
| `concept_ancestor` | **3.2 GB** | **1.3 MB** |
| `concept` | ~500 MB | **200 KB** |
| `concept_relationship` | ~2 GB | **384 KB** |

- WebAPI source_daimon의 Vocab qualifier를 `synthea23m` → `synthea_cdm_benchmark`으로 변경.
- SQL 스크립트: `/tmp/create_benchmark_vocab.sql` (→ 향후 `scripts/create_benchmark_vocab.sql`로 이동 필요)
- **⚠️ 데이터 재생성 시 반드시 이 스크립트도 재실행해야 함.**
- 자세한 내용: `docs/adr/ADR-026_Benchmark_Vocab_Subset.md`

### 4-6. Attrition Trace 시도 (미완료)

`trace_cohort_attrition.py --execute --prune-concept-sets`로 L0~L18 순차 실행 시도:

- L0 (Entry Only): Postgres 재시작 시점에 connection killed → FAILED
- L1~L18: 실행 시도했으나 좀비 쿼리 경합 + WebAPI 오버헤드로 단일 코호트 5~10분 소요
- **최종 판단**: 합성 데이터 생성 로직(`generate_synthea_from_gold.py`) 자체에 문제가 있으므로, 데이터를 수정한 후 attrition trace를 다시 수행하는 것이 더 효율적.

## 5단계: 다음 단계 (TODO)

1. **`generate_synthea_from_gold.py` 합성 로직 수정** — 현재 생성되는 데이터가 Gold cohort의 inclusion rules를 통과하지 못하는 근본 원인 해결
   - **🔧 Codex CLI에서 구현 중** — 상세 계획: [`2026-03-17_generate_synthea_from_gold_fix_plan.md`](./2026-03-17_generate_synthea_from_gold_fix_plan.md)
   - 14단계 TDD 계획: 회귀 테스트 뼈대 → numeric comparator 수정 → nested demographic 재귀 처리 → classify_rule 재귀 판정 → occurrence/window 보존 → unsupported semantics 정책 → benchmark 모듈 재생성
2. 수정된 로직으로 Synthea 모듈 재생성 → FAT JAR 재빌드 → 환자 재생성 → ETL 재실행
3. **Vocab subset 재생성** — `create_benchmark_vocab.sql` 재실행 (새 데이터의 concept 반영)
4. Attrition trace 재실행 — 이번에는 빠르게 (subset vocab + 인덱스 + 메모리 튜닝 적용 상태)
5. 결과에 따라 특정 inclusion rule 디버깅
