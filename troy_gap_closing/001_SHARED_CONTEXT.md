# 001 - Shared Context: Types, Schemas & Constants

> Source of Truth — 모든 서브태스크는 이 문서를 참조합니다.

## 1. 수정 대상 Pydantic Models

### RegisteredConcept (`src/registry/models.py`)
```python
class RegisteredConcept(BaseModel):
    concept_id: int
    concept_name: str
    domain_id: str
    vocabulary_id: str
    include_descendants: bool = True  # ✅ 변경 완료
    is_excluded: bool = False
```

### CohortDefinition (`src/models/ir.py`)
```python
class CohortDefinition(BaseModel):
    primary_criteria: PrimaryCriteria
    inclusion_rules: List[Criteria] = []
    exclusion_rules: List[Criteria] = []
    exit_strategy: str = "OBSERVATION_END"  
    # → ExitStrategy 객체로 변경 필요 (CustomEra 지원)
```

### 신규: ExitStrategy (`src/models/ir.py`)
```python
class CustomEraConfig(BaseModel):
    """CustomEra EndStrategy 설정"""
    drug_codeset_id: int
    gap_days: int = 30
    offset: int = 0

class ExitStrategy(BaseModel):
    strategy_type: Literal["OBSERVATION_END", "FIXED_DURATION", "CUSTOM_ERA"]
    date_offset_days: Optional[int] = None      # FIXED_DURATION용
    custom_era: Optional[CustomEraConfig] = None  # CUSTOM_ERA용
```

## 2. 수정 대상 Mappings

### DOMAIN_TO_CRITERIA_TYPE (`src/agents/agent3/mappings.py`)
```python
# 현재: Drug → DrugExposure
# 변경: 이 매핑은 유지하되, PrimaryCriteria 전용 매핑 추가

DOMAIN_TO_PRIMARY_CRITERIA_TYPE = {
    "Drug": "DrugEra",         # PrimaryCriteria에서는 DrugEra 사용
    "Condition": "ConditionOccurrence",
    ...
}

DOMAIN_TO_CRITERIA_TYPE = {
    "Drug": "DrugExposure",     # InclusionRule에서는 DrugExposure 유지
    "Condition": "ConditionOccurrence",
    ...
}
```

## 3. Circe JSON Target Structure (TROY 참조)

### PrimaryCriteria (DrugEra)
```json
{
  "CriteriaList": [{"DrugEra": {"CodesetId": 0}}],
  "ObservationWindow": {"PriorDays": 365, "PostDays": 0},
  "PrimaryCriteriaLimit": {"Type": "First"}
}
```

### EndStrategy (CustomEra)
```json
{
  "CustomEra": {
    "DrugCodesetId": 0,
    "GapDays": 30,
    "Offset": 0
  }
}
```

### ConceptSet Item (includeDescendants)
```json
{
  "concept": {"CONCEPT_ID": 1503297, ...},
  "includeDescendants": true,
  "isExcluded": false,
  "includeMapped": true
}
```

## 4. 테스트 환경

- **기존 테스트**: `tests/test_agent3.py` (4 tests: mappings, structure, concept_sets, inclusion_rules)
- **실행 명령**: `cd /Users/kyh/Workspace/Broadsea/artemis && conda run -n artemis python -m pytest tests/test_agent3.py -v`

## 5. TROY Ground Truth (LEADER DPP-4)

- **PrimaryCriteria**: `DrugEra` (CodesetId=0, liraglutide)
- **EndStrategy**: `CustomEra` (DrugCodesetId=117, GapDays=30)
- **ConceptSets**: 49개, items에 `includeDescendants` 사용
- **InclusionRules**: 18개 (Age, HbA1c, CV disease, exclusions 등)
