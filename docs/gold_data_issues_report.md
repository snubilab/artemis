# Gold 데이터 3종 내재 문제 분석 보고서

**Date**: 2026-03-13  
**Purpose**: 교수님 점검용 — LEADER / PLATO / ARISTOTLE Gold 데이터의 한계와 잠재적 편향 정리  
**선정 기준**: 질환그룹별 약물 비중복 (T2DM / ACS / AF)

---

## 1. Gold 데이터 개요

| 항목            |       **LEADER**       |          **PLATO**           |        **ARISTOTLE**         |
| --------------- | :--------------------: | :--------------------------: | :--------------------------: |
| Trial           |      NCT01179048       |         NCT00391872          |         NCT00412984          |
| Drug            | Liraglutide vs Placebo |  Ticagrelor vs Clopidogrel   |     Apixaban vs Warfarin     |
| 질환그룹        |     T2DM + CV risk     |             ACS              |       Non-valvular AF        |
| ConceptSets     |           56           |              24              |              33              |
| Unique Concepts |          241           |             115              |             136              |
| Inclusion Rules |           18           |              5               |              15              |
| Base Source     | TROY v1.1 + v3.4 merge | TROY v3.4 + v1.1 cherry-pick | TROY v3.4 + v1.1 cherry-pick |

---

## 2. 공통 구조적 문제 (Cross-cutting Issues)

### 2.1 🔴 Gold 자체가 "Ground Truth"가 아닌 "Best Effort" 구성물

> [!CAUTION]
> 세 Gold 데이터 모두 **TROY (OHDSI community 큐레이션)** v1.1과 v3.4를 선택적으로 merge한 결과물이다. 독립적 전문가 리뷰를 거친 것이 아니며, 원저 프로토콜과의 **차이(gap)**가 존재한다.

- **구축 주체**: 연구팀 내부에서 v1.1과 v3.4를 비교하여 rule별로 "더 나은 쪽"을 선택
- **검증 방법**: Codex 자동 리뷰 + 수동 검증 (피어 리뷰 아님)
- **한계**: OMOP CDM 전문가의 외부 검증 없음 → **selection bias** 가능성

### 2.2 🔴 TROY 버전 간 불일치 기반 merge의 위험

세 Gold 모두 **TROY v1.1과 v3.4의 cherry-pick merge** 방식으로 구축됨:

| 측면                       | v1.1 우위                                   | v3.4 우위                        |
| -------------------------- | ------------------------------------------- | -------------------------------- |
| Protocol 구조 재현         | ⭐⭐⭐⭐⭐ (age-stratified, 약물 whitelist) | ⭐⭐⭐ (flat list)               |
| Drug concept 커버리지      | ⭐⭐⭐⭐⭐ (73 insulin variants)            | ⭐⭐⭐ (19 concepts)             |
| Condition concept 커버리지 | ⭐⭐⭐                                      | ⭐⭐⭐⭐ (ESLD, transplant 확장) |
| `includeDescendants` 정책  | 보수적 (false)                              | 적극적 (true)                    |

**문제**: Cherry-pick 과정에서 **일관된 원칙 없이** 각 rule마다 다른 버전을 선택 → 동일 Gold 내에서 concept 커버리지 정책이 불균일.

### 2.3 🟡 Protocol 미구현 Criteria 존재

세 Gold 모두 원문 프로토콜(NCT + Supplementary Appendix)에 기술된 기준 중 **일부를 구현하지 못함**:

| Trial  | 미구현 Criteria                    | 사유                              |
| ------ | ---------------------------------- | --------------------------------- |
| LEADER | E-7: Planned revascularization     | TROY v1.1/v3.4 **양쪽 모두 누락** |
| PLATO  | E-1: Clopidogrel contraindication  | 너무 일반적, 코딩 불가            |
| PLATO  | E-5: Increased risk of bradycardia | 임상적 판단 필요                  |
| PLATO  | E-6: Moderate/severe liver disease | NCT에만 명시, 본문 미기재         |

→ Gold에 없는 criteria는 **벤치마크에서 아예 측정 불가** — recall 상한선이 이미 100% 미만.

### 2.4 🟡 Protocol에 없는 TROY 추가 기준 포함

| Trial  | 추가 Criteria      | 비고                        |
| ------ | ------------------ | --------------------------- |
| LEADER | No substance abuse | 원문 미명시, TROY 자체 추가 |
| LEADER | No pregnant        | 원문 미명시, TROY 자체 추가 |

→ 이 기준들이 Gold에 포함되면, 자동화 시스템이 프로토콜에 없는 기준까지 맞춰야 하는 **unfair benchmark** 문제 발생.

---

## 3. Trial별 고유 문제

### 3.1 LEADER — 가장 복잡, 가장 많은 issue

#### (a) 🔴 v3.4 HbA1c 원본 버그가 Gold 구축 과정에서 발견됨

| 항목     | v3.4 (❌)                            | v1.1 (✅)                | GOLD          |
| -------- | ------------------------------------ | ------------------------ | ------------- |
| Value    | 10                                   | 7                        | **7 (수정)**  |
| Operator | `gte` (≥10)                          | `lt` (<7)                | **`lt` (<7)** |
| 의미     | ≥10 없어야 함 (사실상 ≤10 모두 포함) | <7 없어야 함 (≥7만 포함) | ≥7만 포함     |

→ **TROY v3.4 원본에 버그가 있었음** — Gold 구축 중 수정했으나, TROY 원본이 community 검증을 통과했음에도 이런 오류가 있었다는 사실 자체가 Gold reference의 신뢰성 문제를 시사.

#### (b) 🟡 고아 ConceptSet 14개

정의만 있고 어떤 rule에서도 참조하지 않는 ConceptSet이 14개 → **유지보수 리스크** + 의도 불명확.

#### (c) 🟡 중복 ConceptSet 존재

- CS 45 ↔ 124 (LVH), CS 46 ↔ 125 (LVD), CS 77 ↔ 97 (Revascularization)
- 동일 임상 개념의 중복 정의 → resolved concept이 달라질 수 있음

#### (d) 🟡 Insulin 배제 범위 과도

No insulin (E-4) rule이 v3.4의 broad blacklist(19 concepts) → 프로토콜상 **허용되는 NPH/long-acting/premixed**까지 배제 위험.

#### (e) 🟢 시간창(lookback) 180일 가정

프로토콜에 명시 없는 operational 결정 → 만성 질환에 과소 적용 가능.

---

### 3.3 PLATO — 가장 단순하나 가장 낮은 성능

#### (a) 🔴 5 rules 중 4개 Wrong (Avg Recall 19.9%, Precision 11.6%)

PLATO는 ACS treatment trial로 criteria가 매우 단순(5 rules)하지만, drug class 의존도가 높아 Agent 2의 drug class 매핑 한계가 극명히 드러남.

| Rule                        | Recall | 핵심 문제                                  |
| --------------------------- | ------ | ------------------------------------------ |
| ACS hospitalization (entry) | 0%     | STEMI/ACS concept 2개만 반환 (vs TROY 102) |
| No fibrinolytics (24h)      | 0%     | Drug class hierarchy 확장 미작동           |
| No oral anticoagulants      | 0%     | Drug class hierarchy 확장 미작동           |
| No CYP 3A4 inhibitors       | 0%     | 과확장 (246 concepts vs TROY 12) → P도 0%  |

#### (b) 🟡 CYP inhibitors/inducers의 Concept 선정 기준 모호

PLATO Gold의 CYP 3A4 inhibitor/inducer 목록(12개 약물: Amiodarone, Carbamazepine, Cimetidine 등)은 TROY 큐레이터의 **임상적 판단**에 의존 — 포함/제외 근거 문서화 없음.

#### (c) 🟡 Orphan CS 3개 (LBBB, MI, Prasugrel)

프로토콜 관련이나 rule에 미연결 — 원래 protocol에서는 사용되지만, Circe JSON 구조 제약으로 rule화 불가능한 것인지, 단순 누락인지 불명확.

#### (d) 🟡 STEMI 정의의 Inclusion/Exclusion 혼재

STEMI concept set (id=28)에서 `Acute non-ST segment elevation MI`를 `isExcluded=true`로 처리 — NSTEMI를 제외하여 STEMI만 남기는 논리이지만, 이 복합 logic이 벤치마크 resolved concept 계산에서 정확히 반영되는지 검증 필요.

---

### 3.4 ARISTOTLE — AF 도메인 첫 Gold, 구조적으로 건전하나 검증 미완

#### (a) 🟡 Orphan CS 13개가 v3.4 원본에 존재 → Gold 구축 시 제거

v3.4 원본에 rule에서 참조되지 않는 CS 13개가 있었음:

- `CHF`, `Major surgery`, `alcohol`, `Heart Failure (NYHA class II-III)`, `Atrial fibrillation` (단독) 등
- Gold 구축 과정에서 **전부 제거** → 최종 orphan 0개
- TROY v3.4 원본의 품질 관리 미흡을 재확인 (LEADER HbA1c 버그와 유사)

#### (b) 🟡 v1.1 cherry-pick 범위가 concept-level에 국한

v1.1에서 cherry-pick한 내용:

- `Diabetes Mellitus` +6 concepts (v1.1이 더 넓은 DM 약물 coverage)
- `Total bilirubin` +1 concept

→ v1.1에만 있는 **ConceptSet 자체** (e.g., `OADs and injectable diabetes medicine` 11 concepts)는 v3.4 rule에서 참조하지 않아 추가 불가. 이 CS가 포함되었을 때의 잠재적 영향은 미검증.

#### (c) 🟡 벤치마크 미등록 (성능 미확인)

Gold JSON은 구축되었으나, Agent 2 벤치마크에 아직 등록되지 않아 recall/precision 미측정. AF 도메인은 기존 T2DM/ACS와 다른 특성 — drug class보다 condition hierarchy (stroke, ICH, CKD 등)의 비중이 높아 다른 패턴의 성능 분포 예상.

#### (d) 🟢 Target/Comparator 차이가 drug entry만 상이 (설계 적절)

- Target: Apixaban entry → Warfarin exclusion
- Comparator: Warfarin entry → Apixaban exclusion
- 나머지 14 exclusion rules 공유 → 올바른 구조

---

## 4. 벤치마크 방법론 자체의 한계

### 4.1 Resolved Concept 비교 방식의 근본 문제

```
Gold_resolved = concept + descendants (includeDescendants=true일 때)
Agent_resolved = agent output + descendants
Recall = |Gold ∩ Agent| / |Gold|
```

> [!WARNING]
> `includeDescendants=true`인 concept의 descendant 수가 수천~수만 개인 경우, **단일 ancestor concept 하나의 포함 여부**가 recall을 지배. 의미론적으로 중요한 개별 concept 수십 개보다, broad ancestor 1개가 recall에 미치는 영향이 압도적.

예시:

- `History of malignant neoplasm` (1 concept) → **5,310 descendants** → 이 1개만 맞추면 recall 100%
- `MEN2 + MTC` (2 concepts) → **6 descendants** → 2개 다 맞춰도 6개에 불과

### 4.2 Trial 간 난이도 비교 불가

| Trial     | Rules | Avg Concepts/Rule | Drug-heavy Rules | 질환그룹        |
| --------- | :---: | :---------------: | :--------------: | --------------- |
| LEADER    |  18   |      ~1,400       |     3 (17%)      | T2DM + CV risk  |
| PLATO     |   5   |      ~1,100       |     4 (80%)      | ACS             |
| ARISTOTLE |  15   |       ~TBD        |      1 (7%)      | Non-valvular AF |

→ PLATO의 낮은 성능은 Gold 자체 문제가 아니라, trial 특성(drug-heavy)과 파이프라인 한계의 교차 효과.

---

## 5. 종합: 교수님께 논의 필요 사항

### 5.1 Gold 데이터를 논문에서 어떻게 위치시킬 것인가?

| 선택지                               | 장점                 | 단점                                     |
| ------------------------------------ | -------------------- | ---------------------------------------- |
| (A) "Expert-curated Gold Standard"   | 벤치마크 신뢰도 높음 | TROY 기반 cherry-pick이며 독립 검증 없음 |
| (B) "TROY-based Reference Set"       | 정직한 표현          | 벤치마크 결과의 무게감 감소              |
| (C) "Semi-automated + Expert Review" | 절충안               | 실제 전문가 리뷰 과정 추가 필요          |

### 5.2 Benchmark 공정성 개선 제안

1. **Protocol-only baseline**: TROY 추가 기준(substance abuse, pregnancy) 제외 후 재측정
2. **Concept-level weighting**: descendant 수로 가중치 부여 vs 현재 flat union
3. **Cross-trial normalization**: trial 특성(drug-heavy vs condition-heavy) 보정

### 5.3 즉시 수정 가능한 사항

| #   | 사항                                                                   | 우선순위 |
| --- | ---------------------------------------------------------------------- | :------: |
| 1   | Orphan ConceptSet 정리 (LEADER 14개, PLATO 3개, ~~ARISTOTLE 13개~~ ✅) |    🟡    |
| 2   | 중복 CS 통합 (LEADER: LVH, LVD, Revascularization)                     |    🟡    |
| 3   | 미구현 criteria 명시적 문서화 (LEADER E-7, PLATO E-1,5,6)              |    🔴    |
| 4   | TROY 추가 기준 별도 표시 (substance abuse, pregnancy)                  |    🟡    |
| 5   | ARISTOTLE 벤치마크 등록 및 성능 측정                                   |    🔴    |
