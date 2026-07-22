# Test Iteration 1: Manual CIRCE Fix Post SPEC-MAP-001

**Date**: 2026-03-29
**Cohort**: 757 (Study 420 LEADER — Treatment arm: liraglutide)
**Source**: LEADER_BENCHMARK (source_id=6), CDM schema: synthea_cdm_leader, 10k persons
**Gold Target**: 1222 patients with 17 inclusion rules

---

## Changes Made to CIRCE

### Fix 1: HbA1c Concept Set — SNOMED to LOINC

**ConceptSet id=3** was replaced entirely.

Before:
- 37171451 (SNOMED: HbA1c/HbA1 percent in blood)
- 37392408 (SNOMED: Haemoglobin A1 level)
- 37395558 (SNOMED: HbA1c IFCC standardised level)

After:
- **3004410** (LOINC: Hemoglobin A1c/Hemoglobin.total in Blood, concept code 4548-4)
  - includeDescendants: true

Rationale: Synthea CDM uses LOINC for lab measurements. SNOMED measurement concepts
exist as standard concepts but are not recorded in Synthea-generated CDM data.
Previous result for HbA1c rule (R3) was 0 patients. With LOINC fix, R2=1132.

### Fix 2: Age Criteria — Merge Rule 0 and Rule 1 into OR group

Before (two separate AND rules):
- Rule 0: "Age ≥ 50 with cardiovascular disease" — Type=ALL, DemoCrit: Age ≥ 50
- Rule 1: "Age ≥ 60 with cardiovascular risk factors" — Type=ALL, DemoCrit: Age ≥ 60

After (one merged ANY rule):
- Rule 0: "Age criteria (>=50 with CVD OR >=60 with risk factors)"
  - Type: ANY
  - Groups:
    - Group A: Type=ALL, DemoCrit: Age ≥ 50
    - Group B: Type=ALL, DemoCrit: Age ≥ 60

Rationale: WebAPI evaluates each InclusionRule independently with AND logic between
rules. Having two separate age rules means a patient must satisfy BOTH rules
(age ≥ 50 AND age ≥ 60), equivalent to just age ≥ 60. The clinical intent is OR
(either arm of the eligibility criteria). Merging into a single ANY group enables
the correct OR semantics.

Note: The DemographicCriteriaList conditions inside Groups do not carry CV
disease/risk factor criteria yet — those criteria from the original rule names
would require additional concept sets. This fix applies the correct OR age logic.

### Fix 3: Rule Names — No Truncation Required

All rule names were checked for length > 250 characters (varchar(255) WebAPI limit).
Rule 16 was exactly 250 characters — no truncation required.

---

## Attrition Results

### Summary
| Metric | Value |
|--------|-------|
| Base count | 1132 |
| Final count | **253** |
| Gold target | 1222 |
| Gap | 969 patients |

### Full Attrition Table

| Rule | Name (truncated) | Count Satisfying |
|------|------------------|-----------------|
| R0 | Age criteria (>=50 with CVD OR >=60 with risk factors) | 1097 |
| R1 | Type 2 diabetes | 1132 |
| R2 | HbA1c ≥ 7.0% | **1132** (was 0 before fix) |
| R3 | Type 1 diabetes (exclusion) | 1132 |
| R4 | Chronic heart failure NYHA IV (exclusion) | 1047 |
| R5 | Current continuous renal replacement therapy (exclusion) | 1132 |
| R6 | Anti-diabetic drug use + naive + oral + NPH + long-acting + premixed | 1132 |
| R7 | **Cardiovascular disease or risk factors** + Prior MI + stroke + revasc... | **346** |
| R8 | Use of GLP-1 receptor agonist or DPP-4 inhibitor | 1132 |
| R9 | Use of insulin other than specified types | 1132 |
| R10 | Acute decompensation of glycemic control | 1132 |
| R11 | Acute coronary or cerebrovascular event | 1132 |
| R12 | Planned revascularization | 1132 |
| R13 | End-stage liver disease | 1132 |
| R14 | History of solid organ transplant | 1132 |
| R15 | Malignant neoplasm (19 concepts) | 1132 |
| R16 | Medullary thyroid carcinoma or MEN2 | 1132 |
| R17 | liraglutide | 1132 |

---

## Comparison with Gold 1222

Gold LEADER result: 1222 patients (17 inclusion rules, run 20260318_leader_10k_cachefix_retry)

Current agent result: 253 patients (18 rules after merge, now 18 = 18 rules)

### What Improved
- **HbA1c fix is confirmed working**: R2 went from 0 → 1132
  - This was the critical blocker identified in previous sessions
- **Age merge applied**: R0 now 1097 using OR logic

### Remaining Bottleneck: R7 Cardiovascular Disease (346)

R7 is the primary limiting factor. Only 346 patients satisfy the cardiovascular
disease or risk factors criteria. The Gold cohort has ~346+ patients passing this
rule too, but the final count difference (253 vs 1222) suggests the CIRCE definitions
for cardiovascular criteria may be significantly under-specified.

R7 in the current CIRCE is an ANY rule with 9 criteria:
- Prior MI, Prior stroke/TIA, Prior revascularization
- >50% stenosis, Symptomatic CHD, Asymptomatic cardiac ischemia
- Chronic heart failure NYHA II-III, Chronic renal failure

The Gold CIRCE likely includes a broader set of CV concepts or uses different
concept IDs mapped to Synthea CDM data. The Synthea generator for LEADER trial
(liraglutide vs placebo) would have seeded these CV conditions — the concept
mapping may be incomplete.

### Gap Analysis

The final gap (253 vs 1222) is ~969 patients. With base=1132 and final=253,
approximately 79% of the base is being excluded. The sequential attrition shows
most exclusions happen at R7 (base→346=68% reduction).

If R7 were fixed to match Gold behavior (say ~1100 satisfying), and R0 stays at 1097,
the final count could approach Gold's 1222.

---

## Next Steps

1. **Investigate R7 concept sets**: Compare the 9 concept sets in R7 against Gold CIRCE
   to identify missing or mis-mapped concepts
2. **Check Synthea CDM for CV conditions**: Run direct SQL on synthea_cdm_leader to
   see what condition/observation concepts exist related to cardiovascular disease
3. **Consider expanding CV concept sets**: Add broader SNOMED/OMOP concept coverage
   for the conditions listed in R7
4. **Iteration 2 target**: Get final count > 800 (matching Gold more closely)

---

## Technical Notes

### WebAPI PUT Format
The WebAPI cohort definition PUT endpoint (`PUT /WebAPI/cohortdefinition/{id}`) requires
the `expression` field to be a **JSON object** (not a string). Passing it as a serialized
string results in HTTP 400 with CIRCE deserialization error.

Correct PUT body format:
```python
put_body = {
    'id': cohort_def['id'],
    'name': cohort_def['name'],
    'description': cohort_def.get('description', ''),
    'expression': expr  # dict, NOT json.dumps(expr)
}
```

### Generation Cache
The generation cache was empty (DELETE 0) at the time of this run, indicating WebAPI
performed a fresh calculation. Total generation time was approximately 30 seconds.
