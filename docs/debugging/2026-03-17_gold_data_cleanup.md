# Gold Data ConceptSet 정리 — 2026-03-17

> 이후 다른 trial Gold도 동일 패턴으로 수정 예정. 이 문서를 템플릿으로 활용.

## 백업

```
data/gold_backup_20260317/   # 8개 파일 전체 백업
```

---

## LEADER (LEADER_GOLD.json, LEADER_GOLD_SUPP.json)

### 수정 1: Calcitonin — Procalcitonin 삭제

| ConceptSet | 삭제 | 사유 |
|---|---|---|
| `calcitonin` (GOLD CS22, SUPP CS24) | `44817130` Procalcitonin | Calcitonin과 Procalcitonin은 별개 검사 |

### 수정 2: eGFR <30 / CKD 4-5 — InclusionRule 삭제

| 삭제 대상 | 사유 |
|---|---|
| InclusionRule #11 (양쪽 파일) | Trial 정의와 충돌 |

관련 ConceptSet(eGFR, CKD 4-5)은 orphan으로 남겨둠 (다른 rule 참조 깨짐 방지).

### 수정 3: ESLD — 3개 concept 삭제

| ConceptSet | 삭제 | 사유 |
|---|---|---|
| `ESLD` (GOLD CS23, SUPP CS8) | `137977` Jaundice | 비특이적 |
| | `4055223` Toxic hepatitis | ESLD 진단 기준에 부적합 |
| | `4058676` Acute necrosis of liver | ESLD 진단 기준에 부적합 |

### 수정 4: Significant liver disease — 5개 concept 삭제

| ConceptSet | 삭제 | 사유 |
|---|---|---|
| `significant liver disease` (GOLD CS35, SUPP CS37) | `197917` Disorder of biliary tract | 비특이적 |
| | `4185719` Cholestatic jaundice syndrome | 비특이적 |
| | `4243963` Hemolytic jaundice | 간질환 아님 (혈액질환) |
| | `4291005` Viral hepatitis | 너무 광범위 |
| | `4337543` Hepatic necrosis | ESLD와 중복/비특이적 |
---

## PLATO (PLATO_GOLD.json, PLATO_GOLD_CLOP.json)

### 수정 1: Rule #0 — Old MI ProcedureOccurrence 제거

**배경**: Rule #0 "ACS enrollment" 내부의 nested ANY Group에서 `ProcedureOccurrence(CodesetId=40, Old MI)`를 
참조하지만, Old MI(`314666`)는 `procedure_occurrence` 테이블에 매핑되기 어려운 condition 성격의 코드.

**구조 (수정 전)**:
```
Rule 0: ACS enrollment
  └─ ConditionOccurrence 'ACS (excluding STEMI)' (CodesetId=30)
       └─ CorrelatedCriteria → Group (ANY, age >= 60):
            ├─ ConditionOccurrence: id=41 (diabetes)       ← 유지
            ├─ ProcedureOccurrence: id=40 (Old MI)         ← 삭제
            └─ ProcedureOccurrence: id=54 (PCI/CABG)       ← 유지
```

| 삭제 대상 | id | concept | 사유 |
|---|---|---|---|
| CriteriaList item (ProcedureOccurrence) | CodesetId=40 | `314666` Old myocardial infarction | condition을 procedure로 참조 — 데이터 불일치 |

**참조 분석**: `CodesetId=40`은 전체 JSON에서 **1회만** 참조 (Rule #0 nested group). 제거 시 다른 rule 영향 없음. ConceptSet `Old MI` 자체도 orphan이 되므로 함께 삭제 가능.

---

## 수정 완료 현황

- [x] LEADER — 4건 수정 (Procalcitonin, eGFR rule, ESLD, Significant liver disease)
- [x] PLATO — 1건 수정 (Old MI ProcedureOccurrence)
- ARISTOTLE — 수정 불필요
- EMPA-REG — 수정 불필요


---

## Implementation Notes

### 수정 전후 비교

#### LEADER_GOLD.json

| 항목 | Before | After |
|---|---|---|
| ConceptSets 수 | 54 | 54 (변동 없음, orphan 유지) |
| InclusionRules 수 | 18 | 17 (eGFR rule 삭제) |
| CS 22 `Calcitonin` | 2 concepts | 1 concept |
| CS 7 `ESLD` | 9 concepts | 6 concepts |
| CS 35 `significant liver disease` | 9 concepts | 4 concepts |

#### LEADER_GOLD_SUPP.json

| 항목 | Before | After |
|---|---|---|
| ConceptSets 수 | 56 | 56 (변동 없음) |
| InclusionRules 수 | 18 | 17 |
| CS 24 `Calcitonin` | 2 concepts | 1 concept |
| CS 8 `End-stage liver disease` | 9 concepts | 6 concepts |
| CS 37 `Significant liver disease` | 9 concepts | 4 concepts |

### ConceptSet 잔존 목록

**ESLD (수정 후 6 concepts):**
- `45769564` End stage liver disease
- `4026032` Acute hepatic failure
- `24966` Esophageal varices
- `28779` Bleeding esophageal varices
- `22340` Esophageal varices without bleeding
- `200528` Ascites

**Significant liver disease (수정 후 4 concepts):**
- `200528` Ascites
- `28779` Bleeding esophageal varices
- `4064161` Cirrhosis of liver
- `4111998` Esophageal varices associated with another disorder

### 수정 절차

1. **백업**: `data/gold_backup_20260317/` 에 원본 8개 JSON 전체 복사
2. **이름 기반 검색 스크립트** 작성 → 인덱스 하드코딩 X, ConceptSet `name` 필드로 검색
3. **concept 제거**: `expression.items[]` 에서 `concept.CONCEPT_ID` 매칭하여 필터링
4. **InclusionRule 제거**: `InclusionRules[]` 에서 이름 패턴으로 검색 후 삭제
5. **검증**: 삭제 대상 concept ID가 전체 JSON에 잔존하지 않는지 확인

### ⚠️ Gotchas

1. **ConceptSet 인덱스 ≠ ConceptSet id**: `ConceptSets[]` 배열의 인덱스와 JSON 내부의 `id` 필드는 별개. 이전 분석(탐색 출력)에서 "CS 23 = ESLD"로 보였지만 실제로는 **CS 7**이었음. 반드시 **이름 기반**으로 검색할 것.
2. **ConceptSet 삭제 대신 orphan 유지**: ConceptSet을 삭제하면 `codesetId` 참조가 전체적으로 밀림. InclusionRule만 삭제하고 ConceptSet은 orphan으로 남겨두는 것이 안전.
3. **GOLD vs SUPP에서 같은 ConceptSet 이름이 다름**: 예) GOLD에서 `ESLD`, SUPP에서 `End-stage liver disease`. 스크립트에서 fallback 패턴 매칭 필요.
4. **JSON indent**: `json.dump(data, f, indent=2, ensure_ascii=False)` 로 저장 — 원본 형식 유지.

### 재현 스크립트 패턴

향후 다른 trial 수정 시 아래 패턴 복제:

```python
import json
from pathlib import Path

def find_cs_by_name(data, name_pattern):
    """이름 패턴으로 ConceptSet 인덱스 찾기"""
    for i, cs in enumerate(data["ConceptSets"]):
        if name_pattern.lower() in cs["name"].lower():
            return i
    raise ValueError(f"Not found: {name_pattern}")

def remove_concepts(data, cs_name, concept_ids):
    """ConceptSet에서 concept ID 목록 제거"""
    idx = find_cs_by_name(data, cs_name)
    cs = data["ConceptSets"][idx]
    cs["expression"]["items"] = [
        item for item in cs["expression"]["items"]
        if item["concept"]["CONCEPT_ID"] not in concept_ids
    ]

def remove_rule_by_name(data, name_pattern):
    """InclusionRule 이름으로 삭제"""
    for i, rule in enumerate(data["InclusionRules"]):
        if name_pattern.lower() in rule["name"].lower():
            del data["InclusionRules"][i]
            return
```
