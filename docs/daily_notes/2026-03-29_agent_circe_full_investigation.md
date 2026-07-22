# Agent CIRCE vs Gold LEADER — 전체 조사 기록 (2026-03-29)

## 목표
artemis agent가 생성한 CIRCE JSON으로 Gold LEADER와 유사한 코호트가 뽑히는지 검증.

---

## 현재 상태 (중단 지점)

- **Agent CIRCE** (study 420, cohort 757): L03에서 0명 탈락
- **Gold CIRCE** (e2e_leader_gold): 1222명 (최종)
- **LEADER_BENCHMARK** 데이터: synthea_cdm_leader (10k persons, liraglutide만 있음)

### Attrition 결과 (cohort 757)
```
L00 EntryOnly:          1132명
L01 Type 2 diabetes:    1132명  ✅
L02 Cardiovascular conditions:  85명  ⚠️ (Sequelae of CV disorders — 너무 좁음)
L03 Cardiovascular risk factors:  0명  ❌ (Evaluation procedure 매핑 오류)
L04~L29:                   0명  (L03에서 전원 탈락)
```

---

## 발견한 버그들 (우선순위 순)

### 버그 1: artemis/data/ 마운트 누락 ← 가장 먼저 수정

**증상**: generate-from-nct 시 supplement PDF를 읽지 못함  
**원인**: artemis-api 컨테이너에 `artemis/data/` 디렉토리가 마운트 안 됨  
```
현재 마운트: src/, tmp/, chroma_db/
누락:        data/  ← papers/NCT01179048/*.pdf, nct_cache/*.json 포함
```
**수정 위치**: `compose/artemis-api.yml` volumes 섹션  
```yaml
volumes:
  - ../artemis/src:/app/src
  - ../artemis/tmp:/app/tmp
  - ../artemis/chroma_db:/app/chroma_db
  - ../artemis/data:/app/data   # ← 추가 필요
```
**영향**: supplement PDF 미탑재 → Agent1이 NCT 텍스트만 파싱 → "Cardiovascular conditions" 세부 분해 불가

---

### 버그 2: generate-from-nct 캐시 히트로 구버전 재사용

**증상**: `cacheHit: true, cacheSourceArtifactId: art_321` — supplement 없이 파싱된 IR 재사용  
**원인**: `run_generate_from_nct()`가 기존 artifact를 캐시로 반환  
**수정 방법**: 캐시 무효화 후 재실행하거나, 캐시 키에 papers_dir 해시 포함  

---

### 버그 3: "Cardiovascular conditions/risk factors" 세부 분해 안 됨

**증상**: Gold는 CV conditions를 6개 개념(CAD, stroke, PAD, CKD, CHF)으로 분리, agent는 한 덩어리  
**원인**: 
1. supplement PDF 미마운트 (버그 1)
2. Agent1 파서가 sub_criteria를 만들긴 하나 SNOMED 계층 수준까지 내려가지 않음

NCT 원문: `"cardiovascular, cerebrovascular or peripheral vascular disease or chronic renal failure or chronic heart failure"`  
Agent1 IR: `"Cardiovascular conditions"` 하나로 묶음  
Gold CIRCE: CS[9~14]로 각각 분리된 concept set

---

### 버그 4: Agent2 fast path 비활성화 (수정 완료 ✅)

**파일**: `artemis/src/agents/agent2/workflow.py`  
**수정 내용**: fast path 주석처리, 전부 slow path 강제  
```python
# Fast path disabled: all queries go through slow path
route_path = "slow"
```
**효과**: INCL/EXCL 방향 정확해짐, 일부 매핑 개선

---

### 버그 5: Agent2 drug class 매핑 오류 (미수정)

**증상**: 
- "GLP-1 receptor agonists" → `prucalopride` (GI 약물, 완전 무관)
- "Cardiovascular risk factors" → `Evaluation procedure` (Procedure, 무관)
- "Human NPH insulin" → `ultralente insulin` (다른 인슐린 종류)

**원인**: slow path도 retriever가 domain_hint를 soft penalty (+0.20)만 적용, 필터링 아님  
**위치**: `artemis/src/agents/agent2/retriever.py:187`  
```python
if domain_hint and domain != domain_hint:
    score += 0.20  # ← 필터 아닌 페널티, 효과 미흡
```

**잠재적 수정**: domain_hint와 불일치하는 candidates 필터링(하드 제거) or 페널티 강화

---

## 시스템 구조 이해

### TTE → CIRCE 생성 흐름
```
1. Atlas TTE UI에서 "Import NCT" 클릭
2. generate-from-nct → Agent1.parse_nct() → IR 생성
   - NCT 텍스트 파싱 (LLM)
   - papers_dir 있으면 supplement PDF도 활용
   - sub_criteria로 복합 기준 분해
3. process-eligibility → 각 criterion에 conceptSet 할당 (LLM 기반)
4. generate-seeded-cohorts → 각 criterion별 Agent2 실행
   - Agent2: complexity router → slow/fast path → retriever → reranker → critic
   - _recommend_seeded_concept_set() 호출
   - 결과로 WebAPI 코호트 정의 생성
5. 생성된 cohort ID → WebAPI에서 attrition 실행
```

### 관련 주요 파일
| 파일 | 역할 |
|------|------|
| `src/agents/agent1/parser.py` | NCT → IR 파싱, sub_criteria 분해 |
| `src/agents/agent2/workflow.py` | concept 매핑 메인 워크플로우 (fast/slow) |
| `src/agents/agent2/retriever.py` | ChromaDB RAG 검색 + domain 페널티 |
| `src/agents/agent2/complexity_router.py` | fast/slow path 라우팅 |
| `src/services/tte_service.py:3012` | `_recommend_seeded_concept_set()` |
| `src/services/tte_service.py:2489` | `_build_seeded_target_circe()` |
| `compose/artemis-api.yml` | 컨테이너 마운트 설정 |

### WebAPI / Data 관련
| Source Key | CDM Schema | 상태 |
|---|---|---|
| LEADER_BENCHMARK | synthea_cdm_leader | 10k persons, liraglutide만 있음 ✅ |
| PLATO_BENCHMARK | synthea_cdm_plato | 25k persons ✅ |
| ARISTOTLE_BENCHMARK | synthea_cdm_aristotle | 20k persons ✅ |

- Gold CIRCE: `artemis/output/e2e_leader_gold/circe_cohort.json`
- Agent CIRCE (최신): WebAPI cohort 757 (study 420)
- attrition trace script: `artemis/scripts/trace_cohort_attrition.py`

---

## 다음 세션에서 할 일

### Step 1: data/ 마운트 추가
```yaml
# compose/artemis-api.yml
- ../artemis/data:/app/data
```
→ `docker-compose up -d artemis-api` 재시작

### Step 2: 캐시 무효화 후 LEADER 재파싱
study 420 삭제 후 새 study 생성, generate-from-nct 재실행 (캐시 무시)
→ supplement PDF 읽혀서 sub_criteria 세부 분해 기대

### Step 3: Agent2 domain 필터링 강화
`retriever.py:187` 수정:
- domain_hint 있을 때 다른 domain 개념 하드 필터링
- 또는 페널티를 0.20 → 0.50 이상으로 강화

### Step 4: attrition 재실행 및 Gold와 비교
목표: L02 통과 (1132명 유지), L03 통과, 최종 Gold 1222명 근사

---

## 오늘 수정 완료된 것
1. ✅ `artemis/scripts/setup_study_benchmarks.sh` — LEADER/PLATO/ARISTOTLE 영구 세팅
2. ✅ `artemis/scripts/run_etl_study.R` — 파라미터화 ETL
3. ✅ `artemis/src/agents/agent2/workflow.py` — fast path 비활성화
4. ✅ WebAPI source credentials 수정 (LEADER/PLATO/ARISTOTLE_BENCHMARK)
5. ✅ synthea_cdm_leader_results 테이블 구조 생성
