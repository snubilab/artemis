# Domain-Level Concept Expansion 전략 분석

**날짜**: 2026-02-28  
**기반 데이터**: Benchmark V5/V6 (LEADER trial, 17 rules)

## 1. 현황 요약

현재 Agent 2의 concept expansion은 **단일 경로**: ChromaDB → (optional) KG expansion.
Drug domain만 ATC ChromaDB expansion (RFC-006)이 추가됨. 나머지 도메인은 추가 확장 전략이 없음.

| Domain | Rules | Avg Recall | 핵심 문제 |
|--------|:---:|:---:|------|
| **Drug** | 3 | **65%** | ✅ ATC 확장으로 GLP1-RA/DPP-4 해결 |
| **Condition** | 9 | **27%** | ❌ SNOMED hierarchy climbing 부재 |
| **Procedure** | 2 | **26%** | ❌ seed concept만 반환, 계층 확장 부족 |
| **Measurement** | 3 | **36%** | ❌ LOINC panel 매칭 부재 |

## 2. 도메인별 분석

---

### 2.1 Drug Domain (ATC Hierarchy) — ✅ 해결됨

**현재 전략**: ATC ChromaDB collection (1,315건) → concept_ancestor → RxNorm Ingredients

| Rule | Recall | 방식 |
|------|:---:|------|
| GLP1-RA/DPP-4/pramlintide | **99%** | ATC 4th level → 14 ingredients |
| Insulin | **97%** | ATC 4th level → 31 ingredients |
| Drug use or dependence | **0%** | ⚠ Agent 1 domain 오분류 (Condition인데 Drug으로 태그) |

**ATC 계층 사용 레벨**:
```
ATC 4th (936건) → 화학적 소분류 (e.g., "GLP-1 analogues") — 현재 사용 ✅
  └ concept_ancestor → RxNorm Ingredient → descendants
```

**남은 이슈**: Agent 1이 "drug use or dependence"를 [Drug]로 오분류. 이건 Agent 1 프롬프트 개선으로 해결 가능.

---

### 2.2 Condition Domain (SNOMED Hierarchy) — ❌ 개선 필요

**현재 전략**: ChromaDB 검색 → seed concept만 반환 (계층 확장 없음)

#### 2.2.1 단순 Condition — Keyword-Based Ancestor Climbing

seed concept에서 concept_ancestor를 역방향 조회하여, **원래 query의 keyword가 포함된 가장 가까운 ancestor**에서 stop.

**검증 결과**:

| Query | Keyword Match Ancestor | desc | TROY | 판정 |
|-------|----------------------|:---:|:---:|:---:|
| Pregnancy | "Pregnancy, childbirth and puerperium finding" | 2,253 | 2,253 | ✅ 정확 |
| End-stage liver disease | "Liver finding" | 716 | 770 | ✅ 근접 |
| Transplant | "Transplantation to recipient" | 264 | 319 | ✅ 근접 |
| T1DM | "Diabetes mellitus" | 132 | 25 | 🔶 과확장 (but seed 자체가 이미 정확) |
| Heart failure | "Heart disease" | 3,111 | 166 | 🔶 과확장 |

대부분의 단순 condition에서 keyword climbing이 잘 작동. seed 자체가 이미 정확한 경우(T1DM) climbing하지 않아도 됨.

**알고리즘**:
```python
def find_best_ancestor(seed_id, query_keywords, max_levels=3):
    ancestors = concept_ancestor(descendant=seed_id, levels=1..max_levels)
    for ancestor in sorted_by_level(ancestors):
        if any(keyword in ancestor.name.lower() for keyword in query_keywords):
            return ancestor  # 가장 가까운 keyword-matching ancestor에서 stop
    return seed  # 매칭 없으면 원래 seed 유지
```

#### 2.2.2 복합 Condition — Agent 1 분해 필요 ("prior CV disease")

"prior CV disease"는 단일 concept이 아닌 **복합 criteria**:

TROY가 사용하는 15개 concept set (106 concepts):
```
[TROY] Myocardial Infarction (1)        [TROY] Stroke, TIAs (10)
[TROY] Revascularization (46)           [TROY] Arterial stenosis (4)
[TROY] Heart Failure NYHA II-III (2)    [TROY] Unstable angina (2)
[TROY] Ischemic heart disease (31)      [TROY] Coronary artery disease (1)
[TROY] Hypertension (1)                 Left ventricular hypertrophy (1)
Left ventricular dysfunction (2)        PAD (1)
Intermittent claudication (1)           Microalbuminuria/proteinuria (2)
[TROY] eGFR (1)
```

**이건 ancestor climbing으로 해결 불가** — "Cardiovascular disease" 하나로 잡으면 8,000+ descendants로 과확장.

**해결 방향**: Agent 1이 "prior CV disease"를 sub-criteria로 분해해야 함:
```
prior CV disease → [
  Myocardial infarction,
  Stroke or TIA,
  Coronary revascularization,
  Peripheral arterial disease,
  Heart failure,
  Coronary artery disease,
  ...
]
```
이를 위해 Agent 1 프롬프트에 **"복합 CV criteria는 하위 질환으로 분해"** 가이드 추가 필요. 또는 "CV disease" 감지 시 SNOMED 하위 children을 자동 나열하는 **concept_ancestor 기반 분해** 방식.

---

### 2.3 Procedure Domain (SNOMED Hierarchy) — ❌ 개선 필요

**현재 전략**: ChromaDB 검색 → seed concept만

| Rule | Recall | Agent 2 | TROY | 분석 |
|------|:---:|:---:|:---:|------|
| Transplant | **4%** | 13 concepts | 319 | 상위 "Transplantation" 계층 필요 |
| Renal replacement | **48%** | 83 concepts | 126 | 부분 매칭 |

Procedure도 Condition과 동일한 **ancestor climbing** 패턴 적용 가능.

---

### 2.4 Measurement Domain (LOINC) — ❌ 개선 필요

**현재 전략**: ChromaDB 검색 → 단일 LOINC 코드만 반환

| Rule | Recall | Agent 2 | TROY | 분석 |
|------|:---:|:---:|:---:|------|
| HbA1C | **100%** | 1 | 1 | ✅ 정확한 1:1 매칭 |
| Calcitonin | **0%** | 15 | 2 | 오매칭 |
| eGFR | **8%** | 8 | 38 | 부분 매칭 — LOINC panel variants 부족 |

LOINC은 SNOMED과 계층 구조가 다름:
- **Panel 기반**: "eGFR" → 여러 method variant (CKD-EPI, MDRD, Cockcroft-Gault 등)
- 계층이 아닌 **그룹** 개념

**제안**: Measurement는 ancestor climbing 대신 `concept_relationship` (Maps to, Has component) 활용.

---

## 3. 통합 전략 제안

| Domain | Vocabulary | 확장 전략 | 구현 방식 |
|--------|-----------|----------|----------|
| **Drug** | ATC | ✅ ATC ChromaDB → concept_ancestor | RFC-006 완료 |
| **Condition** | SNOMED | Ancestor climbing (1-2 levels) | concept_ancestor 역방향 + threshold |
| **Procedure** | SNOMED | Ancestor climbing (1-2 levels) | Condition과 동일 |
| **Measurement** | LOINC | Panel/method variant expansion | concept_relationship 활용 |

### 구현 우선순위

1. **P0**: Condition ancestor climbing — Recall 가장 많이 올릴 수 있음 (Pregnancy 4%→100%, CHF 20%→?, Malignant 40%→?)
2. **P1**: Procedure ancestor climbing — Condition과 같은 패턴 재사용
3. **P2**: Measurement panel expansion — 별도 설계 필요
4. **P3**: Agent 1 domain 분류 개선 — "drug use/dependence" → Condition
