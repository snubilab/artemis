# ACHILLES 집계 데이터 요청서

**요청 대상**: 협력 병원 OMOP CDM 담당자
**작성일**: 2026-07-24
**목적**: TTE(Target Trial Emulation) 코호트를 각 병원 CDM에 맞게 적응(tuning)시키기 위한 개념별 집계 통계 확보
**관련 문서**: ADR-030(사이트별 CDM 적응 계층), ADR-029(기준 실현가능성 게이팅)

---

## 1. 한 줄 요약

**환자 데이터가 아니라, 이미 생성되어 있는 ACHILLES 집계 결과에서 필요한
행만 추출한 `achilles_site_snapshot.zip`을 요청드립니다.** 환자 수준
정보가 없는 집계 데이터이며, 반출 가능 여부는 사이트 거버넌스에 따릅니다.

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
<cdmDatabaseSchema>       ← 환자 데이터 (요청 대상 아님)
<resultsDatabaseSchema>   ← ACHILLES 집계 결과
```

ATLAS/Broadsea를 운영 중이시면 데이터소스 특성화를 위해 **이미 생성되어 있을 가능성이 높습니다.**

### 요청 테이블
`<resultsDatabaseSchema>.achilles_results`에서 아래 6개 analysis만
추출합니다.

| 컬럼 | 내용 |
|------|------|
| `analysis_id` | 분석 종류 번호 |
| `stratum_1` | 선택한 6개 analysis에서 십진수 `concept_id` 문자열 |
| `count_value` | observation period 안에서 해당 이벤트가 한 번 이상 있는 distinct person 수 |

위 의미는 analysis `200/400/600/700/800/1800`에만 적용됩니다. 이
analysis에서는 `stratum_2`~`stratum_5`가 사용되지 않으므로 CSV에서
제외합니다.

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

## 4. 추출 및 bundle 생성

아래 `\copy`는 PostgreSQL 예시입니다. 다른 DBMS에서는 같은 세 컬럼을
CSV로 export해 주십시오.

```sql
\copy (
  SELECT analysis_id, stratum_1, count_value
  FROM <resultsDatabaseSchema>.achilles_results
  WHERE analysis_id IN (200, 400, 600, 700, 800, 1800)
) TO 'achilles_prevalence.csv' CSV HEADER
```

CSV 헤더와 예시는 다음과 같습니다.

```csv
analysis_id,stratum_1,count_value
400,201826,819
1800,3001802,820
```

함께 `manifest.json`을 작성해 주십시오.

```json
{
  "siteKey": "hospital_a",
  "resultsSchema": "hospital_a_results",
  "cdmVersion": "5.4",
  "vocabularyVersion": "2026-06-30",
  "achillesVersion": "1.7.2",
  "achillesRunDate": "2026-07-24",
  "smallCellCount": 5,
  "analysisIds": [200, 400, 600, 700, 800, 1800]
}
```

두 파일을 하나의 ZIP으로 묶어 주십시오.

```text
achilles_site_snapshot.zip
├── achilles_prevalence.csv
└── manifest.json
```

`smallCellCount` 기본값은 5입니다. 값이 양수이면 ACHILLES는
`count_value <= smallCellCount` 행을 삭제합니다. 따라서 누락 행은 0이
아니라 `suppressed_or_absent`로 해석합니다. `smallCellCount=0`은
suppression 해제를 뜻하며, 이 경우에도 0인 CSV 행을 만들지 않습니다.

### ACHILLES가 아직 생성되지 않은 경우

표준 OHDSI R 패키지로 한 번 실행하시면 생성됩니다.

```r
# install.packages("remotes"); remotes::install_github("OHDSI/Achilles")
Achilles::achilles(
  connectionDetails  = connectionDetails,
  cdmDatabaseSchema  = "<cdm_schema>",
  resultsDatabaseSchema = "<resultsDatabaseSchema>",
  sourceName         = "<병원명>"
)
```

---

## 5. 예상 용량

저희 검증 환경(Synthea, 환자 11,771명) 실측을 기준으로 추정한 값입니다.

| 구분 | 행 수 | 용량 |
|------|-------|------|
| 요청 CSV (개념별 환자 수만) | 1,212행 | **약 19 KB** |

**실제 병원 규모 추정**

| CDM 규모 | 요청 CSV |
|----------|----------|
| 중형(10만~50만 명) | 약 0.3~0.6 MB |
| 대형(100만 명 이상) | 약 0.6~1.2 MB |

> 용량은 **환자 수가 아니라 개념 종류 수**에 비례합니다. 환자가 아무리
> 많아도 "당뇨병"이라는 개념은 한 행이므로, 대형 병원이라도 1MB
> 내외입니다.

---

## 6. 개인정보 관련

- 요청 데이터는 환자 수준 정보가 없는 **개념별 distinct person 수 집계**입니다.
- 반출 가능 여부와 전달 방식은 사이트 개인정보·데이터 거버넌스 절차에 따릅니다.
- 적용한 `smallCellCount`는 반드시 manifest에 기록해 주십시오.
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

1. `achilles_site_snapshot.zip`
2. ZIP 내부 `achilles_prevalence.csv`
3. ZIP 내부 `manifest.json` (results 스키마, CDM/vocabulary/ACHILLES 버전,
   실행일, `smallCellCount`, analysis 목록 포함)

---

## 문의

- 담당: 김영현 (yeonghyeon.kim@snu.ac.kr)
- 관련 설계 문서: `artemis/docs/adr/ADR-030_Per_Site_CDM_Adaptation_Layer.md`
