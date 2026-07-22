# PLATO STEMI Regeneration Handoff — 2026-03-31

## 목적

PLATO_BENCHMARK에 STEMI 환자를 포함시키기 위해 Synthea 데이터 재생성 및 DB 재구성.

## 현재 상태

| 항목 | 상태 |
|------|------|
| STEMI (OMOP 4296653 / SNOMED 401303003) | **0건** (현재 PLATO DB에 없음) |
| Generic MI (OMOP 312327 = Acute MI) | 4,150건 존재 (ACS 코드 418579007에서 ETL 매핑) |
| LBBB (OMOP 316998) | 미확인 |
| PLATO 코호트 환자 | 75명 (전원 NSTEMI/UA 경로) |

### 왜 STEMI가 없나

현재 Synthea 모듈 파일 (`artemis_plato.json`)은 **구버전**으로 SNOMED 418579007 (Acute coronary syndrome) 단일 코드만 포함.
`generate_synthea_modules.py`에 STEMI 코드(401303003)가 추가된 것은 commit `fe59422`이지만,
**Synthea 모듈 JSON이 아직 재생성되지 않았고, Synthea도 재실행되지 않았음**.

즉, DB에는 구버전 데이터(25k, 2026-03-18 생성)가 그대로 있음.

## 파일 경로 참조

| 항목 | 경로 |
|------|------|
| Synthea 모듈 생성 스크립트 | `artemis/scripts/generate_synthea_modules.py` |
| Synthea 모듈 출력 디렉터리 | `/Users/kyh/Workspace/Broadsea/data/synthea/synthea/src/main/resources/modules/` |
| 현재 PLATO 모듈 파일 | `…/modules/artemis_plato.json` (구버전, 재생성 필요) |
| Synthea jar (실행용) | `/Users/kyh/Workspace/Broadsea/data/synthea/synthea/build/libs/synthea-with-dependencies.jar` |
| Synthea 작업 디렉터리 | `/Users/kyh/Workspace/Broadsea/data/synthea/synthea/` |
| Synthea CSV 출력 기본 경로 | `…/synthea/output/csv/` |
| setup_study_benchmarks.sh 참조 PLATO_CSV | `/Users/kyh/Workspace/Broadsea/artemis/output/generated_gold_eval/20260318_plato_25k_cachefix/plato/synthea_output/csv` |
| ETL R 스크립트 | `artemis/scripts/run_etl_study.R` |
| 전체 세팅 스크립트 | `artemis/scripts/setup_study_benchmarks.sh` |

## 재생성 절차

### Step 1: Synthea 모듈 재생성

`generate_synthea_modules.py`를 실행해 업데이트된 PLATO 모듈 JSON을 Synthea 모듈 디렉터리에 덮어씀.

```bash
cd /Users/kyh/Workspace/Broadsea
python3 artemis/scripts/generate_synthea_modules.py
```

실행 후 모듈 파일 확인:

```bash
python3 -c "
import json
with open('/Users/kyh/Workspace/Broadsea/data/synthea/synthea/src/main/resources/modules/artemis_plato.json') as f:
    d = json.load(f)
for k,v in d['states'].items():
    if v.get('type') == 'ConditionOnset':
        print(k, v['codes'][0]['code'], v['codes'][0]['display'])
"
```

예상 출력 (3개 조건 코드):
```
Condition 0  401303003  Acute ST segment elevation myocardial infarction (disorder)
Condition 1  22298006   Myocardial infarction (disorder)
Condition 2  63467002   Left bundle branch block (disorder)
```

### Step 2: Synthea 실행 (25k patients)

```bash
cd /Users/kyh/Workspace/Broadsea/data/synthea/synthea

java -Xmx8g \
  -jar build/libs/synthea-with-dependencies.jar \
  -m artemis_plato \
  -p 25000 \
  --exporter.csv.export=true \
  --exporter.fhir.export=false \
  --exporter.hospital.fhir.export=false \
  --exporter.practitioner.fhir.export=false \
  Massachusetts
```

> `-m artemis_plato` 는 `artemis_plato.json` 모듈만 사용.
> 소요 시간: 25k 기준 약 15~30분.

출력 위치: `/Users/kyh/Workspace/Broadsea/data/synthea/synthea/output/csv/`

STEMI 코드 포함 여부 확인:

```bash
grep -c "401303003" /Users/kyh/Workspace/Broadsea/data/synthea/synthea/output/csv/conditions.csv
```

0이면 모듈이 올바르게 반영되지 않은 것. Step 1 재확인 후 재실행.

### Step 3: CSV output을 PLATO_CSV 경로로 복사

`setup_study_benchmarks.sh`가 참조하는 경로로 복사:

```bash
PLATO_CSV="/Users/kyh/Workspace/Broadsea/artemis/output/generated_gold_eval/20260318_plato_25k_cachefix/plato/synthea_output/csv"

# 기존 백업
mkdir -p "${PLATO_CSV}_backup_$(date +%Y%m%d)"
cp -r "$PLATO_CSV/." "${PLATO_CSV}_backup_$(date +%Y%m%d)/"

# 새 CSV 복사
cp /Users/kyh/Workspace/Broadsea/data/synthea/synthea/output/csv/*.csv "$PLATO_CSV/"
```

patients.csv 행 수 확인:

```bash
echo "Patient count: $(( $(wc -l < "$PLATO_CSV/patients.csv") - 1 ))"
```

### Step 4: PLATO_BENCHMARK DB 재구성

```bash
cd /Users/kyh/Workspace/Broadsea
bash artemis/scripts/setup_study_benchmarks.sh plato
```

이 스크립트는 다음을 수행:
1. `synthea_cdm_plato`, `synthea_native_plato`, `synthea_cdm_plato_results` 스키마 DROP → 재생성
2. ETLSyntheaBuilder로 CDM + native 테이블 생성
3. CSV → PostgreSQL 로드 (`\copy` via Docker)
4. Vocab view 생성 (synthea23m 참조)
5. OMOP ETL 실행 (`run_etl_study.R`)

소요 시간: 약 20~40분.

완료 후 출력 예시 (검증):
```
 tbl               | count
-------------------+--------
 person            | 25000
 drug_exposure     | (숫자)
 condition_occ     | (숫자)
 visit_occurrence  | (숫자)
```

### Step 5: STEMI 포함 여부 검증

```bash
docker exec -i -u postgres broadsea-atlasdb psql ohdsi -c "
SELECT c.concept_id, c.concept_name, co.cnt
FROM (
    SELECT condition_concept_id, count(*) AS cnt
    FROM synthea_cdm_plato.condition_occurrence
    WHERE condition_concept_id IN (
        4296653,  -- Acute ST segment elevation MI (STEMI)
        312327,   -- Acute myocardial infarction
        4329847,  -- Myocardial infarction
        316998    -- Left bundle branch block
    )
    GROUP BY 1
) co
JOIN synthea23m.concept c ON c.concept_id = co.condition_concept_id
ORDER BY co.cnt DESC;
"
```

예상: `4296653` (STEMI) 행이 신규로 나타나야 함.

### Step 6: WebAPI 소스 등록 및 캐시 클리어

PLATO WebAPI source key가 없으면 등록 필요 (`PLATO_BENCHMARK`). 현재 webapi.source 테이블에 PLATO 항목이 없으므로 재등록:

```bash
# setup_all_benchmark_sources.sh 실행 (source 등록 포함)
cd /Users/kyh/Workspace/Broadsea/artemis
bash scripts/setup_all_benchmark_sources.sh
```

또는 수동 WebAPI 소스 등록 후 COHORT 캐시 클리어:

```sql
-- WebAPI DB에서 PLATO cohort cache 클리어
WITH source_row AS (
    SELECT source_id FROM webapi.source WHERE source_key = 'PLATO_BENCHMARK'
)
DELETE FROM webapi.generation_cache gc
USING source_row s
WHERE gc.type = 'COHORT' AND gc.source_id = s.source_id;
```

### Step 7: 코호트 재실행 및 결과 검증

PLATO study의 코호트를 WebAPI에서 재생성:

```bash
# evaluate_generated_gold_studies.py 사용 (자동 캐시 클리어 포함)
python3 artemis/scripts/evaluate_generated_gold_studies.py --study plato
```

또는 Atlas UI에서 PLATO_BENCHMARK 소스 선택 후 코호트 수동 Generate.

STEMI 환자가 코호트에 포함되는지 확인:

```sql
-- PLATO treatment 코호트 내 STEMI 환자 확인
-- (cohort_id는 실제 WebAPI 생성 코호트 ID로 대체)
SELECT count(DISTINCT co.person_id)
FROM synthea_cdm_plato.condition_occurrence co
JOIN synthea_cdm_plato_results.cohort c ON c.subject_id = co.person_id
WHERE co.condition_concept_id = 4296653  -- STEMI
  AND c.cohort_definition_id = <PLATO_COHORT_ID>;
```

## 예상 결과

- STEMI (SNOMED 401303003 → OMOP 4296653) 환자가 `condition_occurrence`에 신규 추가됨
- ACS inclusion rule (STEMI OR NSTEMI OR UA = ANY group)이 STEMI 환자도 커버하므로 PLATO 코호트 환자수 75명 → 증가 예상
- PLATO 75명은 현재 전원 NSTEMI/UA 경로이므로 STEMI 추가 후 전체 ACS 스펙트럼 커버

## 주의사항

1. **기존 cohort ID 변경 가능성**: schema DROP/재생성으로 WebAPI cohort_definition 연결이 깨질 수 있음. 재실행 후 cohort ID 재확인 필요.
2. **WebAPI COHORT cache 필수 클리어**: 재ETL 후 반드시 캐시 클리어. `Using cached generation results` 로그 나오면 stale.
3. **모듈 JSON vs generate_synthea_modules.py 동기화**: `artemis_plato.json`은 generate 스크립트 실행 시 덮어씌워짐. 커밋 전 git diff로 확인.
4. **synthea_cdm_plato 외 영향 없음**: LEADER, ARISTOTLE 스키마는 무관. setup_study_benchmarks.sh plato만 실행.
5. **run_etl_study.R의 syntheaFileLoc**: `run_etl_study.R`은 기본값으로 `…/synthea/output/csv`를 참조하지만, `setup_study_benchmarks.sh`는 `docker cp`로 PLATO_CSV 경로를 직접 주입하므로 충돌 없음.

## 관련 커밋

- `fe59422` — fix(synthea): add STEMI condition code to PLATO module (generate_synthea_modules.py 수정, JSON 재생성 미포함)

## 참고 문서

- `artemis/docs/daily_notes/2026-03-31_tte_store_race_condition_and_synthea_stemi.md`
- `.claude/rules/broadsea/webapi-cache.md` — WebAPI cache clear 절차
- `artemis/scripts/setup_study_benchmarks.sh` — 전체 ETL 파이프라인
