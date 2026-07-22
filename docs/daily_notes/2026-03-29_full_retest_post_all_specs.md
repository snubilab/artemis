# Full End-to-End Retest Post All SPECs — 2026-03-29

## Context

Restarted artemis-api with ALL code changes merged to main:
- SPEC-PERF-001: workers 16, KG cap 40, pre-filter 30, critic result cache
- SPEC-MAP-001: vocab preference (LOINC gap 0.50), standard_concept scoring
- SPEC-INFRA-002: demographics groupId preservation (Age OR fix)
- SPEC-MAP-002: includeDescendants, UMLS strict, reranker, critic self-reflection
- AGENT2_CRITIC_MODEL_TIER=gpt-4o (forced, gpt-4o-mini not on Azure)

Target: study 420 (LEADER trial), LEADER_BENCHMARK source (10k patients)
Gold standard: 1222 final count with 17 inclusion rules

## Step 1: process-eligibility

Status: COMPLETED
- artifactId: art_424, jobId: job_433
- generationMode: provisional_ir (structured_section)
- usedFallback: false

## Step 2: CIRCE Structure Analysis

### Eligibility CIRCE (from studies.json)

Total rules: 17 (previously 18 with separate age rules)

| Rule | Name | Type | Groups | Demo | Criteria |
|------|------|------|--------|------|----------|
| R0 | Type 2 diabetes mellitus | ALL | 0 | 0 | 1 |
| R1 | teplizumab | ALL | 0 | 0 | 1 |
| R2 | sitagliptin | ALL | 0 | 0 | 1 |
| R3 | Cirrhosis of liver | ALL | 0 | 0 | 1 |
| R4 | Delirium due to hepatic encephalopathy | ALL | 0 | 0 | 1 |
| R5 | Anti-diabetic drug use (composite) | ANY | 6 | 0 | 0 |
| R6 | CV disease or risk factors (composite) | ANY | 9 | 0 | 0 |
| R7 | GLP-1/DPP-4 inhibitor (composite) | ANY | 3 | 0 | 0 |
| R8 | Insulin other than specified (composite) | ANY | 6 | 0 | 0 |
| R9 | Acute glycemic decompensation (composite) | ANY | 4 | 0 | 0 |
| R10 | Acute coronary/cerebrovascular (composite) | ANY | 6 | 0 | 0 |
| R11 | Planned revascularization (composite) | ANY | 4 | 0 | 0 |
| R12 | End-stage liver disease (composite) | ANY | 6 | 0 | 0 |
| R13 | Solid organ transplant (composite) | ANY | 7 | 0 | 0 |
| R14 | Malignant neoplasm (composite) | ANY | 19 | 0 | 0 |
| R15 | Medullary thyroid / MEN2 (composite) | ANY | 3 | 0 | 0 |
| R16 | Age >= 50 CVD OR >= 60 risk factors | ANY | 2 | 0 | 0 |

### SPEC-INFRA-002 Verification: Age Rule Merge

**WORKING CORRECTLY.** R16 has Type=ANY with 2 Groups:
- G[0]: Type=ALL, DemographicCriteriaList with Age >= 50
- G[1]: Type=ALL, DemographicCriteriaList with Age >= 60

Previously these were two separate rules causing AND logic (both must be true).
Now they are OR'd within one rule.

### HbA1c Mapping

**MISSING from eligibility CIRCE.** No measurement concept set for HbA1c was created.
The HbA1c criterion was listed in sourceFragments but no Measurement rule appears in the output.

However, the treatment cohort (cohort 757 in WebAPI) DOES contain "HbA1c >= 7.0%"
as R2, suggesting the seeded cohort builder added it from a different source.

### Concept Set Quality Issues

79 concept sets total. Key problems:

| Concept Set | Expected | Actual |
|-------------|----------|--------|
| CS[9] | Stroke/TIA | Cerebrovascular accident (SNOMED) — partial match |
| CS[10] | Revascularization | Fluoroscopic guidance — **WRONG** |
| CS[11] | >50% stenosis | Subaortic stenosis — **WRONG** |
| CS[12] | Symptomatic CHD | Observable entity — **WRONG** |
| CS[13] | Heart disease | Heart disease — OK (broad) |
| CS[14] | Heart failure | Heart failure — OK |
| CS[15] | Chronic renal failure | Renal impairment — OK |
| CS[16] | Type 1 diabetes (excl) | Type 1 diabetes mellitus — OK |
| CS[17-18] | Anti-diabetic drug | glimepiride — partial |
| CS[19] | DPP-4 inhibitor | sitagliptin — partial (one drug only) |
| CS[20-25] | GLP-1/insulin | insulin glargine, lispro, lente — **WRONG domain** |
| CS[30-31] | MI | Myocardial infarction — OK |
| CS[33] | Ischemic stroke | Cerebral infarction — OK |
| CS[34] | Hemorrhagic stroke | Intracranial hemorrhage — OK |
| CS[43] | Cirrhosis | Cirrhosis of liver — OK |
| CS[55] | Malignant neoplasm | Neoplastic disease — OK |

### R6 (CV composite) Concept Mapping — Major Issue

R6 should contain: MI, stroke/TIA, revascularization, >50% stenosis, CHD, cardiac ischemia, CHF, CKD.
Actual content:
- G[0]: ProcedureOccurrence CS[10] "Fluoroscopic guidance" — wrong
- G[1]: ConditionOccurrence CS[11] "Subaortic stenosis" — wrong
- G[2]: Observation CS[12] "Observable entity" — wrong
- G[3]: ConditionOccurrence CS[13] "Heart disease" — too broad
- G[4]: ConditionOccurrence CS[14] "Heart failure" — ok
- G[5]: ConditionOccurrence CS[15] "Renal impairment" — ok
- G[6]: ConditionOccurrence CS[16] "Type 1 diabetes mellitus" — wrong rule
- G[7]: DrugExposure CS[17] "glimepiride" — wrong domain
- G[8]: DrugExposure CS[18] "glimepiride" — duplicate

### R7 (GLP-1/DPP-4 exclusion) — Wrong Concepts

Should contain GLP-1 receptor agonists and DPP-4 inhibitors.
Actual: insulin glargine, insulin lispro protamine, lente insulin — all insulin types.

## Step 3: Generate Seeded Cohorts

Status: COMPLETED
- artifactId: art_426, jobId: job_436
- generatedCount: 1 (eligibility section)
- Arm: liraglutide, cohortId: 757

## Step 4: Treatment Cohort (757) Structure

18 rules in treatment cohort (17 eligibility + 1 liraglutide drug rule):
- R0: Age criteria merged (ok)
- R1: Type 2 diabetes
- R2: HbA1c >= 7.0%
- R3-R16: Exclusion rules
- R17: liraglutide (treatment drug)

No rule name truncation needed (max length 250 chars).

## Step 5: WebAPI Generation

- Cleared generation cache for LEADER_BENCHMARK (source_id=6)
- Triggered generation: execution 1015
- Status: COMPLETE

## Step 6: Attrition Results

| Rule | Name (truncated) | Satisfy | Excluded | Pct |
|------|-------------------|---------|----------|-----|
| R0 | Age criteria (>=50 CVD OR >=60 risk) | 1097 | 35 | 96.91% |
| R1 | Type 2 diabetes | 1132 | 0 | 100.00% |
| R2 | HbA1c >= 7.0% | 1132 | 0 | 100.00% |
| R3 | Type 1 diabetes | 1132 | 0 | 100.00% |
| R4 | Chronic heart failure NYHA IV | 1047 | 85 | 92.49% |
| R5 | Current continuous renal replacement | 1132 | 0 | 100.00% |
| R6 | Anti-diabetic drug use (composite) | 1132 | 0 | 100.00% |
| R7 | CV disease or risk factors (composite) | **346** | **786** | **30.57%** |
| R8 | GLP-1/DPP-4 inhibitor | 1132 | 0 | 100.00% |
| R9 | Insulin other than specified | 1132 | 0 | 100.00% |
| R10 | Acute glycemic decompensation | 1132 | 0 | 100.00% |
| R11 | Acute coronary/cerebrovascular | 1132 | 0 | 100.00% |
| R12 | Planned revascularization | 1132 | 0 | 100.00% |
| R13 | End-stage liver disease | 1132 | 0 | 100.00% |
| R14 | Solid organ transplant | 1132 | 0 | 100.00% |
| R15 | Malignant neoplasm | 1132 | 0 | 100.00% |
| R16 | Medullary thyroid / MEN2 | 1132 | 0 | 100.00% |
| R17 | liraglutide | 1132 | 0 | 100.00% |

**Base: 1132, Final: 253**

## Comparison with Previous Results

| Metric | Previous (manual fix) | This Run | Gold |
|--------|----------------------|----------|------|
| Base | 1132 | 1132 | 1132 |
| R0 (Age) | 1097 | 1097 | ~1100 |
| R7 (CV) | 346 | 346 | ~700+ |
| Final | 253 | 253 | 1222 |

**Result: IDENTICAL to previous run (253).** The code changes (SPEC-PERF-001, MAP-001,
MAP-002, INFRA-002) did NOT change the mapping quality for existing criteria.

## Analysis

### What Improved (SPEC-INFRA-002)

1. **Age rules correctly merged** — R16 now uses Type=ANY with Groups containing
   demographic criteria. Previously these were two separate AND rules that would
   have excluded anyone under 60 (since both >=50 AND >=60 were required).

### What Did NOT Improve

1. **R7 (CV composite) still the bottleneck** — satisfy=346 (30.57%) vs Gold ~70%+.
   The concept sets mapped to this rule are fundamentally wrong:
   - "Fluoroscopic guidance" instead of revascularization procedures
   - "Subaortic stenosis" instead of coronary stenosis
   - "Observable entity" instead of symptomatic CHD
   - "Type 1 diabetes" incorrectly placed in CV rule
   - "glimepiride" incorrectly placed in CV rule

2. **HbA1c missing from eligibility CIRCE** — No measurement criterion was generated
   for HbA1c >= 7.0%. It appears in the treatment cohort but not the eligibility
   structured expression.

3. **R8 (GLP-1/DPP-4) maps to insulin** — Wrong drug class entirely.

4. **R2 (HbA1c) satisfy=1132** — This is suspicious. Either the concept set is
   a pass-through (no actual measurement filter) or the Measurement domain
   criterion is not restricting properly.

### Root Cause

The mapping agent (Agent 2) is producing incorrect concept set assignments:
- Concept sets are being created for the right clinical terms but assigned to wrong rules
- Some concept sets contain concepts from wrong domains
- The retriever/reranker/critic pipeline correctly identifies concepts but the
  final CIRCE assembly step places them in wrong rules

### Remaining Gap to Gold (1222)

Final = 253 vs Gold = 1222. The 969-person gap is primarily caused by:
1. **R7 CV composite** excludes 786 people who should satisfy
2. This is because the CV rule contains wrong concepts (stenosis, fluoroscopy)
   instead of proper MI/stroke/revascularization concepts

### Next Steps

1. **Fix concept-to-rule assignment** in the CIRCE builder — the mapping agent
   produces correct individual concept sets but assembles them incorrectly
2. **Add HbA1c measurement rule** to eligibility CIRCE (not just treatment)
3. **Fix GLP-1/DPP-4 concept set** to contain actual GLP-1 RA and DPP-4i drugs
4. Consider manual CIRCE correction as interim solution while agent is improved

---

## Rerun 2: Eligibility Cohort 756 Direct Attrition (same day, later run)

Ran process-eligibility again (4 concurrent runs due to background tasks).
Generated on LEADER_BENCHMARK with eligibility cohort 756 (not treatment cohort 757).

### CIRCE Verification (2nd Run)

- ConceptSets: 79, InclusionRules: 17
- Age rules: CORRECT (Type=ANY, 2 Groups)
- **HbA1c criterion (id=5)**: conceptSetId=6 mapped to "Cerebrovascular accident due to
  occlusion of left posterior communicating artery" (SNOMED 603206). NOT LOINC 3004410.
- **Prior MI criterion (id=13)**: conceptSetId=14 mapped to "glimepiride" (RxNorm 1597756).
  NOT Myocardial Infarction.

### Attrition (Eligibility Cohort 756 on LEADER_BENCHMARK)

| Rule | Name | Satisfying | Pct |
|------|------|-----------|-----|
| base | PrimaryCriteria (liraglutide DrugEra) | 1132 | — |
| R0 | Type 2 diabetes mellitus | 1132 | 100.00% |
| **R1** | **Cerebrovascular accident (should be HbA1c)** | **0** | **0.00%** |
| R2 | insulin lispro | 1132 | 100.00% |
| R3 | Transplant of kidney | 1132 | 100.00% |
| R4 | Disorder due to grafting procedure | 1132 | 100.00% |
| R5 | Anti-diabetic drug use (composite) | 1132 | 100.00% |
| R6 | CV disease or risk factors (composite) | 1132 | 100.00% |
| **R7** | **GLP-1 RA/DPP-4i exclusion** | **0** | **0.00%** |
| R8 | Insulin other than specified | 1132 | 100.00% |
| R9 | Acute glycemic decompensation | 1132 | 100.00% |
| R10 | Acute coronary/cerebrovascular event | 1132 | 100.00% |
| R11 | Planned revascularization | 1132 | 100.00% |
| R12 | End-stage liver disease | 1132 | 100.00% |
| R13 | History of solid organ transplant | 1132 | 100.00% |
| R14 | Malignant neoplasm | 1132 | 100.00% |
| R15 | Medullary thyroid carcinoma/MEN2 | 1132 | 100.00% |
| R16 | Age >= 50/60 | 1097 | 96.91% |
| **final** | | **0** | |

### Key Difference from Run 1

- Run 1 used treatment cohort (757) which had HbA1c as a pass-through: final=253
- Run 2 used eligibility cohort (756) where R1 is cerebrovascular accident: final=0
- The eligibility CIRCE has fundamental concept-to-rule misassignment
- R1 should be HbA1c measurement but is mapped to cerebrovascular accident
- This drops ALL 1132 persons at R1

### Root Cause Analysis

The CIRCE builder's concept set assignment is non-deterministic:
- Each run produces different concept set IDs for the same criteria
- The criteria metadata (domain, sourceText) is correct
- But conceptSetId assignment shuffles between runs
- This is likely a dict/set ordering issue in the builder
