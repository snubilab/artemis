# Agent 2 Mapping Benchmark Report

> **LEADER Trial (NCT01179048)** — TROY v3.4 reference cohort 대비 ARTEMIS Agent 2 매핑 성능 추적
>
> 마지막 업데이트: 2026-02-16

---

## 📊 Progressive Performance Improvement

기능을 단계적으로 추가하면서 TROY reference (46 unique concept sets) 대비 매핑 정확도가 어떻게 변화했는지 추적.

### Benchmark V1: Raw Seed ID + Hierarchy (sep≤2) 비교

| Stage | 추가된 기능 | ✅ Full | 🟡 Partial | ⚠ Wrong | 비고 |
|-------|-----------|---------|-----------|---------|-----|
| Baseline | ChromaDB 440K + Fast/Slow Path | ~18 | ~8 | ~20 | Vector search만 사용. Hierarchy 비교 없음 |
| + Hierarchy Match | `CONCEPT_ANCESTOR` sep≤2 허용 | 22 | 12 | 12 | hierarchy 매칭으로 Wrong 크게 감소 |
| + Concept Boosting | `concept_stats.json` 빈도 기반 가중치 | 23 | 11 | 12 | 미미한 개선 |
| + UMLS Synonym | MRCONSO 동의어 확장 (multi-query) | **24** | **10** | **12** | Slow Path에서 추가 쿼리 생성 |

### Benchmark V2: Resolved Set 비교 (includeDescendants=true 시뮬레이션)

| Stage | 비교 방식 | ✅ Full (≥80%) | 🟡 Partial | ⚠ Wrong (0%) | Avg Recall |
|-------|----------|---------------|-----------|-------------|------------|
| V2 Resolved | CONCEPT_ANCESTOR 양방향 확장 후 비교 | **21** | **15** | **10** | **59.4%** |

> [!NOTE]
> V2에서 Full이 24→21로 줄어든 이유: TROY도 `includeDescendants=true`로 확장하면서 비교 기준이 더 엄격해짐.
> 예: TROY seed 1개 → resolved 100+개. Agent 2의 seed가 다른 부모를 찾으면 recall <80%로 떨어짐.

### 전체 누적 성능 (Baseline → Step 6)

| Step | 변경 | V2 ✅ Full | V2 🟡 | V2 ⚠ | V2 Recall | V3 ✅ Full | V3 🟡 | V3 ⚠ | V3 Recall |
|------|------|:--------:|:-----:|:-----:|:---------:|:--------:|:-----:|:-----:|:---------:|
| Baseline | ChromaDB + Fast/Slow | 21 | 15 | 10 | 59.4% | — | — | — | — |
| Step 1 | Domain Filtering | 21 | 18 | 7 | 61.7% | — | — | — | — |
| Step 2 | KG-RAG (net-zero) | 21 | 18 | 7 | 61.7% | — | — | — | — |
| Step 3 | Adaptive Limit | 23 | 17 | 6 | 65.1% | — | — | — | — |
| Step 4 | Anchor & Climb | **24** | **17** | **5** | **68.3%** | — | — | — | — |
| **Step 5** | **V3 + Agent 3/4 Fixes** | — | — | — | — | **9** | **5** | **7** | **58.5%** |
| **Step 6** | **Pipeline Cache** | — | — | — | — | ⏎ | ⏎ | ⏎ | ⏎ (동일) |

> [!IMPORTANT]
> V2는 **Agent 2 concept set 매핑**만 평가 (46 CS, 이름 매칭). V3는 **Agent 2+3+4 전체 파이프라인**을 Semantic Fingerprinting으로 평가 (46 Fingerprint, 구조 매칭). V3 recall이 낮은 것은 Agent 3 조립 품질, `[TROY]` prefix 불일치, temporal window 차이 때문.

---

## 🔍 주요 실패 유형 분석

### V2 기준 Wrong 10건 (recall=0%)

| Concept Set | TROY seeds | 해결 후 | Agent 2 결과 | 실패 원인 |
|-------------|-----------|---------|------------|----------|
| oxygen use_device | 21 (HCPCS) | 21 | 1 | ❌ **HCPCS device 코드** — vector DB에 없음 |
| Stroke, TIAs | 10 | 96 | 1 | ❌ Agent 2가 상위 개념만 반환, TROY는 세부 분류 |
| Revascularization_final | 46 | 688 | 24 | ❌ TROY의 46개 seed가 다른 hierarchy에 있음 |
| unstable angina | 2 | 11 | 7 | ❌ 다른 부모 개념 선택 |
| microalbuminuria | 2 | 128 | 47 | ❌ Measurement 도메인 mismatch |
| kidney transplant (cond) | 1 | 37 | 13 | ❌ Condition vs Procedure 도메인 혼동 |
| liver disease_proc | 1 | 1 | 249 | ❌ 과확장 (over-expansion) |
| organ transplant_cond | 9 | 115 | 53 | ❌ Condition/Procedure 도메인 경계 |
| transplant_proc | 10 | 204 | 8 | ❌ 일부 procedure만 확장됨 |
| substance abuse | 3 | 3 | 299 | ❌ Drug vs Condition 도메인 혼동 |

### 실패 유형 분류

| 유형 | 건수 | 설명 |
|------|-----|------|
| **도메인 혼동** | 4 | Condition↔Procedure↔Drug 경계에서 잘못된 도메인으로 매핑 |
| **세부 코드 누락** | 3 | 상위 개념은 맞지만, TROY가 기대하는 specific descendants를 못 찾음 |
| **Vocab 커버리지** | 2 | HCPCS, 특수 LOINC 코드가 ChromaDB에 미등록 |
| **과확장** | 1 | Drug 도메인에서 너무 넓은 descendants 포함 |

---

## 📈 V2 Partial Match 상세 (recall 0~80%)

| Concept Set | Recall | TROY resolved | Agent2 resolved | 개선 방향 |
|-------------|--------|--------------|----------------|----------|
| MEN2 | 75% | 4 | 4 | 거의 해결, 1개 edge case |
| Type 1 DM | 76% | 25 | 19 | 일부 subtype 누락 |
| renal dialysis | 75% | 60 | 45 | 좋은 성능, 일부 procedure 누락 |
| Insulin | 74% | 10,432 | 7,689 | Drug 계층 차이, 일부 formulation 미포함 |
| (acute) MI | 68% | 131 | 89 | Acute vs 전체 MI 구분 문제 |
| Calcitonin | 50% | 2 | 21 | 과확장 + seed 1개만 일치 |
| History of malignant neoplasm | 40% | 5,310 | 2,118 | 거대 hierarchy, 부분 커버리지 |
| DPP4 inhibitors | 39% | 1,923 | 746 | Drug ingredient 계층 차이 |
| sig. liver disease | 29% | 708 | 429 | 부분 커버리지 |
| hypertension | 20% | 142 | 29 | 다른 부모 개념 선택 |
| arterial stenosis | 17% | 353 | 107 | 부분 hierarchy overlap |
| Stroke | 5% | 84 | 46 | 대부분 다른 hierarchy |
| ESLD | 1% | 108 | 1 | 거의 실패, hierarchy 미진입 |
| GLP-1 receptor agonists | 47% | 1,386 | 3,624 | 과확장이지만 recall은 중간 |
| COPY OF: DPP4 inhibitors | 39% | 1,923 | 746 | 위와 동일 (중복 항목) |

---

## 🔧 구현된 기능 히스토리

| 날짜 | 기능 | 파일 | 관련 문서 |
|------|------|------|----------|
| 2026-01-27 | 프로젝트 구조화 | — | `docs/experiments/2026-01-27.md` |
| 2026-02-05 | ChromaDB 440K 확장 | `scripts/populate_chromadb.py` | KI: benchmark_stabilization |
| 2026-02-09 | Hierarchy-aware 비교 | `scripts/diagnose_agent2_gaps.py` | — |
| 2026-02-10 | Concept Boosting | `scripts/generate_concept_stats.py` | ADR-011 |
| 2026-02-11 | UMLS Synonym Expansion | `src/agents/agent2/umls_synonym_expander.py` | ADR-012 |
| 2026-02-11 | V2 Resolved Set 비교 | `scripts/diagnose_agent2_gaps_v2.py` | RFC-002 |

---

## 📁 Raw Data

벤치마크 원본 데이터는 `docs/experiments/benchmarks/` 에 보관:
- `v1_hierarchy_aware.log` — V1 전체 로그
- `v2_resolved_set.log` — V2 전체 로그
- `v1_details.json` — V1 per-concept-set 상세
- `v2_details.json` — V2 per-concept-set 상세
- `hierarchy_analysis.json` — 계층 분석 데이터

---

## 🧪 Ablation Study: Step 1 — 도메인 필터링 강화 (2026-02-11)

> **변경 내용**: `_guess_domain()` 함수에 TROY suffix 인식 (`_cond`, `_proc`, `_device`) + 괄호 패턴 (`(condition)`, `(procedure)`) + domain mismatch penalty 0.10→0.20 강화

### V2 Benchmark 결과 비교

| 메트릭 | Baseline | Step 1 | Δ |
|--------|:--------:|:------:|:---:|
| ✅ Full (≥80%) | 21 | **21** | ±0 |
| 🟡 Partial | 15 | **18** | +3 |
| ⚠ Wrong (0%) | 10 | **7** | **-3** |
| Avg Recall | 59.4% | **61.7%** | **+2.3%** |
| Total Time | — | 7.6 min | — |

### 개별 Concept Set 변화 (Wrong→Partial/Full 전환 3건)

| Concept Set | Baseline | Step 1 | Recall | 원인 |
|-------------|----------|--------|--------|------|
| kidney transplant (condition) | ⚠ Wrong | ✅ Full | **92%** | `(condition)` 패턴 → Condition 도메인 힌트 |
| kidney transplant (procedure) | ⚠ Wrong | ✅ Full | **100%** | `(procedure)` 패턴 → Procedure 도메인 힌트 |
| organ transplant_cond | ⚠ Wrong | 🟡 Partial | **50%** | `_cond` suffix → Condition 도메인 힌트 |

### 여전히 Wrong인 7건

| Concept Set | Recall | 실패 원인 |
|-------------|--------|----------|
| oxygen use_device | 0% | HCPCS device 코드 ChromaDB 미등록 |
| Revasculariazation_final | 0% | 46개 seed의 hierarchy가 다름 |
| unstable angina | 0% | Critic이 올바른 sibling 미선택 |
| microalbuminuria | 0% | Measurement→Condition 도메인 교차 |
| liver disease_procedure | 0% | 과확장 (249 vs 1) |
| transplant_proc | 0% | Critic fallback, 올바른 proc 미선택 |
---

## 🧪 Ablation Study: Step 2 — KG Expander + Critic 최적화 (2026-02-11)

> **변경 내용**: 3가지 설정 테스트  
> (A) limit=20→40 + Critic fallback에 KG descendants 포함  
> (B) limit=40 + domain hint injection (fallback 복원)  
> (C) limit=20 + domain hint injection만 유지 (최종 선택)

### V2 Benchmark 결과 비교

| 설정 | ✅ Full | 🟡 Partial | ⚠ Wrong | Avg Recall | 판정 |
|------|:------:|:---------:|:------:|:---------:|:----:|
| Step 1 (baseline) | 21 | 18 | **7** | **61.7%** | — |
| Step 2-A (limit=40+fallback) | 21 | 16 | 9 | 59.7% | ❌ 악화 |
| Step 2-B (limit=40 only) | 21 | 16 | 9 | 60.1% | ❌ 악화 |
| Step 2-C (domain hint only) | 21 | 18 | **7** | **61.7%** | ✅ 유지 |

### 분석: 왜 limit=40이 악화를 유발하는가?

| 개선된 케이스 | 악화된 케이스 |
|-------------|-------------|
| unstable angina: Wrong→Full (91%) | pramlintide: Full→Wrong |
| Heart Failure: Partial 54%→Full (85%) | eGFR: Full→Wrong |
| arterial stenosis: Partial 17%→24% | Calcitonin: Partial 50%→Wrong |

**원인**: limit=40은 Critic에게 더 많은 후보를 제공하여 broad condition (angina, HF)에서는 개선되지만, narrow measurement/drug (pramlintide, eGFR, Calcitonin)에서는 LLM이 잘못된 sibling을 선택하여 seed를 대체함.

### 최종 결정
- **limit=20 유지** (narrow 쿼리 보호 우선)
- **domain hint injection만 유지** (neutral-positive)
- 코드: `workflow.py` + `critic.py` Critic fallback 복원
---

## 🧪 Ablation Study: Step 3 — Adaptive Limit + Domain-Selective Critic (2026-02-11)

> **변경 내용**:
> 1. Adaptive KG limit: Drug/Measurement=15, Condition(≤2 seeds)=40, else=20
> 2. Domain hint를 Critic context에 Condition 도메인에서만 주입 (Drug/Measurement 제외)

### V2 Benchmark 결과 비교

| 설정 | ✅ Full | 🟡 Partial | ⚠ Wrong | Avg Recall |
|------|:------:|:---------:|:------:|:---------:|
| Baseline (V2) | 21 | 15 | 10 | 59.4% |
| Step 1 (Domain Filtering) | 21 | 18 | 7 | 61.7% |
| Step 2 (KG-RAG, net-zero) | 21 | 18 | 7 | 61.7% |
| **Step 3 (Adaptive Limit)** | **23** | **17** | **6** | **65.1%** |
| **Step 4 (Anchor & Climb)** | **24** | **17** | **5** | **68.3%** |

### 개선 상세

| 케이스 | Step 1 → Step 3 | 원인 |
|-------|----------------|------|
| unstable angina | Wrong → **Full 91%** | Condition limit=40 → 더 많은 subtype |
| Heart Failure | Partial 54% → **Full 86%** | Condition limit=40 |
| pramlintide | Full → Full (유지) | Drug limit=15 + hint 제외 |
| eGFR | Full → Full (유지) | Measurement limit=15 + hint 제외 |
| Calcitonin | Partial 50% → Partial 50% (유지) | Measurement limit=15 |

### 남은 Wrong 케이스 (5건)

| 케이스 | 원인 분류 |
|-------|----------|
| oxygen use_device | HCPCS vocab gap |
| liver disease_procedure | 과확장 (249 vs 1) |
| microalbuminuria | Measurement↔Condition 도메인 교차 |
| transplant_proc | Critic fallback, 올바른 proc 미선택 |
| substance abuse | Condition 계층 불일치 |

---

## 🧪 Ablation Study: Step 4 — Anchor & Climb (2026-02-11)

> **변경 내용**:
> 1. `KGConcept`에 `descendant_count: int = 0` 필드 추가
> 2. `expand()` clinical strategy에 `get_ancestors(max_sep=2)` 직접 후보 추가
> 3. `get_ancestors()` Cypher 확장 — descendant count 포함
> 4. `retriever.py` `_PENALIZED_CLASSES` exact match 시 penalty 면제

### V2 Benchmark 결과

| 설정 | ✅ Full | 🟡 Partial | ⚠ Wrong | Avg Recall |
|------|:------:|:---------:|:------:|:---------:|
| Step 3 (Adaptive) | 23 | 17 | 6 | 65.1% |
| **Step 4 (Anchor & Climb)** | **24** | **17** | **5** | **68.3%** |

### Step 3 → Step 4 변화

| 케이스 | Step 3 → Step 4 | 원인 |
|-------|----------------|------|
| Revascularization_final | Wrong → **Full 95%** | 자손 후보 확대 |
| Coronary artery disease | Full → Full 100% | ancestor가 정확한 parent 제공 |
| MI | Full → Full 100% | 유지 |
| CKD 4-5 | — → Full 100% | ancestor climbing |
| Pregnancy | — → Full 99% | ancestor climbing |
| Type 2 DM | Partial → Full 93% | ancestor climbing |
| malignant neoplasm | Partial 26% → Partial 26% | ❌ Critic이 broad parent 무시 |

### 핵심 발견
- **Ancestor climbing의 한계**: broad parent 개념이 후보에 추가되어도, Critic(LLM)이 specific children을 선호하여 broad parent를 선택하지 않음
- **다음 단계**: Critic 프롬프트에 "query와 exact match인 ancestor가 있으면 우선 선택" 지시 필요

---

## 🧪 Ablation Study: Step 5 — Benchmark V3 + Agent 3/4 Bug Fixes (2026-02-16)

> **변경 내용**:
> 1. Agent 3 `_find_concept_set_id()` fuzzy matching 추가 (substring/contains fallback)
> 2. Agent 3 Demographics → `DemographicCriteriaList` 라우팅
> 3. Agent 4 `_validate_semantic()` — CodesetId=0 감지, 도메인 불일치, 빈 criteria
> 4. Benchmark V3 신규: Static Sanity → Semantic Fingerprinting → Concept Set Recall 3-layer 평가

> [!IMPORTANT]
> **V3는 V2와 다른 대상을 측정합니다.**
> - V2: **Agent 2만** 평가 (46 concept set, 이름 매칭)
> - V3: **Agent 2+3+4 전체 파이프라인** 평가 (46 fingerprint, 구조 매칭)
> - V3 recall이 낮은 이유: Agent 3 조립 품질, concept set 이름 불일치 (`[TROY]` prefix), temporal window 차이 반영

### V2 + V3 통합 Progressive Table

| 설정 | V2 ✅ Full | V2 🟡 Partial | V2 ⚠ Wrong | V2 Recall | V3 ✅ Full | V3 🟡 Partial | V3 ⚠ Wrong | V3 Recall |
|------|:--------:|:----------:|:--------:|:---------:|:--------:|:----------:|:--------:|:---------:|
| Baseline (V2) | 21 | 15 | 10 | 59.4% | — | — | — | — |
| Step 1 (Domain Filter) | 21 | 18 | 7 | 61.7% | — | — | — | — |
| Step 2 (KG-RAG, net-zero) | 21 | 18 | 7 | 61.7% | — | — | — | — |
| Step 3 (Adaptive Limit) | 23 | 17 | 6 | 65.1% | — | — | — | — |
| Step 4 (Anchor & Climb) | **24** | **17** | **5** | **68.3%** | — | — | — | — |
| **Step 5 (V3 + Bug Fixes)** | — | — | — | — | **9** | **5** | **7** | **58.5%** |

### V3 Layer 1: Static Validation

| 항목 | 건수 | 설명 |
|------|:----:|------|
| ❌ CodesetId=0 | 4 | Long-acting / Short-acting / Rapid-acting / Animal-derived insulin |
| ⚠ Domain mismatch | 0 | Agent 3 demographics 라우팅 수정으로 해소 |

### V3 Layer 2: Semantic Fingerprinting (21/46 matched)

| 매칭 유형 | 건수 | 설명 |
|-----------|:----:|------|
| ✅ Full match | 9 | criteria_type + occurrence_type + concept name 정확 일치 |
| 🟡 Partial | 5 | 개념 매칭은 맞으나 recall < 80% |
| ❓ Unmatched | 25 | TROY에 없는 ARTEMIS 확장 rule (세부 분해) |
| ⚠ Wrong | 7 | 매칭되었으나 recall=0% |

### V3 Layer 3: Concept Set Recall 상세 (매칭된 21건)

| Rule | Concept Set Match | Recall | TROY | ARTEMIS | 비고 |
|------|------------------|:------:|-----:|------:|------|
| prior CV disease | MI ↔ MI | **100%** | 131 | 131 | 완벽 일치 |
| prior CV disease | HF (NYHA II-III) ↔ CHF II-III | **100%** | 133 | 133 | 완벽 일치 |
| prior CV disease | unstable angina ↔ Unstable Angina | **91%** | 11 | 15 | 거의 일치 |
| prior CV disease | hypertension ↔ Hypertension | 78% | 142 | 111 | 부분 누락 |
| prior CV disease | LV dysfunction ↔ LVH | **100%** | 7 | 228 | 과확장이지만 recall 유지 |
| prior CV disease | LVH ↔ LV systolic dysfunction | **100%** | 6 | 228 | 과확장이지만 recall 유지 |
| prior CV disease | arterial stenosis ↔ Coronary stenosis | 10% | 353 | 34 | ❌ 부분 계층만 매칭 |
| prior CV disease | IHD ↔ TIA | 0% | 255 | 20 | ❌ 잘못된 concept 매칭 |
| prior CV disease | CAD ↔ Carotid stenosis | 0% | 45 | 14 | ❌ 잘못된 concept 매칭 |
| No T1DM | T1DM ↔ T1DM | 76% | 25 | 19 | 일부 subtype 누락 |
| No calcitonin | Calcitonin ↔ calcitonin | 50% | 2 | 16 | 과확장 |
| No GLP-1 RA/DPP-4 | GLP-1 RA ↔ GLP-1 RA | 47% | 1,386 | 3,624 | Drug hierarchy 차이 |
| No GLP-1 RA/DPP-4 | pramlintide ↔ Pramlintide | **100%** | 17 | 17 | 완벽 일치 |
| No insulin | Insulin ↔ Intermediate-acting insulin | 2% | 10,432 | 185 | ❌ ARTEMIS가 세분화 |
| No DKA | DKA ↔ DKA | **100%** | 8 | 8 | 완벽 일치 |
| No acute event | Stroke ↔ ischemic stroke | 1% | 387 | 19 | ❌ 부분 매칭 |
| No CHF (NYHA IV) | HF (NYHA II-III) ↔ CHF IV | **100%** | 133 | 133 | 구조 재사용 |
| No renal replacement | renal dialysis ↔ Renal Dialysis | 70% | 60 | 42 | 부분 누락 |
| No renal replacement | kidney transplant ↔ kidney transplant | **100%** | 13 | 13 | 완벽 일치 |
| No ESLD | liver disease_proc ↔ liver transplant | 0% | 1 | 10 | ❌ 다른 concept |
| No malignant | malignant neoplasm ↔ lung neoplasm | 4% | 5,311 | 220 | ❌ 거대 hierarchy |

### Agent 3 Bug Fix 효과

| 수정 사항 | 영향 |
|-----------|------|
| Fuzzy matching | `planned coronary artery revascularization` → `Coronary artery revascularization` 연결 성공 |
| Demographics routing | Age ≥ 50 → `DemographicCriteriaList` 정상 배치 |
| CodesetId=0 감지 | 4건 Insulin 서브타입 미매핑 경고 출력 |

### 남은 문제점

| 문제 | 건수 | 설명 |
|------|:----:|------|
| CodesetId=0 | 4 | Insulin 세부 유형 Agent 2 매핑 누락 (Long/Short/Rapid/Animal) |
| Wrong match (recall=0%) | 7 | 주로 composite rule 분해로 인한 잘못된 concept set 매칭 |
| Temporal window 불일치 | 다수 | TROY: `-180:0`, ARTEMIS: `365:0` — fingerprint key 불일치 |

---

## 🧪 Ablation Study: Step 6 — Pipeline Speedup (2026-02-16)

> **변경 내용**:
> 1. `agent2_cache.py` — JSON 기반 Agent 2 매핑 결과 캐시 (`data/cache/agent2_cache.json`)
> 2. `kg_expander.py` — Neo4j KG expansion 결과 캐시 (`data/cache/kg_cache.json`)
> 3. `verify_leader_design_e2e.py` — 캐시 통합 + `--no-cache` CLI 플래그

### Speed Benchmark

| 메트릭 | Before (--no-cache) | After (cached) |
|--------|:-------------------:|:--------------:|
| Agent 2 Mapping Time | **~24 min** | **64s** |
| Cache Hit Rate | 0% | **94%** (71/75) |
| Agent 2 Cache Size | — | 31 KB (80 entries) |
| KG Cache Size | — | 540 KB |

---

## 🔧 구현된 기능 히스토리

| 날짜 | 기능 | 파일 | 관련 문서 |
|------|------|------|----------|
| 2026-01-27 | 프로젝트 구조화 | — | `docs/experiments/2026-01-27.md` |
| 2026-02-05 | ChromaDB 440K 확장 | `scripts/populate_chromadb.py` | KI: benchmark_stabilization |
| 2026-02-09 | Hierarchy-aware 비교 | `scripts/diagnose_agent2_gaps.py` | — |
| 2026-02-10 | Concept Boosting | `scripts/generate_concept_stats.py` | ADR-011 |
| 2026-02-11 | UMLS Synonym Expansion | `src/agents/agent2/umls_synonym_expander.py` | ADR-012 |
| 2026-02-11 | V2 Resolved Set 비교 | `scripts/diagnose_agent2_gaps_v2.py` | RFC-002 |
| 2026-02-11 | Domain Filtering 강화 | `src/agents/agent2/workflow.py` | Step 1 |
| 2026-02-11 | Adaptive Limit | `src/agents/agent2/workflow.py` | Step 3 |
| 2026-02-11 | Anchor & Climb | `src/agents/agent2/kg_expander.py` | Step 4 |
| 2026-02-16 | Agent 3 Bug Fixes | `src/agents/agent3/assembler.py` | Step 5 |
| 2026-02-16 | Agent 4 Validator | `src/agents/agent4/validator.py` | Step 5 |
| 2026-02-16 | Benchmark V3 | `scripts/benchmark_v3.py` | Step 5 |
| 2026-02-16 | Pipeline Cache | `src/agents/agent2/agent2_cache.py`, `kg_expander.py` | Step 6 |

---

## 📁 Raw Data

벤치마크 원본 데이터는 `docs/experiments/benchmarks/` 에 보관:
- `v1_hierarchy_aware.log` — V1 전체 로그
- `v2_resolved_set.log` — V2 전체 로그
- `v1_details.json` — V1 per-concept-set 상세
- `v2_details.json` — V2 per-concept-set 상세
- `hierarchy_analysis.json` — 계층 분석 데이터

캐시 데이터:
- `data/cache/agent2_cache.json` — Agent 2 매핑 캐시
- `data/cache/kg_cache.json` — KG expansion 캐시

---

## 🔜 Next Steps (개선 방향)

1. ~~**도메인 필터링 강화**~~ ✅ 완료 (Wrong -3, Recall +2.3%)
2. ~~**KG Expander + Critic 최적화**~~ ⚠ 실험 완료 (net-zero)
3. ~~**Adaptive Limit**~~ ✅ 완료 (**Wrong -4, Recall +5.7%** vs baseline)
4. ~~**Anchor & Climb**~~ ✅ 완료 (**Wrong -5, Recall +8.9%** vs baseline)
5. ~~**Benchmark V3 + Bug Fixes**~~ ✅ 완료 (V3 Recall 58.5%, 21/46 FP matched)
6. ~~**Pipeline Speedup**~~ ✅ 완료 (~24min → 64s, 94% cache hit)
7. **Critic 프롬프트 개선** — broad parent 선택 유도 (malignant neoplasm 26% 해결)
8. **Temporal Window 정규화** — TROY/ARTEMIS window 차이 해소
9. **Insulin 서브타입 매핑** — CodesetId=0 4건 해소
10. **WebAPI SQL Compilation** — ATLAS에서 실제 SQL 컴파일 검증

