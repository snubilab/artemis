# ACHILLES 집계 데이터 요청서

**요청 대상**: 협력 병원 OMOP CDM 담당자
**작성일**: 2026-07-24
**목적**: TTE(Target Trial Emulation) 코호트를 각 병원 CDM에 맞게 적응(tuning)시키기 위한 개념별 집계 통계 확보
**관련 문서**: ADR-030(사이트별 CDM 적응 계층), ADR-029(기준 실현가능성 게이팅)

---

## 1. 한 줄 요약

**환자 데이터가 아니라, 이미 생성되어 있는 ACHILLES 집계 결과 테이블(`achilles_results`)의 사본을 요청드립니다.**
개인정보(PHI)는 포함되지 않으며, "개념(concept)별로 몇 명인가"라는 집계 숫자만 필요합니다.

---

## 2. 왜 필요한가

AI가 생성한 임상시험 코호트를 각 병원 CDM에 적용했을 때 **환자 0명** 또는 왜곡된 결과가 발생했습니다. 원인을 분석한 결과, 병원마다 다음이 다르기 때문입니다.

| 차이 | 예시 |
|------|------|
| Source vocabulary 매핑 | ICD-10 / KCD / 로컬코드 → OMOP 표준개념 매핑이 ETL마다 다름 |
| 코딩 세분도(granularity) | A병원은 "제2형 당뇨병" 일반개념, B병원은 세부 하위형만 사용 |
| 도메인 라우팅 | 같은 사실이 A는 Condition, B는 Observation |
| 데이터 밀도 | 생활습관·특수검사(예: 식이/운동 요법, UACR)가 병원마다 있거나 없음 |

실제 확인된 사례:
- **EMPA-REG 11번 기준**(식이/운동 요법) → 해당 데이터가 없어 **전원 탈락**
- **CARMELINA 9번 기준**(알부민뇨/UACR) → 동일하게 전원 탈락

따라서 **"이 병원 CDM에는 어떤 개념이 실제로 몇 명분 존재하는가"**를 알아야 코호트를 그 병원에 맞게 조정할 수 있습니다. 이 정보를 담고 있는 것이 ACHILLES 집계 결과입니다.

---

## 3. 무엇을 요청드리는가

### 위치
ACHILLES는 CDM 데이터와 **별도의 results 스키마**에 결과를 저장합니다.

```
<cdm_schema>            ← 환자 데이터 (요청 대상 아님)
<cdm_schema>_results    ← ACHILLES 집계 결과 (여기의 achilles_results 요청)
```

ATLAS/Broadsea를 운영 중이시면 데이터소스 특성화를 위해 **이미 생성되어 있을 가능성이 높습니다.**

### 요청 테이블
`<cdm_schema>_results.achilles_results` — 컬럼 구조는 다음과 같습니다.

| 컬럼 | 내용 |
|------|------|
| `analysis_id` | 분석 종류 번호 |
| `stratum_1` | 개념 ID (concept_id) |
| `count_value` | 해당 개념을 가진 **환자 수(distinct person)** |
| `stratum_2` ~ `stratum_5` | 추가 층화 값(연도·연령 등) |

### 필요한 analysis_id (개념별 환자 수)

| analysis_id | 내용 |
|-------------|------|
| 400 | 조건(Condition) 개념별 환자 수 |
| 700 | 약물(Drug) 개념별 환자 수 |
| 800 | 관찰(Observation) 개념별 환자 수 |
| 1800 | 측정(Measurement) 개념별 환자 수 |
| 600 | 시술(Procedure) 개념별 환자 수 |
| 200 | 방문(Visit) 개념별 환자 수 |

---

## 4. 추출 방법 (택 1)

### 방법 A — 필요한 부분만 (권장, 약 1MB 이하)

```sql
\copy (
  SELECT analysis_id, stratum_1, count_value
  FROM <cdm_schema>_results.achilles_results
  WHERE analysis_id IN (200, 400, 600, 700, 800, 1800)
) TO 'achilles_prevalence.csv' CSV HEADER
```

소규모 셀 보호가 필요하시면 조건을 추가해 주십시오(예: `AND count_value >= 10`).

### 방법 B — 테이블 전체

```bash
pg_dump -t '<cdm_schema>_results.achilles_results' -Fc <db> > achilles_results.dump
```

전체도 무방하나, 방법 A만으로 저희 분석에 충분합니다.

### ACHILLES가 아직 생성되지 않은 경우

표준 OHDSI R 패키지로 한 번 실행하시면 생성됩니다.

```r
# install.packages("remotes"); remotes::install_github("OHDSI/Achilles")
Achilles::achilles(
  connectionDetails  = connectionDetails,
  cdmDatabaseSchema  = "<cdm_schema>",
  resultsDatabaseSchema = "<cdm_schema>_results",
  sourceName         = "<병원명>"
)
```

---

## 5. 예상 용량

저희 검증 환경(Synthea, 환자 11,771명) 실측을 기준으로 추정한 값입니다.

| 구분 | 행 수 | 용량 |
|------|-------|------|
| 방법 A (개념별 환자 수만) | 1,212행 | **약 19 KB** |
| 방법 B (테이블 전체) | 704,090행 | 약 41 MB |

**실제 병원 규모 추정**

| CDM 규모 | 방법 A | 방법 B (압축 시) |
|----------|--------|------------------|
| 중형(10만~50만 명) | 약 0.3~0.6 MB | 약 0.5~2 GB (50~200 MB) |
| 대형(100만 명 이상) | 약 0.6~1.2 MB | 약 2~8 GB (200~800 MB) |

> 방법 A의 용량은 **환자 수가 아니라 개념 종류 수**에 비례합니다. 환자가 아무리 많아도 "당뇨병"이라는 개념은 한 행이므로, 대형 병원이라도 1MB 내외입니다.

---

## 6. 개인정보 관련

- 요청 데이터는 **개념별 환자 수 집계**이며, 개인 식별정보·개별 환자 레코드는 **포함되지 않습니다.**
- 소규모 셀은 ACHILLES가 자체적으로 억제하며, 추가 억제 기준이 필요하시면 위 SQL에 조건을 추가해 주십시오.
- 저희는 이 집계값을 코호트 정의를 해당 병원 CDM에 맞게 조정하는 용도로만 사용합니다.

---

## 7. 저희가 이 데이터로 하는 일

1. **개념 해석** — 해당 병원에 실제로 채워진(populated) 개념으로 코호트 개념셋을 조정
2. **세분도 적응** — 일반개념이 비어 있고 하위형만 있는 경우 등을 자동 감지·보정
3. **실현가능성 판정** — 필수 조건 중 환자 수 0인 항목을 찾아 제외/완화를 **제안**(자동 적용하지 않음)
4. **대조군 접지** — 문헌 기반으로 추천된 대조약 중 해당 병원에 실제 존재하는 약제만 사용

최종 결과물은 **해당 병원 CDM에 맞게 조정된 코호트 정의 + 조정 내역 리포트**이며, 모든 변경은 담당자 검토·승인을 거칩니다.

---

## 8. 회신 요청 사항

1. `achilles_prevalence.csv` (방법 A) 또는 전체 덤프
2. CDM 스키마명 / results 스키마명
3. CDM 버전(예: v5.4) 및 vocabulary 버전
4. ACHILLES 실행 시점(데이터 기준일)
5. 소규모 셀 억제 기준을 적용하신 경우 그 임계값

---

## 문의

- 담당: 김영현 (yeonghyeon.kim@snu.ac.kr)
- 관련 설계 문서: `artemis/docs/adr/ADR-030_Per_Site_CDM_Adaptation_Layer.md`
