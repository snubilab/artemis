# Benchmark Failure Root Cause Analysis

> 3-Trial A_direct 벤치마크 실패 패턴 분석  
> Date: 2026-03-11

---

## 실패 패턴 분류

### Pattern 1: Drug Class → Ingredient 분해 실패 🔴

Agent 2가 drug class(약리 분류)를 검색하면 **분류 concept 1개**만 반환.  
TROY는 **개별 성분(RxNorm Ingredient)** 을 수동 나열 + `includeDescendants=true`로 모든 제형 포함.

| Rule              | TROY                                                   | Agent 2                | Gap                  |
| ----------------- | ------------------------------------------------------ | ---------------------- | -------------------- |
| Fibrinolytics     | alteplase, Reteplase 등 6 ingredients → 1,497          | class concept 1개 → 2  | Ingredient 분해 불가 |
| Anticoagulants    | apixaban, warfarin 등 6 ingredients → 1,797            | class concept 1개 → 20 | 〃                   |
| Anti-obesity      | Phentermine, orlistat 등 11 ingredients → 5,572        | class concept 1개 → 1  | 〃                   |
| Systemic steroids | Prednisone, Dexamethasone 등 8 ingredients → 50,668    | 3 concepts → 3         | Partial 분해         |
| Substance abuse   | Drug abuse, Drug dependence, Substance abuse 3종 → 241 | 1 concept → 1          | 〃                   |

**원인**: Agent 2의 UMLS 검색이 pharmacological class를 반환하나, OMOP에서 ATC class → RxNorm Ingredient hierarchy가 불완전.  
**해결**: `expand_drug_class_via_vocab` — ATC hierarchy를 타고 내려가 개별 ingredient를 자동 나열.

---

### Pattern 2: CS name에 "[GOLD]" 접두사 포함 → 검색 방해 🟡

벤치마크의 query text가 `[GOLD] Fibrinolytic agents` 형태. `[GOLD]` 접두사가 UMLS 검색 노이즈 발생 가능.

**영향도**: 경미 (Agent 2가 `_clean_rule_name()`으로 접두사 제거 시도). 하지만 concept set name을 직접 query로 쓰는 A_direct 특성상, naming이 검색 품질에 영향.

---

### Pattern 3: Condition hierarchy 불완전 매핑 🟡

| Rule              | Agent 2 raw | TROY raw | R     | Issue                                                                                    |
| ----------------- | ----------- | -------- | ----- | ---------------------------------------------------------------------------------------- |
| Liver disease     | 25 concepts | 17       | 0% R  | Agent 2가 찾은 개념들이 TROY의 liver disease + lab(ALT/AST/ALP)과 전혀 안 겹침           |
| Bariatric surgery | 1 concept   | 3        | 0% R  | Agent 2: 일반 "bariatric surgery" 1개 vs TROY: 구체적 술식 3종(Bypass, Lap Band, Sleeve) |
| ACS/Stroke (2mo)  | 39 concepts | 24       | 10% R | Agent 2: 더 많이 찾았으나 TROY의 specific concepts과 안 겹침                             |

**원인**:

- **Liver disease**: TROY는 condition(간질환) + lab(ALT/AST/ALP measurement concepts) 결합인데, Agent 2는 condition만 검색
- **Bariatric surgery**: Agent 2가 상위 개념을 찾지만 TROY는 구체적 procedure 3종을 지정
- **ACS/Stroke**: Agent 2 raw=39 > TROY raw=24이지만, 정확한 concept이 다름 (vocabulary/hierarchy 불일치)

---

### Pattern 4: Precision 과잉 문제 🟡

| Rule           | R   | P        | Agent 2 | TROY   | Issue                                                                              |
| -------------- | --- | -------- | ------- | ------ | ---------------------------------------------------------------------------------- |
| eGFR < 30      | 92% | **7%**   | 508     | 38     | Agent 2가 과도하게 넓은 eGFR/CKD concepts 반환                                     |
| CYP inhibitors | 0%  | 0%       | 246     | 12     | Agent 2가 CYP 관련 concept 246개를 반환했으나 TROY의 12개 특정 약물과 전혀 안 겹침 |
| Pregnant       | 15% | **100%** | 2,307   | 15,817 | R은 낮지만 P=100% — Agent 2 결과가 TROY에 포함되나 TROY가 훨씬 넓음                |

**원인**: descendant expansion 범위 차이. Agent 2가 상위 concept을 잡으면 너무 넓게 퍼지거나, TROY의 curated set과 겹치지 않는 다른 hierarchy로 확장.

---

### Pattern 5: Partial 성공 (condition 기반) ✅

| Rule             | R   | P    | F1  | Key                                                  |
| ---------------- | --- | ---- | --- | ---------------------------------------------------- |
| High CV risk     | 57% | 89%  | 69% | MI, Stroke, PAD 등 개별 condition 매핑은 작동        |
| Blood dyscrasias | 60% | 100% | 75% | hemochromatosis + blood diseases 잘 매핑             |
| Cancer (5y)      | 92% | 100% | 96% | malignant neoplasm hierarchy가 잘 정의됨             |
| Glycemic control | 36% | 81%  | 50% | T2DM + HbA1c는 잘 찾지만 antidiabetic drug 부분 누락 |

**결론**: **Condition/Measurement 도메인은 비교적 양호**, Drug 도메인이 체계적 실패.

---

## Trial별 요약

|                    | EMPA-REG                          | PLATO                              | 비고                           |
| ------------------ | --------------------------------- | ---------------------------------- | ------------------------------ |
| **R / P / F1**     | 31.6 / 45.6 / 31.3                | 19.9 / 11.6 / 14.7                 |                                |
| **Drug rule 비율** | 4/13 (31%)                        | 3/5 (60%)                          | PLATO가 drug 비중 높아 더 불리 |
| **Condition ✅**   | CV risk, cancer, blood            | clopidogrel contraindication       |                                |
| **Drug ❌**        | steroids, anti-obesity, substance | fibrinolytics, anticoagulants, CYP | 전부 실패                      |

---

## 개선 우선순위

1. 🔴 **Drug class expansion**: ATC → Ingredient 자동 분해 (Pattern 1 해결, 가장 큰 impact)
2. 🟡 **Lab measurement 통합**: Condition rule에 measurement concept 자동 추가 (liver disease에 ALT/AST/ALP)
3. 🟡 **Procedure specificity**: 상위 procedure → 구체적 하위 procedure 확장 (bariatric surgery)
4. 🟢 **Query name 정제**: `[GOLD]` 접두사 제거, CS name을 자연어로 변환
