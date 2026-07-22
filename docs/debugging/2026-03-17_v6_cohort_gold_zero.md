# V6 Cohort Gold=0 디버깅 최종 보고서

**날짜**: 2026-03-17  
**작성자**: Claude (Antigravity)  
**상태**: 🟡 근본 원인 격리 완료 — 해결책 설계 필요

---

## 최종 진단

### 원인: ConceptSets 수가 많으면 WebAPI가 cohort SQL을 silent failure

| 테스트 | ConceptSets | Inclusion Rules | 결과 |
|:---|:---|:---|:---|
| ATT4 L0 (DrugEra only) | 1 | 0 | **1,424** ✅ |
| Test 4 (EraStart + EraLen + Prior180) | 1 | 0 | **1,093** ✅ |
| Test A (Gold entry + all CS, no rules) | **49** | **0** | **0** ❌ |
| [CSTEST] 30 CS | 30 | 0 | **0** ❌ |
| Gold 166 (full) | 49 | 18 | **0** ❌ |

### 결정적 증거

1. **Entry criteria는 정상**: EraStartDate≥2010, EraLength≥7, PriorDays 180 → 수동 SQL 1,093명과 정확히 일치
2. **ConceptSets만 추가해도 0**: Inclusion Rules 없이 ConceptSets 49개만 추가 → 0명
3. **데이터 정상**: `synthea_cdm_benchmark` vocabulary 테이블 6.3M concepts, 75M ancestors 존재
4. **SqlRender 정상**: 1.19.1 최신, 번역 정상
5. **WebAPI는 에러 없이 COMPLETED 반환**: Silent failure

### 추정 원인

Gold 166의 template SQL은 **113,444 characters** (≈113KB). 49개 ConceptSets가 각각 `UNION ALL`로 `#Codesets` temp table에 INSERT됩니다. 이 SQL이:

1. **PostgreSQL의 single statement size limit** (~1GB이므로 아닐 가능성 높음)
2. **WebAPI/JDBC의 SQL splitting 로직** — WebAPI가 `SqlRender.splitSql()`로 SQL을 분할 실행할 때, 대형 SQL에서 temp table 참조가 끊어질 수 있음
3. **Temp table scope** — `#Codesets`가 한 transaction에서 생성되고, 다른 split된 statement에서 참조되면 보이지 않을 수 있음

---

## 기각된 가설 (전체)

| 가설 | 판정 | 검증 근거 |
|:---|:---|:---|
| SqlRender 버전 오래됨 | ❌ 기각 | 1.19.1 최신 |
| SqlRender 번역 실패 | ❌ 기각 | 동일 JAR 3개 함수 정상 |
| TEMP_EMULATION_SCHEMA | ❌ 기각 | WebAPI에 전달 안 됨 |
| source_dialect 설정 | ❌ 기각 | `postgresql` 확인 |
| Vocabulary 데이터 없음 | ❌ 기각 | 6.3M concepts 존재 |
| Entry criteria 문제 | ❌ 기각 | 1 CS로 1,093명 확인 |
| Inclusion rules 탈락 | ❌ 기각 | 0 rules에서도 0명 (49 CS만으로) |
| 데이터 잘못 생성 | ❌ 기각 | 수동 SQL 1,093명 일치 |
| **ConceptSets 수 → SQL silent failure** | 🎯 확정 | 1 CS=1,093, 49 CS=0 |

---

## 다음 단계 (해결 방안)

### 방안 1: Gold cohort에서 불필요한 ConceptSets 제거

Gold 166에서 사용하지 않는 ConceptSets (예: 중복된 `[TROY]` prefix 셋들)를 제거.
- Inclusion rules가 실제로 참조하는 ConceptSets만 남김
- SQL 크기를 줄여 threshold 이내로 맞춤

### 방안 2: WebAPI SQL splitting 디버깅

`webapi-from-git`으로 소스 빌드 후, `CohortGenerationService`의 SQL 실행 경로에서 `splitSql()` 동작 확인.

### 방안 3: R SqlRender로 직접실행 (우회)

R `DatabaseConnector::executeSql()`은 SQL splitting을 다르게 처리. 동일 SQL을 R로 실행하면 정상 작동할 수 있음.

---

## 타임라인

| 시각 | 발견 |
|:---|:---|
| 13:00 | WebAPI Gold cohort 0명 발견 |
| 14:30 | SqlRender 버전 이론 제기 (3-모델 합의) |
| 16:00 | **SqlRender 1.19.1 정상 확인** → 이론 기각 |
| 16:30 | EUNOMIA 830명 ✅, Lira 1,424명 ✅ |
| 16:55 | Entry criteria 수동 검증 1,093명 일치 |
| 17:00 | **Test A (49 CS + 0 rules) = 0** → ConceptSets가 원인 |
| 17:10 | 30 CS도 0 → 20 이하에서 threshold 존재 가능 |

## 교훈

1. **3개 LLM 합의는 증거가 아니다** — SqlRender 버전 이론은 `find` 한 줄로 기각
2. **격리 테스트가 최고** — Entry Only → +filter → +rules → +CS 단계별로 추가하며 범인 식별
3. **Silent failure는 가장 위험** — WebAPI가 `COMPLETED` + `0명`을 반환하면 정상 같지만 실제로는 SQL이 실패
