# OHDSI Cohort & Concept Set Data Collection

> **Last Updated**: 2026-02-01

## Summary

| Source | Cohorts | Concept Sets |
|--------|---------|--------------|
| Phenotype Library | 1,100 | 2,741 |
| OHDSI Studies | 1,759 | 13,375 |
| ATLAS Demo | 21,279 | 103,027 |
| **Total** | **24,138** | **119,143** |

---

## Data Sources

### 1. OHDSI Phenotype Library
- **URL**: https://github.com/OHDSI/PhenotypeLibrary
- **Location**: `data/phenotype_library/`
- **Description**: 공식 OHDSI Phenotype 정의

### 2. OHDSI Studies
- **URL**: https://github.com/ohdsi-studies/
- **Location**: `data/ohdsi_studies/`
- **Script**: `scripts/fetch_ohdsi_studies.py`
- **Description**: 58개 연구 프로젝트의 코호트 정의

### 3. ATLAS Demo
- **URL**: https://atlas-demo.ohdsi.org/
- **Location**: `data/atlas_cohorts/`
- **Description**: 공개 ATLAS 인스턴스의 코호트 정의

---

## JSON Structure

### ATLAS Cohort JSON
```json
{
  "id": 1783432,
  "name": "[TROY] Dapagliflozin (DECLARE-TIMI 58) v3.4",
  "expression": {
    "ConceptSets": [
      {
        "id": 0,
        "name": "[TROY] T2DM",
        "expression": {
          "items": [
            {
              "concept": {
                "CONCEPT_ID": 201826,
                "CONCEPT_NAME": "Type 2 diabetes mellitus",
                "DOMAIN_ID": "Condition",
                "VOCABULARY_ID": "SNOMED"
              },
              "includeDescendants": true
            }
          ]
        }
      }
    ],
    "PrimaryCriteria": { ... },
    "AdditionalCriteria": { ... }
  }
}
```

### OHDSI Studies Cohort JSON
```json
{
  "ConceptSets": [ ... ],
  "PrimaryCriteria": { ... },
  "InclusionRules": [ ... ]
}
```

---

## Usage in ARTEMIS

### 1. Vector DB Indexing (Agent 2)
ConceptSets를 ChromaDB에 임베딩하여 semantic search 지원:
```bash
python scripts/index_concept_sets.py
```

### 2. Cohort Template Reference (Agent 3)
기존 코호트 정의를 참조하여 JSON 생성 품질 향상

### 3. Benchmark Dataset
파이프라인 검증용 테스트 케이스로 활용

---

## Scripts

| Script | Description |
|--------|-------------|
| `scripts/fetch_ohdsi_studies.py` | OHDSI Studies GitHub에서 코호트 다운로드 |
| `scripts/fetch_atlas_cohorts.py` | ATLAS Demo에서 코호트 다운로드 |
| `scripts/count_ohdsi_data.py` | 수집된 데이터 통계 출력 |
