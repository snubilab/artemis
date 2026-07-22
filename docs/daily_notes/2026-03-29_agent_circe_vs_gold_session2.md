# Agent CIRCE vs Gold LEADER — Session 2 (2026-03-29)

## Completed

### Infrastructure Fixes
- `compose/artemis-api.yml`: `artemis/data:/app/data` volume mount added
- `Dockerfile.tte-api`: pinned to `python:3.10-slim-bookworm` (openjdk-17 fix) + `poppler-utils`
- Container restarted with new mount, pdftotext verified

### Agent2 Tuning
- Domain mismatch penalty: 0.20 -> 0.50 (`retriever.py:188`)
- ThreadPoolExecutor max_workers: 4 -> 16 (all 7 sites in `workflow.py`)

### LEADER Re-parsing
- `forceRefresh=true` + supplement PDF (NEJMoa1603827 appendix)
- Result: 20 inclusion + 61 exclusion criteria (was 8 inclusion before)
- CV conditions properly decomposed: Prior MI, stroke/TIA, revascularization, stenosis, CHD, CHF, CKD
- art_416 -> applied to study 420 (version 5)

### Eligibility Processing
- art_418: 79 ConceptSets, 18 InclusionRules
- Sub-criteria grouped with `Type: "ANY"` (OR logic) in CIRCE
- Processing time: ~45 minutes (4 workers, 158 criteria dispatched)

### Attrition Results (Cohort 757 on LEADER_BENCHMARK)
```
baseCount: 1132 (liraglutide drug_era users)
R0: Age >= 50 + CV disease     -> 1097 (97%)
R1: Age >= 60 + CV risk        ->  248 (22%)
R2: Type 2 diabetes            -> 1132 (100%)
R3: HbA1c >= 7.0%              ->    0 (0%)   <-- BLOCKER
R4: Type 1 diabetes (excl)     -> 1132 (100%)
R5: CHF NYHA IV (excl)         -> 1047 (93%)
R8: CV disease composite (ANY) ->  346 (31%)
```

### Root Cause: HbA1c Mapping Error
- Agent mapped: SNOMED 37171451 (HbA1c percent in blood) -- UK Biobank variant
- Gold uses:    LOINC 3004410 (Hemoglobin A1c/Hemoglobin.total in Blood) -- standard
- Both are `standard_concept='S'`, but LOINC is the CDM measurement standard
- Vector similarity: "HbA1c percent" beats "Hemoglobin A1c/Hemoglobin.total" textually
- Vocab preference gap (0.25) was insufficient to overcome vector distance difference

### Gold CIRCE Analysis
- 232 concepts: 205 S (94%), 1 C (ATC), 13 NULL (ICD9/deprecated SNOMED)
- Non-standard concepts are intentional for coverage (ICD9Proc, ICD10CM)

## SPECs Created
1. **SPEC-PERF-001**: Agent2 performance optimization (candidate cap, critic cache, model tiering, KG limit)
2. **SPEC-MAP-001**: Vocab preference strengthening + standard_concept scoring

## In Progress
- Both SPECs dispatched for parallel implementation via worktree isolation
- perf-implementer: workflow.py, kg_expander.py, critic.py, critic_cache.py
- map-implementer: retriever.py, vector.py

## Next Steps
1. Merge both SPEC implementations
2. Re-run process-eligibility with optimized pipeline
3. Fix HbA1c mapping -> re-run attrition -> target Gold 1222
4. WebAPI rule name truncation (varchar(255) limit)
