# Final Integration Test -- Post All SPECs + Seed Quality Fixes (2026-03-29)

## Code Changes Active
- SPEC-PERF-001 (M1-M5): Candidate pre-filtering, critic model tiering, critic result cache
- SPEC-MAP-001 (M1-M2): Vocab preference strengthening, standard_concept scoring
- SPEC-INFRA-002: Demographics groupId fix
- SPEC-MAP-002 (M1-M3 + review fixes): Various mapping improvements
- Task 1: Query pre-expansion (query_expander.py)
- Task 2: ATC distance threshold 0.4
- Task 3: Critic KG preservation
- AGENT2_CRITIC_MODEL_TIER=gpt-4o (env var in compose)

## CIRCE Structure
- Total concept sets: **79**
- Total inclusion rules: **17** (7 inclusion + 10 exclusion)
- Age rule: **ONE rule (Rule 16)** with Type=ANY, 2 Groups (Age>=50 + Age>=60), each with DemographicCriteriaList -- correct OR structure
- Primary Criteria: DrugEra with CodesetId=1 (liraglutide, 3 concepts including 40170911 RxNorm Ingredient)
- Observation Window: 365 prior days, 0 post days

### Rule Structure
| Rule | Name (truncated) | Type |
|---|---|---|
| 0 | Type 2 diabetes mellitus | INC |
| 1 | Cerebrovascular accident due to occlusion of left posterior communicating artery | INC |
| 2 | insulin lispro | INC |
| 3 | Transplant of kidney | INC |
| 4 | Disorder due to grafting procedure | INC |
| 5 | Anti-diabetic drug use + ... (6 components) | INC |
| 6 | Cardiovascular disease or risk factors + Prior MI + ... (9 components) | INC |
| 7 | Use of GLP-1 receptor agonist or DPP-4 inhibitor + ... (3 components) | EXC |
| 8 | Use of insulin other than specified types + ... (6 components) | EXC |
| 9 | Acute decompensation of glycemic control + ... (4 components) | EXC |
| 10 | Acute coronary or cerebrovascular event + ... (6 components) | EXC |
| 11 | Planned revascularization + ... (4 components) | EXC |
| 12 | End-stage liver disease + ... (6 components) | EXC |
| 13 | History of solid organ transplant + ... (7 components) | EXC |
| 14 | Malignant neoplasm + ... (19 components) | EXC |
| 15 | Medullary thyroid carcinoma or MEN2 + ... (3 components) | EXC |
| 16 | Age >= 50 with CV disease + Age >= 60 with CV risk factors | EXC |

## Key Concept Mappings

| Criterion | Concept | Vocab | Correct? |
|---|---|---|---|
| HbA1c >= 7.0% | **MISSING** - no HbA1c concept set found | N/A | NO - not mapped at all |
| MI (Prior MI) | Heart failure (316139) in Rule 6 Group 1 | SNOMED | NO - should be Myocardial infarction (4329847) |
| Stroke (Prior stroke) | Cerebrovascular accident due to occlusion of left posterior communicating artery (603206) | SNOMED | NO - too specific, should be generic stroke |
| GLP-1 RA (liraglutide) | liraglutide (40170911) + 2 RxNorm Extension | RxNorm | YES - correct |
| Type 2 DM | Type 2 diabetes mellitus (201826) | SNOMED | YES - correct |
| Age rule | DemographicCriteria Age >= 50 / >= 60 | Demographics | YES - correct structure |

### Concept Set Quality Issues
Many concept sets have misleading or wrong names/concepts:
- CS[4] "Relative risk of developing disease assessed" -- should be anti-diabetic drug related
- CS[5] "Mass of skin" -- should be a diabetes/drug criterion
- CS[6] "Cerebrovascular accident due to occlusion of left posterior communicating artery" -- too specific for generic stroke/TIA
- CS[8] "Structural disorder of heart" -- used for symptomatic CHD
- CS[9] "Observable entity" -- vague, should be a specific clinical finding
- CS[10] "Heart disease" -- used for CV risk factors (too broad)
- CS[11] "Heart failure" -- used for Prior MI (WRONG concept)
- CS[29] "Preinfarction syndrome" -- used for Acute MI (should be Myocardial infarction)

## Attrition Results

Source: LEADER_BENCHMARK (source_id=6, 10K persons, 1403 liraglutide drug eras)

| Rule | Name | Count | % of Base |
|---|---|---|---|
| base | Entry (liraglutide DrugEra + 365d obs) | 1132 | 100% |
| R0 | Type 2 diabetes mellitus | 1132 | 100% |
| R1 | Cerebrovascular accident... (stroke) | **0** | **0%** |
| R2 | insulin lispro | 1132 | 100% |
| R3 | Transplant of kidney | 1132 | 100% |
| R4 | Disorder due to grafting procedure | 1132 | 100% |
| R5 | Anti-diabetic drug use composite | 1132 | 100% |
| R6 | CV disease or risk factors composite | 1132 | 100% |
| R7 | Exclude GLP-1 RA or DPP-4i | **0** | **0%** |
| R8 | Exclude insulin other types | 1132 | 100% |
| R9 | Exclude acute decompensation | 1132 | 100% |
| R10 | Exclude acute coronary/cerebrovascular | 1132 | 100% |
| R11 | Exclude planned revascularization | 1132 | 100% |
| R12 | Exclude end-stage liver disease | 1132 | 100% |
| R13 | Exclude solid organ transplant | 1132 | 100% |
| R14 | Exclude malignant neoplasm | 1132 | 100% |
| R15 | Exclude MTC/MEN2 | 1132 | 100% |
| R16 | Age >= 50/60 | 1097 | 96.9% |
| **final** | | **0** | **0%** |

### Blocking Rules Analysis

**Rule 1 (0 persons): "Cerebrovascular accident due to occlusion of left posterior communicating artery"**
- This is an INCLUSION rule requiring patients to have this very specific stroke variant
- Should be part of the CV composite rule (Rule 6), not standalone
- The concept (603206) is too specific -- LEADER required generic prior stroke/TIA
- Even if correct, should be inclusion in an OR group, not a standalone AND rule

**Rule 7 (0 persons): "Exclude GLP-1 receptor agonist or DPP-4 inhibitor"**
- This EXCLUDES patients who have used GLP-1 RA
- Since ALL 1132 base patients are on liraglutide (a GLP-1 RA), ALL are excluded
- Root cause: The exclusion concept set likely includes liraglutide itself
- LEADER excluded *prior* GLP-1 RA use, but the concept set captures *any* GLP-1 RA including the study drug
- Fix: Either exclude liraglutide from the GLP-1 RA exclusion set, or add temporal logic (prior to index only)

## Comparison with Gold

| Metric | Gold | Agent | Delta |
|---|---|---|---|
| Base count | 1132 | 1132 | 0 |
| Final count | 1222 | 0 | -1222 |
| Rule count | 17 | 17 | 0 |
| Concept sets | 232 | 79 | -153 |

Gold final is 1222 (higher than base 1132 because Gold uses different entry criteria).
Agent final is 0 due to two blocking rules.

## Remaining Issues

### Critical (blocks all patients)
1. **Rule 1 standalone stroke inclusion**: "Cerebrovascular accident due to occlusion of left posterior communicating artery" is a standalone AND inclusion rule that should be part of CV composite OR group. Also uses wrong concept (too specific).
2. **Rule 7 GLP-1 RA exclusion includes study drug**: Liraglutide (the study drug) is being excluded by the GLP-1 RA exclusion rule. Need temporal constraint or concept exclusion.

### Major (wrong concepts)
3. **HbA1c missing**: No measurement concept set for HbA1c >= 7.0% -- a key LEADER inclusion criterion
4. **Prior MI maps to Heart failure**: CS[11] "Heart failure" is used where Myocardial infarction should be
5. **Prior stroke maps to very specific variant**: CS[6] should be generic stroke/cerebrovascular accident
6. **Many concept sets have wrong/irrelevant concepts**: "Mass of skin", "Finding of neonate", "Observable entity", "Relative risk of developing disease assessed"

### Minor (structure issues)
7. **Rules 1-4 appear to be misplaced sub-criteria**: Should be merged into composite rules rather than standalone AND rules
8. **Concept set naming**: Many sets named after irrelevant top-level SNOMED concepts rather than the clinical criteria they represent
9. **79 concept sets vs Gold 232**: Significantly fewer concepts mapped, reducing precision

### Root Cause Analysis
The mapping quality issues stem from:
- Agent2 concept recommender returning irrelevant SNOMED parents instead of specific clinical concepts
- Incorrect domain routing (e.g., "Prior MI" mapped to Heart failure instead of Myocardial infarction)
- Missing HbA1c mapping suggests Measurement domain handling gap
- Rule structure generation placing sub-criteria as standalone AND rules instead of within composite OR groups
- GLP-1 RA exclusion not accounting for the study drug being a GLP-1 RA itself
