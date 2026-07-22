# Synthea Benchmark Data Generation Pipeline

> Cohort-Level Jaccard Similarity 평가를 위한 타겟 환자 생성 및 ETL 파이프라인 문서

## 1. 개요

ARTEMIS Agent의 Cohort-level 평가(`benchmark_v6_cohort.py`)에는 **특정 임상 조건을 만족하는 합성 환자가** OMOP CDM에 존재해야 합니다. 범용 Synthea 데이터(synthea23m 등)는 특정 RCT 기준에 맞는 환자가 거의 없으므로, **타겟 Synthea 모듈** 3종을 제작하여 조건 만족 환자를 대량 생성합니다.

## 2. 아키텍처

```
Synthea Module (.json)
       ↓  ./run_synthea -m artemis_leader -p 10000
CSV Files (output/csv/)
       ↓  docker cp → load_synthea.sql
synthea_native_benchmark (PostgreSQL)
       ↓  run_etl_full.sh → run_etl_benchmark.R (ETLSyntheaBuilder)
synthea_cdm_benchmark (OMOP CDM v5.4)
       ↓  WebAPI cohort generation
benchmark_v6_cohort.py → Jaccard Similarity
```

## 3. Synthea 타겟 모듈 (3종)

경로: `data/synthea/synthea/src/main/resources/modules/`

### 3.1 `artemis_leader.json` (LEADER Trial — NCT01179048)

| 항목 | 값 |
| :--- | :--- |
| 대상 연령 | 62세 |
| 주요 질환 | Type 2 Diabetes (SNOMED 44054006) |
| 관찰 | HbA1c = 8.5% (LOINC 4548-4) |
| 처방 1 | **Metformin 500mg** (RxNorm 860975) — Rule 3 통과용 |
| 처방 2 | Liraglutide (RxNorm 897122) — Index drug |

### 3.2 `artemis_plato.json` (PLATO Trial — NCT00391872)

| 항목 | 값 |
| :--- | :--- |
| 대상 연령 | 60세 |
| 주요 질환 | Acute Coronary Syndrome (SNOMED 418579007) |
| Encounter | inpatient |
| 처방 | Ticagrelor 90mg (RxNorm 1115005) |

### 3.3 `artemis_aristotle.json` (ARISTOTLE Trial — NCT00412984)

| 항목 | 값 |
| :--- | :--- |
| 대상 연령 | 76세 |
| 주요 질환 | Atrial Fibrillation (SNOMED 49436004) |
| 처방 | Apixaban 5mg (RxNorm 1364441) |

## 4. 실행 워크플로우

### Step 1: Synthea 환자 생성

```bash
cd /Users/kyh/Workspace/Broadsea/data/synthea/synthea

# CSV 초기화 후 생성 (10,000명)
rm -rf output/csv/*
./run_synthea -m artemis_leader -p 10000 --exporter.csv.export=true
```

> **주의**: 모듈명은 `-m` 플래그로 지정. `artemis_leader`, `artemis_plato`, `artemis_aristotle` 중 택 1.

### Step 2: CSV를 Docker 컨테이너로 복사

```bash
docker cp output/csv broadsea-atlasdb:/tmp/synthea_csv
```

### Step 3: Native 테이블에 로드

```bash
docker exec -i broadsea-atlasdb psql -U postgres -d ohdsi < /tmp/load_synthea.sql
```

**`load_synthea.sql`** — 8개 테이블 TRUNCATE + COPY:

```sql
TRUNCATE TABLE synthea_native_benchmark.patients CASCADE;
TRUNCATE TABLE synthea_native_benchmark.encounters CASCADE;
TRUNCATE TABLE synthea_native_benchmark.conditions CASCADE;
TRUNCATE TABLE synthea_native_benchmark.medications CASCADE;
TRUNCATE TABLE synthea_native_benchmark.procedures CASCADE;
TRUNCATE TABLE synthea_native_benchmark.observations CASCADE;
TRUNCATE TABLE synthea_native_benchmark.organizations CASCADE;
TRUNCATE TABLE synthea_native_benchmark.providers CASCADE;

\copy synthea_native_benchmark.patients FROM '/tmp/synthea_csv/patients.csv' WITH (FORMAT csv, HEADER true);
\copy synthea_native_benchmark.encounters FROM '/tmp/synthea_csv/encounters.csv' WITH (FORMAT csv, HEADER true);
\copy synthea_native_benchmark.conditions FROM '/tmp/synthea_csv/conditions.csv' WITH (FORMAT csv, HEADER true);
\copy synthea_native_benchmark.medications FROM '/tmp/synthea_csv/medications.csv' WITH (FORMAT csv, HEADER true);
\copy synthea_native_benchmark.procedures FROM '/tmp/synthea_csv/procedures.csv' WITH (FORMAT csv, HEADER true);
\copy synthea_native_benchmark.observations FROM '/tmp/synthea_csv/observations.csv' WITH (FORMAT csv, HEADER true);
\copy synthea_native_benchmark.organizations FROM '/tmp/synthea_csv/organizations.csv' WITH (FORMAT csv, HEADER true);
\copy synthea_native_benchmark.providers FROM '/tmp/synthea_csv/providers.csv' WITH (FORMAT csv, HEADER true);
```

> [!CAUTION]
> `organizations.csv`와 `providers.csv`를 반드시 로드해야 합니다. 누락 시 `visit_occurrence`가 0건이 되어 `drug_exposure` 등 모든 하위 테이블이 빈 상태로 생성됩니다 (INNER JOIN 의존성).

### Step 4: OMOP CDM ETL 실행

```bash
cd /Users/kyh/Workspace/Broadsea/artemis
bash scripts/run_etl_full.sh
```

이 스크립트는:
1. `synthea_cdm_benchmark` 스키마를 DROP + CREATE
2. `run_etl_benchmark.R`을 실행하여 7-step ETL 수행

**`run_etl_benchmark.R`** 핵심 로직:
- Step 1: CDM 테이블 생성
- Step 2-3: Skip (native 테이블은 Step 3에서 이미 로드됨)
- Step 4: `synthea23m` 스키마의 Vocabulary를 VIEW로 참조 (재로드 불필요)
- Step 5: Mapping & Rollup 테이블 생성
- Step 6: Extra 인덱스 생성
- Step 7: Event 테이블 로드 (person, visit_occurrence, drug_exposure 등)

### Step 5: 벤치마크 실행

```bash
# 캐시 초기화 필수 (스키마 재생성 시)
rm -f output/v6_cohort_gold_cache.json

CDM_SCHEMA=synthea_cdm_benchmark conda run -n artemis python -u scripts/benchmark_v6_cohort.py \
  --trial LEADER \
  --mode E2E_SUPP \
  --gold data/gold/LEADER/LEADER_GOLD.json
```

> [!WARNING]
> `synthea_cdm_benchmark` 스키마를 재생성하면 기존 WebAPI cohort_definition_id가 무효화됩니다. 반드시 `v6_cohort_gold_cache.json`을 삭제하여 Gold Cohort를 재생성하세요.

## 5. 검증 쿼리

```bash
# visit_occurrence 건수 확인 (0이면 ETL 실패)
docker exec broadsea-atlasdb psql -U postgres -d ohdsi -c \
  "SELECT count(*) FROM synthea_cdm_benchmark.visit_occurrence;"

# drug_exposure 건수 확인
docker exec broadsea-atlasdb psql -U postgres -d ohdsi -c \
  "SELECT count(*) FROM synthea_cdm_benchmark.drug_exposure;"

# Metformin 매핑 확인 (LEADER용)
docker exec broadsea-atlasdb psql -U postgres -d ohdsi -c \
  "SELECT drug_concept_id, count(*) FROM synthea_cdm_benchmark.drug_exposure GROUP BY 1 ORDER BY 2 DESC LIMIT 10;"
```

## 6. 최종 데이터 프로파일 (LEADER 10k, 2026-03-16)

| CDM Table | Row Count |
| :--- | :--- |
| person | 10,000 |
| encounters (native) | 96,189 |
| conditions (native) | 4,758 |
| medications (native) | 6,668 |
| observations (native) | 292,345 |
| organizations | 514 |
| providers | 514 |
| drug_exposure (CDM) | 6,668 |

## 7. 알려진 이슈 및 해결책

| 이슈 | 원인 | 해결 |
| :--- | :--- | :--- |
| `visit_occurrence` = 0 rows | ETL의 `insert_visit_occurrence.sql`이 `provider`/`care_site`와 INNER JOIN → 빈 테이블이면 전부 DROP | `load_synthea.sql`에 `organizations.csv` + `providers.csv` 로드 추가 |
| Gold Cohort 0명 (캐시 문제) | 스키마 재생성 후 `v6_cohort_gold_cache.json`이 이전 cohort_definition_id를 참조 | `rm -f output/v6_cohort_gold_cache.json` |
| Agent Rule 4 전원 탈락 | Agent 1이 OR 조건을 AND로 파싱 | Agent 1 Boolean 파서 개선 필요 (미해결) |
