# TROY LEADER v3.4 데이터 품질 감사 보고서

**감사 대상**: `[TROY] Liraglutide (LEADER) v3.4.json`
**감사 일시**: 2026-02-20
**DB 검증 환경**: Broadsea OMOP CDM v5.0 (synthea_cdm schema)
**관련 ADR**: [ADR-013: TROY는 정답이 아닌 전문가 재해석](../adr/ADR-013_TROY_Is_Not_Ground_Truth.md)

---

## Executive Summary

TROY LEADER 코호트 정의에서 **88개 데이터 품질 이슈**가 발견되었다. TROY를 벤치마크 gold standard로 사용할 때 **ARTEMIS의 recall이 과소평가**되며, TROY 자체의 문제를 ARTEMIS의 결함으로 오판할 위험이 있다.

| 유형 | 건수 | 심각도 |
|------|------|--------|
| Concept ID가 DB에 없음 (NOT_FOUND) | 22 | 🔴 Critical |
| Non-standard concept 사용 | 18 | 🔴 Critical |
| Non-standard + includeDescendants인데 descendant 0개 | 11 | 🔴 Critical |
| includeDescendants 누락 (descendant 있는데 미포함) | 25 | 🟡 Major |
| 중복 ConceptSet | 3 | 🟡 Major |
| 미참조 ConceptSet | 3 | 🟡 Major |
| 도메인 불일치 | 2 | 🟡 Major |
| Design Paper 대비 내용 추가/변경 | 4 | 🔵 Info |
| **합계** | **88** | |

---

## 🔴 Critical Issues

### 1. 존재하지 않는 Concept ID (22건)

TROY에 포함된 concept ID가 현재 OMOP Vocabulary DB에 존재하지 않는다. Vocabulary 버전 차이(TROY 작성 시점 vs 현재) 또는 오타로 추정.

**주요 영향: Revascularization ConceptSet**

| CS Name | 미발견 ID 수 | 예시 |
|---------|------------|------|
| `[TROY] Revasculariazation_final` | 20 | 44511130 (PTCA of multiple coronary arteries) |
| `COPY OF: [TROY] History of malignant neoplasm` | 1 | 42542326 (Non-melanoma skin cancer) |
| `COPY OF: [TROY] unstable angina` | 1 | 35207680 (Unstable angina) |

> [!CAUTION]
> Revascularization CS에서 46개 seed concept 중 **20개(43%)가 DB에 존재하지 않는다**. 이 CS를 기준으로 ARTEMIS의 recall을 평가하면 구조적으로 불공정하다.

### 2. Non-Standard Concept 사용 (18건)

OHDSI 표준에 따르면 코호트 정의에는 `standard_concept = 'S'`인 concept만 사용해야 한다. TROY는 deprecated(D), upgraded(U), 또는 standard_concept=NULL인 concept을 18건 포함한다.

**대표 사례: Substance Abuse**

| TROY Concept ID | Name | standard_concept | invalid_reason | Standard Equivalent |
|-----------------|------|-----------------|----------------|-------------------|
| 436954 | Drug abuse | NULL | D (Deprecated) | 1448779 (Harmful pattern of substance use) |
| 440069 | Drug dependence | NULL | U (Upgraded) | 37165431 (Substance dependence) |
| 4279309 | Substance abuse | NULL | D (Deprecated) | 1448779 (Harmful pattern of substance use) |

> [!WARNING]
> Substance abuse CS의 **3개 seed concept 모두 non-standard**이며, OHDSI `concept_ancestor` 테이블에서 이들의 descendant는 **0개**이다.
> ARTEMIS가 올바르게 standard concept를 선택하더라도 TROY와의 overlap은 0%가 된다 — 이는 ARTEMIS의 결함이 아니라 TROY의 데이터 문제이다.

**Revascularization에서도 동일 패턴:**

| TROY Concept ID | Name | invalid_reason | Standard Equivalent |
|-----------------|------|----------------|-------------------|
| 4019536 | Percutaneous transluminal angioplasty of artery NEC | D | 4184832 |
| 4006788 | Percutaneous transluminal coronary angioplasty | D | 4184832 |
| 2000064 | PTCA [ICD-9-CM] | NULL | 4184832 |

### 3. Non-Standard + includeDescendants = Dead Code (11건)

Non-standard concept에 `includeDescendants: true`를 설정해도, 해당 concept이 `concept_ancestor` 테이블에 없으므로 descendant 확장이 **전혀 작동하지 않는다**. 사실상 dead code.

| CS Name | 해당 ID 수 |
|---------|----------|
| `[TROY] Revasculariazation_final` | 6 (중복 포함) |
| `[TROY] substance abuse` | 3 |
| `COPY OF: [TROY] unstable angina` | 1 |
| `[TROY] ischemic heart disease` | 1 |

---

## 🟡 Major Issues

### 4. includeDescendants 미설정 (25건)

Descendant가 존재하지만 `includeDescendants: false` (또는 미설정)인 concept. 임상적으로 하위 concept을 놓칠 수 있다.

| CS Name | 해당 Concept 수 | 총 누락 Descendants |
|---------|---------------|-------------------|
| `[TROY] Stroke, TIAs` | 9 | ~523 |
| `[TROY] Stroke` | 8 | ~523 |
| `[TROY] Revasculariazation_final` | 4+4 | ~24 |
| `pramlintide` | 1 | 18 |

> [!IMPORTANT]
> Stroke/TIA CS에서 `includeDescendants: false`로 설정된 결과, 수백 개의 cerebrovascular disease 하위 개념이 코호트에서 누락된다.

### 5. 중복 ConceptSet (3건)

동일 이름의 ConceptSet이 다른 ID로 2회 정의됨:

- `[TROY] Revasculariazation_final` (오타 포함) — 2회
- `[TROY] eGFR` — 2회
- `[TROY] microalbuminuria or proteimuria` (오타 포함) — 2회

### 6. 미참조 ConceptSet (3건)

정의되었으나 어떤 InclusionRule, PrimaryCriteria, EndStrategy에서도 사용되지 않는 ConceptSet:

- `oxygen use_device` (id=56)
- `COPY OF: [TROY] DPP4 inhibitors` (id=94)
- `[TROY] microalbuminuria or proteimuria` (id=86, 중복 중 하나)

### 7. 도메인 불일치 (2건)

Criteria가 기대하는 도메인과 실제 concept의 도메인이 다름:

| Rule | Criteria Type | Expected | Actual Concept | Domain |
|------|--------------|----------|----------------|--------|
| No acute coronary/cerebrovascular | ProcedureOccurrence | Procedure | 443563 (Arteriosclerosis of bypass graft) | **Condition** |
| No CHF | ConditionOccurrence | Condition | 4239130 (Oxygen therapy) | **Procedure** |

---

## 🔵 Design Paper 대비 변형 (Informational)

### 8. 전문가 재구성 (ADR-013 참조)

| 항목 | Design Paper | TROY |
|------|-------------|------|
| CV disease 조건 | 12개 개별 criteria | 1개 composite rule (Groups/SubGroups) |
| ESLD | 1 criteria | 4 sub-criteria + bilirubin + liver procedure 추가 |
| Renal replacement | 1 criteria | ESRD + kidney transplant (cond/proc) + renal dialysis 추가 |
| 전체 Rule 수 | ~32 | 18 (재그룹핑) |

### 9. 오타

- `Revasculariazation_final` → Revascularization
- `microalbuminuria or proteimuria` → proteinuria

---

## 벤치마크에 미치는 영향

### Recall 과소평가 구간

| 벤치마크 Rule | 영향 유형 | 방향 |
|-------------|---------|------|
| Substance abuse | Non-standard seed → 0 descendants → overlap 불가능 | ARTEMIS recall **구조적으로 0%** |
| Revascularization | 20/46 seed NOT_FOUND → pool 왜곡 | recall **과소평가** |
| Stroke/TIA | includeDescendants 미설정 → pool 축소 | recall 비교 **불공정** |
| Malignant neoplasm | 제외 concept (42542326) DB 미존재 | precision 필터 미작동 |

### 권장 사항

1. **TROY를 gold standard에서 제외** — ADR-013 결정 유지
2. **Design Paper criteria를 1차 평가 기준**으로 사용
3. **Concept mapping 평가는 standard concept 기준** — TROY의 non-standard concept은 standard equivalent로 치환 후 비교
4. **NOT_FOUND concept은 벤치마크 분모에서 제외** — 존재하지 않는 concept 기반 recall 평가는 무의미

---

## 데이터 파일

- 감사 스크립트 출력: [`output/troy_audit_20260220.json`](file:///Users/kyh/Workspace/Broadsea/artemis/output/troy_audit_20260220.json)
- TROY 원본: [`data/sample/LEADER/[TROY] Liraglutide (LEADER) v3.4.json`](file:///Users/kyh/Workspace/TTE/data/sample/LEADER/[TROY]%20Liraglutide%20(LEADER)%20v3.4.json)
